"""The linter: HCON port, each rule, and the contact app passing clean."""

import pytest

import hx_vocab as V
from hxlint import hcon_parse, hcon_split, lint_html, lint_paths, lint_script, lint_source, parse_swap_spec, parse_trigger_specs
from tests.conftest import FULL, PARTIAL, ROOT


def rules(findings, severity=None):
    return sorted({f.rule for f in findings if severity is None or f.severity == severity})


# ------------------------------------------------------------------ HCON port


def test_hcon_parse_matches_the_documented_examples():
    assert hcon_parse("foo:1 bar:true") == {"foo": 1, "bar": True}
    assert hcon_parse("sse.mode:once") == {"sse": {"mode": "once"}}
    assert hcon_parse('{"foo": 1}') == {"foo": 1}
    assert hcon_parse("delay:200ms changed") == {"delay": "200ms", "changed": True}
    assert hcon_parse("from:'closest form'") == {"from": "closest form"}
    assert hcon_parse("from:closest form") == {"from": "closest", "form": True}  # the docs' own silent no-op
    assert hcon_split('from:".a, .b", click') == ['from:".a, .b"', " click"]


def test_trigger_and_swap_specs():
    assert parse_trigger_specs("search, keyup delay:200ms changed") == [
        {"name": "search"},
        {"name": "keyup", "delay": "200ms", "changed": True},
    ]
    assert parse_trigger_specs("keyup[ctrlKey && key == 'l'] from:body")[0]["name"] == "keyup[ctrlKey && key == 'l']"
    with pytest.raises(ValueError):
        parse_trigger_specs("click[ctrlKey")
    assert parse_swap_spec("delete swap:1s") == {"style": "delete", "swap": "1s"}
    assert parse_swap_spec("append") == {"style": "beforeend"}
    assert parse_swap_spec("swap:1s") == {"style": "innerHTML", "swap": "1s"}


def test_vocabulary_is_generated_from_htmx_and_knows_the_facts_that_bit_us():
    assert V.VERSION.startswith("4.")
    assert "hx-select" in V.CORE_ATTRIBUTES and "hx-status" in V.CORE_ATTRIBUTES
    assert "hx-ext" in V.REMOVED_ATTRIBUTES and "hx-vars" in V.REMOVED_ATTRIBUTES
    assert "delete" in V.SWAP_STYLES and "outerMorph" in V.SWAP_STYLES
    assert V.SWAP_ALIASES["append"] == "beforeend"
    assert {"swap", "settle", "show", "showTarget", "transition"} <= set(V.SWAP_MODIFIERS)
    assert {"once", "changed", "delay", "throttle", "from", "consume"} <= set(V.TRIGGER_MODIFIERS)
    assert V.HTMX2_EVENT_NAMES["htmx:afterSwap"] == "htmx:after:swap"
    assert V.HTMX2_EVENT_NAMES["htmx:load"] == "htmx:after:init" and V.HTMX2_EVENT_NAMES["htmx:xhr:progress"] == "(removed)"
    assert not any(v.startswith("(see") for v in V.HTMX2_EVENT_NAMES.values())


# ---------------------------------------------------------------- the rules


def test_valid_htmx4_passes_including_the_things_the_first_draft_flagged():
    html = """<html><body hx-boost:inherited="true">
    <span hx-get="/count" hx-trigger="revealed, contacts-changed from:body"></span>
    <div hx-on::after:swap="doA()" hx-on:click="doB()" hx-on="load -> doC(); keyup[key=='Escape'] from:body -> doD()"></div>
    <form hx-post="/x" hx-status:422="target:#errors" hx-swap="outerHTML swap:1s settle:20ms show:top showTarget:#top"></form>
    <div id="errors"></div><div id="top"></div>
    <a hx-delete="/c/1" hx-target="closest tr" hx-swap="delete swap:1s" hx-confirm="Sure?">x</a>
    <input hx-get="/v" hx-trigger="change, keyup delay:200ms changed" hx-target="next .error">
    <div hx-get="/news" hx-trigger="every 2s"></div>
    <div hx-target:inherited="#top" hx-confirm:inherited="ok?"><button hx-post="/a">a</button></div>
    <hx-partial hx-target="#top" hx-swap="outerHTML"><div id="t2"></div></hx-partial>
    <button hx-get="/x" hx-config="timeout:5000" hx-vals='{"a": 1}' hx-include="closest form">b</button>
    </body></html>"""
    assert lint_html(html) == []


def test_htmx2_attributes_are_errors_with_the_replacement():
    f = lint_html('<div hx-ext="sse" hx-vars="a:1" hx-disabled-elt="this" hx-request="timeout:1"></div>')
    assert rules(f) == ["htmx2-attribute"] and len(f) == 4
    assert "hx-disable" in [x.message for x in f if "hx-disabled-elt" in x.message][0]


