"""
hxlint.py -- lint HTML for the htmx 4 vocabulary.

Coding agents learned htmx 1 and 2 and will write it into an htmx 4 app:
implicit inheritance, ``hx-ext``, ``hx-vars``, camelCase event names, the old
``show:#x:top`` syntax. Every one of those is silent in the browser. This
module makes them loud, in three places:

- at test time, on every HTML response (``HX(app)`` wires it under ``app.testing``);
- at debug time, as a warning on the first render;
- statically, on template source: ``flask hx lint templates/``.

The vocabulary is generated from htmx's own files (``hx_vocab.py``), and
``hx-trigger`` / ``hx-swap`` values are parsed with a port of htmx's HCON
parser rather than a hand-written grammar, because the hand-written table is
where a linter's false errors come from.
"""

from __future__ import annotations

import difflib
import json
import pathlib
import re
import sys
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Iterable

import hx_vocab as V

__all__ = ["Finding", "lint_html", "lint_source", "lint_paths", "hcon_parse", "hcon_split", "parse_trigger_specs", "parse_swap_spec", "parse", "Node"]

VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}
JINJA = "__JINJA__"
SELECTOR_HEADS = {"closest", "next", "previous", "find", "findAll", "global"}
# htmx 2 event names, lowercased without hyphens: attribute names reach the lint lowercased, and htmx 2 also
# fired each event in kebab-case, the form its docs used (hx-on::after-request).
_HTMX2_EVENTS = {k.lower(): (k, v) for k, v in V.HTMX2_EVENT_NAMES.items()}


# ---------------------------------------------------------------------- HCON

_HCON = re.compile(
    r"""(?:"([^"]+)"|'([^']+)'|([^\s,:]+))(?:\s*:\s*(?:"([^"]*)"|'([^']*)'|<((?:[^/]|/(?!>))+)/>|([^\s,]+)))?(?=\s|,|$)"""
)
_HCON_SPLIT = re.compile(r""",(?![^\[]*\])(?![^(]*\))(?![^<]*/>)(?=(?:[^"']|"[^"]*"|'[^']*')*$)""")
_TRIGGER = re.compile(r"^\s*(\S+\[[^\]]*\]|\S+)\s*(.*?)\s*$", re.S)


def _merge(source: dict, target: dict) -> dict:
    for key, val in source.items():
        if isinstance(val, dict) and isinstance(target.get(key), dict):
            _merge(val, target[key])
        else:
            target[key] = val
    return target


def hcon_parse(string: str | None) -> dict:
    """htmx's mini config language: ``foo:1 bar:true`` -> ``{"foo": 1, "bar": True}``."""
    if not string:
        return {}
    string = string.strip()
    if string.startswith("{"):
        return json.loads(string)
    result: dict = {}
    for m in _HCON.finditer(string):
        dq, sq, bare, dv, sv, hv, bv = m.groups()
        key = dq if dq is not None else sq if sq is not None else bare
        raw = next((v for v in (dv, sv, hv, bv) if v is not None), "true").strip()
        value: object = raw
        try:
            value = json.loads(raw)
        except (ValueError, TypeError):
            pass
        if bare is not None and "." in bare:
            pair: dict = value  # type: ignore[assignment]
            for segment in reversed(bare.split(".")):
                pair = {segment: pair}
        else:
            pair = {key: value}
        _merge(pair, result)
    return result


def hcon_split(string: str) -> list[str]:
    """Split at top-level commas; commas inside ``[]``, ``()``, quotes are kept."""
    return _HCON_SPLIT.split(string)


def parse_trigger_specs(spec: str) -> list[dict]:
    specs = []
    for s in hcon_split(spec):
        m = _TRIGGER.match(s)
        name, rest = (m.group(1), m.group(2)) if m else (None, "")
        if not name:
            continue
        if re.search(r"\[[^\]]*$", name):
            raise ValueError(f"unterminated filter in trigger {name!r}")
        specs.append({"name": name, **hcon_parse(rest)})
    return specs


