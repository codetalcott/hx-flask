# Next steps

The findings of the 2026-09-12 review of developer and agent UX, turned into work
items. Cross-checked the same day against dj-hx at `main`: it vendors `hxlint.py`
and `hx_vocab.py` from here, its README already states several things this one only
implies, and its `mapcore.py` is ahead of `hxmap.py`. Where the two projects should
move together, the item says so.

## Status, 2026-09-12

Every item is done. Two rounds:

**Landed** (hx-flask #1, dj-hx #1). 1.1 `HxBareResponse` in Flask, partial
requests only. 1.2 the two map warnings. 1.3 `oob-in-template` at info. 1.4 the
`hx.render` error naming `hx.page`. 2.1 to 2.4 in README.md, 2.5 `llms.txt`.
3.1 `hx.fragment(partial=)`. 3.2 `HxUnknownBlock` kept, dj-hx's CLAUDE.md now
names the two exceptions that differ. 4 `mapcore.py` canonical here, `hxmap.py`
the adapter, dj-hx's sync script and pin extended to it. 5 `CHANGELOG.md`, CI,
CLAUDE.md.

**In review.** 3.3 `flask hx map --by-template` and `manage.py hx_map
--by-template`, in `mapcore.format_by_template` so both CLIs share it. The
1.1 port into dj-hx's `guard.py` as a recorded finding, with the README row,
the `llms.txt` row and three tests; `is_html` moved from its middleware to its
guard. dj-hx's changelog now covers the vendored map core and the two warnings.

The editable-install line from item 5 was dropped: setuptools refuses this flat
layout ("multiple top-level modules"), so the README keeps the direct install
and CI installs the three packages by name.

Verified: 71 tests here plus 7 in Chromium, `flask hx lint` 0 errors, `flask hx
map` 0 errors 0 warnings; dj-hx 113 tests, ruff clean, its example map clean;
the vendoring pin green from both sides.

Two things noticed while working here, neither in scope and neither fixed:

- A 304 answering a partial request is recorded as `HxRedirectIntoFragment` by
  both guards, because the branch is `300 <= status < 400`. htmx skips the swap
  on a 304 by design, so the message ("fetch will follow it") is wrong. It needs
  its own branch, or none.
- `Handler.templates` records what a verb named, so `hx.render("index.html",
  partial="rows")` indexes `index.html#rows` and never `index.html`. The
  by-template view therefore says who renders the block but not who renders the
  page around it.

## Ground rules for every item

- A new failure mode is three edits: the guard, a row in the README's "What is loud"
  table, a test in `tests/`. Every row of that table has a test today; keep it so.
- `hxlint.py` and `hx_vocab.py` are canonical here. After touching either, run dj-hx's
  `tools/sync_shared.py` and its suite; `tests/test_shared_core.py` there pins the
  copies. Keep `hxlint.py` free of Flask imports.
- Error messages name the handler and say what to change. They are the documentation.
- `flask hx lint templates` and `flask hx map` stay at zero errors and zero warnings
  for the port; `tests/test_hxmap.py` asserts it.

## Order

1. The guards in `hx.py` (1.1, 1.4) and the lint rule (1.3). Independent of the rest.
2. Adopt dj-hx's `mapcore.py` (4) before adding map checks, so 1.2 is written once.
3. The README (2), once the behavior it describes exists.
4. Vocabulary (3) last; it is a rename across both projects.

Sizes: XS under an hour, S an afternoon, M a day.

## 1. Close the enforcement gap

The review's central finding: every guard fires only for code that calls an hx verb,
so the Flask idioms an agent already knows pass silently.

### 1.1 A bare response to a partial request is loud (`hx.py`) — S

`return render_template(...)`, `return ""` and `make_response(...)` answering a partial
request are 200s today. Under `app.testing` they should raise; in production, log.

```python
class HxBareResponse(HxError):
    """A response built without an hx verb answered a request that targets an element."""

# HX._after_request, in the 2xx partial branch, before _bridge_flash:
elif partial and status < 300 and html:
    if not isinstance(response, HxResponse):
        _loud(HxBareResponse, "answered a request that targets an element without an hx verb "
              "(render_template, a string, make_response); whether it is a page or a fragment "
              "cannot be checked. Use hx.render(..., partial=...), hx.fragment, hx.text or hx.removed.")
    self._bridge_flash(response)
```

- Partial requests only. A bare page to a boosted link is correct, and a third-party
  blueprint answering boosted links must not raise.
- **Decision:** also flag a bare response to a *full* request whose body has no `<html`
  near the start, meaning a fragment file rendered into `<body>`? It is a heuristic.
  Recommendation: leave it out; 1.2 catches that handler statically.
- `abort(404)` and error pages are excluded by `status < 300`; `send_file` and JSON by
  the `html` test.
- Tests, one section in `tests/test_hx.py`: `render_template`, `""` and `make_response`
  each raise under `PARTIAL`; none raise under `FULL` or with no headers; a 404 under
  `PARTIAL` does not raise. No existing test returns bare HTML to a partial request
  (the `/plain` route in the Vary test is only requested as a browser).
- README row: "A handler answers a partial request without an hx verb | `HxBareResponse`".
- Port to dj-hx's `guard.py` afterwards as a recorded finding; it has the same gap.

### 1.2 The map warns on unchecked handlers and on the escape hatches — S

Today `build_map` skips any handler with no verbs (`if not h.verbs: continue`), and
`.retarget()` and `.reswap()` are invisible. dj-hx's `mapcore.check` has the identical
skip, so do this in `mapcore.py` after item 4.

- A control reaching a handler that calls no verb → warning:
  `index.html:12 <button> reaches plain() which calls no hx verb, so whether it answers
  with a page or a fragment cannot be checked; call hx.render/page/fragment/text/removed
  (or the verb is in a helper the scanner cannot see).`
  A warning, not an error: a wrapper function is a legitimate false positive, and the
  message says so.
- `Handler` gains `escapes: set[str]`; the visitor records `retarget` and `reswap` the
  way it records `.trigger()`. Each control reaching such a handler → warning:
  `contacts() calls .retarget(); index.html:9 <input#search> can no longer predict its
  DOM effect from the template. Keep the comment that says why.`
  `print_map` prints an `escapes:` line under `verbs:`.
- Tests in `tests/test_hxmap.py` with `make_app`: a no-verb handler behind a control, and
  a retargeting handler. The port has neither case (`archive_content` has no verb, but
  its link is `hx-boost="false"`, so it is not a control), so it stays at zero warnings.

### 1.3 The lint notes `hx-swap-oob` and `hx-select-oob` (`hxlint.py`, shared) — S

"What changed elsewhere" is the handler's decision, said with `.partial()` or
`.trigger()`. A template can say it too with `hx-swap-oob`, and the lint is silent.
Add rule `oob-in-template`. Precedent for a design opinion in the lint at info level:
`select-not-body`, `delete-without-include`.

`hx-swap-oob decides what changed elsewhere from the template; here the handler says it
with .partial() or .trigger(). Keep it only for a swap style .partial() cannot express
(it always swaps outerHTML by id).`

- **Decision:** info (visible, never fails) or warning (logged on every test response)?
  Recommendation: info.
- Test in `tests/test_hxlint.py`; the port has no oob attributes. Sync to dj-hx.
- README, under the principles (2.2): `hx-swap-oob` is allowed for what `.partial()`
  cannot express, and the lint notes each use.

### 1.4 `hx.render` without `partial=` says what to do (`hx.py`) — XS

Today: `TypeError: _Hx.render() missing 1 required positional argument: 'partial'`.
Make `partial: str | None = None` and raise at once:

`contacts_view() calls hx.render('show.html') with no partial; name the block a partial
request gets, or call hx.page for a page-only handler.`

This keeps the property that `render` forces the decision. `hxmap._templates` already
tolerates a missing partial.

## 2. Draw the line in the README

dj-hx's README has a section "Principles, stated so an agent can apply them" and a
glossary. This README has neither, and two of its rules overstate.

### 2.1 Glossary — XS

Four lines, matching dj-hx's terms so the two READMEs agree:

- **Page**: the full document; what a browser, a boosted link or a body-targeted
  control gets.
- **Fragment**: what a control that targets an element gets; a block of the page
  template, or a file the page includes.
- **Partial**: htmx 4's word. `HX-Request-Type: partial` is a request for a fragment;
  `<hx-partial>` is an extra region in a response; `partial=` names the block;
  `.partial("count")` appends one.
- **Block**: Jinja's word for the region `partial=` names.

### 2.2 Principles, stated so an agent can apply them — S

Port dj-hx's list with Flask names, plus two bullets it lacks:

- **Never `return redirect(...)`, `return ""` or `return "", 204` to an htmx request.**
  Say what happened: `hx.redirect`, `hx.removed`, `hx.text`. (In `hx.py`'s docstring
  today; not in the README.)
- **Never read `HX-Source` or `HX-Target`.** The question is `hx.wants_page`.
- **Announce facts; do not update regions.** `.trigger("contacts-changed")` with
  `hx-trigger="contacts-changed from:body"` on the element that cares; `.partial()`
  only when the handler already holds the data and the region is a block of the same
  template. This is the trigger-versus-partial guidance the review found missing.
- **The template predicts the DOM effect; the handler predicts the resource effect and
  the representation.** `.retarget()` and `.reswap()` break the first half; use them
  with a comment saying why, and `flask hx map` names each use (1.2).
- **The template says whether a control navigates.** *New.* `hx-push-url="true"` on
  the control. htmx 4 pushes the final URL after a 303, so the handler rarely needs
  `.push_url()`; reserve `.push_url()` and `.replace_url()` for a canonical URL that
  differs from the requested one, with a comment.
  **Decision:** this assigns URL pushing to the template. The alternative, handler
  owned, means removing `hx-push-url` from the templates and calling `.push_url()` in
  `contacts()` and `contacts_delete()`. Recommendation: template, because "navigates"
  is a property of the control a reader of the template should see, and the port
  already does it that way.
- **Every control says `url_for`.** The map resolves it; the trailing slash cannot drift.
- **Every name is literal.** `hx.render("index.html", partial="rows")` is matched by
  `{% block rows %}` in that file. The one convention, a partial's root `id` equals its
  name, is checked at the render.

Close with dj-hx's paragraph on tiers (delete the dependency, else fail at the first
deterministic moment, else check statically, else document) and its "What was
rejected, and why" list. Both apply verbatim.

