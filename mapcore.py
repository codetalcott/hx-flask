"""
mapcore.py -- the map engine, framework-neutral: controls in templates <-> the
handlers that answer them <-> the events they exchange.

Built from a static scan of the literal strings people and agents both write.
A framework adapter supplies three things: preprocessed template sources
(``url_for('x')`` or ``{% url 'x' %}`` already turned into ``URLFOR:x``), a
resolver from a control's URL and method to a handler key, and the handlers
themselves with the verbs they call (``scan_function``). ``hxmap.py`` is the
Flask adapter; ``dj_hx.hxmap`` is the Django one. This file is canonical in
hx-flask and vendored by dj-hx (``tools/sync_shared.py`` there).

Its first check is the one a Python attribute DSL could not make: a partial
control that reaches a handler calling only ``page``, or a full control that
reaches one calling only ``fragment`` or ``text``, is reported at scan time.
Its second is the one the request-time guards cannot make: a control that
reaches a handler calling no verb at all, so nothing can check its shape, and
a handler that calls ``.retarget()`` or ``.reswap()``, so its controls'
templates no longer predict the DOM effect.
"""

from __future__ import annotations

import ast
import re
import sys
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from urllib.parse import urlsplit

import hx_vocab as vocab
from hxlint import JINJA, Node, parse, parse_trigger_specs

__all__ = [
    "URLFOR",
    "Control",
    "Listener",
    "Handler",
    "Map",
    "scan_templates",
    "scan_function",
    "check",
    "print_map",
    "format_map",
    "PAGE_VERBS",
    "FRAGMENT_VERBS",
    "VERBS",
    "ESCAPE_HATCHES",
]

URLFOR = "URLFOR:"
_NAME = re.compile(r"""['"]([A-Za-z][\w-]*)['"]""")

DOM_EVENTS = {
    "click", "dblclick", "submit", "reset", "change", "input", "keyup", "keydown", "keypress", "blur", "focus",
    "focusin", "focusout", "mouseenter", "mouseleave", "mouseover", "mouseout", "mousedown", "mouseup", "mousemove",
    "pointerdown", "pointerup", "pointermove", "touchstart", "touchend", "touchmove", "scroll", "search", "toggle",
    "transitionend", "animationend", "wheel", "contextmenu", "drop", "dragover", "dragstart", "dragend", "paste",
    "copy", "cut", "select", "invalid", "resize", "hashchange", "popstate", "DOMContentLoaded",
} | set(vocab.SPECIAL_TRIGGERS)

VERBS = {"render", "page", "fragment", "invalid", "redirect", "removed", "text"}
PAGE_VERBS = {"page"}
FRAGMENT_VERBS = {"fragment", "text", "removed"}
ESCAPE_HATCHES = ("retarget", "reswap")
ALL_METHODS = "*"


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
    name: str = ""
    rules: list[str] = field(default_factory=list)
    verbs: set[str] = field(default_factory=set)
    by_method: dict[str, set[str]] = field(default_factory=dict)
    templates: set[str] = field(default_factory=set)
    announces: set[str] = field(default_factory=set)
    escapes: set[str] = field(default_factory=set)
    reads_values: bool = False
    flashes: bool = False
    controls: list[Control] = field(default_factory=list)

    def verbs_for(self, method: str) -> set[str]:
        """
        The verbs a request with ``method`` can reach. Scopes are ``"*"`` (every
        method), ``"GET,POST"`` (only those) or ``"!DELETE"`` (every method but
        those), from ``if request.method == ...`` branches in the handler.
        """
        found: set[str] = set()
        for scope, verbs in self.by_method.items():
            if scope == ALL_METHODS:
                found |= verbs
            elif scope.startswith("!"):
                if method not in scope[1:].split(","):
                    found |= verbs
            elif method in scope.split(","):
                found |= verbs
        return found

    @property
    def label(self) -> str:
        return f"{self.name or self.endpoint}()"


@dataclass
class Map:
    handlers: dict[str, Handler]
    controls: list[Control]
    listeners: list[Listener]
    script_names: set[str]
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


# ------------------------------------------------------------------ templates


def scan_templates(
    sources: dict[str, str], resolve: Callable[[str, str], tuple[str | None, str | None]]
) -> tuple[list[Control], list[Listener], set[str], bool]:
    """``sources`` are already preprocessed: expressions are ``JINJA``, url tags are ``URLFOR:name``."""
    trees = {name: parse(src)[0] for name, src in sources.items()}
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
                if attr == "hx-on" or attr.startswith("hx-on:"):
                    script_names.update(_NAME.findall(value or ""))
            control = _control_for(name, node, boosting, resolve)
            if control:
                controls.append(control)
            listeners += _listeners_for(name, node)
    return controls, listeners, script_names, boosting


def _control_for(file: str, node: Node, boosting: bool, resolve) -> Control | None:
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

    endpoint, problem = resolve(url, method)
    return Control(
        file, node.line, node.describe(), method, url.replace(URLFOR, "url:"), endpoint, scope, why, boosted,
        node.resolved("hx-include") is not None, problem,
    )


