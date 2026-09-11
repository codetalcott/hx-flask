# contact.app, handler-first

The contact application from *Hypermedia Systems*, on htmx 4, with the server
owning every outcome. Same routes, same templates, same model as the book's
`ch10-full` snapshot; the difference is where the decisions live.

- `hx.py` is the whole library, about 250 lines including docstrings.
- `hxlint.py` lints rendered HTML and template source for the htmx 4 vocabulary.
- `hxmap.py` maps every control in the templates to the handler that answers it.
- `hx_vocab.py` is generated from the htmx 4.0.0 source tree by `tools/gen_vocab.py`.

The design and the reasoning behind it are in the "Handler-first htmx for Flask"
design document; the short version is below.

## Run it

```
uv venv && uv pip install flask
.venv/bin/flask --app app run
```

Then open http://127.0.0.1:5000. Tests:

```
uv pip install pytest playwright
.venv/bin/python -m playwright install chromium     # only for tests/test_browser.py
.venv/bin/python -m pytest                          # -m "not browser" to skip the real browser
.venv/bin/flask --app app hx lint templates         # the static lint
.venv/bin/flask --app app hx map                    # controls <-> handlers, checked
```

## The three rules

1. **The handler owns every response-side decision**: which representation, the
   status, what changed elsewhere, what to announce. It says so through htmx 4's
   own protocol: `HX-Request-Type` in; `HX-Trigger`, `<hx-partial>`, 422 and a
   plain 303 out.
2. **The HTML keeps the request-side controls and stays sufficient to predict
   the DOM effect.** `hx-get`, `hx-target`, `hx-trigger`, `hx-swap` live in the
   template. Nothing here changes a target or a swap from a header, and nothing
   here reads `HX-Source` or `HX-Target`: the handler never learns an element id.
3. **One template per resource.** Fragments are Jinja blocks of the page
   template, named in the handler, so page and fragment cannot drift.

## The vocabulary

```python
from hx import HX, hx

HX(app, flash_template="layout.html")   # Vary, the guards, the flash bridge, the lint

hx.is_htmx / hx.wants_page / hx.wants_fragment      # HX-Request-Type, nothing else

hx.render("index.html", partial="rows", **ctx)     # the page, or the block, by request type
hx.page("show.html", **ctx)                        # always the page; raises on a partial request
hx.fragment("archive_ui.html", **ctx)              # always a fragment; loud on a boosted request
hx.invalid("new.html", partial="form", **ctx)      # render, status 422
hx.redirect(url)                                   # a plain 303; raises on a partial request
hx.removed()                                       # 200, empty; the control's hx-swap="delete" acts
hx.text("(3 total)")                               # an escaped text fragment

response.trigger("contacts-changed")               # HX-Trigger, always JSON, always with a target (body)
response.partial("count")                          # appends <hx-partial hx-target="#count"> from the block
response.push_url(url) / .replace_url(url) / .with_status(code)
```

`flash()` keeps working: on a fragment response, pending messages are rendered
through the layout's `flash` block and appended as an `<hx-partial>`.

## What is loud

Every row of the design's silent-failure catalogue has a test in `tests/`.
Under `app.testing` these raise; otherwise they log.

| Failure | What happens now |
|---|---|
| A page answers a request that targets an element | `hx.page` raises `HxPageIntoFragment` |
| A fragment answers a boosted or body-targeted request | `hx.fragment` / `hx.text` raise `HxFragmentIntoPage` |
| Any 3xx answers a partial request, including Werkzeug's slash 308 | `HxRedirectIntoFragment`, naming the handler or the routing |
| A 204 answers a partial request | `HxNoSwap`: htmx 4 leaves the target untouched |
| `flash()` on a fragment with no flash template | `HxFlashUnconfigured` |
| A block used as a partial whose root is not `id="<block>"` | `HxPartialRootId` at the render |
| `partial=` names a block the template does not define | `HxUnknownBlock`, listing the blocks it does |
| An htmx request without `HX-Request-Type` | `HxProtocolError`: this needs htmx 4 |
| htmx 2 idioms in the HTML: `hx-ext`, implicit inheritance, `revealed`, camelCase events, `show:#x:top` | `hxlint`, on every test response and in `flask hx lint` |
| A partial control pointing at a page-only handler, or a boosted link at a fragment-only one | `flask hx map` |

## htmx 4 facts this depends on

All verified against `src/htmx.js` at tag v4.0.0, line numbers in the design document.

- `HX-Request-Type` is `full` when the target is the body or `hx-select` is set, else `partial`.
- `hx-push-url="true"` pushes the URL after redirects, so a plain 303 updates the location bar.
- A `delete` swap runs regardless of response content, and honors `swap:1s`.
- `HX-Trigger` fires on the source element, or the swap target, or `document` if both are gone. That is why `.trigger()` always sets a `target`.
- Attributes reach descendants only with `:inherited`; `<body hx-boost="true">` boosts nothing.
- `hx-delete` sends query parameters and excludes the enclosing form unless asked with `hx-include`.
- Only 204 and 304 skip the swap. A 422 body swaps with no client configuration.

## Repairs to the book snapshot, named so nobody attributes them to the design

- `PAGE_SIZE` is 10, matching the paging the chapter describes; the snapshot had 100.
- `contacts()` passes `page` to `Contact.all`.
- The delete-all route is `/contacts`, not `/contacts/`, which Werkzeug answered with a 308.
- Load More asks for `page + 1` behind `contacts|length == 10`.
- The two `id="spinner"` are now one `#search-spinner` and an unnamed indicator.