### 2.3 Fix rule 2 and rule 3 — XS

- Rule 2 says "the handler never learns an element id". `.partial("count")` and the
  flash bridge name one by convention. Reword: "the handler never reads an element id
  from the request; the only ids it names are block names, and the render checks each."
- Rule 3 says fragments are blocks of the page template. `archive_ui.html` is a file
  included by the page and served by three handlers. Reword: "Fragments are Jinja
  blocks of the page template, or a file the page includes, named in the handler;
  either way page and fragment are one source and cannot drift." The dot-means-file
  rule already implements this.
- Same two edits in dj-hx's README.

### 2.4 Split the loud table by what happens in production — XS

The table says "Under `app.testing` these raise; otherwise they log." Not uniformly
true. Adopt dj-hx's sentence and add a column:

| Raises always | Raises under `app.testing`, logs otherwise (`_loud`) |
|---|---|
| `HxPageIntoFragment` (`hx.page`) | `HxFragmentIntoPage` (`hx.fragment`, `hx.text`) |
| `HxRedirectIntoFragment` from `hx.redirect` | `HxRedirectIntoFragment` from the after-request guard: a plain 3xx, Werkzeug's slash 308 |
| `HxUnknownBlock`, `HxPartialRootId` | `HxNoSwap`, `HxFlashUnconfigured`, `HxLintError`, `HxBareResponse` (1.1) |
| `HxProtocolError`, `HxNotInitialized` | |

