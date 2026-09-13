# Changelog

## Unreleased

### Added

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

- A 304 answering a partial request is no longer reported as a redirect that
  fetch would follow; htmx skips the swap on a 304 by design.

### Removed

- `HX(provenance=)`, `HX(lint_warnings=)`, `HX(extensions=)`, `hx.test_headers`,
  `hx.current_url`, `HxResponse.push_url` and `.replace_url`. Nothing used them;
  set `HX-Push-Url` on the response directly for a canonical URL.
- `static/js/hx-live-4.0.0.js`, loaded by the layout and used by no template.
- `PLAN.md`. Still open from it: `--by-template` names the block a verb renders,
  never the page around it.

## 0.0.0

- contact.app, handler-first: `hx.py`, the port, the linter, the map, tests.