def test_unknown_attribute_suggests():
    f = lint_html('<div hx-targt="#x"></div>')
    assert rules(f, "error") == ["unknown-attribute"] and "did you mean hx-target?" in f[0].message
    assert "did you mean hx-trigger?" in lint_html('<div hx-triger="click"></div>')[0].message


def test_suggestions_compare_the_name_after_hx():
    # The shared prefix used to make any short name "close": hx-取得 (a localized hx-get) suggested hx-ws.
    [finding] = lint_html('<div hx-取得="/x"></div>')
    assert finding.rule == "unknown-attribute" and "did you mean" not in finding.message
    assert "did you mean" not in lint_html('<div hx-foo="1"></div>')[0].message


def test_swap_values():
    assert rules(lint_html('<div hx-swap="outerhtml"></div>')) == ["swap-style-case"]
    assert rules(lint_html('<div hx-swap="replace"></div>')) == ["unknown-swap-style"]
    assert rules(lint_html('<div hx-swap="innerHTML show:#other:top"></div>')) == ["swap-show-syntax"]
    assert rules(lint_html('<div hx-swap="innerHTML swapp:1s"></div>')) == ["unknown-swap-modifier"]
    assert rules(lint_html('<div hx-swap="upsert"></div>')) == []  # extension style; nothing says it is not loaded
    assert rules(lint_html('<html><script src="/js/htmx.js"></script><div hx-swap="upsert"></div></html>')) == ["unknown-swap-style"]


def test_trigger_values():
    assert rules(lint_html('<div hx-get="/a" hx-trigger="click queue:all"></div>')) == ["trigger-queue"]
    f = lint_html('<input hx-get="/a" hx-trigger="keyup from:closest form">')
    assert rules(f) == ["trigger-unquoted-selector"] and "from:'closest form'" in f[0].message
    assert rules(lint_html('<div hx-get="/a" hx-trigger="click delayy:1s"></div>')) == ["unknown-trigger-modifier"]
    assert rules(lint_html('<div hx-get="/a" hx-trigger="click[ctrlKey"></div>')) == ["trigger-syntax"]


def test_htmx2_event_names_in_hx_on():
    assert rules(lint_html('<div hx-on::afterSwap="x()"></div>')) == ["htmx2-event-name"]
    assert rules(lint_html('<div hx-on:htmx:afterSwap="x()"></div>')) == ["htmx2-event-name"]
    assert rules(lint_html('<div hx-on="htmx:beforeRequest -> x()"></div>')) == ["htmx2-event-name"]


def test_htmx2_kebab_case_event_names_in_hx_on():
    # htmx 2's documented form; htmx 4 listens for htmx:after-request, which it never fires
    [finding] = lint_html('<form hx-post="/x" hx-on::after-request="this.reset()"></form>')
    assert finding.rule == "htmx2-event-name" and finding.severity == "error"
    assert "htmx:after-request is htmx 2's kebab-case name for htmx:afterRequest; htmx 4 fires only htmx:after:request" in finding.message
    assert rules(lint_html('<div hx-on:htmx:config-request="x()"></div>')) == ["htmx2-event-name"]
    assert rules(lint_html('<div hx-on="htmx:before-swap -> x()"></div>')) == ["htmx2-event-name"]
    assert lint_html('<form hx-post="/x" hx-on::after:request="this.reset()"></form>') == []
    assert lint_html('<div hx-on:my-event="x()"></div>') == []  # an app's own kebab-case event


def test_htmx2_event_names_in_hx_trigger():
    assert rules(lint_html('<div hx-get="/x" hx-trigger="htmx:afterSwap from:body"></div>')) == ["htmx2-event-name"]
    [finding] = lint_html('<div hx-get="/x" hx-trigger="load, htmx:after-request from:body"></div>')
    assert "htmx:after-request is htmx 2's kebab-case name for htmx:afterRequest" in finding.message
    assert rules(lint_html('<div hx-get="/x" hx-trigger="htmx:beforeFoo"></div>')) == ["htmx2-event-name"]
    # htmx 4's own names, including the camelCase segment some of them carry, and an app's events
    for trigger in ("htmx:after:request from:body", "htmx:after:viewTransition", "contacts-changed from:body", "keyup delay:200ms changed"):
        assert lint_html(f'<div hx-get="/x" hx-trigger="{trigger}"></div>') == [], trigger


