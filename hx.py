"""
hx.py -- handler-first htmx 4 for Flask.

The handler owns every response-side decision: which representation to send,
the status, what changed elsewhere on the page, what to announce. It says so
through htmx 4's own protocol: ``HX-Request-Type`` on the way in, ``HX-Trigger``,
``<hx-partial>``, 422 and a plain 303 on the way out.

The HTML keeps the request-side controls (``hx-get``, ``hx-target``,
``hx-trigger``, ``hx-swap``) and stays sufficient to predict the DOM effect.
Nothing here changes a target or a swap from a header, and nothing here reads
``HX-Source`` or ``HX-Target``: the handler never learns an element id.

Fragments are Jinja blocks of the page template, named in the handler::

    from hx import HX, hx

    HX(app, flash_template="layout.html")

    @app.get("/contacts")
    def contacts():
        return hx.render("index.html", partial="rows", contacts=Contact.all())

Three rules that cause most mistakes:

1. Never ``return redirect(...)``, ``return ""`` or ``return "", 204`` to an
   htmx request. Say what happened: ``hx.redirect``, ``hx.removed``, ``hx.text``.
2. Never read ``HX-Source`` or ``HX-Target``. If you want to, the real question
   is whether the client asked for a page or a fragment: ``hx.wants_page``.
3. A block used as a partial (``.partial("count")``, the flash block) must have a
   root element whose ``id`` is the block name. The render checks it.

Requires htmx 4 (``HX-Request-Type``). An htmx request without that header
raises ``HxProtocolError`` rather than guessing.
"""

from __future__ import annotations

import json
import re
import sys
from html import escape
from typing import Any

import click
from flask import Response, current_app, g, request, session
from flask import render_template as _flask_render_template
from flask.signals import before_render_template, template_rendered
from werkzeug.routing import RequestRedirect
from werkzeug.utils import redirect as _werkzeug_redirect

__all__ = [
    "HX",
    "hx",
    "HxResponse",
    "HxError",
    "HxProtocolError",
    "HxNotInitialized",
    "HxPageIntoFragment",
    "HxFragmentIntoPage",
    "HxRedirectIntoFragment",
    "HxNoSwap",
    "HxBareResponse",
    "HxUnknownBlock",
    "HxPartialRootId",
    "HxFlashUnconfigured",
    "HxLintError",
]

REQUEST_HEADER = "HX-Request"
REQUEST_TYPE_HEADER = "HX-Request-Type"
VARY_HEADERS = ("HX-Request", "HX-Request-Type")


# --------------------------------------------------------------------------- errors


class HxError(Exception):
    """Base class. Every error names the handler and says what to change."""


class HxProtocolError(HxError):
    """The request is htmx but not htmx 4 (no ``HX-Request-Type``)."""


class HxNotInitialized(HxError):
    """A verb was called on an app that never ran ``HX(app)``."""


class HxPageIntoFragment(HxError):
    """``hx.page`` answered a request whose target is not the body."""


class HxFragmentIntoPage(HxError):
    """``hx.fragment`` or ``hx.text`` answered a boosted or body-targeted htmx request."""


class HxRedirectIntoFragment(HxError):
    """A 3xx answered a request whose target is not the body; fetch would follow it."""


class HxNoSwap(HxError):
    """A 204 answered a partial request; htmx 4 leaves the target untouched."""


class HxBareResponse(HxError):
    """A response built without an hx verb answered a request that targets an element."""


class HxUnknownBlock(HxError):
    """A ``partial=`` names a block the template does not define."""


class HxPartialRootId(HxError):
    """A block rendered as a partial has no root element carrying ``id=<block>``."""


class HxFlashUnconfigured(HxError):
    """``flash()`` was called on a fragment response and no flash template is set."""


class HxLintError(HxError):
    """The rendered HTML failed the htmx 4 lint (see ``hxlint``)."""


# ------------------------------------------------------------------- the response