def parse_swap_spec(swap: str, default: str = "innerHTML") -> dict:
    swap = (swap or "").strip()
    style = default
    if swap and not re.match(r"^\S*:", swap):
        m = re.match(r"^(\S+)\s*(.*)$", swap, re.S)
        style, swap = m.group(1), m.group(2)
    return {"style": V.SWAP_ALIASES.get(style, style), **hcon_parse(swap)}


# ------------------------------------------------------------------- the tree


class Node:
    __slots__ = ("tag", "attrs", "children", "parent", "line")

    def __init__(self, tag: str, attrs: dict[str, str | None], parent: Node | None, line: int):
        self.tag = tag
        self.attrs = attrs
        self.children: list[Node] = []
        self.parent = parent
        self.line = line

    def ancestors(self) -> Iterable[Node]:
        n = self.parent
        while n is not None:
            yield n
            n = n.parent

    def descendants(self) -> Iterable[Node]:
        for c in self.children:
            yield c
            yield from c.descendants()

    def describe(self) -> str:
        if self.attrs.get("id"):
            return f"{self.tag}#{self.attrs['id']}"
        if self.attrs.get("class"):
            return f"{self.tag}.{self.attrs['class'].split()[0]}"
        return self.tag

    def own(self, name: str) -> str | None:
        """The attribute on this element, plain or ``:inherited``."""
        v = self.attrs.get(name)
        return v if v is not None else self.attrs.get(name + ":inherited")

    def resolved(self, name: str) -> str | None:
        """htmx 4 resolution: own value, else an ancestor's ``name:inherited``."""
        v = self.own(name)
        if v is not None:
            return v
        for a in self.ancestors():
            v = a.attrs.get(name + ":inherited")
            if v is not None:
                return v
        return None

    def is_request(self) -> bool:
        return any(self.own(a) is not None for a in V.REQUEST_ATTRIBUTES)


