"""
Fixtures. The contact app reads and writes contacts.json in the working
directory, the way the book runs it, so every test gets a fresh copy in a
temporary directory and the model's sleeps are switched off.
"""

import os
import pathlib
import shutil
import sys

import pytest
from flask import Flask
from jinja2 import DictLoader

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

PARTIAL = {"HX-Request": "true", "HX-Request-Type": "partial", "Accept": "text/html"}
FULL = {"HX-Request": "true", "HX-Request-Type": "full", "Accept": "text/html"}


@pytest.fixture(scope="session")
def workdir(tmp_path_factory):
    d = tmp_path_factory.mktemp("contactapp")
    shutil.copy(ROOT / "contacts.json", d / "pristine.json")
    shutil.copy(ROOT / "contacts.json", d / "contacts.json")
    os.chdir(d)
    return d


@pytest.fixture(scope="session")
def contact_app(workdir):
    import types

    import contacts_model

    # The model sleeps to demonstrate lazy loading and a slow archive. Replace the
    # module reference it holds, not time.sleep itself, so nothing else is affected.
    contacts_model.time = types.SimpleNamespace(sleep=lambda seconds: None, time=__import__("time").time)
    import app as app_module

    app_module.app.testing = True
    return app_module.app


@pytest.fixture
def app(contact_app, workdir):
    """The book's contact app, database reset, archiver idle."""
    shutil.copy(workdir / "pristine.json", workdir / "contacts.json")
    from contacts_model import Archiver, Contact

    Contact.load_db()
    Archiver.archive_status = "Waiting"
    Archiver.archive_progress = 0
    return contact_app


@pytest.fixture
def client(app):
    return app.test_client()


LAYOUT = """<!doctype html><html><body hx-boost:inherited="true">
{% block flash %}<div id="flash">{% for m in get_flashed_messages() %}<p class="flash">{{ m }}</p>{% endfor %}</div>{% endblock %}
{% block content %}{% endblock %}
</body></html>"""

INDEX = """{% extends "layout.html" %}{% block content %}
<table><tbody>{% block rows %}{% for item in items %}<tr><td>{{ item }}</td></tr>{% endfor %}{% endblock %}</tbody></table>
{% block count %}<span id="count">{{ items|length }}</span>{% endblock %}
{% block badcount %}<span class="count">{{ items|length }}</span>{% endblock %}
{% block extra %}<i>{{ extra }}</i>{% endblock %}
{% endblock %}"""

FORM = """{% extends "layout.html" %}{% block content %}
{% block form %}<form id="form"><span class="error">{{ error }}</span></form>{% endblock %}
{% endblock %}"""

ROWS_FILE = """{% for item in items %}<tr><td>{{ item }}</td></tr>{% endfor %}"""


@pytest.fixture
def make_app():
    """A minimal app with in-memory templates for exercising hx.py directly."""
    from hx import HX

    def factory(templates=None, register=True, **hx_kwargs):
        app = Flask("t")
        app.secret_key = "k"
        app.testing = True
        app.jinja_env.loader = DictLoader(
            {"layout.html": LAYOUT, "index.html": INDEX, "form.html": FORM, "rows.html": ROWS_FILE, **(templates or {})}
        )
        if register:
            HX(app, **hx_kwargs)
        return app

    return factory
