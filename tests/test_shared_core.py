"""
hxlint.py, hx_vocab.py and mapcore.py are canonical here and vendored by dj-hx,
whose tools/sync_shared.py rewrites one or two import lines per file. When
dj-hx is checked out, its copies must match; when this fails, run that script.
"""

import os
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
DJ_HX = pathlib.Path(os.environ.get("DJ_HX", "~/projects/dj-hx")).expanduser()

REWRITES = {
    "hxlint.py": (("import hx_vocab as V\n", "from . import hx_vocab as V\n"),),
    "hx_vocab.py": (),
    "mapcore.py": (
        ("import hx_vocab as vocab\n", "from . import hx_vocab as vocab\n"),
        ("from hxlint import ", "from .hxlint import "),
    ),
}


@pytest.mark.skipif(not DJ_HX.exists(), reason="dj-hx is not checked out")
@pytest.mark.parametrize("name", sorted(REWRITES))
def test_dj_hx_vendors_the_current_copy(name):
    ours = (ROOT / name).read_text()
    for flask, django in REWRITES[name]:
        assert flask in ours, f"{name} no longer has the import line sync_shared rewrites"
        ours = ours.replace(flask, django, 1)
    theirs = (DJ_HX / "dj_hx" / name).read_text()
    assert theirs == ours, f"dj_hx/{name} is behind; run tools/sync_shared.py in dj-hx"
