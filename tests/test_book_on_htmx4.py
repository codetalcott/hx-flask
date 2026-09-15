"""
The scorecard: the book's contact.app, unchanged, loaded with htmx 4.

Templates and handlers are copied from bigskysoftware/contact-app at bfddbfc
(BSD 2-Clause), trimmed to the lines that break; the model is left out. The
chapter 9 additions (the Alpine toolbar, the RSJS menu) are from its master,
6b9449c; the chapter 8 examples are figures in the book, which the app never
included, from the 2nd-edition branch of bigskysoftware/hypermedia-systems-book
at 8e04898. Each test is a row of HTMX4.md and asserts the finding that catches
it, from code that never adopted an hx verb. The two marked ``browser`` observe
what htmx 4 does where reading its source was not enough.
"""

import pytest
from flask import Flask, flash, redirect, render_template, request

from hxlint import lint_html, lint_script, lint_source
from hxmap import build_map
from tests.conftest import ROOT

LAYOUT = """<html lang="">
<head>
    <title>Contact App</title>
    <script src="/static/js/htmx-1.8.0.js"></script>
</head>
<body hx-boost="true">
<main>
    {% for message in get_flashed_messages() %}
      <div class="flash">{{ message }}</div>
    {% endfor %}
    {% block content %}{% endblock %}
</main>
</body>
</html>"""

INDEX = """{% extends 'layout.html' %}

{% block content %}

    {% include 'archive_ui.html' %}

    <form action="/contacts" method="get" class="tool-bar">
        <label for="search">Search Term</label>
        <input id="search" type="search" name="q" value="{{ request.args.get('q') or '' }}"
               hx-get="/contacts"
               hx-trigger="search, keyup delay:200ms changed"
               hx-target="tbody"
               hx-push-url="true"
               hx-indicator="#spinner"/>
        <img style="height: 20px" id="spinner" class="htmx-indicator" src="/static/img/spinning-circles.svg"/>
        <input type="submit" value="Search"/>
    </form>

    <form>
    <table>
        <tbody>
        {% include 'rows.html' %}
        </tbody>
    </table>
        <button hx-delete="/contacts"
                hx-confirm="Are you sure you want to delete these contacts?"
                hx-target="body">
            Delete Selected Contacts
        </button>
    </form>
    <p>
        <a href="/contacts/new">Add Contact</a>
        <span hx-get="/contacts/count" hx-trigger="revealed">
          <img id="spinner" style="height: 20px"  class="htmx-indicator" src="/static/img/spinning-circles.svg"/>
        </span>
    </p>

{% endblock %}"""

ROWS = """{% for contact in contacts %}
    <tr>
        <td><input type="checkbox" name="selected_contact_ids" value="{{ contact.id }}"></td>
        <td>
            <a href="#" hx-delete="/contacts/{{ contact.id }}"
                        hx-confirm="Are you sure you want to delete this contact?"
                        hx-swap="outerHTML swap:1s"
                        hx-target="closest tr">Delete</a>
        </td>
    </tr>
{% endfor %}"""

ARCHIVE_UI = """<div id="archive-ui" hx-target="this" hx-swap="outerHTML">
    {% if archiver.status() == "Waiting" %}
        <button hx-post="/contacts/archive">
            Download Contact Archive
        </button>
    {% elif archiver.status() == "Running" %}
        <div hx-get="/contacts/archive" hx-trigger="load delay:500ms">
            Creating Archive...
        </div>
    {% elif archiver.status() == "Complete" %}
        <a hx-boost="false" href="/contacts/archive/file" _="on load click() me">Archive Downloading!</a>
        <button hx-delete="/contacts/archive">Clear Download</button>
    {% endif %}
</div>"""

BOOK = {"layout.html": LAYOUT, "index.html": INDEX, "rows.html": ROWS, "archive_ui.html": ARCHIVE_UI}

# ----------------------------------------------------- chapter 9, contact-app master (6b9449c)

