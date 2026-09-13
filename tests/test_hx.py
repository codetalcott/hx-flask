"""
hx.py behaviour, one section per row of the design's silent-failure catalogue.
Each test seeds the failure the book's app could contain and asserts that it
is loud, or cannot be represented.
"""

import json

import pytest
from flask import abort, flash, make_response, redirect, render_template, request, send_file
from flask.signals import template_rendered

import hx as hxmod
from hx import (
    HX,
    HxBareResponse,
    HxError,
    HxFlashUnconfigured,
    HxFragmentIntoPage,
    HxNoSwap,
    HxNotInitialized,
    HxPageIntoFragment,
    HxPartialRootId,
    HxProtocolError,
    HxRedirectIntoFragment,
    HxUnknownBlock,
    hx,
)
from tests.conftest import FULL, PARTIAL

ITEMS = ["ada", "grace", "linus"]


# ------------------------------------------------ full page into a fragment target


def test_render_negotiates_on_request_type(make_app):
    app = make_app()

    @app.get("/")
    def index():
        return hx.render("index.html", partial="rows", items=ITEMS)

    c = app.test_client()
    assert b"<html>" in c.get("/").data  # a browser
    assert b"<html>" in c.get("/", headers=FULL).data  # a boosted link
    body = c.get("/", headers=PARTIAL).data  # a control targeting tbody
    assert b"<html>" not in body
    assert body.count(b"<tr>") == 3


def test_render_accepts_a_template_file_as_the_partial(make_app):
    app = make_app()

    @app.get("/")
    def index():
        return hx.render("index.html", partial="rows.html", items=ITEMS)

    assert app.test_client().get("/", headers=PARTIAL).data.count(b"<tr>") == 3


def test_render_without_a_partial_names_the_fix(make_app):
    app = make_app()

    @app.get("/")
    def index():
        return hx.render("index.html", items=ITEMS)

    with pytest.raises(HxError, match=r"index\(\) calls hx.render\('index.html'\) with no partial; name the block"):
        app.test_client().get("/")


def test_page_raises_when_the_request_targets_an_element(make_app):
    app = make_app()

    @app.get("/")
    def index():
        return hx.page("index.html", items=ITEMS)

    c = app.test_client()
    assert c.get("/").status_code == 200
    assert c.get("/", headers=FULL).status_code == 200
    with pytest.raises(HxPageIntoFragment, match="index\\(\\) renders the page index.html"):
        c.get("/", headers=PARTIAL)


# ------------------------------------------ bare fragment into a boosted request


def test_fragment_is_loud_when_htmx_asked_for_a_page(make_app):
    app = make_app()

    @app.get("/rows")
    def rows():
        return hx.fragment("index.html", partial="rows", items=ITEMS)

    @app.get("/count")
    def count():
        return hx.text("3 items")

    c = app.test_client()
    assert c.get("/rows", headers=PARTIAL).data.count(b"<tr>") == 3
    assert c.get("/rows").status_code == 200  # a browser or curl may fetch a fragment
    with pytest.raises(HxFragmentIntoPage, match="rows\\(\\) answers a boosted"):
        c.get("/rows", headers=FULL)
    with pytest.raises(HxFragmentIntoPage):
        c.get("/count", headers=FULL)


# ------------------------------------------------- redirect followed into a fragment


def test_redirect_is_a_plain_303_and_refuses_partial_requests(make_app):
    app = make_app()

    @app.post("/save")
    def save():
        return hx.redirect("/", code=303)

    c = app.test_client()
    r = c.post("/save")
    assert (r.status_code, r.headers["Location"]) == (303, "/")
    r = c.post("/save", headers=FULL)
    assert r.status_code == 303 and "HX-Location" not in r.headers
    with pytest.raises(HxRedirectIntoFragment, match="save\\(\\) redirects to /"):
        c.post("/save", headers=PARTIAL)


def test_after_request_guard_catches_a_plain_flask_redirect(make_app):
    app = make_app()

    @app.post("/save")
    def save():
        return redirect("/")  # bypassed the verbs

    with pytest.raises(HxRedirectIntoFragment, match="answered a request that targets an element with a 302"):
        app.test_client().post("/save", headers=PARTIAL)


def test_after_request_guard_names_a_routing_redirect(make_app):
    app = make_app()

    @app.route("/things/", methods=["DELETE"])
    def things():
        return hx.removed()

    with pytest.raises(HxRedirectIntoFragment, match="DELETE /things got a 308 from URL routing"):
        app.test_client().delete("/things", headers=PARTIAL)