The principle, stated once: the verbs raise where the outcome is certain at call time
and the alternative is a corrupted DOM; everything the after-request guard finds is
logged in production and raised under testing, so a false positive cannot 500 a live
app. No behavior change. If a row looks wrong once written down, that is the moment
to move it.

### 2.5 `llms.txt` — S

dj-hx ships one, and its CLAUDE.md requires every signature, error and lint-rule change
to be mirrored there. Add the same here: the vocabulary block, the three rules, the
principles (2.2), the glossary (2.1), the loud table (2.4), the test headers and the
two CLI commands. Add the mirror rule to CLAUDE.md.

## 3. Vocabulary, aligned with dj-hx

dj-hx uses *partial* for the named region and *fragment* for the response shape, and
its `fragment(request, template, partial=None)` names the parameter `partial`. Do not
rename `partial=` to `fragment=`; that would diverge. Do align the one outlier.

### 3.1 `hx.fragment(template, block=None)` → `partial=None` — XS

Three callers in `tests/` use `block=`; `app.py` passes none. Update
`hxmap._templates` to read `partial` only, the docstrings, README and CLAUDE.md.

### 3.2 `HxUnknownBlock` — decision

dj-hx raises `HxUnknownPartial`, and its CLAUDE.md says exception names mirror
hx-flask. Either rename here for parity or correct dj-hx's note. Recommendation: keep
`HxUnknownBlock`, since Jinja calls it a block and the message says "has no block",
and amend dj-hx's CLAUDE.md to list the two names that differ (`HxUnknownPartial`,
`HxMessagesUnconfigured`).