INDEX_CH09 = """{% extends 'layout.html' %}

{% block content %}
    <form x-data="{ selected: [] }">
    <template
        x-if="selected.length > 0">
        <div class="box info tool-bar flxed top">
            <slot x-text="selected.length"></slot>
            contacts selected

            <button type="button" class="bad bg color border"
                @click="confirm(`Delete ${selected.length} contacts?`) &&
                    htmx.ajax('DELETE', '/contacts', { source: $root, target: document.body })"
            >Delete</button>
            <hr aria-orientation="vertical">
            <button type="button" @click="selected = []">Cancel</button>
        </div>
    </template>
    <table>
        <tbody>
        {% include 'rows.html' %}
        </tbody>
    </table>
    </form>
{% endblock %}"""

ROW_CH09 = """<tr>
        <td><input type="checkbox" name="selected_contact_ids" value="{id}"
            x-model="selected"></td>
        <td>
            <div data-overflow-menu>
                <button type="button" aria-haspopup="menu"
                    aria-controls="contact-menu-{id}"
                    >Options</button>
                <div role="menu" hidden id="contact-menu-{id}">
                    <a role="menuitem" href="/contacts/{id}/edit">Edit</a>
                    <a role="menuitem" href="/contacts/{id}">View</a>
                    <a role="menuitem" href="#"
                        hx-delete="/contacts/{id}"
                        hx-confirm="Are you sure you want to delete this contact?"
                        hx-swap="outerHTML swap:1s"
                        hx-target="closest tr">Delete</a>
                </div>
            </div>
        </td>
    </tr>"""

# static/js/rsjs-menu.js, without its keyboard handling
RSJS_MENU = """function overflowMenu(subtree = document) {
  subtree.querySelectorAll("[data-overflow-menu]").forEach(menuRoot => {
    const
    button = menuRoot.querySelector("[aria-haspopup]"),
    menu = menuRoot.querySelector("[role=menu]"),
    items = [...menu.querySelectorAll("[role=menuitem]")];

    const isOpen = () => !menu.hidden;

    items.forEach(item => item.setAttribute("tabindex", "-1"));

    function toggleMenu(open = !isOpen()) {
      if (open) {
        menu.hidden = false;
        button.setAttribute("aria-expanded", "true");
        items[0].focus();
      } else {
        menu.hidden = true;
        button.setAttribute("aria-expanded", "false");
      }
    }

    toggleMenu(isOpen());
    button.addEventListener("click", () => toggleMenu());
  })
}

addEventListener("htmx:load", e => overflowMenu(e.target));
"""

# ------------------------------------------- chapter 8 figures, 2nd-edition branch (8e04898)

CONFIG_REQUEST = """document.body.addEventListener("htmx:configRequest", configEvent => {
  configEvent.detail.headers['X-SPECIAL-TOKEN'] =
    localStorage['special-token'];
})"""

NOT_FOUND = """document.body.addEventListener('htmx:beforeSwap', evt => {
  if (evt.detail.xhr.status === 404) {
    showNotFoundError();
  }
});"""

ABORT = """<button id="contacts-btn" hx-get="/contacts" hx-target="body">
  Get Contacts
</button>
<button
  _="on click send htmx:abort to #contacts-btn
    on htmx:beforeRequest from #contacts-btn remove @disabled from me
    on htmx:afterRequest from #contacts-btn add @disabled to me">
  Cancel
</button>"""


@pytest.fixture
def book(make_app):
    return book_app(make_app(BOOK))


@pytest.fixture
def book_ch09(make_app):
    return book_app(make_app({**BOOK, "index.html": INDEX_CH09}))


