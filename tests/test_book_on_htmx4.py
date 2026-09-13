"""
The scorecard: the book's contact.app, unchanged, loaded with htmx 4.

Templates and handlers are copied from bigskysoftware/contact-app at bfddbfc
(BSD 2-Clause), trimmed to the lines that break; the model is left out. Each
test is a row of HTMX4.md and asserts the finding that catches it, from code
that never adopted an hx verb.
"""

import pytest
from flask import flash, redirect, render_template, request

from hxlint import lint_source
from hxmap import build_map

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


@pytest.fixture
def book(make_app):
    app = make_app(BOOK)

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
