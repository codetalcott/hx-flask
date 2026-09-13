# contact.app, handler-first

The contact application from *Hypermedia Systems*, on htmx 4, with the server
owning every response-side decision. Same routes, templates and model as the
book's `ch10-full` snapshot; the difference is where the decisions live.

- `hx.py` is the library, one file.
- `hxlint.py` lints rendered HTML and template source for the htmx 4 vocabulary.
- `hxmap.py` maps every control in the templates to the handler that answers it,
  and checks the two agree; the engine is `mapcore.py`.
- `hx_vocab.py` is generated from the htmx 4.0.0 source tree by `tools/gen_vocab.py`.

[`llms.txt`](llms.txt) is the reference: the vocabulary, the principles, the
glossary, every error and every check. [`HTMX4.md`](HTMX4.md) is what the book's
own app breaks on htmx 4, and what catches each break.

The same design for Django is [dj-hx](https://github.com/codetalcott/dj-hx),
which vendors `hxlint.py`, `hx_vocab.py` and `mapcore.py` from here.

## Run it

```
uv venv && uv pip install flask
.venv/bin/flask --app app run
```

Then open http://127.0.0.1:5000. Tests and tools:

```
uv pip install pytest playwright
.venv/bin/python -m playwright install chromium     # only for tests/test_browser.py
.venv/bin/python -m pytest                          # -m "not browser" to skip the real browser
.venv/bin/flask --app app hx lint templates         # the static lint
.venv/bin/flask --app app hx map                    # controls <-> handlers, checked
.venv/bin/flask --app app hx map --by-template      # the same map, read from the templates
```

## Use it in your app

Nothing is on PyPI. Copy the files next to the module that creates your app;
they need Flask and nothing else.

| File | Gives you | Without it |
|---|---|---|
| `hx.py` | the verbs, the guards, the flash bridge, `flask hx` | |
| `hxlint.py`, `hx_vocab.py` | the lint on every HTML response under `app.testing` or `app.debug`, and `flask hx lint` | `HxLintError`, until you copy them or pass `HX(app, lint=False)` |
| `mapcore.py`, `hxmap.py` | `flask hx map` | `flask hx map` cannot run |

Then:

1. `HX(app, flash_template="layout.html")`, or `HX(flash_template=...).init_app(app)`
   in a factory. The CLI takes a factory too: `flask --app "pkg:create_app()" hx map`.
2. Load htmx 4 (`static/js/htmx-4.0.0.js` here) and boost with
   `<body hx-boost:inherited="true">`.
3. Give every control `url_for(...)`. The map cannot resolve a URL built by
   hand, and warns instead of checking it.
4. In tests, send the headers htmx 4 sends:
   `{"HX-Request": "true", "HX-Request-Type": "partial"}`, or `"full"`.
5. Run `flask hx lint templates` and `flask hx map` in CI; each exits 1 on errors.

Hand an agent [`llms.txt`](llms.txt).

## The three rules

1. **The handler owns every response-side decision**: which representation, the
   status, what changed elsewhere, what to announce. It says so through htmx 4's
   own protocol: `HX-Request-Type` in; `HX-Trigger`, `<hx-partial>`, 422, a
   plain 303 and `HX-Redirect` out.
2. **The HTML keeps the request-side controls and stays sufficient to predict
   the DOM effect.** `hx-get`, `hx-target`, `hx-trigger`, `hx-swap` live in the
   template. Nothing changes a target or a swap from a header, and the handler
   never reads an element id from the request (`HX-Source`, `HX-Target`).
3. **One template per resource.** Fragments are Jinja blocks of the page
   template, or a file the page includes, named in the handler; either way page
   and fragment are one source and cannot drift.

## What is loud

Silent failure, not API surface, is the friction. Each failure lands on the
first tier it can: delete the dependency, else fail at the first deterministic
moment, else check statically, else document. The verbs raise where the outcome
is certain at call time; what the after-request guard finds raises under
`app.testing` and is logged otherwise, so a false positive cannot 500 a live
app. Every row has a test.

| Failure | What happens now | In production |
|---|---|---|
| A page answers a request that targets an element | `hx.page` raises `HxPageIntoFragment` | raises |
| A fragment answers a boosted or body-targeted request | `hx.fragment` / `hx.text` raise `HxFragmentIntoPage` | logs |
| `hx.redirect` answers a partial request | raises `HxRedirectIntoFragment` | raises |
| Any other 3xx but 304 answers a partial request, including Werkzeug's slash 308 and a login check's 302 | the guard raises `HxRedirectIntoFragment`, naming the handler or the routing, and `hx.navigate` for leaving the page | logs |
| A 204 answers a partial request | `HxNoSwap`: htmx 4 leaves the target untouched | logs |
| A response built without an hx verb answers a partial request | `HxBareResponse`: `render_template`, a string or `make_response` cannot be checked | logs |
| `flash()` on a fragment with no flash template | `HxFlashUnconfigured` | logs |
| A block used as a partial whose root is not `id="<block>"` | `HxPartialRootId` at the render | raises |
| `partial=` names a block the template does not define | `HxUnknownBlock`, listing the blocks it does | raises |
| `hx.render` called with no `partial=` | `HxError`, naming `hx.page` for a page-only handler | raises |
| An htmx request without `HX-Request-Type`, including a test that sends only `HX-Request` | `HxProtocolError`: this needs htmx 4. A verb raises it; the guard raises it for a response built without one | raises from a verb; logs from the guard |
| The lint is on and `hxlint.py` or `hx_vocab.py` is missing, as when only `hx.py` was copied | `HxLintError`, naming the files to copy | off unless `HX(lint=True)`; then logs once |
| htmx 2 idioms in the HTML: `<body hx-boost="true">`, `hx-ext`, implicit inheritance, htmx 2 event names in `hx-on` or `hx-trigger`, camelCase or kebab-case (`hx-on::after-request`), `show:#x:top` | `hxlint`, on every test response and in `flask hx lint` | off unless `HX(lint=True)`; then logs |
| A partial control pointing at a page-only handler, or a boosted link at a fragment-only one | `flask hx map`, errors | |
| A handler reads the `HX-Trigger` request header, or `request.form` on DELETE: both always empty in htmx 4 | `flask hx map`, errors, with or without hx verbs | |
| A control reaching a handler that calls no hx verb; `.retarget()` or `.reswap()`; reading `HX-Target` or `HX-Source` | `flask hx map`, warnings | |

## What was rejected

- **Controls declared in Python.** It hides what a control does from a reader of
  the template, and `flask hx map` checks the agreement from the HTML instead.
- **Server-side retargeting as a default.** `HX-Retarget`, `HX-Reswap` and
  `HX-Location` make a control's DOM effect invisible from the template.
  `HX-Redirect` is not one of them: it replaces the page instead of changing
  what the control swaps, and `hx.navigate` sends it only where a 303 would
  land inside the target.
- **htmx 2 compatibility.** Without `HX-Request-Type` the page-or-fragment
  question is a guess.
- **Decorators that render a returned dict.** A handler that sometimes returns a
  dict and sometimes a redirect has two return types.