def test_htmx2_event_names_in_javascript():
    html = """<html><body>
    <script>
      document.body.addEventListener("htmx:configRequest", e => {});
      addEventListener('htmx:after-request', e => {});
      document.addEventListener(`htmx:after:swap`, e => e.detail.ctx);
      htmx.on("contacts-changed", e => {});
    </script>
    <button onclick="document.body.addEventListener('htmx:afterSwap', f)">x</button>
    </body></html>"""
    f = lint_html(html)
    assert [(x.rule, x.element, x.line) for x in f] == [("htmx2-event-name", "script", 3), ("htmx2-event-name", "script", 4), ("htmx2-event-name", "button", 8)]
    assert "htmx:configRequest is the htmx 2 event name; htmx 4 calls it htmx:config:request." == f[0].message
    assert "htmx 4 fires only htmx:after:request, so this listener never runs" in f[1].message
    assert lint_html('<script type="application/ld+json">{"name": "htmx:after:swap"}</script>') == []


def test_htmx2_event_names_in_hyperscript_and_alpine():
    hyperscript = """<button _="on click send htmx:abort to #contacts-btn
        on htmx:beforeRequest from #contacts-btn remove @disabled from me">Cancel</button>"""
    [finding] = lint_html(hyperscript)
    assert finding.rule == "htmx2-event-name" and "htmx:before:request" in finding.message  # htmx:abort is htmx 4's too
    assert finding.line == 1  # an attribute's findings carry its element's line
    assert rules(lint_html('<script type="text/hyperscript">on htmx:afterSwap log me</script>')) == ["htmx2-event-name"]
    assert len(lint_html('<form x-on:htmx:afterSwap="a()" @htmx:after-request.window="b()"></form>')) == 2
    assert lint_html('<form x-on:htmx:after:swap="a()" @htmx:after:request.window="b()"></form>') == []


def test_events_htmx_4_removed_and_htmx_load():
    [removed] = lint_html('<script>el.addEventListener("htmx:xhr:progress", show)</script>')
    assert removed.message == "htmx:xhr:progress is an htmx 2 event that htmx 4 no longer fires."
    [load] = lint_script('addEventListener("htmx:load", e => overflowMenu(e.target));', file="rsjs-menu.js")
    assert str(load).startswith("[error] htmx2-event-name rsjs-menu.js:1: htmx:load is the htmx 2 event name; htmx 4 calls it htmx:after:init.")
    assert "htmx.onLoad(fn)" in load.message
    assert rules(lint_html('<div hx-on::load="x()"></div>')) == ["htmx2-event-name"]
    assert lint_html('<a hx-on:load="this.click()">x</a>') == []  # the DOM's load, not htmx's


def test_detail_xhr_is_htmx_2():
    js = """document.body.addEventListener('htmx:before:swap', evt => {
      if (evt.detail.xhr.status === 404) { showNotFoundError(); }
    });"""
    [finding] = lint_script(js, file="app.js")
    assert (finding.rule, finding.severity, finding.line) == ("htmx2-detail-xhr", "error", 2)
    assert "htmx 4 uses fetch()" in finding.message and "ctx.response.status" in finding.message
    # The spike's held-out apps read it in hx-on handlers
    f = lint_html('<form hx-post="/x" hx-on::after:request="JSON.parse(event.detail.xhr.responseText)"></form>')
    assert rules(f) == ["htmx2-detail-xhr"]
    assert rules(lint_html("""<div _="on htmx:after:request if event.detail['xhr'].status is 200 log it"></div>""")) == ["htmx2-detail-xhr"]
    assert lint_script("evt.detail.ctx.response.status; xhrCount++; detail.xhrs") == []


def test_lint_paths_reads_scripts_and_skips_htmx_itself(tmp_path, capsys):
    (tmp_path / "js").mkdir()
    (tmp_path / "js" / "menu.js").write_text('addEventListener("htmx:load", init);\n')
    (tmp_path / "js" / "htmx-2-compat.js").write_text('maybeRetriggerEvent(elt, "htmx:load", detail);\n')
    (tmp_path / "js" / "htmx-4.0.0.min.js").write_text('trigger("htmx:afterSwap")\n')
    (tmp_path / "page.html").write_text("<p>ok</p>")
    assert lint_paths([str(tmp_path)]) == 1
    out = capsys.readouterr().out
    assert "menu.js:1" in out and "compat" not in out and "min.js" not in out
    assert "hx lint: 2 files, 1 errors" in out


def test_implicit_inheritance_is_the_2e_todo():
    archive_1e = '<div id="archive-ui" hx-target="this" hx-swap="outerHTML"><button hx-post="/archive">Go</button></div>'
    f = lint_html(archive_1e)
    assert rules(f) == ["implicit-inheritance"] and len(f) == 2
    assert "hx-target:inherited" in f[0].message
    body_1e = '<html><body hx-boost="true"><a href="/x">x</a></body></html>'
    f = lint_html(body_1e)
    assert rules(f, "error") == ["boost-not-inherited"] and "does nothing" in f[0].message
    assert lint_html('<html><body hx-boost:inherited="true"><a href="/x">x</a></body></html>') == []


