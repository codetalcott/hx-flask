# Changelog

## Unreleased

### Added

- Lint rule `htmx2-event-name` reads JavaScript as well as `hx-on` and
  `hx-trigger`: quoted event names in `<script>`, `onclick`, Alpine's `@click`
  and `x-on:htmx:...`, hyperscript's `_`, and `.js` files, which `flask hx lint`
  now searches (`flask hx lint templates static/js`), skipping htmx's own files.
  `addEventListener("htmx:configRequest", ...)`, the book's chapter 8 idiom,
  listens for an event htmx 4 never fires. `hxlint.lint_script()` lints a
  JavaScript source.
- Lint rule `htmx2-detail-xhr` (error): `event.detail.xhr`, which is undefined
  under htmx 4's `fetch()`, so the handler throws.
- `flask hx map` sees `htmx.ajax(verb, url, options)` in a `<script>` or an
  attribute as a control, scoped the way htmx 4 scopes it. A `fetch()` that
  reaches a handler is listed under it, and a warning when that handler calls
  `hx.render`, which answers fetch with the page.
- `flask hx map` reports JSON (`jsonify(...)`, a returned dict or list) reaching
  an htmx control, instead of "calls no hx verb": an error when every return is
  JSON, a warning when one is.
- `HTMX4.md` tracks the book's `2nd-edition` branch per row, and covers
  chapters 8 and 9: the event renames, `detail.xhr`, the RSJS menu's
  `htmx:load`, and the Alpine toolbar's `htmx.ajax` DELETE. Two browser tests
  confirm the facts reading the source did not settle.
- `hx.navigate(url)`: leave the page whatever the control targets, for a login
  check or an expired session. A plain 303 when the request wanted a page,
  `HX-Redirect` when it targets an element. A flash queued before it waits for
  the page it loads. The map treats it as saying nothing about shape, so a
  login branch does not hide a page-only handler.
- The after-request guard raises `HxProtocolError` under `app.testing` (and
  logs otherwise) for an htmx request without `HX-Request-Type` answered
  without a verb. A test that sends only `HX-Request` no longer passes every
  guard silently.
- A lint that is on but cannot import `hxlint` raises `HxLintError` under
  `app.testing`, naming the files to copy, and logs once otherwise. It used to
  switch itself off without a word when only `hx.py` was copied.
- Lint rule `htmx2-event-name` catches kebab-case event names
  (`hx-on::after-request`), htmx 2's documented form, which htmx 4 never fires,
  and checks the events in `hx-trigger` as well as `hx-on`
  (`hx-trigger="htmx:afterSwap from:body"`).
- README: "Use it in your app", the files to copy and what each one gives.
  `llms.txt`: the same, the app-factory CLI, and leaving the page.
- `flask hx map` errors on a handler that reads the `HX-Trigger` request header,
  which htmx 4 does not send, and on one that reads `request.form` on DELETE,
  which htmx 4 sends as query parameters; it warns on a read of `HX-Target` or
  `HX-Source`. These need no hx verb, so they hold for code that never adopted
  `hx.py`.
- Lint rule `boost-not-inherited` (error): a plain `hx-boost` on anything but
  `<a>`/`<form>`, whether or not the links are in the same file. It replaces the
  `implicit-inheritance` warning for `hx-boost`, which the static lint missed on
  a layout.
- `tests/test_book_on_htmx4.py`: the tools run on the book's unmodified code,
  one test per break. `HTMX4.md` describes each for the book's authors.
- `HxBareResponse`: a response built without an hx verb (`render_template`, a
  string, `make_response`) answering a partial request raises under
  `app.testing` and logs otherwise. The guards no longer fire only for code
  that already uses the verbs.
- `mapcore.py`, the framework-neutral map engine, canonical here and vendored
  by dj-hx; `hxmap.py` is the Flask adapter over it. Verbs are found through any
  alias of `hx`, and `if request.method == ...` branches scope verbs to that
  method.
- `flask hx map` warns on a control that reaches a handler calling no hx verb,
  and on a handler that calls `.retarget()` or `.reswap()`, naming the controls
  whose templates no longer predict the DOM effect.
- `flask hx map --by-template`: the map read from the other end, every template
  and block a handler names with the handlers that render it. Editing a block is
  where the page-and-fragment agreement is easiest to break, and the template
  cannot say who renders it.
- Lint rule `oob-in-template` (info): `hx-swap-oob` and `hx-select-oob` put the
  handler's decision in the template.
- README: the principles stated for agents, a glossary of page, fragment,
  partial and block, and the loud table split by what happens in production.
  `llms.txt`, the self-contained reference for an agent.
- `tests/test_shared_core.py` pins dj-hx's vendored copies when it is checked
  out. A CI workflow.

### Changed

- The map's escape-hatch and DELETE checks run for handlers that call no verb.
  The "sends no form values on DELETE" warning is scoped by
  `if request.method == ...` branches, like the verbs.
- README keeps the rules and the loud table; `llms.txt` is the reference.
- `hx.fragment(template, partial=...)`; the parameter was `block=`.
- `hx.render` without `partial=` raises an `HxError` naming `hx.page`, instead
  of a `TypeError`.
- Rule 2 no longer claims the handler never learns an element id; it never
  reads one from the request. Rule 3 admits a file the page includes.

### Fixed

- `hx_vocab.HTMX2_EVENT_NAMES` has htmx 4's rename for every htmx 2 event:
  `htmx:load` (`htmx:after:init`, and the lint names `htmx.onLoad`),
  `htmx:beforeSend`, `htmx:timeout`, and the removed `htmx:xhr:*` and
  `htmx:validation:*`. The generator skipped every name without a capital
  letter, and left four others as "(see htmx-2-compat.js)".
- `unknown-attribute` suggestions compare the name after `hx-`: `hx-取得`
  suggested `hx-ws`, because the shared prefix made any short name close.
- A 304 answering a partial request is no longer reported as a redirect that
  fetch would follow; htmx skips the swap on a 304 by design.
- `hxlint.lint_html(extensions=)` takes the name htmx registers an extension
  under (`sse`, `ws`, `upsert`, the names `htmx.config.extensions` wants) as
  well as its file name (`hx-sse`). The short name used to match nothing, so
  every extension attribute on the page warned `extension-not-loaded`.
  `hx_vocab.EXTENSION_NAMES` is generated from `src/ext/*.js`.

### Removed

- `HX(provenance=)`, `HX(lint_warnings=)`, `HX(extensions=)`, `hx.test_headers`,
  `hx.current_url`, `HxResponse.push_url` and `.replace_url`. Nothing used them;
  set `HX-Push-Url` on the response directly for a canonical URL.
- `static/js/hx-live-4.0.0.js`, loaded by the layout and used by no template.
- `PLAN.md`. Still open from it: `--by-template` names the block a verb renders,
  never the page around it.

## 0.0.0

- contact.app, handler-first: `hx.py`, the port, the linter, the map, tests.
