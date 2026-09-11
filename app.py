from flask import Flask, flash, request, send_file, url_for

from contacts_model import Archiver, Contact
from hx import HX, hx

Contact.load_db()

# ========================================================
# Flask App
# ========================================================

app = Flask(__name__)

app.secret_key = b"hypermedia rocks"

HX(app, flash_template="layout.html")


@app.route("/")
def index():
    return hx.redirect(url_for("contacts"))


@app.route("/contacts")
def contacts():
    search = request.args.get("q")
    page = int(request.args.get("page", 1))
    if search is not None:
        contacts_set = Contact.search(search)
    else:
        contacts_set = Contact.all(page)
    return hx.render(
        "index.html", partial="rows", contacts=contacts_set, page=page, archiver=Archiver.get()
    )


@app.route("/contacts/archive", methods=["POST"])
def start_archive():
    archiver = Archiver.get()
    archiver.run()
    return hx.fragment("archive_ui.html", archiver=archiver)


@app.route("/contacts/archive", methods=["GET"])
def archive_status():
    archiver = Archiver.get()
    return hx.fragment("archive_ui.html", archiver=archiver)


@app.route("/contacts/archive/file", methods=["GET"])
def archive_content():
    archiver = Archiver.get()
    return send_file(archiver.archive_file(), "archive.json", as_attachment=True)


@app.route("/contacts/archive", methods=["DELETE"])
def reset_archive():
    archiver = Archiver.get()
    archiver.reset()
    return hx.fragment("archive_ui.html", archiver=archiver)


@app.route("/contacts/count")
def contacts_count():
    count = Contact.count()
    return hx.text(f"({count} total Contacts)")


@app.route("/contacts/new", methods=["GET"])
def contacts_new_get():
    return hx.page("new.html", contact=Contact())


@app.route("/contacts/new", methods=["POST"])
def contacts_new():
    c = Contact(
        None,
        request.form["first_name"],
        request.form["last_name"],
        request.form["phone"],
        request.form["email"],
    )
    if not c.save():
        return hx.invalid("new.html", partial="form", contact=c)
    flash("Created New Contact!")
    return hx.redirect(url_for("contacts"))


@app.route("/contacts/<int:contact_id>")
def contacts_view(contact_id):
    contact = Contact.find(contact_id)
    return hx.page("show.html", contact=contact)


@app.route("/contacts/<int:contact_id>/edit", methods=["GET"])
def contacts_edit_get(contact_id):
    contact = Contact.find(contact_id)
    return hx.page("edit.html", contact=contact)


@app.route("/contacts/<int:contact_id>/edit", methods=["POST"])
def contacts_edit_post(contact_id):
    c = Contact.find(contact_id)
    c.update(
        request.form["first_name"],
        request.form["last_name"],
        request.form["phone"],
        request.form["email"],
    )
    if not c.save():
        return hx.invalid("edit.html", partial="form", contact=c)
    flash("Updated Contact!")
    return hx.redirect(url_for("contacts_view", contact_id=contact_id))


@app.route("/contacts/<int:contact_id>/email", methods=["GET"])
def contacts_email_get(contact_id):
    c = Contact.find(contact_id)
    c.email = request.args.get("email")
    c.validate()
    return hx.text(c.errors.get("email") or "")


@app.route("/contacts/<int:contact_id>", methods=["DELETE"])
def contacts_delete(contact_id):
    contact = Contact.find(contact_id)
    contact.delete()
    flash("Deleted Contact!")
    if hx.wants_page:  # the edit page's button targets the body
        return hx.redirect(url_for("contacts"))
    return hx.removed()  # a row's link says hx-swap="delete"


@app.route("/contacts", methods=["DELETE"])
def contacts_delete_all():
    # DELETE is a query-parameter method in htmx 4; the ids arrive because the
    # button says hx-include="closest form".
    contact_ids = list(map(int, request.args.getlist("selected_contact_ids")))
    for contact_id in contact_ids:
        contact = Contact.find(contact_id)
        contact.delete()
    flash("Deleted Contacts!")
    contacts_set = Contact.all(1)
    return hx.render(
        "index.html", partial="rows", contacts=contacts_set, page=1, archiver=Archiver.get()
    ).trigger("contacts-changed")


if __name__ == "__main__":
    app.run()
