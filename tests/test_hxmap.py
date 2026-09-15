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


def test_navigate_says_nothing_about_the_shape_a_handler_answers_with(make_app):
    from flask import session

    from hx import hx

    templates = {
        "page.html": """{% extends "layout.html" %}{% block content %}
            <button hx-get="{{ url_for('guarded') }}" hx-target="#panel">guarded</button>
            <button hx-get="{{ url_for('gone') }}" hx-target="#panel">gone</button>
            <a href="{{ url_for('gone') }}">gone, boosted</a>
            <div id="panel"></div>{% endblock %}""",
    }
    app = make_app(templates)

    @app.get("/guarded")
    def guarded():
        if "user" not in session:
            return hx.navigate("/login")
        return hx.page("page.html")  # the login check must not hide this

    @app.get("/gone")
    def gone():
        return hx.navigate("/elsewhere")  # right for a partial control and a boosted link alike

    m = build_map(app)
    assert m.handlers["gone"].verbs == {"navigate"}
    assert m.errors == ["page.html:2 <button> targets an element (hx-target=#panel) but guarded() only calls hx.page; the page would land inside it. Target body, or give the handler a partial."]
    assert m.warnings == []


def test_map_reports_request_headers_that_name_an_element(make_app):
    from flask import render_template, request

    from hx import hx

    app = make_app()

    @app.get("/search")
    def search():
        if request.headers.get("HX-Trigger") == "search":  # the book's idiom: htmx 4 never sends it
            return render_template("rows.html", items=[])
        return hx.page("index.html", items=[])

    @app.get("/panel")
    def panel():
        if "HX-Target" in request.headers:
            return hx.fragment("rows.html", items=[])
        return hx.page("index.html", items=[])

    @app.get("/quiet")
    def quiet():
        return hx.removed().trigger("done")  # an HX-Trigger response header is htmx 4's own

    m = build_map(app)
    assert m.errors == [
        "search() reads the HX-Trigger request header, which htmx 4 does not send (the requesting element is "
        "HX-Source), so the test is always false. To choose a page or a fragment, ask HX-Request-Type (hx.wants_page)."
    ]
    assert [w for w in m.warnings if "request header" in w] == [
        "panel() reads the HX-Target request header, so it depends on an element id the template can change. "
        "To choose a page or a fragment, ask HX-Request-Type (hx.wants_page)."
    ]
    assert m.handlers["search"].header_reads == {"hx-trigger"} and m.handlers["quiet"].header_reads == set()


def test_map_reports_a_request_body_read_on_delete(make_app):
    from flask import request

    from hx import hx

    templates = {
        "page.html": """{% extends "layout.html" %}{% block content %}<form>
            <button hx-delete="{{ url_for('bulk') }}" hx-include="closest form" hx-target="tbody">bulk</button>
            <button hx-delete="{{ url_for('either') }}" hx-target="body">either</button>
            </form>{% endblock %}""",
    }
    app = make_app(templates)

    @app.delete("/bulk")
    def bulk():
        for i in request.form.getlist("id"):  # always empty: DELETE values are query parameters
            pass
        return hx.render("index.html", partial="rows", items=[])

    @app.route("/either", methods=["POST", "DELETE"])
    def either():
        if request.method == "POST":
            request.form.get("name")
            return hx.redirect("/")
        return hx.redirect("/")

    @app.delete("/unreached")
    def unreached():
        request.form.getlist("id")  # no control resolves here, and no verb: the route is DELETE-only
        return ""

    m = build_map(app)
    assert m.errors == [
        'bulk() reads request.form on DELETE, but htmx 4 sends DELETE values as query parameters, so it is always '
        'empty; read the query string (request.args / request.GET), with hx-include="closest form" on the control '
        "if the values are in a form.",
        "unreached() reads request.form on DELETE, but htmx 4 sends DELETE values as query parameters, so it is "
        'always empty; read the query string (request.args / request.GET), with hx-include="closest form" on the '
        "control if the values are in a form.",
    ]
    assert m.handlers["either"].body_reads_for("DELETE") == set() and m.handlers["either"].body_reads_for("POST") == {"request.form"}
    assert not any("sends no form values" in w for w in m.warnings)