def resolve_path(url: str) -> str | None:
    """The path of a literal URL, or None when it is computed or relative."""
    if JINJA in url or not url.startswith("/"):
        return None
    return urlsplit(url).path


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


class HandlerVisitor(ast.NodeVisitor):
    """
    Walks one handler's body. ``verb_names`` maps the local names a call can
    use to the verb they mean (``{"render": "render", "hx.render": "render"}``);
    ``flash_names`` are the calls that queue a message; ``value_attrs`` the
    request attributes that read submitted values.
    """

    def __init__(self, handler: Handler, verb_names: dict[str, str], flash_names: Iterable[str], value_attrs: Iterable[str], method: str = ALL_METHODS):
        self.h = handler
        self.verb_names = verb_names
        self.flash_names = set(flash_names)
        self.value_attrs = set(value_attrs)
        self.method = method

    def _dotted(self, node: ast.AST) -> str | None:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            head = self._dotted(node.value)
            return f"{head}.{node.attr}" if head else None
        return None

    def visit_FunctionDef(self, node):
        self._visit_stmts(node.body)

    visit_AsyncFunctionDef = visit_FunctionDef  # noqa: N815

    def visit_If(self, node: ast.If):
        self._visit_stmts([node])

    def _visit_stmts(self, stmts) -> None:
        """
        Statement lists, so ``if request.method == "DELETE": ...; return`` scopes
        its body to DELETE and everything after it to the other methods.
        """
        outer = self.method
        for stmt in stmts:
            methods = _methods_tested(stmt.test) if isinstance(stmt, ast.If) else None
            if methods is None:
                if isinstance(stmt, ast.If):
                    self.visit(stmt.test)
                    self._visit_stmts(stmt.body)
                    self._visit_stmts(stmt.orelse)
                else:
                    self.visit(stmt)
                continue
            saved = self.method
            self.method = _narrow(saved, methods)
            self._visit_stmts(stmt.body)
            self.method = _exclude(saved, methods)
            self._visit_stmts(stmt.orelse)
            self.method = saved
            if stmt.body and isinstance(stmt.body[-1], (ast.Return, ast.Raise)):
                self.method = _exclude(self.method, methods)
        self.method = outer

    def visit_Call(self, node: ast.Call):
        name = self._dotted(node.func)
        if name is not None:
            verb = self.verb_names.get(name)
            if verb is not None:
                self.h.verbs.add(verb)
                self.h.by_method.setdefault(self.method, set()).add(verb)
                self._templates(verb, node)
            elif name in self.flash_names or name.rsplit(".", 1)[-1] in self.flash_names:
                self.h.flashes = True
        if isinstance(node.func, ast.Attribute):
            if node.func.attr == "trigger" and node.args and isinstance(node.args[0], ast.Constant):
                self.h.announces.add(str(node.args[0].value))
            elif node.func.attr in ESCAPE_HATCHES:
                self.h.escapes.add(node.func.attr)
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute):
        if node.attr in self.value_attrs and self._dotted(node.value) in ("request", "self.request"):
            self.h.reads_values = True
        self.generic_visit(node)

    def _templates(self, verb: str, call: ast.Call):
        if verb not in ("render", "page", "fragment", "invalid"):
            return
        consts = [a.value for a in call.args if isinstance(a, ast.Constant) and isinstance(a.value, str)]
        kw = {k.arg: k.value.value for k in call.keywords if isinstance(k.value, ast.Constant) and isinstance(k.value.value, str)}
        template = consts[0] if consts else kw.get("template")
        partial = kw.get("partial") or (consts[1] if len(consts) > 1 else None)
        if template:
            self.h.templates.add(f"{template}#{partial}" if partial and "." not in partial else (partial or template))


def _narrow(scope: str, methods: set[str]) -> str:
    if scope == ALL_METHODS:
        return ",".join(sorted(methods))
    if scope.startswith("!"):
        return ",".join(sorted(methods - set(scope[1:].split(","))))
    return ",".join(sorted(set(scope.split(",")) & methods))


def _exclude(scope: str, methods: set[str]) -> str:
    if scope == ALL_METHODS:
        return "!" + ",".join(sorted(methods))
    if scope.startswith("!"):
        return "!" + ",".join(sorted(set(scope[1:].split(",")) | methods))
    return ",".join(sorted(set(scope.split(",")) - methods))


def _methods_tested(test: ast.AST) -> set[str] | None:
    """``request.method == "POST"`` or ``request.method in ("PUT", "PATCH")`` -> the methods; else None."""
    if not isinstance(test, ast.Compare) or len(test.ops) != 1:
        return None
    left = test.left
    if not (isinstance(left, ast.Attribute) and left.attr == "method"):
        return None
    right = test.comparators[0]
    if isinstance(test.ops[0], ast.Eq) and isinstance(right, ast.Constant):
        return {str(right.value).upper()}
    if isinstance(test.ops[0], ast.In) and isinstance(right, (ast.Tuple, ast.List, ast.Set)):
        values = [e.value for e in right.elts if isinstance(e, ast.Constant)]
        return {str(v).upper() for v in values} if values else None
    return None