class HxResponse(Response):
    """A Flask response with the handler-side vocabulary attached."""

    hx_kind: str = "page"  # page | fragment | text | removed | redirect
    hx_template: str | None = None
    hx_context: dict[str, Any] | None = None

    def trigger(self, name: str, *, target: str = "body", **detail: Any) -> HxResponse:
        """
        Announce ``name`` to the page after the swap.

        Always the JSON form and always with a ``target``: after a ``delete``
        swap the element that made the request is gone and htmx 4 would
        dispatch on ``document``, where a ``from:body`` listener cannot hear
        it. ``detail`` keys are unpacked into the scope of ``hx-on`` handlers.
        """
        existing = self.headers.get("HX-Trigger")
        data = json.loads(existing) if existing else {}
        data[name] = {"target": target, **detail}
        self.headers["HX-Trigger"] = json.dumps(data)
        return self

    def partial(self, block: str, template: str | None = None) -> HxResponse:
        """
        Also update the region ``#<block>`` with the block of the same name.

        Attached only to fragment responses; a page already contains the
        region. The block's root element must carry ``id="<block>"``.
        """
        if self.hx_kind != "fragment":
            return self
        tpl = template or self.hx_template
        if tpl is None:
            raise HxError(".partial() needs a template; this response has none")
        html = _render_block(tpl, block, dict(self.hx_context or {}))
        _check_root_id(html, block, f"{tpl}#{block}")
        self.set_data(self.get_data() + _wrap_partial(block, html, "partial").encode())
        return self

    def push_url(self, url: str) -> HxResponse:
        self.headers["HX-Push-Url"] = url
        return self

    def replace_url(self, url: str) -> HxResponse:
        self.headers["HX-Replace-Url"] = url
        return self

    def with_status(self, code: int) -> HxResponse:
        self.status_code = code
        return self

    # Escape hatches. Both change the DOM effect of a control from the server,
    # which the template can then no longer predict. Use with a comment.
    def retarget(self, selector: str) -> HxResponse:
        self.headers["HX-Retarget"] = selector
        return self

    def reswap(self, spec: str) -> HxResponse:
        self.headers["HX-Reswap"] = spec
        return self


# ------------------------------------------------------------------- rendering


def _state() -> HX:
    ext = current_app.extensions.get("hx")
    if ext is None:
        raise HxNotInitialized("HX(app) was never called; hx verbs need it for Vary, the guards and the flash bridge")
    return ext


def _loud(exc: type[HxError], message: str) -> None:
    """Raise under ``app.testing``; log otherwise. The message names the handler."""
    who = f"{request.endpoint}()" if request.endpoint else f"{request.method} {request.path}"
    message = f"{who} {message}"
    if current_app.testing:
        raise exc(message)
    current_app.logger.warning("hx: %s", message)


def _provenance(detail: str) -> str:
    if not _state().provenance:
        return ""
    return f"<!-- hx: {request.endpoint}() {detail} -->\n"


_ROOT_TAG = re.compile(r"^\s*(?:<!--.*?-->\s*)*<([a-zA-Z][\w-]*)([^>]*)>", re.S)
_ID_ATTR = re.compile(r"""\sid\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))""")


def _check_root_id(html: str, block: str, where: str) -> None:
    m = _ROOT_TAG.match(html)
    if not m:
        raise HxPartialRootId(f"{where} is used as a partial but does not start with an element; it must be one element with id=\"{block}\"")
    idm = _ID_ATTR.search(" " + m.group(2))
    found = idm and (idm.group(1) or idm.group(2) or idm.group(3))
    if found != block:
        have = f'id="{found}"' if found else "no id"
        raise HxPartialRootId(f"{where} is used as a partial, so its root <{m.group(1)}> must carry id=\"{block}\"; it has {have}")


def _wrap_partial(block: str, html: str, kind: str) -> str:
    return f'\n<hx-partial hx-target="#{block}" hx-swap="outerHTML">{_provenance(f"{kind} #{block}")}{html}</hx-partial>'


def _render_block(template_name: str, block: str, context: dict[str, Any]) -> str:
    """Render one block of a template, with Flask's context and signals."""
    app = current_app._get_current_object()  # the real app, so signal receivers match
    tpl = app.jinja_env.get_template(template_name)
    try:
        block_fn = tpl.blocks[block]
    except KeyError:
        have = ", ".join(sorted(tpl.blocks)) or "none"
        raise HxUnknownBlock(f"{template_name} has no block {block!r}; it defines: {have}. Blocks it only inherits do not count.") from None
    app.update_template_context(context)
    before_render_template.send(app, _async_wrapper=app.ensure_sync, template=tpl, context=context)
    rendered = "".join(block_fn(tpl.new_context(context)))
    template_rendered.send(app, _async_wrapper=app.ensure_sync, template=tpl, context=context)
    return rendered


def _render_partial(template: str, partial: str, context: dict[str, Any]) -> tuple[str, str]:
    """A name containing a dot is a template file; anything else is a block."""
    if "." in partial:
        return _flask_render_template(partial, **context), partial
    return _render_block(template, partial, context), f"{template}#{partial}"


def _response(body: str, *, kind: str, template: str | None, context: dict[str, Any] | None, status: int = 200) -> HxResponse:
    resp = HxResponse(body, status=status, mimetype="text/html")
    resp.hx_kind = kind
    resp.hx_template = template
    resp.hx_context = context
    return resp


# -------------------------------------------------------------------- the verbs