def test_a_plain_boost_in_a_layout_is_an_error_though_the_links_are_elsewhere():
    layout = '<html><body hx-boost="true"><main>{% block content %}{% endblock %}</main></body></html>'
    f = lint_source(layout, file="layout.html")
    assert rules(f, "error") == ["boost-not-inherited"] and "hx-boost:inherited" in f[0].message
    assert lint_source('<div hx-boost="false"><a href="/x">x</a></div>') != []  # a plain false disables nothing either
    assert lint_source('<a hx-boost="false" href="/file">x</a><form hx-boost="true"></form>') == []
    assert lint_source('<div hx-boost:inherited="true">{% block content %}{% endblock %}</div>') == []


def test_delete_controls():
    f = lint_html('<form><button hx-delete="/c">x</button></form>')
    assert rules(f) == ["delete-default-swap", "delete-without-include"]
    assert lint_html('<form><button hx-delete="/c" hx-include="closest form" hx-target="tbody" hx-swap="outerHTML">x</button></form>') == []
    assert lint_html('<form hx-delete="/c" hx-swap="delete"></form>') == []


def test_missing_target_only_on_documents():
    html = '<html><body><button hx-get="/x" hx-target="#gone" hx-indicator="#spin">x</button></body></html>'
    assert rules(lint_html(html)) == ["missing-target"]
    assert lint_html('<button hx-get="/x" hx-target="#gone">x</button>') == []  # a fragment cannot know


def test_duplicate_ids_and_select_info():
    f = lint_html('<html><body><img id="spinner"><img id="spinner"><button hx-get="/x" hx-select="tbody > tr" hx-target="closest tr">x</button></body></html>')
    assert rules(f, "error") == ["duplicate-id"] and rules(f, "info") == ["select-not-body"]


def test_oob_in_a_template_is_noted_not_failed():
    f = lint_html('<div id="count" hx-swap-oob="true">3</div><div hx-select-oob="#flash"></div>')
    assert rules(f) == ["oob-in-template"] and {x.severity for x in f} == {"info"} and len(f) == 2
    assert ".partial()" in f[0].message


def test_extension_attributes_need_their_script_when_the_page_is_known():
    page = '<html><script src="/static/js/htmx-4.0.0.js"></script><body><div hx-live="x"></div></body></html>'
    assert rules(lint_html(page)) == ["extension-not-loaded"]
    page = page.replace("</script>", '</script><script src="/static/js/hx-live-4.0.0.js"></script>', 1)
    assert lint_html(page) == []
    assert lint_html('<div hx-live="x"></div>') == []  # a fragment: nothing says it is not loaded
    assert lint_html('<div hx-live="x"></div>', extensions=("hx-sse",)) != []


def test_extensions_answer_to_the_name_htmx_registers_as_well_as_the_file_name():
    # hx-sse.js registers 'sse', the name htmx.config.extensions takes; hx-live.js registers 'hx-live'
    for name in ("sse", "hx-sse"):
        assert lint_html('<div hx-sse:connect="/events"></div>', extensions=(name,)) == [], name
    assert lint_html('<div hx-swap="upsert"></div>', extensions=("upsert",)) == []
    assert rules(lint_html('<div hx-live="x"></div>', extensions=("sse",))) == ["extension-not-loaded"]


# ----------------------------------------------------------- template source


def test_source_mode_skips_jinja_and_finds_vocabulary_errors():
    src = '{% extends "layout.html" %}{% block content %}<a hx-get="{{ url_for(\'x\') }}" hx-trigger="load delay:{{ d }}" hx-swap="outerhtml">x</a>{% endblock %}'
    f = lint_source(src, file="t.html")
    assert rules(f) == ["swap-style-case"] and str(f[0]).startswith("[error] swap-style-case <a> t.html:1:")


def test_the_contact_app_templates_lint_clean(capsys):
    assert lint_paths([str(ROOT / "templates")]) == 0
    out = capsys.readouterr().out
    assert "0 errors" in out and "[warning]" not in out and "[error]" not in out


def test_the_contact_app_pages_lint_clean(client):
    for url, headers in (("/contacts", FULL), ("/contacts/1/edit", FULL), ("/contacts/new", FULL), ("/contacts/1", FULL), ("/contacts?q=a", PARTIAL), ("/contacts/archive", PARTIAL)):
        body = client.get(url, headers=headers).data.decode()
        assert [f for f in lint_html(body) if f.severity != "info"] == [], url


def test_the_lint_hook_is_wired_into_after_request(make_app):
    from hx import HxLintError, hx

    app = make_app({"bad.html": '<div hx-get="/x" hx-swap="outerhtml"></div>'})

    @app.get("/")
    def index():
        return hx.fragment("bad.html")

    with pytest.raises(HxLintError, match="swap-style-case"):
        app.test_client().get("/", headers=PARTIAL)
