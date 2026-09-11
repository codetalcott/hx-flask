"""
hxmap.py -- map every control in the templates to the handler that answers it.

    flask hx map

For each endpoint: the hx verbs it calls and the template and block it names;
the controls in the templates that point at it, each classified as ``full``
or ``partial`` by htmx 4's own rule (the target is ``body``, ``hx-select`` is
present, or the element is boosted); the events it announces and the elements
that listen. Built from a static scan of the literal strings in handlers and
templates, which is what people and agents both write.

Its first check is the one a Python attribute DSL could not make: a partial
control that reaches a handler calling only ``page``, or a full control that
reaches one calling only ``fragment`` or ``text``, is reported at scan time.
"""

from __future__ import annotations

import ast
import inspect
import re
import sys
import textwrap
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from werkzeug.routing import RequestRedirect
from werkzeug.exceptions import HTTPException

import hx_vocab as V
from hxlint import JINJA, Node, parse, parse_trigger_specs

__all__ = ["build_map", "print_map", "Control", "Handler", "Listener"]

URLFOR = "URLFOR:"
_JINJA_URLFOR = re.compile(r"\{\{\s*url_for\(\s*['\"]([\w.]+)['\"][^}]*\}\}", re.S)
_JINJA_EXPR = re.compile(r"\{\{.*?\}\}", re.S)
_JINJA_TAG = re.compile(r"\{%.*?%\}|\{#.*?#\}", re.S)
_NAME = re.compile(r"""['"]([A-Za-z][\w-]*)['"]""")

DOM_EVENTS = {
    "click", "dblclick", "submit", "reset", "change", "input", "keyup", "keydown", "keypress", "blur", "focus",
    "focusin", "focusout", "mouseenter", "mouseleave", "mouseover", "mouseout", "mousedown", "mouseup", "mousemove",
    "pointerdown", "pointerup", "pointermove", "touchstart", "touchend", "touchmove", "scroll", "search", "toggle",
    "transitionend", "animationend", "wheel", "contextmenu", "drop", "dragover", "dragstart", "dragend", "paste",
    "copy", "cut", "select", "invalid", "resize", "hashchange", "popstate", "DOMContentLoaded",
} | set(V.SPECIAL_TRIGGERS)

PAGE_VERBS = {"page"}
FRAGMENT_VERBS = {"fragment", "text", "removed"}


@dataclass
class Control:
    file: str
    line: int
    element: str
    method: str
    url: str
    endpoint: str | None
    scope: str  # full | partial | unknown
    why: str
    boosted: bool = False
    include: bool = False
    problem: str | None = None


@dataclass
class Listener:
    file: str
    line: int
    element: str
    event: str


@dataclass
class Handler:
    endpoint: str
    rules: list[str] = field(default_factory=list)
    verbs: set[str] = field(default_factory=set)
    templates: set[str] = field(default_factory=set)
    announces: set[str] = field(default_factory=set)
    reads_values: bool = False
    flashes: bool = False
    controls: list[Control] = field(default_factory=list)


@dataclass
class Map:
    handlers: dict[str, Handler]
    controls: list[Control]
    listeners: list[Listener]
    script_names: set[str]
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


# ------------------------------------------------------------------ templates


def _preprocess(source: str) -> str:
    source = _JINJA_URLFOR.sub(lambda m: URLFOR + m.group(1), source)
    source = _JINJA_EXPR.sub(JINJA, source)
    return _JINJA_TAG.sub(lambda m: "\n" * m.group(0).count("\n"), source)


def _scan_templates(app) -> tuple[list[Control], list[Listener], set[str], bool]:
    loader = app.jinja_env.loader
    sources = {name: loader.get_source(app.jinja_env, name)[0] for name in loader.list_templates() if name.endswith((".html", ".jinja", ".jinja2", ".j2"))}
    trees = {name: parse(_preprocess(src))[0] for name, src in sources.items()}
    boosting = any(
        n.attrs.get("hx-boost:inherited") not in (None, "false") for root in trees.values() for n in root.descendants()
    )
    script_names: set[str] = set()
    for src in sources.values():
        for block in re.findall(r"<script[^>]*>(.*?)</script>", src, re.S):
            script_names.update(_NAME.findall(block))
    controls: list[Control] = []
    listeners: list[Listener] = []
    for name, root in trees.items():
        for node in root.descendants():
            for attr, value in node.attrs.items():
                if attr in ("hx-on",) or attr.startswith("hx-on:"):
                    script_names.update(_NAME.findall(value or ""))
            control = _control_for(app, name, node, boosting)
            if control:
                controls.append(control)
            listeners += _listeners_for(name, node)
    return controls, listeners, script_names, boosting