class _Hx:
    """The request-side view and the response verbs. One instance: ``hx``."""

    # request side ------------------------------------------------------

    @property
    def is_htmx(self) -> bool:
        return request.headers.get(REQUEST_HEADER) == "true"

    @property
    def request_type(self) -> str | None:
        """``"full"``, ``"partial"``, or ``None`` for a browser."""
        if not self.is_htmx:
            return None
        rtype = request.headers.get(REQUEST_TYPE_HEADER)
        if rtype not in ("full", "partial"):
            raise HxProtocolError(
                "HX-Request is set but HX-Request-Type is not; this needs htmx 4. "
                "A proxy stripping headers, or an htmx 2 client, are the usual causes."
            )
        return rtype

    @property
    def wants_page(self) -> bool:
        """A browser, a boosted link, or a control that targets the body."""
        return self.request_type != "partial"

    @property
    def wants_fragment(self) -> bool:
        return self.request_type == "partial"

    @property
    def current_url(self) -> str | None:
        return request.headers.get("HX-Current-URL")

    # response side -----------------------------------------------------

    def render(self, template: str, partial: str | None = None, **context: Any) -> HxResponse:
        """The page for ``wants_page``, otherwise ``partial``: a block of ``template`` or a file."""
        _state()
        if partial is None:
            raise HxError(
                f"{request.endpoint}() calls hx.render({template!r}) with no partial; name the block a partial "
                "request gets, or call hx.page for a page-only handler."
            )
        if self.wants_page:
            return self._page(template, context)
        return self._fragment(template, partial, context)

    def page(self, template: str, **context: Any) -> HxResponse:
        """Always the page. Raises if the request wanted a fragment."""
        _state()
        if self.wants_fragment:
            raise HxPageIntoFragment(
                f"{request.endpoint}() renders the page {template} but this htmx request targets an element, "
                "not the body. Give the control hx-target=\"body\", or use hx.render(..., partial=...)."
            )
        return self._page(template, context)

    def fragment(self, template: str, partial: str | None = None, **context: Any) -> HxResponse:
        """Always a fragment: the file, or the block ``partial`` of it. Loud if htmx asked for a page."""
        _state()
        self._guard_fragment(f"fragment {template}" + (f"#{partial}" if partial else ""))
        return self._fragment(template, partial or template, context)

    def invalid(self, template: str, partial: str, **context: Any) -> HxResponse:
        """``render`` with status 422. htmx 4 swaps it; a browser shows it."""
        return self.render(template, partial, **context).with_status(422)

    def redirect(self, url: str, code: int = 303) -> HxResponse:
        """A plain redirect. Raises if the request wanted a fragment, because fetch would follow it there."""
        _state()
        if self.wants_fragment:
            raise HxRedirectIntoFragment(
                f"{request.endpoint}() redirects to {url}, but this htmx request targets an element, not the body; "
                "fetch would follow the redirect and swap the page into it. Give the control hx-target=\"body\", "
                "or return a fragment."
            )
        resp = _werkzeug_redirect(url, code=code, Response=HxResponse)
        resp.hx_kind = "redirect"
        return resp

    def removed(self) -> HxResponse:
        """The resource is gone. The control's ``hx-swap="delete"`` removes its representation."""
        _state()
        return _response(_provenance("removed").rstrip("\n"), kind="removed", template=None, context=None)

    def text(self, value: Any) -> HxResponse:
        """An escaped text fragment, for a span or an error slot."""
        _state()
        self._guard_fragment("text")
        return _response(escape(str(value)), kind="text", template=None, context=None)

    # helpers -----------------------------------------------------------

    def test_headers(self, *, partial: bool = True) -> dict[str, str]:
        """Headers htmx 4 sends, for the test client."""
        return {REQUEST_HEADER: "true", REQUEST_TYPE_HEADER: "partial" if partial else "full", "Accept": "text/html"}

    def _guard_fragment(self, what: str) -> None:
        if self.is_htmx and self.wants_page:
            _loud(
                HxFragmentIntoPage,
                f"answers a boosted or body-targeted htmx request with a {what}; it would land in <body> with no layout. "
                "Point the control at an element, or render a page.",
            )

    def _page(self, template: str, context: dict[str, Any]) -> HxResponse:
        body = _flask_render_template(template, **context)
        return _response(body, kind="page", template=template, context=context)

    def _fragment(self, template: str, partial: str, context: dict[str, Any]) -> HxResponse:
        body, where = _render_partial(template, partial, context)
        return _response(_provenance(where) + body, kind="fragment", template=template, context=context)


hx = _Hx()


# ------------------------------------------------------------------ the extension


