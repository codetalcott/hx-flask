"""
hxmap.py -- map every control in the templates to the handler that answers it.

    flask hx map

The Flask adapter over ``mapcore``: Jinja preprocessing (``url_for('x')`` to
``URLFOR:x``), URL resolution through ``app.url_map``, and an AST scan of each
endpoint's source for the hx verbs it calls. The scan, the checks and the
report are ``mapcore.py``, shared with dj-hx.

For each endpoint: the verbs it calls and the template and block it names; the
controls in the templates that point at it, each classified as ``full`` or
``partial`` by htmx 4's own rule (the target is ``body``, ``hx-select`` is
present, or the element is boosted); the events it announces and the elements
that listen. A partial control reaching a page-only handler, a full control
reaching a fragment-only one, a control reaching a handler that calls no verb,
and a handler that retargets or reswaps are all reported at scan time.
"""

from __future__ import annotations

import ast
import inspect
import re
import textwrap
from typing import Any

from werkzeug.exceptions import HTTPException
from werkzeug.routing import RequestRedirect

import mapcore
from hxlint import JINJA
from mapcore import URLFOR, Control, Handler, Listener, Map

__all__ = ["build_map", "print_map", "Control", "Handler", "Listener", "Map"]

_JINJA_URLFOR = re.compile(r"\{\{\s*url_for\(\s*['\"]([\w.]+)['\"][^}]*\}\}", re.S)
_JINJA_EXPR = re.compile(r"\{\{.*?\}\}", re.S)
_JINJA_TAG = re.compile(r"\{%.*?%\}|\{#.*?#\}", re.S)

FLASH_NAMES = ("flash",)
VALUE_ATTRS = ("args", "form", "values", "json", "get_json")


# ------------------------------------------------------------------ templates


def _preprocess(source: str) -> str:
    source = _JINJA_URLFOR.sub(lambda m: URLFOR + m.group(1), source)
    source = _JINJA_EXPR.sub(JINJA, source)
    return _JINJA_TAG.sub(lambda m: "\n" * m.group(0).count("\n"), source)


def _sources(app) -> dict[str, str]:
    loader = app.jinja_env.loader
    return {
        name: _preprocess(loader.get_source(app.jinja_env, name)[0])
        for name in loader.list_templates()
        if name.endswith((".html", ".jinja", ".jinja2", ".j2"))
    }


def _resolver(app):
    adapter = app.url_map.bind("localhost")

    def resolve(url: str, method: str) -> tuple[str | None, str | None]:
        if url.startswith(URLFOR):
            endpoint = url[len(URLFOR):]
            if endpoint not in app.view_functions:
                return None, f"url_for('{endpoint}') names no endpoint"
            return endpoint, None
        path = mapcore.resolve_path(url)
        if path is None:
            return None, "computed URL; cannot resolve statically"
        try:
            endpoint, _ = adapter.match(path, method=method)
            return endpoint, None
        except RequestRedirect as e:
            return None, f"{method} {path} is a {e.code} from URL routing (trailing slash?); fetch follows it silently"
        except HTTPException as e:
            return None, f"{method} {path} matches no route ({e.code})"

    return resolve


# ------------------------------------------------------------------- handlers


def _verb_names(module) -> dict[str, str]:
    """
    Every dotted name a handler in ``module`` can call a verb by: ``hx.render``
    always, ``h.render`` after ``from hx import hx as h``, ``m.hx.render``
    after ``import hx as m``.
    """
    names = {f"hx.{v}": v for v in mapcore.VERBS}
    try:
        tree = ast.parse(inspect.getsource(module))
    except (OSError, TypeError, SyntaxError):
        return names
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "hx":
            for alias in node.names:
                if alias.name == "hx" and alias.asname:
                    names.update({f"{alias.asname}.{v}": v for v in mapcore.VERBS})
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "hx":
                    head = alias.asname or "hx"
                    names.update({f"{head}.hx.{v}": v for v in mapcore.VERBS})
    return names


def _scan_handlers(app) -> dict[str, Handler]:
    handlers: dict[str, Handler] = {}
    for rule in app.url_map.iter_rules():
        if rule.endpoint == "static":
            continue
        h = handlers.setdefault(rule.endpoint, Handler(rule.endpoint))
        methods = sorted((rule.methods or set()) - {"HEAD", "OPTIONS"})
        h.rules.append(f"{','.join(methods)} {rule.rule}")
    names_by_module: dict[Any, dict[str, str]] = {}
    for endpoint, h in handlers.items():
        func = app.view_functions.get(endpoint)
        if func is None:
            continue
        func = inspect.unwrap(func)
        try:
            tree = ast.parse(textwrap.dedent(inspect.getsource(func)))
        except (OSError, TypeError, SyntaxError):
            continue
        module = inspect.getmodule(func)
        if module not in names_by_module:
            names_by_module[module] = _verb_names(module)
        mapcore.scan_function(h, tree, names_by_module[module], flash_names=FLASH_NAMES, value_attrs=VALUE_ATTRS)
    return handlers


# --------------------------------------------------------------------- the map


def build_map(app) -> Map:
    handlers = _scan_handlers(app)
    controls, listeners, script_names, _ = mapcore.scan_templates(_sources(app), _resolver(app))
    return mapcore.check(handlers, controls, listeners, script_names, verb_prefix="hx.")


def print_map(app, check: bool = True, out=None, by_template: bool = False) -> int:
    return mapcore.print_map(build_map(app), check, out, by_template)