class _TreeBuilder(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node("#root", {}, None, 0)
        self.stack = [self.root]
        self.scripts: list[str] = []

    def handle_starttag(self, tag, attrs):
        node = Node(tag, {k: v for k, v in attrs}, self.stack[-1], self.getpos()[0])
        self.stack[-1].children.append(node)
        if tag == "script":
            src = node.attrs.get("src")
            if src:
                self.scripts.append(src)
        if tag not in VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        node = Node(tag, {k: v for k, v in attrs}, self.stack[-1], self.getpos()[0])
        self.stack[-1].children.append(node)

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                return


def parse(html: str) -> tuple[Node, list[str]]:
    b = _TreeBuilder()
    b.feed(html)
    b.close()
    return b.root, b.scripts


# ------------------------------------------------------------------ findings


@dataclass
class Finding:
    severity: str  # error | warning | info
    rule: str
    message: str
    element: str = ""
    line: int | None = None
    file: str | None = None

    def __str__(self) -> str:
        where = ""
        if self.file:
            where = f" {self.file}:{self.line}"
        elif self.line:
            where = f" line {self.line}"
        el = f" <{self.element}>" if self.element else ""
        return f"[{self.severity}] {self.rule}{el}{where}: {self.message}"


def _suggest(name: str, options: Iterable[str]) -> str:
    close = difflib.get_close_matches(name, list(options), n=1, cutoff=0.6)
    return f" (did you mean {close[0]}?)" if close else ""


class _Linter:
    def __init__(self, root: Node, scripts: list[str], extensions: Iterable[str], is_document: bool, source_mode: bool, file: str | None):
        self.root = root
        self.is_document = is_document
        self.source_mode = source_mode
        self.file = file
        self.findings: list[Finding] = []
        loaded = set(extensions)
        for src in scripts:
            for ext in V.EXTENSION_ATTRIBUTES:
                short = ext.split("-", 1)[-1]
                if ext in src or f"/{short}" in src or f"{short}." in src:
                    loaded.add(ext)
        # No information at all (a fragment, no config): allow every known extension.
        self.loaded: set[str] | None = loaded if (loaded or scripts) else None
        self.nodes = list(root.descendants())
        self.ids: dict[str, list[Node]] = {}
        for n in self.nodes:
            if n.attrs.get("id"):
                self.ids.setdefault(n.attrs["id"], []).append(n)
        self.boosting = any(n.attrs.get("hx-boost:inherited") not in (None, "false") for n in self.nodes)

    def add(self, severity: str, rule: str, node: Node | None, message: str) -> None:
        self.findings.append(Finding(severity, rule, message, node.describe() if node else "", node.line if node else None, self.file))

    def run(self) -> list[Finding]:
        for node in self.nodes:
            for name, value in list(node.attrs.items()):
                base = name[5:] if name.startswith("data-hx-") else name
                if not base.startswith("hx-"):
                    continue
                self.attribute_name(node, base)
                stem = re.sub(r"(:inherited|:append)+$", "", base)
                if stem in ("hx-swap-oob", "hx-select-oob"):
                    self.add("info", "oob-in-template", node, f"{stem} decides what changed elsewhere from the template; here the handler says it with .partial() or .trigger(). Keep it only for a swap style .partial() cannot express (it always swaps outerHTML by id).")
                if value is None or JINJA in value:
                    continue
                if stem == "hx-swap":
                    self.swap_value(node, value)
                elif stem == "hx-swap-oob" and value not in ("true", "false"):
                    self.swap_value(node, value)
                elif stem == "hx-trigger":
                    self.trigger_value(node, value)
                elif stem == "hx-on" or stem.startswith("hx-on:"):
                    self.on_events(node, base, value)
                elif stem in ("hx-target", "hx-indicator") and self.is_document and not self.source_mode:
                    self.id_exists(node, stem, value)
            self.inheritance(node)
            self.delete_control(node)
            if node.own("hx-select") is not None and node.resolved("hx-target") != "body":
                self.add("info", "select-not-body", node, "hx-select prunes a page on the client; the server can send the fragment instead (HX-Request-Type is 'full' here).")
        for id_, nodes in self.ids.items():
            if len(nodes) > 1:
                tags = ", ".join(n.tag for n in nodes)
                self.add("error", "duplicate-id", nodes[1], f'id="{id_}" appears {len(nodes)} times ({tags}); selectors and hx-indicator find only the first.')
        return self.findings

    # rules --------------------------------------------------------------

    def attribute_name(self, node: Node, name: str) -> None:
        stem = re.sub(r"(:inherited|:append)+$", "", name)
        if stem in V.REMOVED_ATTRIBUTES:
            self.add("error", "htmx2-attribute", node, f"{stem} is not htmx 4; {V.REMOVED_ATTRIBUTES[stem]}.")
            return
        if stem in V.CORE_ATTRIBUTES:
            return
        for fam in V.FAMILIES:
            if stem == fam.rstrip(":") or stem.startswith(fam if fam.endswith(":") else fam + ":"):
                if fam in ("hx-on", "hx-status:"):
                    return
                self.extension_loaded(node, stem, fam.rstrip(":"))
                return
        for ext, attrs in V.EXTENSION_ATTRIBUTES.items():
            if stem in attrs:
                self.extension_loaded(node, stem, ext)
                return
        everything = list(V.CORE_ATTRIBUTES) + [a for attrs in V.EXTENSION_ATTRIBUTES.values() for a in attrs]
        self.add("error", "unknown-attribute", node, f"{name} is not an htmx 4 attribute{_suggest(stem, everything)}; htmx ignores it silently.")

    def extension_loaded(self, node: Node, attr: str, ext: str) -> None:
        if self.loaded is None or ext in self.loaded:
            return
        self.add("warning", "extension-not-loaded", node, f"{attr} needs the {ext} extension, and no script for it is on this page.")

    def swap_value(self, node: Node, value: str) -> None:
        spec = parse_swap_spec(value)
        style = spec.pop("style")
        known = set(V.SWAP_STYLES) | set(V.SWAP_ALIASES)
        for ext_style, ext in V.EXTENSION_SWAP_STYLES.items():
            if self.loaded is None or ext in self.loaded:
                known.add(ext_style)
        if style not in known:
            by_case = {s.lower(): s for s in known}
            if style.lower() in by_case:
                self.add("error", "swap-style-case", node, f'hx-swap="{style}" is not a style; htmx 4 matches case, use {by_case[style.lower()]}.')
            else:
                self.add("error", "unknown-swap-style", node, f'hx-swap style "{style}" is not htmx 4{_suggest(style, known)}; the swap silently does nothing.')
        for key, val in spec.items():
            if key not in V.SWAP_MODIFIERS:
                self.add("error", "unknown-swap-modifier", node, f'hx-swap modifier "{key}" is not htmx 4{_suggest(key, V.SWAP_MODIFIERS)}.')
            elif key in ("show", "scroll") and isinstance(val, str) and ":" in val:
                self.add("error", "swap-show-syntax", node, f'hx-swap "{key}:{val}" is the htmx 2 combined form; htmx 4 wants {key}:{val.rsplit(":", 1)[-1]} {key}Target:{val.rsplit(":", 1)[0]}.')

    def trigger_value(self, node: Node, value: str) -> None:
        try:
            specs = parse_trigger_specs(value)
        except ValueError as e:
            self.add("error", "trigger-syntax", node, str(e))
            return
        for spec in specs:
            name = spec.pop("name").split("[", 1)[0]
            self.event_name(node, name)
            previous_key, previous_val = None, None
            for key, val in spec.items():
                if key == "queue":
                    self.add("error", "trigger-queue", node, 'hx-trigger "queue:" is removed in htmx 4; use hx-sync="this:queue all".')
                elif key in V.TRIGGER_MODIFIERS:
                    pass
                elif name == "every" and re.match(r"^\d+(ms|s|m|h)?$", key):
                    pass
                elif previous_key in ("from", "target") and previous_val in SELECTOR_HEADS and val is True:
                    self.add("error", "trigger-unquoted-selector", node, f'hx-trigger "{previous_key}:{previous_val} {key}" parses as two tokens and attaches no listener; quote it: {previous_key}:\'{previous_val} {key}\'.')
                else:
                    self.add("error", "unknown-trigger-modifier", node, f'hx-trigger modifier "{key}" on {name} is not htmx 4{_suggest(key, V.TRIGGER_MODIFIERS)}.')
                previous_key, previous_val = key, val

    def on_events(self, node: Node, attr: str, value: str) -> None:
        events = []
        if attr == "hx-on":
            for part in re.split(r";(?=[^;]*->)", value):
                if "->" in part:
                    events.append(part.split("->", 1)[0].strip().split()[0])
        elif attr.startswith("hx-on::"):
            events.append("htmx:" + attr[len("hx-on::"):])
        elif attr.startswith("hx-on:"):
            events.append(attr[len("hx-on:"):])
        for event in events:
            self.event_name(node, event)

    def event_name(self, node: Node, event: str) -> None:
        """An event listened for in ``hx-on`` or ``hx-trigger``: htmx 4 fires none of htmx 2's names."""
        event = event.split("[", 1)[0]
        found = _HTMX2_EVENTS.get(event.lower().replace("-", ""))
        if found and "-" in event:
            old, new = found
            self.add("error", "htmx2-event-name", node, f"{event} is htmx 2's kebab-case name for {old}; htmx 4 fires only {new}, so this listener never runs.")
        elif found:
            old, new = found
            self.add("error", "htmx2-event-name", node, f"{old} is the htmx 2 event name; htmx 4 calls it {new}.")
        elif re.match(r"^htmx:[a-z]+[A-Z]", event):
            self.add("error", "htmx2-event-name", node, f"{event} looks like an htmx 2 camelCase event; htmx 4 names are colon-separated (htmx:after:swap).")

    def inheritance(self, node: Node) -> None:
        if node.tag == "hx-partial":
            return
        if node.is_request():
            return
        inner = [d for d in node.descendants() if d.is_request()]
        boosted_inner = self.boosting and any(d.tag in ("a", "form") for d in node.descendants())
        for attr in V.INHERITABLE:
            if attr == "hx-boost" or node.attrs.get(attr) is None:
                continue
            if inner or boosted_inner:
                n = len(inner) or "the boosted"
                self.add("warning", "implicit-inheritance", node, f"{attr} on <{node.describe()}> reaches none of the {n} controls inside it; htmx 4 needs {attr}:inherited.")
        # htmx 4 boosts only <a> and <form>; on anything else a plain hx-boost is read by nothing.
        # No descendant test: in a layout the links live in the child templates.
        if node.attrs.get("hx-boost") is not None and node.tag not in ("a", "form"):
            self.add("error", "boost-not-inherited", node, f"hx-boost on <{node.describe()}> does nothing; htmx 4 boosts only <a> and <form>, and reaches them from an ancestor only with hx-boost:inherited.")

    def delete_control(self, node: Node) -> None:
        if node.own("hx-delete") is None:
            return
        if node.tag != "form" and any(a.tag == "form" for a in node.ancestors()) and node.resolved("hx-include") is None:
            self.add("info", "delete-without-include", node, "hx-delete inside a form sends none of the form's values in htmx 4; add hx-include=\"closest form\" if the handler needs them (flask hx map checks).")
        swap = node.resolved("hx-swap")
        target = (node.resolved("hx-target") or "this").strip()
        removes_itself = target == "this" or target.startswith("closest")
        style = parse_swap_spec(swap or "")["style"] if swap and JINJA not in swap else ("innerHTML" if not swap else None)
        if style == "innerHTML" and removes_itself:
            self.add("warning", "delete-default-swap", node, 'hx-delete on the default innerHTML swap: an empty response leaves an empty element behind; say hx-swap="delete" (or outerHTML).')

    def id_exists(self, node: Node, attr: str, value: str) -> None:
        m = re.match(r"^#([\w-]+)$", value.strip())
        if m and m.group(1) not in self.ids:
            self.add("error", "missing-target", node, f'{attr}="{value}" matches nothing on this page; htmx will fire htmx:error at click time and swap nothing.')


# --------------------------------------------------------------------- entry


def lint_html(html: str, *, extensions: Iterable[str] = (), is_document: bool | None = None, file: str | None = None, source_mode: bool = False) -> list[Finding]:
    root, scripts = parse(html)
    if is_document is None:
        is_document = any(n.tag in ("html", "body") for n in root.descendants())
    return _Linter(root, scripts, extensions, is_document, source_mode, file).run()


_JINJA_EXPR = re.compile(r"\{\{.*?\}\}", re.S)
_JINJA_TAG = re.compile(r"\{%.*?%\}|\{#.*?#\}", re.S)


def lint_source(text: str, file: str | None = None, extensions: Iterable[str] = ()) -> list[Finding]:
    """Lint template source without rendering. Values that contain Jinja are not parsed."""
    text = _JINJA_EXPR.sub(JINJA, text)
    text = _JINJA_TAG.sub(lambda m: " " * m.group(0).count("\n") if False else "\n" * m.group(0).count("\n"), text)
    return lint_html(text, extensions=extensions, is_document=False, file=file, source_mode=True)


def lint_paths(paths: Iterable[str], extensions: Iterable[str] = (), out=None) -> int:
    out = out or sys.stdout
    files: list[pathlib.Path] = []
    for p in paths:
        path = pathlib.Path(p)
        files += sorted(path.rglob("*.html")) if path.is_dir() else [path]
    errors = 0
    for f in files:
        for finding in lint_source(f.read_text(), file=str(f), extensions=extensions):
            print(finding, file=out)
            errors += finding.severity == "error"
    print(f"hx lint: {len(files)} files, {errors} errors", file=out)
    return 1 if errors else 0
