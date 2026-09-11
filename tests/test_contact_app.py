"""The ported contact.app, exercised the way htmx 4 and a browser would."""

import json

import pytest

from hx import HxFragmentIntoPage, HxPageIntoFragment
from tests.conftest import FULL, PARTIAL


def test_index_redirects_to_contacts(client):
    r = client.get("/")
    assert (r.status_code, r.headers["Location"]) == (303, "/contacts")


def test_contacts_page_for_browsers_and_boosted_links(client):
    for headers in ({}, FULL):
        r = client.get("/contacts", headers=headers)
        body = r.data.decode()
        assert r.status_code == 200
        assert 'hx-boost:inherited="true"' in body
        assert body.count("<tr>") == 12  # header, ten rows, the Load More sentinel
        assert 'hx-get="/contacts?page=2"' in body
        assert "hx-select" not in body


def test_search_and_paging_get_rows_only(client):
    r = client.get("/contacts?q=a", headers=PARTIAL)
    body = r.data.decode()
    assert "<html" not in body and "<table" not in body and "<tr>" in body

    body = client.get("/contacts?page=2", headers=PARTIAL).data.decode()
    assert body.count("<tr>") == 11 and 'hx-get="/contacts?page=3"' in body


def test_row_delete_removes_and_flashes_in_place(client):
    r = client.delete("/contacts/3", headers=PARTIAL)
    body = r.data.decode()
    assert r.status_code == 200
    assert body.startswith('\n<hx-partial hx-target="#flash" hx-swap="outerHTML">')
    assert '<div class="flash">Deleted Contact!</div>' in body
    assert "<tr>" not in body
    assert b'value="3"' not in client.get("/contacts", headers=PARTIAL).data


def test_edit_page_delete_redirects_to_the_list_with_the_flash(client):
    r = client.delete("/contacts/3", headers=FULL)
    assert (r.status_code, r.headers["Location"]) == (303, "/contacts")
    page = client.get("/contacts", headers=FULL).data.decode()
    assert '<div class="flash">Deleted Contact!</div>' in page


def test_bulk_delete_rerenders_rows_and_announces(client):
    r = client.delete("/contacts?selected_contact_ids=1&selected_contact_ids=2", headers=PARTIAL)
    body = r.data.decode()
    assert r.status_code == 200
    assert json.loads(r.headers["HX-Trigger"]) == {"contacts-changed": {"target": "body"}}
    assert "<tr>" in body and 'value="1"' not in body and 'value="2"' not in body
    assert "Deleted Contacts!" in body


def test_bulk_delete_route_no_longer_needs_a_trailing_slash(client):
    assert client.delete("/contacts", headers=PARTIAL).status_code == 200


def test_new_contact_validation_is_422(client):
    form = {"first_name": "A", "last_name": "B", "phone": "1", "email": ""}
    r = client.post("/contacts/new", data=form, headers=FULL)
    assert r.status_code == 422 and b"<html" in r.data and b"Email Required" in r.data
    r = client.post("/contacts/new", data=form, headers=PARTIAL)
    assert r.status_code == 422 and b"<html" not in r.data and r.data.strip().startswith(b'<form id="form"')


def test_new_contact_success_redirects_and_flashes(client):
    form = {"first_name": "A", "last_name": "B", "phone": "1", "email": "ab@example.com"}
    r = client.post("/contacts/new", data=form, headers=FULL)
    assert (r.status_code, r.headers["Location"]) == (303, "/contacts")
    assert b"Created New Contact!" in client.get("/contacts").data


def test_edit_saves_and_redirects_to_the_contact(client):
    form = {"first_name": "Z", "last_name": "B", "phone": "1", "email": "zb@example.com"}
    r = client.post("/contacts/5/edit", data=form, headers=FULL)
    assert (r.status_code, r.headers["Location"]) == (303, "/contacts/5")
    assert b"<h1>Z B</h1>" in client.get("/contacts/5").data


def test_pages_refuse_to_answer_partial_requests(client):
    with pytest.raises(HxPageIntoFragment):
        client.get("/contacts/5", headers=PARTIAL)
    with pytest.raises(HxPageIntoFragment):
        client.get("/contacts/new", headers=PARTIAL)


def test_email_validation_and_count_are_text_fragments(client):
    r = client.get("/contacts/5/email?email=", headers=PARTIAL)
    assert r.data == b"Email Required"
    r = client.get("/contacts/count", headers=PARTIAL)
    assert r.data == b"(100 total Contacts)"
    with pytest.raises(HxFragmentIntoPage):
        client.get("/contacts/count", headers=FULL)


def test_archive_states_render_as_fragments(client, monkeypatch):
    from contacts_model import Archiver

    monkeypatch.setattr(Archiver, "run", lambda self: setattr(Archiver, "archive_status", "Running"))
    body = client.get("/contacts/archive", headers=PARTIAL).data.decode()
    assert "Download Contact Archive" in body and 'hx-target="#archive-ui"' in body
    body = client.post("/contacts/archive", headers=PARTIAL).data.decode()
    assert "Creating Archive" in body and 'hx-trigger="load delay:500ms"' in body
    Archiver.archive_status = "Complete"
    body = client.get("/contacts/archive", headers=PARTIAL).data.decode()
    assert 'hx-on:load="this.click()"' in body
    body = client.delete("/contacts/archive", headers=PARTIAL).data.decode()
    assert "Download Contact Archive" in body


def test_archive_download_passes_through_untouched(client):
    r = client.get("/contacts/archive/file", headers=PARTIAL)
    assert r.status_code == 200 and r.headers["Content-Disposition"].startswith("attachment")
    r.close()


def test_every_control_names_its_handler(app):
    """The templates use url_for, so a search for a function name finds every caller."""
    import pathlib

    for path in pathlib.Path(app.root_path, "templates").glob("*.html"):
        text = path.read_text()
        assert 'hx-get="/' not in text and 'hx-post="/' not in text and 'hx-delete="/' not in text, path.name