def test_guard_logs_instead_of_raising_outside_testing_and_runs_once(make_app, caplog):
    app = make_app()
    app.testing = False
    passes = []

    @app.after_request
    def count_passes(response):
        passes.append(response.status_code)
        return response

    @app.post("/save")
    def save():
        return redirect("/")

    with caplog.at_level("WARNING"):
        r = app.test_client().post("/save", headers=PARTIAL)
    assert r.status_code == 302  # logged, not raised, so the redirect went out
    assert sum("answered a request that targets an element" in m for m in caplog.messages) == 1


def test_a_304_to_a_partial_request_is_not_a_redirect(make_app):
    app = make_app()

    @app.get("/rows")
    def rows():
        return "", 304  # htmx skips the swap on a 304 by design; fetch follows nothing

    assert app.test_client().get("/rows", headers=PARTIAL).status_code == 304


# ------------------------------------------------------------- delete outcomes


def test_removed_is_an_empty_200_and_204_is_loud(make_app):
    app = make_app()

    @app.delete("/a")
    def a():
        return hx.removed()

    @app.delete("/b")
    def b():
        return "", 204

    c = app.test_client()
    r = c.delete("/a", headers=PARTIAL)
    assert (r.status_code, r.data) == (200, b"")
    with pytest.raises(HxNoSwap, match="b\\(\\) answered a request that targets an element with a 204"):
        c.delete("/b", headers=PARTIAL)


# --------------------------------------------------- responses built without a verb


def test_bare_responses_to_a_partial_request_are_loud(make_app):
    app = make_app()

    @app.get("/tpl")
    def tpl():
        return render_template("index.html", items=ITEMS)  # the Flask idiom: a page into an element

    @app.get("/empty")
    def empty():
        return ""  # blanks the target

    @app.get("/made")
    def made():
        return make_response("<tr><td>x</td></tr>")

    @app.get("/gone")
    def gone():
        abort(404)

    c = app.test_client()
    for url in ("/tpl", "/empty", "/made"):
        with pytest.raises(HxBareResponse, match=r"\(\) answered a request that targets an element without an hx verb"):
            c.get(url, headers=PARTIAL)
        assert c.get(url).status_code == 200  # a browser
        assert c.get(url, headers=FULL).status_code == 200  # a boosted link is answered by any code that renders a page
    assert c.get("/gone", headers=PARTIAL).status_code == 404  # an error page is not the handler's shape


# ------------------------------------------------------------ validation errors


def test_invalid_is_422_as_page_or_block(make_app):
    app = make_app()

    @app.post("/new")
    def new():
        return hx.invalid("form.html", partial="form", error="Email Required")

    c = app.test_client()
    r = c.post("/new", headers=FULL)
    assert r.status_code == 422 and b"<html>" in r.data and b"Email Required" in r.data
    r = c.post("/new", headers=PARTIAL)
    assert r.status_code == 422 and b"<html>" not in r.data and r.data.strip().startswith(b'<form id="form">')


# --------------------------------------------------------------------- events


def test_trigger_always_names_a_target(make_app):
    app = make_app()

    @app.delete("/x")
    def x():
        return hx.removed().trigger("contacts-changed").trigger("count", n=3, target="#count")

    r = app.test_client().delete("/x", headers=PARTIAL)
    assert json.loads(r.headers["HX-Trigger"]) == {
        "contacts-changed": {"target": "body"},
        "count": {"target": "#count", "n": 3},
    }


# ------------------------------------------------------------------- partials


def test_partial_appends_the_block_as_an_hx_partial(make_app):
    app = make_app()

    @app.get("/")
    def index():
        return hx.render("index.html", partial="rows", items=ITEMS).partial("count")

    c = app.test_client()
    body = c.get("/", headers=PARTIAL).data.decode()
    assert body.count("<tr>") == 3
    assert '<hx-partial hx-target="#count" hx-swap="outerHTML"><span id="count">3</span></hx-partial>' in body
    assert "<hx-partial" not in c.get("/", headers=FULL).data.decode()  # the page already has the region


def test_partial_root_must_carry_the_block_name_as_id(make_app):
    app = make_app()

    @app.get("/")
    def index():
        return hx.render("index.html", partial="rows", items=ITEMS).partial("badcount")

    with pytest.raises(HxPartialRootId, match='root <span> must carry id="badcount"; it has no id'):
        app.test_client().get("/", headers=PARTIAL)


