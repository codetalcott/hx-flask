"""flask hx map: controls to handlers, both directions, checked statically."""

import io

from hxmap import build_map, print_map


def by(controls, **match):
    return [c for c in controls if all(getattr(c, k) == v for k, v in match.items())]


def test_every_control_in_the_contact_app_resolves_and_agrees_with_its_handler(app):
    m = build_map(app)
    assert m.errors == [] and m.warnings == []
    assert all(c.endpoint for c in m.controls), [c for c in m.controls if not c.endpoint]
    # htmx 4's own full/partial rule, applied statically
    search = by(m.controls, element="input#search")[0]
    assert (search.endpoint, search.scope, search.why) == ("contacts", "partial", "hx-target=tbody")
    row_delete = by(m.controls, method="DELETE", endpoint="contacts_delete", scope="partial")
    assert row_delete and row_delete[0].why == "hx-target=closest tr"
    page_delete = by(m.controls, method="DELETE", endpoint="contacts_delete", scope="full")
    assert page_delete and page_delete[0].why == "hx-target=body"
    new_form = by(m.controls, endpoint="contacts_new", method="POST")[0]
    assert new_form.boosted and new_form.scope == "full"
    bulk = by(m.controls, endpoint="contacts_delete_all")[0]
    assert bulk.include and bulk.scope == "partial"


def test_the_contact_app_events_pair_up(app):
    m = build_map(app)
    assert m.handlers["contacts_delete_all"].announces == {"contacts-changed"}
    assert [l.element for l in m.listeners if l.event == "contacts-changed"] == ["span#count"]
    assert m.handlers["contacts"].templates == {"index.html#rows"}
    assert m.handlers["contacts_delete"].verbs == {"redirect", "removed"}
    assert m.handlers["contacts_delete_all"].reads_values and m.handlers["contacts_delete_all"].flashes


def test_map_prints_and_exits_clean_for_the_contact_app(app):
    out = io.StringIO()
    assert print_map(app, out=out) == 0
    text = out.getvalue()
    assert "contacts()  GET /contacts" in text
    assert "announces contacts-changed -> index.html:" in text
    assert "0 errors, 0 warnings" in text


def test_map_reports_the_mismatches_a_dsl_could_not(make_app):
    from flask import request

    from hx import hx

    templates = {
        "layout.html": '<html><body hx-boost:inherited="true">{% block content %}{% endblock %}</body></html>',
        "page.html": """{% extends "layout.html" %}{% block content %}
            <button hx-get="{{ url_for('detail') }}" hx-target="#panel">open</button>
            <a href="/rows">rows as a page</a>
            <span hx-get="/nowhere" hx-trigger="load"></span>
            <div hx-trigger="orphan from:body" hx-get="{{ url_for('rows') }}" hx-target="#panel"></div>
            <form><button hx-delete="/items" hx-target="tbody">bulk</button></form>
            <div id="panel"></div>{% endblock %}""",
        "detail.html": "<html><body>detail</body></html>",
    }
    app = make_app(templates)

    @app.get("/page")
    def page():
        return hx.page("page.html")

    @app.get("/detail")
    def detail():
        return hx.page("detail.html")

    @app.get("/rows")
    def rows():
        return hx.fragment("page.html", partial="content").trigger("nobody-listens")

    @app.delete("/items")
    def items():
        ids = request.args.getlist("id")
        return hx.removed()

    m = build_map(app)
    errors = "\n".join(m.errors)
    warnings = "\n".join(m.warnings)
    assert "<button> targets an element (hx-target=#panel) but detail() only calls hx.page" in errors
    assert "<a> wants a page (boosted) but rows() only calls hx.fragment" in errors
    assert "GET /nowhere matches no route (404)" in errors
    assert "event 'orphan' is listened for (page.html:" in warnings
    assert "event 'nobody-listens' is announced by rows() but nothing in the templates listens" in warnings
    assert "<button> sends no form values on DELETE, but items() reads request values" in warnings
    assert len(m.errors) == 3 and len(m.warnings) == 3


def test_map_treats_script_dispatched_events_as_announced(make_app):
    from hx import hx

    templates = {
        "layout.html": '<html><body>{% block content %}{% endblock %}<script>btn.dispatchEvent(new Event("confirmed"))</script></body></html>',
        "page.html": '{% extends "layout.html" %}{% block content %}<button hx-delete="{{ url_for(\'go\') }}" hx-target="body" hx-trigger="confirmed">x</button>{% endblock %}',
    }
    app = make_app(templates)

    @app.delete("/go")
    def go():
        return hx.redirect("/")

    m = build_map(app)
    assert m.warnings == [] and m.errors == []


def test_map_warns_on_handlers_it_cannot_check_and_on_the_escape_hatches(make_app):
    from flask import render_template

    from hx import hx

    templates = {
        "layout.html": "<html><body>{% block content %}{% endblock %}</body></html>",
        "page.html": """{% extends "layout.html" %}{% block content %}
            <button hx-get="{{ url_for('plain') }}" hx-target="#panel">plain</button>
            <button hx-get="{{ url_for('moved') }}" hx-target="#panel">moved</button>
            <div id="panel"></div>{% endblock %}""",
    }
    app = make_app(templates)

    @app.get("/plain")
    def plain():
        return render_template("page.html")  # no verb: nothing can check its shape

    @app.get("/moved")
    def moved():
        return hx.fragment("page.html", partial="content").retarget("#elsewhere")  # the template no longer predicts this

    m = build_map(app)
    warnings = "\n".join(m.warnings)
    assert m.errors == []
    assert "<button> reaches plain() which calls no hx verb" in warnings
    assert "call hx.render/page/fragment/text/removed" in warnings
    assert "moved() calls .retarget(); page.html:" in warnings and "<button> can no longer predict its DOM effect" in warnings
    assert m.handlers["moved"].escapes == {"retarget"}
    out = io.StringIO()
    print_map(app, out=out)
    assert "  escapes: retarget" in out.getvalue()


def test_map_sees_verbs_through_an_alias_of_hx(make_app):
    from hx import hx as h

    templates = {
        "layout.html": "<html><body>{% block content %}{% endblock %}</body></html>",
        "page.html": '{% extends "layout.html" %}{% block content %}<button hx-get="{{ url_for(\'rows\') }}" hx-target="#panel">x</button><div id="panel"></div>{% endblock %}',
    }
    app = make_app(templates)

    @app.get("/rows")
    def rows():
        return h.render("page.html", partial="content")

    m = build_map(app)
    assert m.handlers["rows"].verbs == {"render"} and m.warnings == [] and m.errors == []


def test_by_template_says_who_renders_each_block(app):
    out = io.StringIO()
    assert print_map(app, out=out, by_template=True) == 0
    text = out.getvalue()
    # The block two handlers serve, which the template itself cannot say
    rows = text.split("index.html#rows\n", 1)[1].split("\nnew.html", 1)[0]
    assert "contacts()  GET /contacts" in rows
    assert "contacts_delete_all()  DELETE /contacts" in rows
    assert "    <- index.html:9 <input#search> GET partial (hx-target=tbody)" in rows
    # A fragment file three handlers render
    archive = text.split("archive_ui.html\n", 1)[1].split("\nedit.html", 1)[0]
    assert [li.strip() for li in archive.splitlines() if not li.startswith("    ")] == [
        "archive_status()  GET /contacts/archive",
        "reset_archive()  DELETE /contacts/archive",
        "start_archive()  POST /contacts/archive",
    ]
    assert text.rstrip().endswith("hx map: 7 templates, 15 handlers")
    assert "[error]" not in text and "controls," not in text  # not the by-handler report as well
