# Third-party code

`contact.app` is a port of *Hypermedia Systems*' sample application, kept
close to the book's `ch10-full` snapshot so the two can be compared line for
line.

- `static/js/htmx-4.0.0.js` — htmx, by Big Sky Software. 0BSD.
- `static/missing.css` — missing.css, by Ollie Williams and contributors. MIT.
- `static/img/spinning-circles.svg` — from SVG Loaders, by Sam Herbert. MIT.
- `contacts.json`, the routes and the templates, and the book excerpts in
  `tests/test_book_on_htmx4.py` — from *Hypermedia Systems* (Gross, Stepinski,
  Akşimşek), whose sample application is published under the BSD 2-Clause
  license.

`hx_vocab.py` is generated from the htmx 4.0.0 source tree by
`tools/gen_vocab.py`; the vocabulary is htmx's, the generator is this
project's. dj-hx vendors `hxlint.py`, `hx_vocab.py` and `mapcore.py` from here.
