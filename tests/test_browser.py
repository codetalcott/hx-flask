"""
A real browser against the ported app: the protocol claims the design makes,
observed rather than reasoned about. Needs Playwright and a Chromium build:

    .venv/bin/python -m playwright install chromium
    .venv/bin/python -m pytest -m browser
"""

import threading

import pytest

pytestmark = pytest.mark.browser
sync_api = pytest.importorskip("playwright.sync_api")


@pytest.fixture
def live(app):
    from werkzeug.serving import make_server

    server = make_server("127.0.0.1", 0, app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


@pytest.fixture(scope="module")
def browser():
    with sync_api.sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


@pytest.fixture
def page(browser):
    context = browser.new_context()
    page = context.new_page()
    page.on("dialog", lambda d: d.accept())
    console_errors = []
    # A 4xx response is logged by the browser as a failed resource; that is the
    # status doing its job, not an error in the page.
    page.on("console", lambda m: console_errors.append(m.text) if m.type == "error" and "Failed to load resource" not in m.text else None)
    page.on("pageerror", lambda e: console_errors.append(str(e)))
    page.console_errors = console_errors
    yield page
    context.close()


expect = sync_api.expect


def reveal_count(page):
    """The count loads on 'revealed'; in a headless viewport it starts below the fold."""
    page.locator("#count").scroll_into_view_if_needed()


def test_lazy_count_then_row_delete_fades_out_and_flashes_in_place(page, live):
    page.goto(f"{live}/contacts")
    reveal_count(page)
    expect(page.locator("#count")).to_have_text("(100 total Contacts)")
    expect(page.locator("tbody tr")).to_have_count(11)  # ten rows and Load More
    first = page.locator("tbody tr").first
    name = first.locator("td").nth(1).inner_text()
    first.get_by_text("Delete").click()  # the dialog is accepted by the fixture
    expect(page.locator("tbody tr")).to_have_count(10, timeout=4000)  # after the 1s fade
    expect(page.locator("tbody")).not_to_contain_text(name)
    expect(page.locator("#flash")).to_contain_text("Deleted Contact!")
    assert page.console_errors == []


def test_bulk_delete_rerenders_rows_and_the_count_hears_the_event(page, live):
    page.goto(f"{live}/contacts")
    reveal_count(page)
    expect(page.locator("#count")).to_have_text("(100 total Contacts)")
    boxes = page.locator("input[name=selected_contact_ids]")
    boxes.nth(0).check()
    boxes.nth(1).check()
    page.get_by_text("Delete Selected Contacts").click()
    expect(page.locator("#count")).to_have_text("(98 total Contacts)")  # contacts-changed reached body
    expect(page.locator("#flash")).to_contain_text("Deleted Contacts!")
    expect(page.locator("tbody tr")).to_have_count(11)
    assert page.console_errors == []


def test_delete_from_the_edit_page_lands_on_the_list_with_the_flash(page, live):
    page.goto(f"{live}/contacts/5/edit")
    page.get_by_text("Delete Contact", exact=True).click()
    expect(page).to_have_url(f"{live}/contacts")  # the URL after a plain 303, pushed by htmx
    expect(page.locator("#flash")).to_contain_text("Deleted Contact!")
    expect(page.locator("tbody tr")).to_have_count(11)
    assert page.locator("html").count() == 1


def test_active_search_swaps_rows_and_pushes_the_url(page, live):
    page.goto(f"{live}/contacts")
    page.locator("#search").type("an")
    expect(page).to_have_url(f"{live}/contacts?q=an")
    rows = page.locator("tbody tr")
    expect(rows.first).to_contain_text("an", ignore_case=True)
    assert "Load More" not in page.locator("tbody").inner_text()


def test_load_more_appends_the_next_page(page, live):
    page.goto(f"{live}/contacts")
    page.get_by_text("Load More").click()
    expect(page.locator("tbody tr")).to_have_count(21)
    assert page.locator("tbody").inner_text().count("Load More") == 1


def test_validation_error_swaps_a_422_page_into_the_body(page, live):
    page.goto(f"{live}/contacts/new")
    page.fill("#first_name", "Ada")
    page.fill("#last_name", "Lovelace")
    page.fill("#phone", "555")
    page.get_by_text("Save").click()
    expect(page.locator(".error").first).to_have_text("Email Required")
    assert page.locator("html").count() == 1
    assert page.console_errors == []


def test_new_contact_success_redirects_with_the_flash(page, live):
    page.goto(f"{live}/contacts/new")
    page.fill("#first_name", "Ada")
    page.fill("#last_name", "Lovelace")
    page.fill("#phone", "555")
    page.fill("#email", "ada@example.com")
    page.get_by_text("Save").click()
    expect(page).to_have_url(f"{live}/contacts")
    expect(page.locator("#flash")).to_contain_text("Created New Contact!")