def test_unknown_block_lists_the_blocks_the_template_defines(make_app):
    app = make_app()

    @app.get("/")
    def index():
        return hx.render("index.html", partial="rowz", items=ITEMS)

    with pytest.raises(HxUnknownBlock, match="index.html has no block 'rowz'; it defines: badcount, content, count, extra, rows"):
        app.test_client().get("/", headers=PARTIAL)


# -------------------------------------------------------------- block rendering


def test_blocks_see_context_processors_and_fire_the_template_signal(make_app):
    app = make_app()
    seen = []

    @app.context_processor
    def more():
        return {"extra": "processed"}

    @app.get("/")
    def index():
        return hx.fragment("index.html", partial="extra", items=ITEMS)

    def receiver(sender, template, context, **kw):
        seen.append(template.name)

    template_rendered.connect(receiver, app)
    try:
        body = app.test_client().get("/", headers=PARTIAL).data
    finally:
        template_rendered.disconnect(receiver, app)
    assert body.strip() == b"<i>processed</i>"
    assert seen == ["index.html"]


# ---------------------------------------------------------------- flash bridge


def test_flash_reaches_a_fragment_response_as_a_partial(make_app):
    app = make_app(flash_template="layout.html")

    @app.delete("/x")
    def x():
        flash("Deleted!")
        return hx.removed()

    @app.get("/")
    def index():
        return hx.render("index.html", partial="rows", items=ITEMS)

    c = app.test_client()
    body = c.delete("/x", headers=PARTIAL).data.decode()
    assert body.startswith("\n<hx-partial hx-target=\"#flash\" hx-swap=\"outerHTML\">")
    assert '<p class="flash">Deleted!</p>' in body
    # consumed: the next page does not show it again
    assert b"Deleted!" not in c.get("/").data


def test_flash_on_a_full_response_stays_in_the_page(make_app):
    app = make_app(flash_template="layout.html")

    @app.get("/")
    def index():
        flash("Hello")
        return hx.render("index.html", partial="rows", items=ITEMS)

    body = app.test_client().get("/", headers=FULL).data.decode()
    assert '<p class="flash">Hello</p>' in body and "<hx-partial" not in body


def test_flash_without_a_flash_template_is_loud(make_app):
    app = make_app()

    @app.delete("/x")
    def x():
        flash("Deleted!")
        return hx.removed()

    with pytest.raises(HxFlashUnconfigured, match="x\\(\\) called flash\\(\\) while answering a fragment request"):
        app.test_client().delete("/x", headers=PARTIAL)


def test_flash_bridge_skips_streamed_and_non_html_responses(make_app, tmp_path):
    app = make_app(flash_template="layout.html")
    f = tmp_path / "archive.json"
    f.write_text("[]")

    @app.get("/file")
    def file():
        flash("pending")
        return send_file(f, as_attachment=True, download_name="archive.json")

    r = app.test_client().get("/file", headers=PARTIAL)
    assert r.status_code == 200 and r.data == b"[]"


# ------------------------------------------------------------------- headers


def test_every_response_varies_on_the_htmx_headers(make_app):
    app = make_app()

    @app.get("/")
    def index():
        return hx.render("index.html", partial="rows", items=ITEMS)

    @app.get("/plain")
    def plain():
        return "plain"

    c = app.test_client()
    for r in (c.get("/"), c.get("/", headers=PARTIAL), c.get("/plain")):
        assert {"HX-Request", "HX-Request-Type"} <= set(r.headers["Vary"].split(", "))


def test_htmx_request_without_request_type_is_a_protocol_error(make_app):
    app = make_app()

    @app.get("/")
    def index():
        return hx.render("index.html", partial="rows", items=ITEMS)

    with pytest.raises(HxProtocolError, match="needs htmx 4"):
        app.test_client().get("/", headers={"HX-Request": "true"})


def test_verbs_refuse_to_run_without_the_extension(make_app):
    app = make_app(register=False)

    @app.get("/")
    def index():
        return hx.render("index.html", partial="rows", items=ITEMS)

    with pytest.raises(HxNotInitialized):
        app.test_client().get("/")


# ------------------------------------------------------------------------ text


def test_text_escapes(make_app):
    app = make_app()

    @app.get("/e")
    def e():
        return hx.text("<b>Email Required</b>")

    r = app.test_client().get("/e", headers=PARTIAL)
    assert r.data == b"&lt;b&gt;Email Required&lt;/b&gt;" and r.mimetype == "text/html"


def test_request_side_never_exposes_element_ids():
    assert not any(name in ("source", "target", "trigger") for name in dir(hxmod._Hx))
