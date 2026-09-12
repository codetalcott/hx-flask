# contact.app, handler-first

The contact application from *Hypermedia Systems*, on htmx 4, with the server
owning every outcome. Same routes, same templates, same model as the book's
`ch10-full` snapshot; the difference is where the decisions live.

- `hx.py` is the whole library, one file.
- `hxlint.py` lints rendered HTML and template source for the htmx 4 vocabulary.
- `hxmap.py` maps every control in the templates to the handler that answers it;
  the engine is `mapcore.py`.
- `hx_vocab.py` is generated from the htmx 4.0.0 source tree by `tools/gen_vocab.py`.
- `llms.txt` is the same reference as this file, self-contained, for an agent
  writing code against `hx.py`.

The same design for Django is [dj-hx](https://github.com/codetalcott/dj-hx),
which vendors `hxlint.py`, `hx_vocab.py` and `mapcore.py` from here.

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
   here reads `HX-Source` or `HX-Target`: the handler never reads an element id
   from the request. The only ids it names are block names, and the render
   checks each one.
3. **One template per resource.** Fragments are Jinja blocks of the page
   template, or a file the page includes, named in the handler; either way page
   and fragment are one source and cannot drift.

## Principles, stated so an agent can apply them

The three rules have working consequences. Each is a sentence to check code
against.

- **Never `return redirect(...)`, `return ""` or `return "", 204` to an htmx
  request.** Say what happened: `hx.redirect`, `hx.removed`, `hx.text`. A
  response built without a verb that answers a partial request is loud
  (`HxBareResponse`).
- **Never read `HX-Source` or `HX-Target`.** The real question is whether the
  client asked for a page or a fragment: `hx.wants_page`.
- **Announce facts; do not update regions.** Prefer `.trigger("contacts-changed")`
  with `hx-trigger="contacts-changed from:body"` on the element that cares, and
  `.partial()` only when the handler already holds the data and the region is a
  block of the same template. `.trigger()` always names a target, so the event
  lands whether or not the swap removed the element that asked. `hx-swap-oob`
  in a template does the handler's job; keep it for a swap style `.partial()`
  cannot express, and the lint notes each use.
- **The template predicts the DOM effect; the handler predicts the resource
  effect and the representation.** `.retarget()` and `.reswap()` exist and break
  the first half; use them with a comment saying why. `flask hx map` names
  every handler that calls one.
- **The template says whether a control navigates.** `hx-push-url="true"` on
  the control. htmx 4 pushes the final URL after a 303, so a handler rarely
  needs `.push_url()`; reserve `.push_url()` and `.replace_url()` for a canonical
  URL that differs from the one requested, with a comment.
- **Every control says `url_for`.** Then a control names the handler that
  answers it, a search for the handler finds every caller, and the trailing
  slash cannot drift from the route.
- **Every name is literal.** `hx.render("index.html", partial="rows")` is
  matched by `{% block rows %}` in that file; nothing is derived from a naming
  scheme. The one convention, a partial's root `id` equals its name, is checked
  at the render.

Silent failure, not API surface, is the friction, for people and agents alike.
Every row of the catalogue below lands on the first tier it can: delete the
dependency (there is no `source` or `target` to read; `.trigger()` cannot omit
a target), else fail at the first deterministic moment (the verbs raise, the
after-request guard is loud), else check statically (the lint, the map), else
document.

What was rejected, and why:

- **Controls declared in Python**, an `hx_attrs(get=..., target=...)` helper or
  control objects beside the handler. It hides what the search box does from a
  reader of `index.html`, it is a vocabulary agents have never seen, and it does
  not enforce the agreement it seems to promise. `flask hx map` does, from the
  HTML people and agents already write.
- **Server-side retargeting as a default.** `HX-Retarget`, `HX-Reswap` and
  `HX-Location` make a control's DOM effect invisible from the template.
- **htmx 2 compatibility.** Without `HX-Request-Type` the page-or-fragment
  question is a guess.
- **Decorators that render a returned dict.** A handler that sometimes returns a
  dict and sometimes a redirect has two return types, which is an agent trap.

## The vocabulary

```python
from hx import HX, hx

HX(app, flash_template="layout.html")   # Vary, the guards, the flash bridge, the lint

hx.is_htmx / hx.wants_page / hx.wants_fragment      # HX-Request-Type, nothing else

hx.render("index.html", partial="rows", **ctx)     # the page, or the block, by request type
hx.page("show.html", **ctx)                        # always the page; raises on a partial request
hx.fragment("archive_ui.html", **ctx)              # always a fragment: a file, or partial="block"; loud on a boosted request
hx.invalid("new.html", partial="form", **ctx)      # render, status 422
hx.redirect(url)                                   # a plain 303; raises on a partial request
hx.removed()                                       # 200, empty; the control's hx-swap="delete" acts
hx.text("(3 total)")                               # an escaped text fragment

response.trigger("contacts-changed")               # HX-Trigger, always JSON, always with a target (body)
response.partial("count")                          # appends <hx-partial hx-target="#count"> from the block
response.push_url(url) / .replace_url(url) / .with_status(code)
response.retarget(selector) / .reswap(spec)        # the escape hatches; the map reports them
```

Four words, because htmx and Jinja each have their own:

- **Page**: the full document; what a browser, a boosted link or a body-targeted
  control gets.
- **Fragment**: what a control that targets an element gets; a block of the page
  template, or a file the page includes.
- **Partial**: htmx 4's word. `HX-Request-Type: partial` is a request for a
  fragment; `<hx-partial>` is an extra region in a response; `partial=` names
  the block; `.partial("count")` appends one.
- **Block**: Jinja's word for the region `partial=` names. A `partial=`
  containing a dot (`rows.html`) is a file instead.

`flash()` keeps working: on a fragment response, pending messages are rendered
through the layout's `flash` block and appended as an `<hx-partial>`.

## What is loud

Every row of the design's silent-failure catalogue has a test in `tests/`. The
verbs raise where the outcome is certain at call time and the alternative is a
corrupted DOM. Everything the after-request guard finds raises under
`app.testing` and is logged otherwise, so a false positive cannot 500 a live
app.

| Failure | What happens now | In production |
|---|---|---|
| A page answers a request that targets an element | `hx.page` raises `HxPageIntoFragment` | raises |
| A fragment answers a boosted or body-targeted request | `hx.fragment` / `hx.text` raise `HxFragmentIntoPage` | logs |
| `hx.redirect` answers a partial request | raises `HxRedirectIntoFragment` | raises |
| Any other 3xx answers a partial request, including Werkzeug's slash 308 | the guard raises `HxRedirectIntoFragment`, naming the handler or the routing | logs |
| A 204 answers a partial request | `HxNoSwap`: htmx 4 leaves the target untouched | logs |
| A response built without an hx verb answers a partial request | `HxBareResponse`: `render_template`, a string or `make_response` cannot be checked | logs |
| `flash()` on a fragment with no flash template | `HxFlashUnconfigured` | logs |
| A block used as a partial whose root is not `id="<block>"` | `HxPartialRootId` at the render | raises |
| `partial=` names a block the template does not define | `HxUnknownBlock`, listing the blocks it does | raises |
| `hx.render` called with no `partial=` | `HxError`, naming `hx.page` for a page-only handler | raises |
| An htmx request without `HX-Request-Type` | `HxProtocolError`: this needs htmx 4 | raises |
| htmx 2 idioms in the HTML: `hx-ext`, implicit inheritance, camelCase events, `show:#x:top` | `hxlint`, on every test response and in `flask hx lint` | off unless `HX(lint=True)`; then logs |
| A partial control pointing at a page-only handler, or a boosted link at a fragment-only one | `flask hx map` | |
| A control pointing at a handler that calls no hx verb; a handler that calls `.retarget()` or `.reswap()` | `flask hx map`, as warnings | |

## htmx 4 facts this depends on

All verified against `src/htmx.js` at tag v4.0.0.

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