def test_htmx_ajax_in_a_script_or_an_attribute_is_a_control(make_app):
    from flask import request

    from hx import hx

    templates = {
        "page.html": """{% extends "layout.html" %}{% block content %}
            <form x-data="{ selected: [] }">
              <button type="button" @click="confirm(`Delete ${selected.length}?`) &&
                  htmx.ajax('DELETE', '/items', { source: $root, target: document.body })">Delete</button>
            </form>
            <script>
              htmx.ajax('GET', '{{ url_for("detail") }}', '#panel');
              htmx.ajax("GET", `/detail/${id}`, {target: "#panel"});
              htmx.ajax('POST', '/nowhere', {target: 'body', values: {a: [1, 2]}});
            </script>
            <div id="panel"></div>{% endblock %}""",
    }
    app = make_app(templates)

    @app.delete("/items")
    def items():
        request.form.getlist("id")  # the source form's values arrive as query parameters
        return hx.redirect("/")

    @app.get("/detail")
    def detail():
        return hx.page("page.html")

    m = build_map(app)
    toolbar = by(m.controls, via="htmx.ajax", method="DELETE")[0]
    assert (toolbar.line, toolbar.element, toolbar.endpoint, toolbar.scope, toolbar.why) == (3, "button", "items", "full", "htmx.ajax target=body")
    script = by(m.controls, via="htmx.ajax", endpoint="detail")[0]
    assert (script.line, script.element, script.scope, script.url) == (7, "script", "partial", "url:detail")
    assert m.errors == [
        'items() reads request.form on DELETE, but htmx 4 sends DELETE values as query parameters, so it is always empty; read the query string (request.args / request.GET), with hx-include="closest form" on the control if the values are in a form.',
        "page.html:7 <script> targets an element (htmx.ajax target=#panel) but detail() only calls hx.page; the page would land inside it. Target body, or give the handler a partial.",
        "page.html:9 <script> POST /nowhere: POST /nowhere matches no route (404)",
    ]
    assert m.warnings == ["page.html:8 <script> GET `/detail/${id}`: computed URL; cannot resolve statically"]


def test_fetch_is_listed_under_its_handler_and_checked_only_where_it_cannot_work(make_app):
    from flask import jsonify

    from hx import hx

    templates = {
        "page.html": """{% extends "layout.html" %}{% block content %}<script>
            const token = await (await fetch("/token")).text();
            fetch('{{ url_for("rows") }}').then(r => r.text()).then(html => tbody.innerHTML = html);
            fetch("https://api.example.com/x", {method: "POST"});
            </script>{% endblock %}""",
    }
    app = make_app(templates)

    @app.get("/token")
    def token():
        return jsonify(token="t")  # JSON to a script is what fetch is for

    @app.get("/rows")
    def rows():
        return hx.render("index.html", partial="rows", items=[])

    m = build_map(app)
    assert m.errors == []
    assert m.warnings == [
        "page.html:3 <script> calls fetch() on GET url:rows, but rows() chooses its answer from HX-Request-Type (hx.render), "
        "which fetch never sends, so the script always gets the page. Call htmx.ajax() instead, and the map checks it like any control."
    ]
    assert [(c.endpoint, c.why) for c in m.controls] == [("token", "fetch: not checked"), ("rows", "fetch: not checked")]
    out = io.StringIO()
    print_map(app, out=out)
    assert "  <- page.html:2 <script> GET unknown (fetch: not checked)" in out.getvalue()
    assert "hx map: 0 controls, 2 fetch calls," in out.getvalue()


def test_map_reports_json_returned_to_a_control(make_app):
    from flask import jsonify, make_response, render_template, request, session

    from hx import hx

    templates = {
        "page.html": """{% extends "layout.html" %}{% block content %}
            <button hx-post="{{ url_for('subscribe') }}" hx-target="#msg">subscribe</button>
            <button hx-get="{{ url_for('status') }}" hx-target="#msg">status</button>
            <button hx-get="{{ url_for('either') }}" hx-target="#msg">either</button>
            <button hx-get="{{ url_for('negotiated') }}" hx-target="#msg">negotiated</button>
            <button hx-delete="{{ url_for('gone') }}" hx-target="#msg">gone</button>
            <button hx-get="{{ url_for('helper') }}" hx-target="#msg">helper</button>
            <div id="msg"></div>{% endblock %}""",
    }
    app = make_app(templates)

    @app.post("/subscribe")
    def subscribe():
        if "user" not in session:
            return hx.navigate("/login")  # leaving says nothing about the answer
        return jsonify(ok=True), 201

    @app.get("/status")
    def status():
        return {"status": "ok"}

    @app.get("/either")
    def either():
        if request.accept_mimetypes.best == "application/json":
            return make_response([1, 2])
        return render_template("page.html")

    @app.get("/negotiated")
    def negotiated():
        if request.is_json:
            return {"a": 1}
        return hx.render("index.html", partial="rows", items=[])

    @app.route("/gone", methods=["GET", "DELETE"])
    def gone():
        if request.method == "GET":
            return {"gone": True}
        return hx.removed()

    @app.get("/helper")
    def helper():
        def payload():
            return {"nested": True}  # not the handler's return

        return render_template("page.html", data=payload())

    m = build_map(app)
    assert m.errors == [
        "page.html:2 <button> reaches subscribe(), which returns JSON (jsonify(...)); htmx swaps a response as HTML, so the JSON "
        "text lands in the target. Answer with HTML (hx.render/fragment/text), or call the endpoint with fetch() from the script that uses the data.",
        "page.html:3 <button> reaches status(), which returns JSON (a dict); htmx swaps a response as HTML, so the JSON text lands in the target. "
        "Answer with HTML (hx.render/fragment/text), or call the endpoint with fetch() from the script that uses the data.",
    ]
    assert [w.split(";")[0] for w in m.warnings] == [
        "page.html:4 <button> reaches either(), which can return JSON (a list)",
        "page.html:7 <button> reaches helper() which calls no hx verb, so whether it answers with a page or a fragment cannot be checked",
    ]
    assert m.handlers["gone"].json_returns == {"GET": {"a dict"}}


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
