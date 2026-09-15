# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

The *Hypermedia Systems* contact.app (the book's `ch10-full` snapshot) ported to htmx 4 with a
handler-first design, plus the library that demonstrates it: `hx.py` (one file), its tools `hxlint.py`
and `hxmap.py` over `mapcore.py`, and the generated `hx_vocab.py`. The port is `app.py`,
`contacts_model.py`, `templates/`, `contacts.json`.

- `llms.txt` is the complete reference (vocabulary, principles, errors, checks). Any change to a verb
  signature, an error, a lint rule or a map check must be mirrored there.
- `README.md` has the three rules and the loud table; a new guard needs a row there.
- `HTMX4.md` is written for the book's authors: what the book's own app breaks on htmx 4, each row a
  test in `tests/test_book_on_htmx4.py`. Keep it factual; it is not a pitch for `hx.py`.
- `CHANGELOG.md` records user-visible changes.

The sibling project [dj-hx](https://github.com/codetalcott/dj-hx) **vendors `hxlint.py`, `hx_vocab.py`
and `mapcore.py` from here** (its `tools/sync_shared.py` rewrites the import lines). Keep those three
free of Flask imports and keep `mapcore`'s `scan_function` / `check` calls compatible with
`dj_hx/hxmap.py`. After changing one, run the sync script in dj-hx and its suite.
`tests/test_shared_core.py` here fails until the copies match, when dj-hx is checked out at
`~/projects/dj-hx` (or `$DJ_HX`), and is skipped otherwise.

## Commands

There is no activation step; every command is prefixed with `.venv/bin/`.

```
uv venv && uv pip install flask pytest playwright          # one-time setup
.venv/bin/flask --app app run                              # http://127.0.0.1:5000

.venv/bin/python -m pytest                                 # everything, including the browser suite
.venv/bin/python -m pytest -m "not browser"                # skip Playwright
.venv/bin/python -m pytest tests/test_hx.py -k negotiates  # one test
.venv/bin/python -m playwright install chromium            # once, for tests/test_browser.py

.venv/bin/flask --app app hx lint templates static/js      # static htmx 4 lint of template source and scripts
.venv/bin/flask --app app hx map                           # every control -> its handler, checked; exit 1 on errors
HTMX_SRC=~/path/to/htmx-4.0.0 .venv/bin/python tools/gen_vocab.py   # regenerate hx_vocab.py
```

`pyproject.toml` sets `pythonpath = ["."]`, so tests import `hx`, `hxlint`, `app` as top-level modules.
The flat layout has no build backend and no editable install. No formatter or Python linter is
configured. CI runs the suite, the lint and the map on Python 3.10 and 3.13.

## Architecture: what the code does not say on its face

- **Request type comes only from `HX-Request-Type`.** An htmx request without it raises
  `HxProtocolError`. Nothing reads `HX-Source`, `HX-Target` or `HX-Trigger` from the request, and the
  map reports any handler that does.
- **Fragments are Jinja blocks of the page template.** `partial="rows"` renders block `rows`; a value
  containing a dot is a template file. `_render_block` fires Flask's template signals. A block appended
  as `<hx-partial>` (`.partial()`, the flash bridge) must have a root `id` equal to its name.
- **Raise versus log.** The verbs, the block and root-id checks and the protocol check raise
  unconditionally: the alternative is a corrupted DOM. Everything the after-request hook finds goes
  through `_loud()`: raises under `app.testing`, logs otherwise. The README table has a column for
  this; keep it accurate. Error messages name the handler and say what to change.
- **`hx_vocab.py` is generated; do not edit it.** Change `tools/gen_vocab.py` and regenerate.
- **`hxlint.py`** parses HTML into a `Node` tree and checks it against `hx_vocab.py`; `hx-trigger` and
  `hx-swap` go through a port of htmx's HCON parser. Severities: error fails the CLI and raises under
  testing, warning logs, info is a design opinion (`select-not-body`, `delete-without-include`,
  `oob-in-template`). The one info on `index.html` (delete-without-include on the row Delete) is
  expected.
- **`mapcore.py` is the framework-neutral map engine**; new map logic belongs there. `hxmap.py` is the
  Flask adapter: `url_for` rewritten to a `URLFOR:` marker, resolution through `app.url_map`, `inspect`
  plus `ast` per endpoint. Verb and body reads are scoped by `if request.method == ...` branches.
  Header-read, DELETE body-read and JSON-return checks run whether or not the handler calls a verb.
  `htmx.ajax()` calls in scripts and attributes are controls; `fetch()` calls are listed, not checked.
  A finding on an attribute carries its element's line; only `<script>` bodies and `.js` files report per line.
- `retarget()` / `reswap()` are escape hatches the map reports. Do not use them in the port.

The port keeps everything line-for-line comparable with `ch10-full` except where htmx 4 forces a change
or `HTMX4.md` names a repair. `contacts_model.py` reads `contacts.json` from the working directory;
`Contact.count()` and `Archiver` sleep on purpose.

## Tests

- `conftest.py`: `workdir` copies `contacts.json` into a temp dir and `chdir`s there; `app` resets the
  database and archiver and stubs the model's sleeps; `client` is the test client; `PARTIAL` and `FULL`
  are the header dicts htmx 4 sends; `make_app(templates=..., **hx_kwargs)` builds a throwaway app with
  `DictLoader` templates.
- `test_hx.py` has a section per row of the loud table. A new guard needs a README row, an `llms.txt`
  line and a test.
- `test_hxlint.py` and `test_hxmap.py` assert the contact app lints with no errors and maps with **zero
  errors and zero warnings**. Any template or handler change must keep that true.
- `test_book_on_htmx4.py` runs the tools on the book's unmodified code; each test is a row of `HTMX4.md`.
- `test_browser.py` (`@pytest.mark.browser`) drives Chromium against a real server.

## Rules the tooling enforces

- Never `return redirect(...)`, `return ""`, `return "", 204` or `render_template(...)` to an htmx
  request. Use `hx.redirect`, `hx.navigate`, `hx.removed`, `hx.text`, `hx.render`.
- Write htmx 4, not htmx 2: `:inherited` for descendants (`<body hx-boost:inherited="true">`); no
  `hx-ext`; colon-separated events; `show:top showTarget:#x`.
- Routes must match control URLs exactly; a trailing-slash 308 answering a partial request is loud.
- `hx-delete` sends query parameters: read `request.args`, and say `hx-include="closest form"`.
- What changed elsewhere is the handler's decision (`.trigger()`, `.partial()`), not `hx-swap-oob`.
  URL pushing is the template's: `hx-push-url="true"` on the control.