def scan_function(handler: Handler, tree: ast.AST, verb_names: dict[str, str], flash_names=("flash", "add_message", "success", "info", "warning", "error", "debug"), value_attrs=("GET", "POST", "FILES", "body", "args", "form", "values", "json", "get_json"), method: str = ALL_METHODS) -> None:
    HandlerVisitor(handler, verb_names, flash_names, value_attrs, method).visit(tree)


# --------------------------------------------------------------------- checks


def check(handlers: dict[str, Handler], controls: list[Control], listeners: list[Listener], script_names: set[str], verb_prefix: str = "") -> Map:
    """
    The checks. ``verb_prefix`` is how the framework spells a verb in a
    message: ``"hx."`` for Flask's ``hx.page``, ``""`` for Django's ``page``.
    """
    m = Map(handlers, controls, listeners, script_names)
    for c in controls:
        if c.problem:
            # A computed URL is ordinary template code; a name or path that resolves to nothing is a defect.
            (m.warnings if c.problem.startswith("computed") else m.errors).append(
                f"{c.file}:{c.line} <{c.element}> {c.method} {c.url}: {c.problem}"
            )
            continue
        h = handlers.get(c.endpoint)
        if h is None:
            continue
        h.controls.append(c)
        if not h.verbs:
            m.warnings.append(
                f"{c.file}:{c.line} <{c.element}> reaches {h.label} which calls no hx verb, so whether it answers "
                f"with a page or a fragment cannot be checked; call {verb_prefix}render/page/fragment/text/removed "
                f"(or the verb is in a helper the scanner cannot see)."
            )
            continue
        for hatch in sorted(h.escapes):
            m.warnings.append(
                f"{h.label} calls .{hatch}(); {c.file}:{c.line} <{c.element}> can no longer predict its DOM effect "
                f"from the template. Keep the comment that says why."
            )
        verbs = h.verbs_for(c.method)
        if not verbs:
            continue
        if c.scope == "partial" and verbs <= PAGE_VERBS:
            m.errors.append(
                f"{c.file}:{c.line} <{c.element}> targets an element ({c.why}) but {h.label} only calls {verb_prefix}page; "
                f"the page would land inside it. Target body, or give the handler a partial."
            )
        elif c.scope == "full" and verbs <= FRAGMENT_VERBS:
            m.errors.append(
                f"{c.file}:{c.line} <{c.element}> wants a page ({c.why}) but {h.label} only calls "
                f"{verb_prefix}{'/'.join(sorted(verbs))}; a bare fragment would land in <body>."
            )
        if c.method == "DELETE" and not c.include and h.reads_values and not c.boosted:
            m.warnings.append(
                f"{c.file}:{c.line} <{c.element}> sends no form values on DELETE, but {h.label} reads request values; "
                f'add hx-include="closest form".'
            )
    announced = {e for h in handlers.values() for e in h.announces}
    listened = {li.event for li in listeners}
    for event in sorted(listened - announced):
        where = ", ".join(f"{li.file}:{li.line}" for li in listeners if li.event == event)
        if event in script_names:
            continue  # dispatched by a script or hx-on handler in the templates
        m.warnings.append(f"event '{event}' is listened for ({where}) but no handler announces it with .trigger() and no script names it.")
    for event in sorted(announced - listened):
        w = ", ".join(h.label for h in handlers.values() if event in h.announces)
        m.warnings.append(f"event '{event}' is announced by {w} but nothing in the templates listens for it.")
    return m


def format_map(m: Map, check_: bool = True) -> str:
    lines = []
    for h in sorted(m.handlers.values(), key=lambda h: (h.rules[0] if h.rules else "", h.endpoint)):
        lines.append(f"{h.label}  {'; '.join(h.rules)}")
        if h.verbs:
            lines.append(f"  verbs: {', '.join(sorted(h.verbs))}" + (f"  -> {', '.join(sorted(h.templates))}" if h.templates else ""))
        if h.escapes:
            lines.append(f"  escapes: {', '.join(sorted(h.escapes))}")
        for c in h.controls:
            lines.append(f"  <- {c.file}:{c.line} <{c.element}> {c.method} {c.scope} ({c.why})")
        for event in sorted(h.announces):
            heard = ", ".join(f"{li.file}:{li.line} <{li.element}>" for li in m.listeners if li.event == event) or "nothing"
            lines.append(f"  announces {event} -> {heard}")
    if check_:
        lines += [f"[error] {e}" for e in m.errors] + [f"[warning] {w}" for w in m.warnings]
        lines.append(f"hx map: {len(m.controls)} controls, {len(m.handlers)} handlers, {len(m.errors)} errors, {len(m.warnings)} warnings")
    return "\n".join(lines) + "\n"


def print_map(m: Map, check_: bool = True, out=None) -> int:
    """Write the map; one write, so a framework's output wrapper adds no blank lines."""
    (out or sys.stdout).write(format_map(m, check_))
    return 1 if (check_ and m.errors) else 0
