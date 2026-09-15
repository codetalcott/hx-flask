# contact.app on htmx 4

What the *Hypermedia Systems* contact app does when it loads htmx 4.0.0 with no
other change, and which check in this repository reports each problem. The
templates and handlers are copied from
[bigskysoftware/contact-app](https://github.com/bigskysoftware/contact-app) at
`bfddbfc`, trimmed to the lines involved. The chapter 9 additions come from its
`master` at `6b9449c`, and the chapter 8 examples from the book's figures. None
of them use `hx.py`. Every row below is a test in
[`tests/test_book_on_htmx4.py`](tests/test_book_on_htmx4.py). Line numbers in
the htmx 4 column refer to `static/js/htmx-4.0.0.js`. "Observed" means a
Chromium test confirms what reading the source suggests.

The last column tracks the `2nd-edition` branch of
[bigskysoftware/hypermedia-systems-book](https://github.com/bigskysoftware/hypermedia-systems-book/tree/2nd-edition)
at `8e04898` (2026-04-21). Each row is **fixed**, **TODO** (an inline
`// TODO:` in a chapter, or an item in `TODO.md`) or **not yet noted**.
Chapter line numbers refer to the `.typ` files on that branch.

## What breaks

| The book's code | What a reader sees | The htmx 4 change | Reported by | 2nd-edition draft |
|---|---|---|---|---|
| `layout.html`: `<body hx-boost="true">` | Every link and form is a full page load, silently | Attributes reach descendants only with `:inherited`, and only `<a>` and `<form>` are boosted (941-964) | `flask hx lint`: `boost-not-inherited` (error) | **TODO** at ch05:277. The Attribute Inheritance section's `<div hx-boost="true">` examples (ch05:185, 209) are not marked |
| `contacts()`: `request.headers.get('HX-Trigger') == 'search'` | Typing in the search box swaps the whole page into `<tbody>` | The request header naming the element is now `HX-Source` (434); `HX-Trigger` exists only as a response header | `flask hx map` (error) | **Not yet noted.** Still taught in ch06 (289-318, 429, 626, 704) |
| `contacts_delete()`: `request.headers.get('HX-Trigger') == 'delete-btn'` | The edit page's Delete Contact empties `<body>` | Same | `flask hx map` (error) | **Not yet noted.** Still taught in ch06 (992-1042) |
| `contacts_delete_all()`: `request.form.getlist("selected_contact_ids")` | Delete Selected deletes nothing and flashes "Deleted Contacts!" | GET and DELETE send their values as query parameters, and include the enclosing form only with `hx-include` (476-485) | `flask hx map` (error) | **Fixed** in ch06 prose (`hx-include="closest form"`, `request.args.getlist`, 1253-1310). `code/ch10-full/app.py:128` still reads `request.form`, and that snapshot still loads htmx 1.8.0 |
| `archive_ui.html`: `hx-target="this" hx-swap="outerHTML"` on the wrapper | Each archive state renders inside the button or div that asked for it | Inheritance needs `:inherited`; the default target is the element itself and the default swap is `innerHTML` (191, 458) | `flask hx lint`: `implicit-inheritance` (warning) | **TODO** at ch07:154 |

Present in the snapshot before htmx 4, and reported by the same checks. Both
are still in the branch's `code/ch10-full`:

- The delete-all route is `/contacts/` while the button says `/contacts`.
  Werkzeug answers with a 308 and fetch follows it, so the request works by
  accident (`flask hx map`, error).
- `index.html` has two `id="spinner"` elements. `hx-indicator="#spinner"` finds
  the first one, which happens to be the right one (`flask hx lint`, error).

This port also fixes several `ch10-full` details unrelated to htmx: `PAGE_SIZE`
is 10, matching the chapter's paging (the snapshot had 100); `contacts()` passes
`page` to `Contact.all`; Load More asks for `page + 1` behind
`contacts|length == 10`.

## Chapters 8 and 9: events and scripting

The branch's `TODO.md` plans to "rewrite ch08 events section for htmx 4 event
names" and "mirror the rename into ch09", and to rewrite the ch08
response-codes section. These rows are the code those items cover.

| The book's code | What a reader sees | The htmx 4 change | Reported by | 2nd-edition draft |
|---|---|---|---|---|
| ch08 figures: `document.body.addEventListener("htmx:configRequest", ...)` setting `detail.headers` or `detail.parameters` | No request carries `X-SPECIAL-TOKEN` or `token` | The event is `htmx:config:request` (510), and its detail is `{ctx}`: the header goes in `detail.ctx.request.headers` | `flask hx lint`: `htmx2-event-name` (error). Nothing reports `detail.headers` | **TODO** in `TODO.md` (ch08:436, 473) |
| ch08 figure: `addEventListener('htmx:beforeSwap', ...)` testing `evt.detail.xhr.status === 404` | The 404 response swaps into the target, and `showNotFoundError()` never runs | Every status but 204 and 304 swaps (202). The event is `htmx:before:swap` (1270); htmx 4 uses `fetch()`, so the detail has no `xhr`, and renaming the event alone makes the listener throw | `flask hx lint`: `htmx2-event-name` and `htmx2-detail-xhr` (errors) | **TODO** in `TODO.md`, both sections (ch08:677) |
| ch08 figure, hyperscript: `on htmx:beforeRequest from #contacts-btn` / `on htmx:afterRequest ...` | The Cancel button's `disabled` never changes | The events are `htmx:before:request` and `htmx:after:request` (579, 591); `htmx:abort` is unchanged (1995) | `flask hx lint`: `htmx2-event-name` (error) | **TODO** in `TODO.md` (ch08:536) |
| `rsjs-menu.js`: `addEventListener("htmx:load", e => overflowMenu(e.target))` | No Options menu opens, so each row's Edit, View and Delete are out of reach | htmx 4 fires no `htmx:load`. Its documented rename, `htmx:after:init`, fires on each element that has htmx attributes, and none of those contains a menu. `htmx.onLoad(overflowMenu)` works (1529). Observed | `flask hx lint static/js`: `htmx2-event-name` (error) | **TODO** in `TODO.md` (ch09:667) |
| ch09, Alpine: `x-on:htmx:after-request="doSomething()"` | `doSomething()` never runs | htmx 4 fires `htmx:after:request` and no kebab-case alias | `flask hx lint`: `htmx2-event-name` (error) | **TODO** in `TODO.md` (ch09:933) |
| `index.html`, the Alpine toolbar: `htmx.ajax('DELETE', '/contacts', { source: $root, target: document.body })` | Delete in the selection toolbar deletes nothing | The source form's checkboxes are sent, as query parameters (476-485, 1577). `contacts_delete_all()` reads `request.form`, as in the row above. Observed | `flask hx map` (errors: the 308, and `request.form` on DELETE) | **Not yet noted** at ch09:1065; its handler is the ch06 row's, fixed in prose |

Not covered: chapter 8's other TODOs (the hoisted `hx-target`/`hx-sync` at
ch08:324, out-of-band swaps at 716, `class-tools` at 850), the JSON API, and
anything that depends on runtime data.

## htmx 4 facts this relies on

- `HX-Request-Type` is `full` when the target is the body or `hx-select` is set,
  else `partial` (578). A handler can choose page or fragment from it alone.
- htmx 4 sends `HX-Source` for the requesting element and `HX-Target` for the
  target, but no `HX-Trigger` request header (402-442).
- `hx-delete` sends query parameters and excludes the enclosing form unless the
  control says `hx-include` (476-485). A form that is itself the source, as in
  `htmx.ajax(..., {source: form})`, sends its values.
- Only 204 and 304 skip the swap (202); a 422 body swaps with no client
  configuration.
- A `delete` swap runs whatever the response contains (1314), and honors `swap:1s`.
- `hx-push-url="true"` pushes the final URL after a redirect, so a plain 303
  updates the location bar.
- An `HX-Trigger` response header fires on the source element, or on `document`
  if the swap removed it (1573).
- No htmx event's detail has htmx 2's `xhr`, `headers`, `parameters` or `elt`.
  The request and swap events carry `{ctx}`: `ctx.request.headers`,
  `ctx.response.status`, `ctx.text` (510-591, 1270).
- `htmx.onLoad(fn)` calls `fn` with each root htmx processes: the body at load,
  the new content after a swap (1529).
