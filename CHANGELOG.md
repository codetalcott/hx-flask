# Changelog

## Unreleased

### Added

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
- Lint rule `oob-in-template` (info): `hx-swap-oob` and `hx-select-oob` put the
  handler's decision in the template.
- README: the principles stated for agents, a glossary of page, fragment,
  partial and block, and the loud table split by what happens in production.
  `llms.txt`, the self-contained reference for an agent.
- `tests/test_shared_core.py` pins dj-hx's vendored copies when it is checked
  out. A CI workflow.

### Changed

- `hx.fragment(template, partial=...)`; the parameter was `block=`.
- `hx.render` without `partial=` raises an `HxError` naming `hx.page`, instead
  of a `TypeError`.
- Rule 2 no longer claims the handler never learns an element id; it never
  reads one from the request. Rule 3 admits a file the page includes.

## 0.0.0

- contact.app, handler-first: `hx.py`, the port, the linter, the map, tests.