def book_app(app):
    @app.route("/contacts")
    def contacts():
        search = request.args.get("q")
        if search:
            if request.headers.get("HX-Trigger") == "search":
                return render_template("rows.html", contacts=[])
        return render_template("index.html", contacts=[])

    @app.route("/contacts/<contact_id>", methods=["DELETE"])
    def contacts_delete(contact_id=0):
        if request.headers.get("HX-Trigger") == "delete-btn":
            flash("Deleted Contact!")
            return redirect("/contacts", 303)
        else:
            return ""

    @app.route("/contacts/", methods=["DELETE"])
    def contacts_delete_all():
        contact_ids = list(map(int, request.form.getlist("selected_contact_ids")))  # noqa: F841
        flash("Deleted Contacts!")
        return render_template("index.html", contacts=[])

    @app.route("/contacts/archive", methods=["POST", "GET", "DELETE"])
    def archive():
        return render_template("archive_ui.html", archiver=None)

    @app.route("/contacts/count")
    def contacts_count():
        return "(0 total Contacts)"

    return app


def findings(name, severity=None):
    return [f for f in lint_source(BOOK[name], file=name) if severity is None or f.severity == severity]


def test_the_layout_boosts_nothing():
    """`<body hx-boost="true">`: every link is a full page load, and nothing says so."""
    errors = findings("layout.html", "error")
    assert [f.rule for f in errors] == ["boost-not-inherited"]
    assert "hx-boost:inherited" in errors[0].message


def test_active_search_asks_for_a_header_htmx_4_does_not_send(book):
    """`HX-Trigger == 'search'` is never true, so the search puts the whole page into <tbody>."""
    assert any(e.startswith("contacts() reads the HX-Trigger request header, which htmx 4 does not send") for e in build_map(book).errors)


def test_the_edit_page_delete_asks_for_a_header_htmx_4_does_not_send(book):
    """`HX-Trigger == 'delete-btn'` is never true, so the edit page's Delete swaps "" into <body>."""
    assert any(e.startswith("contacts_delete() reads the HX-Trigger request header") for e in build_map(book).errors)


def test_bulk_delete_reads_a_form_it_is_never_sent(book):
    """DELETE values are query parameters: nothing is deleted, and the flash says it was."""
    errors = build_map(book).errors
    assert "index.html:25 <button> DELETE /contacts: DELETE /contacts is a 308 from URL routing (trailing slash?); fetch follows it silently" in errors
    assert any(e.startswith("contacts_delete_all() reads request.form on DELETE, but htmx 4 sends DELETE values as query parameters") for e in errors)


def test_two_spinners_share_an_id():
    """Latent rather than visible: hx-indicator="#spinner" finds the first, which happens to be search's."""
    assert [f.rule for f in findings("index.html", "error")] == ["duplicate-id"]


def test_the_archive_ui_targets_inherit_nothing():
    """Without :inherited each button targets itself with innerHTML: the next archive UI lands inside the button."""
    warnings = findings("archive_ui.html", "warning")
    assert {f.rule for f in warnings} >= {"implicit-inheritance"}
    assert any("hx-target:inherited" in f.message for f in warnings) and any("hx-swap:inherited" in f.message for f in warnings)


# ------------------------------------------------------------------ chapter 9


def test_the_toolbar_delete_reaches_the_handler_that_reads_a_form(book_ch09):
    """`htmx.ajax('DELETE', '/contacts', {source: $root, ...})`: a control the map now sees, reaching the same empty read."""
    m = build_map(book_ch09)
    toolbar = [c for c in m.controls if c.via == "htmx.ajax"]
    assert [(c.line, c.method, c.scope) for c in toolbar] == [(11, "DELETE", "full")]
    assert "index.html:11 <button.bad> DELETE /contacts: DELETE /contacts is a 308 from URL routing (trailing slash?); fetch follows it silently" in m.errors