def _control_for(app, file: str, node: Node, boosting: bool) -> Control | None:
    method = url = None
    boosted = False
    for verb in ("get", "post", "put", "patch", "delete", "query"):
        v = node.own(f"hx-{verb}")
        if v is not None:
            method, url = verb.upper(), v
            break
    if url is None and node.own("hx-action") is not None:
        url = node.own("hx-action")
        method = (node.own("hx-method") or "GET").upper()
    if url is None and boosting and node.tag in ("a", "form") and node.resolved("hx-boost") != "false":
        if node.tag == "a":
            url, method = node.attrs.get("href"), "GET"
        else:
            # A form with no action submits to the current URL, which is not knowable
            # statically; in practice such a form is a container for other controls.
            url, method = node.attrs.get("action"), (node.attrs.get("method") or "GET").upper()
        if not url or url.startswith(("#", "javascript:", "mailto:", "http")):
            return None
        boosted = True
    if url is None:
        return None

    target = (node.resolved("hx-target") or "").strip()
    select = node.own("hx-select") is not None
    if select:
        scope, why = "full", "hx-select"
    elif target == "body" or (boosted and not target):
        scope, why = "full", "boosted" if boosted and not target else "hx-target=body"
    elif JINJA in target:
        scope, why = "unknown", "target is computed"
    else:
        scope, why = "partial", f"hx-target={target}" if target else "no hx-target"

    endpoint, problem = _resolve(app, url, method)
    return Control(file, node.line, node.describe(), method, url.replace(URLFOR, "url_for:"), endpoint, scope, why, boosted, node.resolved("hx-include") is not None, problem)


def _resolve(app, url: str, method: str) -> tuple[str | None, str | None]:
    if url.startswith(URLFOR):
        endpoint = url[len(URLFOR):]
        if endpoint not in app.view_functions:
            return None, f"url_for('{endpoint}') names no endpoint"
        return endpoint, None
    if JINJA in url or not url.startswith("/"):
        return None, "computed URL; cannot resolve statically"
    path = urlsplit(url).path
    adapter = app.url_map.bind("localhost")
    try:
        endpoint, _ = adapter.match(path, method=method)
        return endpoint, None
    except RequestRedirect as e:
        return None, f"{method} {path} is a {e.code} from URL routing (trailing slash?); fetch follows it silently"
    except HTTPException as e:
        return None, f"{method} {path} matches no route ({e.code})"


def _listeners_for(file: str, node: Node) -> list[Listener]:
    out = []
    trigger = node.own("hx-trigger")
    if trigger and JINJA not in trigger:
        try:
            for spec in parse_trigger_specs(trigger):
                name = spec["name"].split("[", 1)[0]
                if name not in DOM_EVENTS and not name.startswith("htmx:"):
                    out.append(Listener(file, node.line, node.describe(), name))
        except ValueError:
            pass
    for attr, value in node.attrs.items():
        if attr == "hx-on" and value:
            for part in re.split(r";(?=[^;]*->)", value):
                if "->" in part:
                    name = part.split("->", 1)[0].strip().split()[0].split("[", 1)[0]
                    if name not in DOM_EVENTS and not name.startswith("htmx:"):
                        out.append(Listener(file, node.line, node.describe(), name))
        elif attr.startswith("hx-on:") and not attr.startswith("hx-on::"):
            name = attr[len("hx-on:"):]
            if name not in DOM_EVENTS and not name.startswith("htmx:"):
                out.append(Listener(file, node.line, node.describe(), name))
    return out


# ------------------------------------------------------------------- handlers


class _HandlerVisitor(ast.NodeVisitor):
    def __init__(self, handler: Handler):
        self.h = handler

    def visit_Call(self, node: ast.Call):
        f = node.func
        if isinstance(f, ast.Attribute):
            if isinstance(f.value, ast.Name) and f.value.id == "hx":
                self.h.verbs.add(f.attr)
                self._templates(f.attr, node)
            elif f.attr == "trigger" and node.args and isinstance(node.args[0], ast.Constant):
                self.h.announces.add(str(node.args[0].value))
        elif isinstance(f, ast.Name) and f.id == "flash":
            self.h.flashes = True
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute):
        if isinstance(node.value, ast.Name) and node.value.id == "request" and node.attr in ("args", "form", "values", "get_json", "json"):
            self.h.reads_values = True
        self.generic_visit(node)

    def _templates(self, verb: str, call: ast.Call):
        if verb not in ("render", "page", "fragment", "invalid"):
            return
        consts = [a.value for a in call.args if isinstance(a, ast.Constant) and isinstance(a.value, str)]
        kw = {k.arg: k.value.value for k in call.keywords if isinstance(k.value, ast.Constant) and isinstance(k.value.value, str)}
        template = consts[0] if consts else kw.get("template")
        partial = kw.get("partial") or kw.get("block") or (consts[1] if len(consts) > 1 else None)
        if template:
            self.h.templates.add(f"{template}#{partial}" if partial and "." not in partial else (partial or template))