class HX:
    """
    Register the after-request work: ``Vary``, the guards (a 3xx, a 204 or a
    response built without an hx verb answering a partial request), the flash
    bridge and the lint. ``flash_template`` is the template whose ``flash``
    block renders pending messages; its root element must be ``id="flash"``.
    """

    def __init__(
        self,
        app=None,
        *,
        flash_template: str | None = None,
        flash_block: str = "flash",
        lint: bool | None = None,
        lint_warnings: str = "log",
        extensions: tuple[str, ...] = (),
        provenance: bool | None = None,
    ):
        self.flash_template = flash_template
        self.flash_block = flash_block
        self.lint = lint
        self.lint_warnings = lint_warnings
        self.extensions = tuple(extensions)
        self._provenance = provenance
        self.app = None
        if app is not None:
            self.init_app(app)

    def init_app(self, app) -> None:
        self.app = app
        app.extensions["hx"] = self
        app.after_request(self._after_request)
        app.cli.add_command(_cli)

    @property
    def provenance(self) -> bool:
        return current_app.debug if self._provenance is None else self._provenance

    @property
    def lint_enabled(self) -> bool:
        return (current_app.testing or current_app.debug) if self.lint is None else self.lint

    # after request -----------------------------------------------------

    def _after_request(self, response):
        # Flask runs after_request again on the error response it builds when
        # a handler here raises. Once is enough.
        if getattr(g, "_hx_after_request_done", False) or sys.exc_info()[0] is not None:
            return response
        g._hx_after_request_done = True

        response.vary.update(VARY_HEADERS)

        is_htmx = request.headers.get(REQUEST_HEADER) == "true"
        partial = is_htmx and request.headers.get(REQUEST_TYPE_HEADER) == "partial"
        status = response.status_code
        html = response.mimetype == "text/html" and not response.is_streamed and not response.direct_passthrough

        if partial and 300 <= status < 400:
            if isinstance(request.routing_exception, RequestRedirect):
                _loud(
                    HxRedirectIntoFragment,
                    f"got a {status} from URL routing: the control's URL differs from the route by a trailing slash, "
                    "and fetch will follow it into an element that is not the body. Match the route exactly.",
                )
            else:
                _loud(
                    HxRedirectIntoFragment,
                    f"answered a request that targets an element with a {status}; fetch will follow it and swap the "
                    "page into that element. Use hx.redirect on a body-targeted control, or return a fragment.",
                )
        elif partial and status == 204:
            _loud(HxNoSwap, "answered a request that targets an element with a 204; htmx 4 does not swap it. Use hx.removed() with hx-swap=\"delete\", or return a fragment.")
        elif partial and status < 300 and html:
            if not isinstance(response, HxResponse):
                _loud(
                    HxBareResponse,
                    "answered a request that targets an element without an hx verb (render_template, a string, "
                    "make_response); whether it is a page or a fragment cannot be checked. "
                    "Use hx.render(..., partial=...), hx.fragment, hx.text or hx.removed.",
                )
            self._bridge_flash(response)

        if html and self.lint_enabled:
            self._lint(response)
        return response

    def _bridge_flash(self, response) -> None:
        # Peek, never pop: rendering the block pops, and only once we know we append.
        if not session.get("_flashes"):
            return
        if not self.flash_template:
            _loud(
                HxFlashUnconfigured,
                "called flash() while answering a fragment request, and HX(flash_template=...) is not set; "
                "the message would appear on some later page load instead.",
            )
            return
        html = _render_block(self.flash_template, self.flash_block, {})
        _check_root_id(html, self.flash_block, f"{self.flash_template}#{self.flash_block}")
        response.set_data(response.get_data() + _wrap_partial(self.flash_block, html, "flash").encode())

    def _lint(self, response) -> None:
        try:
            import hxlint
        except ImportError:
            return
        body = response.get_data(as_text=True)
        findings = hxlint.lint_html(body, extensions=self.extensions)
        errors = [f for f in findings if f.severity == "error"]
        warnings = [f for f in findings if f.severity == "warning"]
        if self.lint_warnings == "raise":
            errors += warnings
            warnings = []
        for f in warnings:
            current_app.logger.warning("hx lint: %s", f)
        if errors:
            _loud(HxLintError, "rendered HTML failed the htmx 4 lint:\n  " + "\n  ".join(str(f) for f in errors))


# ---------------------------------------------------------------------- the CLI


@click.group("hx")
def _cli():
    """htmx 4 tools: lint templates, map controls to handlers."""


@_cli.command("lint")
@click.argument("paths", nargs=-1, type=click.Path(exists=True))
def _cli_lint(paths):
    """Lint template source for the htmx 4 vocabulary (no rendering)."""
    import hxlint

    code = hxlint.lint_paths(paths or ("templates",))
    sys.exit(code)


@_cli.command("map")
@click.option("--check/--no-check", default=True, help="Also check controls against the verbs their handlers call.")
@click.option("--by-template", is_flag=True, help="Group by template and block: who renders each one.")
def _cli_map(check, by_template):
    """Map every control in the templates to the handler that answers it."""
    import hxmap

    code = hxmap.print_map(current_app, check=check, by_template=by_template)
    sys.exit(code)