@pytest.mark.browser
def test_the_toolbar_delete_sends_the_checkboxes_as_query_parameters(browser, serve):
    """Observed: the source form's values go, as a query string, so request.form is still empty."""
    received = []
    app = Flask("book_ch09", static_folder=str(ROOT / "static"))

    @app.get("/contacts")
    def contacts():
        rows = "".join(ROW_CH09.format(id=i) for i in (1, 2, 3))
        return f'<html><head><script src="/static/js/htmx-4.0.0.js"></script></head><body><form x-data="{{ selected: [] }}"><table><tbody>{rows}</tbody></table></form></body></html>'

    @app.route("/contacts/", methods=["DELETE"])
    def contacts_delete_all():
        contact_ids = list(map(int, request.form.getlist("selected_contact_ids")))
        received.append((contact_ids, request.args.getlist("selected_contact_ids"), request.headers.get("HX-Request-Type")))
        return '<p id="flash">Deleted Contacts!</p>'

    page = browser.new_page()
    page.goto(serve(app) + "/contacts")
    page.locator("input[value='1']").check()
    page.locator("input[value='2']").check()
    # Alpine is not loaded here; $root is the element with x-data
    page.evaluate("htmx.ajax('DELETE', '/contacts', { source: document.querySelector('[x-data]'), target: document.body })")
    page.wait_for_selector("#flash")
    assert received == [([], ["1", "2"], "full")]
    page.close()


def test_the_overflow_menu_waits_for_an_event_htmx_4_does_not_fire():
    [finding] = lint_script(RSJS_MENU, file="static/js/rsjs-menu.js")
    assert (finding.rule, finding.line) == ("htmx2-event-name", 28)
    assert "htmx:after:init" in finding.message and "htmx.onLoad(fn)" in finding.message


@pytest.mark.browser
def test_the_overflow_menu_opens_only_with_htmx_onload(browser, serve):
    """Observed: htmx:load never fires; htmx:after:init fires on the elements htmx initializes, which hold no menu."""
    app = Flask("book_ch09", static_folder=str(ROOT / "static"))
    variants = {
        "book": RSJS_MENU,
        "after-init": RSJS_MENU.replace('"htmx:load"', '"htmx:after:init"'),
        "onload": RSJS_MENU.replace('addEventListener("htmx:load", e => overflowMenu(e.target));', "htmx.onLoad(overflowMenu);"),
    }

    @app.get("/<variant>")
    def contacts(variant):
        return f"""<html><head><script src="/static/js/htmx-4.0.0.js"></script><script type="module">{variants[variant]}</script>
            <script>htmx.onLoad(() => document.body.dataset.processed = "yes")</script></head>
            <body><table><tbody>{ROW_CH09.format(id=1)}</tbody></table></body></html>"""

    base = serve(app)
    page = browser.new_page()
    opened = {}
    for variant in variants:
        page.goto(f"{base}/{variant}")
        page.wait_for_selector("body[data-processed]")
        page.get_by_text("Options").click()
        opened[variant] = page.locator("#contact-menu-1").is_visible()
    assert opened == {"book": False, "after-init": False, "onload": True}
    page.close()


def test_alpine_listens_for_a_kebab_case_event():
    """ch09's Alpine section: `x-on:htmx:after-request` listens for an event htmx 4 never fires."""
    [finding] = lint_html('<div x-on:htmx:after-request="doSomething()"></div>')
    assert finding.rule == "htmx2-event-name" and "htmx:after:request" in finding.message


# ------------------------------------------------------------------ chapter 8


def test_the_token_listener_waits_for_a_renamed_event():
    [finding] = lint_script(CONFIG_REQUEST)
    assert finding.message == "htmx:configRequest is the htmx 2 event name; htmx 4 calls it htmx:config:request."


def test_the_404_dialog_waits_for_a_renamed_event_and_reads_xhr():
    """htmx 4 swaps the 404 into the target; renamed alone, the listener would throw on detail.xhr."""
    assert [(f.rule, f.line) for f in lint_script(NOT_FOUND)] == [("htmx2-event-name", 1), ("htmx2-detail-xhr", 2)]


def test_the_cancel_button_waits_for_renamed_events():
    """The hyperscript Cancel button: `htmx:abort` is still htmx 4's; the two it listens for are not."""
    assert [f.message.split(";")[0] for f in lint_html(ABORT)] == [
        "htmx:beforeRequest is the htmx 2 event name",
        "htmx:afterRequest is the htmx 2 event name",
    ]