def _scan_handlers(app) -> dict[str, Handler]:
    handlers: dict[str, Handler] = {}
    for rule in app.url_map.iter_rules():
        if rule.endpoint == "static":
            continue
        h = handlers.setdefault(rule.endpoint, Handler(rule.endpoint))
        methods = sorted((rule.methods or set()) - {"HEAD", "OPTIONS"})
        h.rules.append(f"{','.join(methods)} {rule.rule}")
    for endpoint, h in handlers.items():
        func = app.view_functions.get(endpoint)
        if func is None:
            continue
        try:
            src = textwrap.dedent(inspect.getsource(inspect.unwrap(func)))
            tree = ast.parse(src)
        except (OSError, TypeError, SyntaxError):
            continue
        _HandlerVisitor(h).visit(tree)
    return handlers


# --------------------------------------------------------------------- checks


def build_map(app) -> Map:
    handlers = _scan_handlers(app)
    controls, listeners, script_names, _ = _scan_templates(app)
    m = Map(handlers, controls, listeners, script_names)
    for c in controls:
        if c.problem:
            m.errors.append(f"{c.file}:{c.line} <{c.element}> {c.method} {c.url}: {c.problem}")
            continue
        h = handlers.get(c.endpoint)
        if h is None:
            continue
        h.controls.append(c)
        if not h.verbs:
            continue
        if c.scope == "partial" and h.verbs <= PAGE_VERBS:
            m.errors.append(
                f"{c.file}:{c.line} <{c.element}> targets an element ({c.why}) but {h.endpoint}() only calls hx.page; "
                f"the page would land inside it. Target body, or give the handler a partial."
            )
        elif c.scope == "full" and h.verbs <= FRAGMENT_VERBS:
            m.errors.append(
                f"{c.file}:{c.line} <{c.element}> wants a page ({c.why}) but {h.endpoint}() only calls "
                f"hx.{'/'.join(sorted(h.verbs))}; a bare fragment would land in <body>."
            )
        if c.method == "DELETE" and not c.include and h.reads_values and not c.boosted:
            m.warnings.append(
                f"{c.file}:{c.line} <{c.element}> sends no form values on DELETE, but {h.endpoint}() reads request values; "
                f'add hx-include="closest form".'
            )
    announced = {e for h in handlers.values() for e in h.announces}
    listened = {l.event for l in listeners}
    for event in sorted(listened - announced):
        where = ", ".join(f"{l.file}:{l.line}" for l in listeners if l.event == event)
        if event in script_names:
            continue  # dispatched by a script or hx-on handler in the templates
        m.warnings.append(f"event '{event}' is listened for ({where}) but no handler announces it with .trigger() and no script names it.")
    for event in sorted(announced - listened):
        who = ", ".join(h.endpoint + "()" for h in handlers.values() if event in h.announces)
        m.warnings.append(f"event '{event}' is announced by {who} but nothing in the templates listens for it.")
    return m


def print_map(app, check: bool = True, out=None) -> int:
    out = out or sys.stdout
    m = build_map(app)
    for h in sorted(m.handlers.values(), key=lambda h: h.rules[0].split(" ", 1)[1]):
        print(f"{h.endpoint}()  {'; '.join(h.rules)}", file=out)
        if h.verbs:
            print(f"  verbs: {', '.join(sorted(h.verbs))}" + (f"  -> {', '.join(sorted(h.templates))}" if h.templates else ""), file=out)
        for c in h.controls:
            print(f"  <- {c.file}:{c.line} <{c.element}> {c.method} {c.scope} ({c.why})", file=out)
        if h.announces:
            for event in sorted(h.announces):
                heard = ", ".join(f"{l.file}:{l.line} <{l.element}>" for l in m.listeners if l.event == event) or "nothing"
                print(f"  announces {event} -> {heard}", file=out)
    if check:
        for e in m.errors:
            print(f"[error] {e}", file=out)
        for w in m.warnings:
            print(f"[warning] {w}", file=out)
        print(f"hx map: {len(m.controls)} controls, {len(m.handlers)} handlers, {len(m.errors)} errors, {len(m.warnings)} warnings", file=out)
        return 1 if m.errors else 0
    return 0