### 3.3 A by-template view in the map — S, optional

Someone editing `index.html#rows` has no in-file signal that `contacts()` and
`contacts_delete_all()` both serve it. `flask hx map --by-template` inverts data the
map already holds: template#block → handlers → controls. No new scanning.

## 4. Share the map core with dj-hx — M

dj-hx split its map into a framework-neutral `mapcore.py` (template scan, AST visitor,
checks, formatting) and a Django adapter, and its CLAUDE.md says "New map logic
belongs in mapcore because hx-flask shares the core." hx-flask does not, yet:
`hxmap.py` here is the older monolith. mapcore is ahead in two ways this repo wants:

- `verb_names` maps any dotted name to a verb, so `from hx import hx as h` or a module
  alias is no longer invisible (the review's alias-blind finding).
- `by_method` scopes verbs to `if request.method == ...` branches, which a Flask app
  will want the moment one handler serves two methods.

Steps:

1. Copy `dj-hx/dj_hx/mapcore.py` here as `mapcore.py` with flat imports
   (`import hx_vocab as vocab`, `from hxlint import ...`). Two differences from
   today's `hxmap.py`: mapcore prints computed URLs as `url:` rather than `url_for:`,
   and treats a computed URL as a warning rather than an error. `tests/test_hxmap.py`
   asserts neither, so both are free.
2. Rewrite `hxmap.py` as the Flask adapter, keeping `build_map(app)` and
   `print_map(app, check=True, out=None)` so `hx.py`'s CLI and the tests do not
   change: Jinja preprocessing (`url_for` → `URLFOR:`), `_resolve` through
   `app.url_map`, `inspect` plus `ast` per endpoint into
   `scan_function(handler, tree, verb_names, flash_names=("flash",),
   value_attrs=("args", "form", "values", "json", "get_json"))`, then `check` and
   `format_map`. Build `verb_names` from the handler module's `from hx import ...` and
   `import hx as ...` statements.
3. Add 1.2's checks to `mapcore.check`, once.
4. **Decision: canonical home.** `sync_shared.py` pulls `hxlint.py` and `hx_vocab.py`
   from here. Recommendation: make `mapcore.py` canonical here too, add it to that
   script with the same import rewrite, and let dj-hx's `test_shared_core.py` pin it.
   The alternative, dj-hx canonical with a second sync script here, means two scripts
   in two directions.
5. Mirror dj-hx's `test_shared_core.py` here: when `~/projects/dj-hx` is checked out,
   assert the three copies match. It is what notices drift from this side.

## 5. Housekeeping — XS each

- `CHANGELOG.md`, starting at the version that ships section 1. dj-hx's changelog names
  hx-flask's copies, so the two should be able to cite each other.
- README install line: `uv pip install -e ".[dev]"` alongside the two-command form;
  `pyproject.toml` already declares the dev extra.
- A CI workflow running `pytest -m "not browser"`, `flask hx lint templates` and
  `flask hx map`, as dj-hx has.
- CLAUDE.md: the architecture section for `mapcore.py`, the new guard, the llms.txt
  mirror rule.

## Decisions to make before starting

| Item | Decision | Recommendation |
|---|---|---|
| 1.1 | Bare response to a *full* request: `<html` heuristic, or nothing | Nothing; 1.2 covers it statically |
| 1.3 | Severity of `oob-in-template` | info |
| 2.2 | Who owns URL pushing | The template; `.push_url()` only for canonical-URL corrections |
| 3.2 | Rename `HxUnknownBlock` | Keep; fix dj-hx's note |
| 4 | Canonical home of `mapcore.py` | Here, via the existing sync script |
