# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

The *Hypermedia Systems* contact.app (the book's `ch10-full` snapshot) ported to htmx 4 with a
handler-first design: the server owns every response-side decision. Two things live here:

- **`hx.py`**, the library (one file), plus its tools `hxlint.py`, `hxmap.py` over `mapcore.py`, and
  the generated `hx_vocab.py`.
- **The port** that demonstrates it: `app.py`, `contacts_model.py`, `templates/`, `contacts.json`.

README.md states the three rules, the principles an agent can check code against, a glossary, the
silent-failure catalogue (each row has a test), and the htmx 4 facts the design depends on. Read it
before changing `hx.py`. `llms.txt` is the same reference, self-contained, for an agent writing code
against the library: any change to a verb signature, an error, a lint rule or a map check must be
mirrored there and in the README. `CHANGELOG.md` records user-visible changes; `PLAN.md` is the work
list and its status.

The same design for Django is the sibling project [dj-hx](https://github.com/codetalcott/dj-hx), which
**vendors `hxlint.py`, `hx_vocab.py` and `mapcore.py` from here** (its `tools/sync_shared.py` rewrites
the import lines). Keep those three files free of Flask imports. After changing one, run that script in
dj-hx and its suite. `tests/test_shared_core.py` here fails until the copies match, when dj-hx is checked
out at `~/projects/dj-hx` (or `$DJ_HX`), and is skipped otherwise.

## Commands

There is no activation step; every command is prefixed with `.venv/bin/`.

```
uv venv && uv pip install flask pytest playwright          # one-time setup
.venv/bin/flask --app app run                              # http://127.0.0.1:5000

.venv/bin/python -m pytest                                 # everything, including the browser suite
.venv/bin/python -m pytest -m "not browser"                # skip Playwright
.venv/bin/python -m pytest tests/test_hx.py -k negotiates  # one test
.venv/bin/python -m playwright install chromium            # once, for tests/test_browser.py

.venv/bin/flask --app app hx lint templates                # static htmx 4 lint of template source
.venv/bin/flask --app app hx map                           # every control -> its handler, checked; exit 1 on errors
HTMX_SRC=~/path/to/htmx-4.0.0 .venv/bin/python tools/gen_vocab.py   # regenerate hx_vocab.py
```

`pyproject.toml` sets `pythonpath = ["."]`, so tests import `hx`, `hxlint`, `app` etc. as top-level
modules. The flat layout has no build backend, so there is no editable install; install the
dependencies and run from the checkout. There is no formatter or Python linter configured. CI
(`.github/workflows/ci.yml`) runs the suite, the lint and the map on Python 3.10 and 3.13.

## Architecture

### hx.py: the request/response protocol

- `HX(app, flash_template=...)` is a Flask extension. It registers one `after_request` hook that adds
  `Vary`, guards a partial request against a 3xx, a 204, or a response built without an hx verb
  (`HxBareResponse`: `render_template`, a string, `make_response`), bridges `flash()` messages into an
  `<hx-partial>` on fragment responses, and lints every HTML response. It also registers the
  `flask hx` CLI group.
- `hx` is a singleton. Request side: `is_htmx`, `wants_page`, `wants_fragment`, decided **only** by
  the `HX-Request-Type` header (`full` or `partial`). An htmx request without it raises
  `HxProtocolError`. Nothing reads `HX-Source` or `HX-Target`; the handler never reads an element id
  from the request.
- Response verbs return an `HxResponse` whose `hx_kind` is page, fragment, text, removed or redirect.
  `hx.render(template, partial=...)` negotiates, and raises an `HxError` naming `hx.page` when
  `partial` is missing; `hx.page` / `hx.fragment` / `hx.text` / `hx.redirect` / `hx.removed` assert
  one shape and raise (or log) when the request asked for the other.
- **Fragments are Jinja blocks of the page template.** `partial="rows"` renders block `rows` of the
  named template; a `partial=` value containing a dot is treated as a template file instead.
  `_render_block` fires Flask's `before_render_template` / `template_rendered` signals so test
  fixtures still see it.
- `.partial("count")` and the flash bridge append `<hx-partial hx-target="#count">`. The block's root
  element **must** carry `id="<block name>"`; `_check_root_id` enforces it at render time.
- `.trigger(name)` always emits the JSON `HX-Trigger` form with a `target` (default `body`) because
  after a `delete` swap the source element is gone.
- **Raise versus log.** `hx.page`, `hx.redirect`, the block and root-id checks and the protocol check
  raise unconditionally: the alternative is a corrupted DOM. Everything the after-request hook and
  `_guard_fragment` find goes through `_loud()`, which raises under `app.testing` and logs a warning
  otherwise, so a false positive cannot 500 a live app. The README's table has a column for this;
  keep it accurate.
- Errors name the handler and say what to change; keep new messages in that style.
- `retarget()` / `reswap()` are escape hatches that break rule 2 (the HTML predicts the DOM effect).
  The map reports every handler that calls one. Do not use them in the port.

### hxlint.py: the htmx 4 vocabulary made loud

Parses HTML into a `Node` tree (`html.parser`), then runs rules against `hx_vocab.py`: htmx 2
attributes (`hx-ext`, `hx-vars`), unknown attributes, swap styles and modifiers, trigger modifiers,
camelCase event names, implicit inheritance (htmx 4 needs `:inherited`), missing `#id` targets,
duplicate ids, `hx-delete` without `hx-swap="delete"`. `hx-trigger` and `hx-swap` values go through
a port of htmx's HCON parser, not a hand-written grammar.

It runs in three places: on every HTML response under `app.testing` / `app.debug` (errors raise via
`HxLintError`, warnings log), on template source via `flask hx lint` (Jinja expressions are replaced
with a `__JINJA__` placeholder so computed values are skipped), and in `tests/test_hxlint.py`.
Findings have severity error / warning / info; only errors fail the CLI. Design opinions live at
`info`: `select-not-body`, `delete-without-include`, and `oob-in-template` (`hx-swap-oob` /
`hx-select-oob` put the handler's decision in the template). The one `info` finding on `index.html`
(delete-without-include on the row Delete link) is expected.

### mapcore.py and hxmap.py: controls to handlers, statically

`mapcore.py` is the framework-neutral engine, canonical here and vendored by dj-hx: the template scan
(`scan_templates`), the AST visitor that finds verb calls (`scan_function`, with `verb_names` mapping
any dotted alias to a verb and `if request.method == ...` branches scoping verbs to that method), the
checks (`check`, with `verb_prefix` for how the framework spells a verb in a message) and the two reports
(`format_map` by handler, `format_by_template` by template and block). New map logic belongs there. `hxmap.py` is the Flask adapter: `url_for(...)` rewritten
to a `URLFOR:` marker, resolution through `app.url_map`, `inspect` plus `ast` per endpoint, and
`verb_names` built from each handler module's imports of `hx`. `build_map(app)` and
`print_map(app, check, out)` are the adapter's surface; `hx.py`'s CLI and the tests use only those.

Each control is classified `full` or `partial` by htmx 4's own rule (`hx-target="body"`, `hx-select`,
or boosted). Errors: a partial control reaching a page-only handler, a full control reaching a
fragment-only handler, a trailing-slash 308 from routing, a URL or `url_for` that resolves to nothing.
Warnings: a control reaching a handler that calls no verb (its shape cannot be checked), a handler that
calls `.retarget()` or `.reswap()`, a DELETE that reads form values without `hx-include`, a computed
URL, and events announced or listened for on only one side.

### hx_vocab.py: generated, do not edit

Every list is read from the htmx 4.0.0 source tree by `tools/gen_vocab.py`, which fails loudly when
a file it depends on has moved. A hand-listed vocabulary is where a linter's false errors come from.
To change the vocabulary, change the generator and regenerate.

### The port

`app.py` is one handler per route, each calling exactly one hx verb per outcome. `contacts_model.py`
is the book's in-memory model backed by `contacts.json` **in the working directory**; `Contact.count()`
and `Archiver` sleep on purpose to demonstrate lazy loading and a slow job. Templates: `layout.html`
sets `hx-boost:inherited="true"` and defines the `flash` block; `index.html` defines the `rows` block;
`new.html` / `edit.html` define the `form` block; `archive_ui.html` is a fragment file the index page
includes. The README names the deliberate repairs to the book snapshot; keep everything else
line-for-line comparable with `ch10-full`.

## Tests

- `tests/conftest.py`: `workdir` (session) copies `contacts.json` into a temp dir and `chdir`s
  there; `app` resets the database and archiver before each test and stubs `contacts_model.time` so
  the sleeps are no-ops; `client` is the Flask test client. `PARTIAL` and `FULL` are the header
  dicts htmx 4 sends. `make_app(templates=..., **hx_kwargs)` builds a throwaway Flask app with
  in-memory `DictLoader` templates for exercising `hx.py` and the map without the port.
- `test_hx.py` has one section per row of the silent-failure catalogue. A new guard in `hx.py`
  needs a row in the README table, a line in `llms.txt`, and a test here.
- `test_hxlint.py` and `test_hxmap.py` assert the contact app passes lint with no errors and maps
  with **zero errors and zero warnings**. Any template or handler change must keep that true.
- `test_shared_core.py` pins dj-hx's vendored copies of the three shared files; skipped when dj-hx is
  not checked out.
- `test_browser.py` (`@pytest.mark.browser`) starts a real Werkzeug server and drives Chromium via
  Playwright; it observes the protocol claims rather than reasoning about them.

## Rules that the tooling enforces

- Never `return redirect(...)`, `return ""`, `return "", 204` or `render_template(...)` to an htmx
  request. Use `hx.redirect`, `hx.removed`, `hx.text`, `hx.render`.
- Never branch on `HX-Source` or `HX-Target`. The question is always `hx.wants_page`.
- Write htmx 4, not htmx 2: attributes reach descendants only with `:inherited`; no `hx-ext`;
  events are colon-separated (`htmx:after:swap`); `show:top showTarget:#x`, not `show:#x:top`.
- Routes must match control URLs exactly. A trailing-slash 308 from Werkzeug answering a partial
  request raises `HxRedirectIntoFragment`.
- `hx-delete` sends query parameters and excludes the enclosing form unless the control says
  `hx-include="closest form"`.
- What changed elsewhere is the handler's decision: `.trigger()` or `.partial()`, not `hx-swap-oob`
  in a template. URL pushing is the template's: `hx-push-url="true"` on the control.
