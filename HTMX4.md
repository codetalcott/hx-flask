# contact.app on htmx 4

What the *Hypermedia Systems* contact app does when it loads htmx 4.0.0 with no
other change, and which check in this repository reports each problem. The
templates and handlers are copied from
[bigskysoftware/contact-app](https://github.com/bigskysoftware/contact-app) at
`bfddbfc`, trimmed to the lines involved. None of them use `hx.py`. Every row
below is a test in [`tests/test_book_on_htmx4.py`](tests/test_book_on_htmx4.py).
Line numbers refer to `static/js/htmx-4.0.0.js`.

## What breaks

| The book's code | What a reader sees | The htmx 4 change | Reported by |
|---|---|---|---|
| `layout.html`: `<body hx-boost="true">` | Every link and form is a full page load, silently | Attributes reach descendants only with `:inherited`, and only `<a>` and `<form>` are boosted (941-964) | `flask hx lint`: `boost-not-inherited` (error) |
| `contacts()`: `request.headers.get('HX-Trigger') == 'search'` | Typing in the search box swaps the whole page into `<tbody>` | The request header naming the element is now `HX-Source` (434); `HX-Trigger` exists only as a response header | `flask hx map` (error) |
| `contacts_delete()`: `request.headers.get('HX-Trigger') == 'delete-btn'` | The edit page's Delete Contact empties `<body>` | Same | `flask hx map` (error) |
| `contacts_delete_all()`: `request.form.getlist("selected_contact_ids")` | Delete Selected deletes nothing and flashes "Deleted Contacts!" | GET and DELETE send their values as query parameters, and include the enclosing form only with `hx-include` (476-485) | `flask hx map` (error) |
| `archive_ui.html`: `hx-target="this" hx-swap="outerHTML"` on the wrapper | Each archive state renders inside the button or div that asked for it | Inheritance needs `:inherited`; the default target is the element itself and the default swap is `innerHTML` (191, 458) | `flask hx lint`: `implicit-inheritance` (warning) |

Present in the snapshot before htmx 4, and reported by the same checks:

- The delete-all route is `/contacts/` while the button says `/contacts`.
  Werkzeug answers with a 308 and fetch follows it, so the request works by
  accident (`flask hx map`, error).
- `index.html` has two `id="spinner"` elements. `hx-indicator="#spinner"` finds
  the first one, which happens to be the right one (`flask hx lint`, error).

This port also fixes several `ch10-full` details unrelated to htmx: `PAGE_SIZE`
is 10, matching the chapter's paging (the snapshot had 100); `contacts()` passes
`page` to `Contact.all`; Load More asks for `page + 1` behind
`contacts|length == 10`.

Not covered: later chapters (the Alpine toolbar, the RSJS menu), the JSON API,
_hyperscript, and anything that depends on runtime data.

## htmx 4 facts this relies on

- `HX-Request-Type` is `full` when the target is the body or `hx-select` is set,
  else `partial` (578). A handler can choose page or fragment from it alone.
- htmx 4 sends `HX-Source` for the requesting element and `HX-Target` for the
  target, but no `HX-Trigger` request header (402-442).
- `hx-delete` sends query parameters and excludes the enclosing form unless the
  control says `hx-include` (476-485).
- Only 204 and 304 skip the swap (202); a 422 body swaps with no client
  configuration.
- A `delete` swap runs whatever the response contains (1314), and honors `swap:1s`.
- `hx-push-url="true"` pushes the final URL after a redirect, so a plain 303
  updates the location bar.
- An `HX-Trigger` response header fires on the source element, or on `document`
  if the swap removed it (1573).
