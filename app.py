import os
import sqlite3
import csv
import io
from functools import wraps
from datetime import datetime, date, timedelta
from flask import (
    Flask, render_template, request, redirect,
    url_for, flash, g, Response, session
)

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-change-in-production")

DATABASE = os.environ.get("DATABASE_PATH", "crm.db")

# ---------------------------------------------------------------------------
# Login credentials — set APP_USERNAME and APP_PASSWORD in Railway Variables
# ---------------------------------------------------------------------------

APP_USERNAME = os.environ.get("APP_USERNAME", "admin")
APP_PASSWORD = os.environ.get("APP_PASSWORD", "password")

# ---------------------------------------------------------------------------
# Pipeline status values (used in forms and templates)
# ---------------------------------------------------------------------------

PIPELINE_STATUSES = [
    "New",
    "Contacted",
    "Interested",
    "Follow Up Needed",
    "Committed",
    "Donated",
    "Volunteered",
    "Not Interested",
]

# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

def get_db():
    db = getattr(g, "_database", None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
    return db


@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, "_database", None)
    if db is not None:
        db.close()


def init_db():
    db = sqlite3.connect(DATABASE)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")

    # Create tables if they do not exist
    db.executescript("""
        CREATE TABLE IF NOT EXISTS contacts (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            first_name   TEXT NOT NULL,
            last_name    TEXT NOT NULL,
            contact_type TEXT NOT NULL CHECK(contact_type IN ('donor','volunteer')),
            phone        TEXT,
            email        TEXT,
            organization TEXT,
            status       TEXT DEFAULT 'New',
            notes        TEXT,
            created_at   TEXT DEFAULT (datetime('now')),
            updated_at   TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS outreach_logs (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            contact_id      INTEGER NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
            outreach_date   TEXT NOT NULL,
            team_member     TEXT NOT NULL,
            method          TEXT NOT NULL CHECK(method IN ('call','text','email','in_person')),
            outcome         TEXT NOT NULL CHECK(outcome IN ('reached','voicemail','no_answer','interested','follow_up_needed','donated','volunteered')),
            donation_amount REAL DEFAULT 0,
            follow_up_date  TEXT,
            notes           TEXT,
            created_at      TEXT DEFAULT (datetime('now'))
        );
    """)
    db.commit()

    # Migrate old status values to pipeline values for any existing data
    try:
        db.execute("UPDATE contacts SET status = 'New' WHERE status IN ('active', 'prospect')")
        db.execute("UPDATE contacts SET status = 'Not Interested' WHERE status = 'inactive'")
        db.commit()
    except Exception:
        pass

    db.close()


# ---------------------------------------------------------------------------
# Startup — runs at import time so gunicorn and python app.py both work
# ---------------------------------------------------------------------------

init_db()


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("logged_in"):
            flash("Please log in to continue.", "error")
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


# ---------------------------------------------------------------------------
# Login / Logout
# ---------------------------------------------------------------------------

@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("logged_in"):
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        if username == APP_USERNAME and password == APP_PASSWORD:
            session["logged_in"] = True
            session["username"] = username
            return redirect(url_for("dashboard"))
        flash("Incorrect username or password. Please try again.", "error")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("login"))


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def week_bounds():
    today = date.today()
    mon = today - timedelta(days=today.weekday())
    sun = mon + timedelta(days=6)
    return str(mon), str(sun)


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

@app.route("/")
@login_required
def dashboard():
    db = get_db()
    week_start, week_end = week_bounds()
    today_str = str(date.today())

    total_contacts   = db.execute("SELECT COUNT(*) FROM contacts").fetchone()[0]
    total_donors     = db.execute("SELECT COUNT(*) FROM contacts WHERE contact_type='donor'").fetchone()[0]
    total_volunteers = db.execute("SELECT COUNT(*) FROM contacts WHERE contact_type='volunteer'").fetchone()[0]

    attempts_week = db.execute(
        "SELECT COUNT(*) FROM outreach_logs WHERE outreach_date BETWEEN ? AND ?",
        (week_start, week_end)
    ).fetchone()[0]

    reached_week = db.execute(
        "SELECT COUNT(*) FROM outreach_logs WHERE outreach_date BETWEEN ? AND ? AND outcome='reached'",
        (week_start, week_end)
    ).fetchone()[0]

    followups_week = db.execute(
        "SELECT COUNT(*) FROM outreach_logs WHERE follow_up_date BETWEEN ? AND ?",
        (week_start, week_end)
    ).fetchone()[0]

    overdue = db.execute(
        "SELECT COUNT(*) FROM outreach_logs WHERE follow_up_date < ? AND follow_up_date IS NOT NULL AND follow_up_date != ''",
        (today_str,)
    ).fetchone()[0]

    donations_week = db.execute(
        "SELECT COALESCE(SUM(donation_amount),0) FROM outreach_logs WHERE outreach_date BETWEEN ? AND ?",
        (week_start, week_end)
    ).fetchone()[0]

    recent = db.execute("""
        SELECT ol.*, c.first_name || ' ' || c.last_name AS contact_name
        FROM outreach_logs ol
        JOIN contacts c ON c.id = ol.contact_id
        ORDER BY ol.outreach_date DESC, ol.created_at DESC
        LIMIT 10
    """).fetchall()

    # Contacts needing follow-up (pipeline status = Follow Up Needed)
    followup_contacts = db.execute("""
        SELECT * FROM contacts
        WHERE status = 'Follow Up Needed'
        ORDER BY updated_at ASC
    """).fetchall()

    # Contact counts by pipeline status
    status_counts = db.execute("""
        SELECT status, COUNT(*) as cnt
        FROM contacts
        GROUP BY status
        ORDER BY cnt DESC
    """).fetchall()

    return render_template("dashboard.html",
        total_contacts=total_contacts,
        total_donors=total_donors,
        total_volunteers=total_volunteers,
        attempts_week=attempts_week,
        reached_week=reached_week,
        followups_week=followups_week,
        overdue=overdue,
        donations_week=donations_week,
        recent=recent,
        week_start=week_start,
        week_end=week_end,
        followup_contacts=followup_contacts,
        status_counts=status_counts,
    )


# ---------------------------------------------------------------------------
# Contacts
# ---------------------------------------------------------------------------

@app.route("/contacts")
@login_required
def contacts():
    db = get_db()
    q      = request.args.get("q", "").strip()
    ctype  = request.args.get("type", "").strip()
    status = request.args.get("status", "").strip()

    sql = "SELECT * FROM contacts WHERE 1=1"
    params = []
    if q:
        sql += " AND (first_name LIKE ? OR last_name LIKE ? OR email LIKE ? OR organization LIKE ?)"
        like = f"%{q}%"
        params += [like, like, like, like]
    if ctype in ("donor", "volunteer"):
        sql += " AND contact_type = ?"
        params.append(ctype)
    if status:
        sql += " AND status = ?"
        params.append(status)
    sql += " ORDER BY last_name, first_name"

    rows = db.execute(sql, params).fetchall()
    return render_template("contacts.html",
        contacts=rows, q=q, ctype=ctype, status=status,
        pipeline_statuses=PIPELINE_STATUSES)


@app.route("/contacts/new", methods=["GET", "POST"])
@login_required
def contact_new():
    if request.method == "POST":
        f = request.form
        first_name   = f["first_name"].strip()
        last_name    = f["last_name"].strip()
        contact_type = f["contact_type"]
        phone        = f.get("phone", "").strip()
        email        = f.get("email", "").strip()
        organization = f.get("organization", "").strip()
        status       = f.get("status", "New")
        notes        = f.get("notes", "").strip()

        if not first_name or not last_name:
            flash("First name and last name are required.", "error")
            return render_template("contact_form.html", contact=f, action="new",
                                   pipeline_statuses=PIPELINE_STATUSES)

        db = get_db()
        if email:
            dup = db.execute("SELECT id FROM contacts WHERE email = ?", (email,)).fetchone()
            if dup:
                flash("A contact with that email already exists.", "error")
                return render_template("contact_form.html", contact=f, action="new",
                                       pipeline_statuses=PIPELINE_STATUSES)
        if phone:
            dup = db.execute("SELECT id FROM contacts WHERE phone = ?", (phone,)).fetchone()
            if dup:
                flash("A contact with that phone number already exists.", "error")
                return render_template("contact_form.html", contact=f, action="new",
                                       pipeline_statuses=PIPELINE_STATUSES)

        db.execute(
            "INSERT INTO contacts (first_name,last_name,contact_type,phone,email,organization,status,notes) VALUES (?,?,?,?,?,?,?,?)",
            (first_name, last_name, contact_type, phone, email, organization, status, notes)
        )
        db.commit()
        flash(f"{first_name} {last_name} added successfully.", "success")
        return redirect(url_for("contacts"))

    return render_template("contact_form.html", contact={}, action="new",
                           pipeline_statuses=PIPELINE_STATUSES)


@app.route("/contacts/<int:cid>/edit", methods=["GET", "POST"])
@login_required
def contact_edit(cid):
    db = get_db()
    contact = db.execute("SELECT * FROM contacts WHERE id=?", (cid,)).fetchone()
    if not contact:
        flash("Contact not found.", "error")
        return redirect(url_for("contacts"))

    if request.method == "POST":
        f = request.form
        first_name   = f["first_name"].strip()
        last_name    = f["last_name"].strip()
        contact_type = f["contact_type"]
        phone        = f.get("phone", "").strip()
        email        = f.get("email", "").strip()
        organization = f.get("organization", "").strip()
        status       = f.get("status", "New")
        notes        = f.get("notes", "").strip()

        if not first_name or not last_name:
            flash("First name and last name are required.", "error")
            return render_template("contact_form.html", contact=f, action="edit", cid=cid,
                                   pipeline_statuses=PIPELINE_STATUSES)

        if email:
            dup = db.execute("SELECT id FROM contacts WHERE email=? AND id!=?", (email, cid)).fetchone()
            if dup:
                flash("Another contact with that email already exists.", "error")
                return render_template("contact_form.html", contact=f, action="edit", cid=cid,
                                       pipeline_statuses=PIPELINE_STATUSES)
        if phone:
            dup = db.execute("SELECT id FROM contacts WHERE phone=? AND id!=?", (phone, cid)).fetchone()
            if dup:
                flash("Another contact with that phone already exists.", "error")
                return render_template("contact_form.html", contact=f, action="edit", cid=cid,
                                       pipeline_statuses=PIPELINE_STATUSES)

        db.execute("""
            UPDATE contacts SET first_name=?,last_name=?,contact_type=?,phone=?,email=?,
            organization=?,status=?,notes=?,updated_at=datetime('now') WHERE id=?
        """, (first_name, last_name, contact_type, phone, email, organization, status, notes, cid))
        db.commit()
        flash("Contact updated.", "success")
        return redirect(url_for("contact_detail", cid=cid))

    return render_template("contact_form.html", contact=contact, action="edit", cid=cid,
                           pipeline_statuses=PIPELINE_STATUSES)


@app.route("/contacts/<int:cid>")
@login_required
def contact_detail(cid):
    db = get_db()
    contact = db.execute("SELECT * FROM contacts WHERE id=?", (cid,)).fetchone()
    if not contact:
        flash("Contact not found.", "error")
        return redirect(url_for("contacts"))
    logs = db.execute(
        "SELECT * FROM outreach_logs WHERE contact_id=? ORDER BY outreach_date DESC, created_at DESC",
        (cid,)
    ).fetchall()
    return render_template("contact_detail.html", contact=contact, logs=logs)


@app.route("/contacts/<int:cid>/delete", methods=["POST"])
@login_required
def contact_delete(cid):
    db = get_db()
    contact = db.execute("SELECT * FROM contacts WHERE id=?", (cid,)).fetchone()
    if contact:
        db.execute("DELETE FROM contacts WHERE id=?", (cid,))
        db.commit()
        flash(f"{contact['first_name']} {contact['last_name']} deleted.", "success")
    return redirect(url_for("contacts"))


# ---------------------------------------------------------------------------
# Outreach Logs
# ---------------------------------------------------------------------------

@app.route("/outreach")
@login_required
def outreach_logs():
    db = get_db()
    logs = db.execute("""
        SELECT ol.*, c.first_name || ' ' || c.last_name AS contact_name
        FROM outreach_logs ol
        JOIN contacts c ON c.id = ol.contact_id
        ORDER BY ol.outreach_date DESC, ol.created_at DESC
    """).fetchall()
    return render_template("outreach_logs.html", logs=logs)


@app.route("/outreach/new", methods=["GET", "POST"])
@app.route("/contacts/<int:cid>/outreach/new", methods=["GET", "POST"])
@login_required
def outreach_new(cid=None):
    db = get_db()
    contacts_list = db.execute(
        "SELECT id, first_name || ' ' || last_name AS name FROM contacts ORDER BY last_name"
    ).fetchall()

    if request.method == "POST":
        f = request.form
        contact_id      = f["contact_id"]
        outreach_date   = f["outreach_date"]
        team_member     = f["team_member"].strip()
        method          = f["method"]
        outcome         = f["outcome"]
        donation_amount = f.get("donation_amount", "0") or "0"
        follow_up_date  = f.get("follow_up_date", "").strip() or None
        notes           = f.get("notes", "").strip()

        if not contact_id or not outreach_date or not team_member:
            flash("Contact, date, and team member are required.", "error")
            return render_template("outreach_logs.html",
                logs=db.execute("SELECT ol.*, c.first_name||' '||c.last_name AS contact_name FROM outreach_logs ol JOIN contacts c ON c.id=ol.contact_id ORDER BY ol.outreach_date DESC").fetchall(),
                contacts_list=contacts_list, show_form=True, form_data=f, preselect_cid=cid)

        try:
            donation_amount = float(donation_amount)
        except ValueError:
            donation_amount = 0.0

        db.execute("""
            INSERT INTO outreach_logs (contact_id,outreach_date,team_member,method,outcome,donation_amount,follow_up_date,notes)
            VALUES (?,?,?,?,?,?,?,?)
        """, (contact_id, outreach_date, team_member, method, outcome, donation_amount, follow_up_date, notes))
        db.commit()
        flash("Outreach log added.", "success")

        if cid:
            return redirect(url_for("contact_detail", cid=cid))
        return redirect(url_for("outreach_logs"))

    logs = db.execute("""
        SELECT ol.*, c.first_name || ' ' || c.last_name AS contact_name
        FROM outreach_logs ol JOIN contacts c ON c.id = ol.contact_id
        ORDER BY ol.outreach_date DESC, ol.created_at DESC
    """).fetchall()
    return render_template("outreach_logs.html",
        logs=logs, contacts_list=contacts_list,
        show_form=True, form_data={}, preselect_cid=cid)


# ---------------------------------------------------------------------------
# Weekly Report
# ---------------------------------------------------------------------------

@app.route("/report")
@login_required
def weekly_report():
    db = get_db()
    week_start, week_end = week_bounds()
    today_str = str(date.today())

    total_attempts = db.execute(
        "SELECT COUNT(*) FROM outreach_logs WHERE outreach_date BETWEEN ? AND ?",
        (week_start, week_end)
    ).fetchone()[0]

    unique_contacts = db.execute(
        "SELECT COUNT(DISTINCT contact_id) FROM outreach_logs WHERE outreach_date BETWEEN ? AND ?",
        (week_start, week_end)
    ).fetchone()[0]

    by_method = db.execute(
        "SELECT method, COUNT(*) as cnt FROM outreach_logs WHERE outreach_date BETWEEN ? AND ? GROUP BY method ORDER BY cnt DESC",
        (week_start, week_end)
    ).fetchall()

    by_outcome = db.execute(
        "SELECT outcome, COUNT(*) as cnt FROM outreach_logs WHERE outreach_date BETWEEN ? AND ? GROUP BY outcome ORDER BY cnt DESC",
        (week_start, week_end)
    ).fetchall()

    by_team = db.execute(
        "SELECT team_member, COUNT(*) as cnt FROM outreach_logs WHERE outreach_date BETWEEN ? AND ? GROUP BY team_member ORDER BY cnt DESC",
        (week_start, week_end)
    ).fetchall()

    followups_due = db.execute("""
        SELECT ol.follow_up_date, c.first_name || ' ' || c.last_name AS contact_name,
               ol.team_member, ol.notes, c.id AS contact_id
        FROM outreach_logs ol JOIN contacts c ON c.id = ol.contact_id
        WHERE ol.follow_up_date BETWEEN ? AND ?
        ORDER BY ol.follow_up_date
    """, (week_start, week_end)).fetchall()

    overdue_followups = db.execute("""
        SELECT ol.follow_up_date, c.first_name || ' ' || c.last_name AS contact_name,
               ol.team_member, ol.notes, c.id AS contact_id
        FROM outreach_logs ol JOIN contacts c ON c.id = ol.contact_id
        WHERE ol.follow_up_date < ? AND ol.follow_up_date IS NOT NULL AND ol.follow_up_date != ''
        ORDER BY ol.follow_up_date
    """, (today_str,)).fetchall()

    donation_total = db.execute(
        "SELECT COALESCE(SUM(donation_amount),0) FROM outreach_logs WHERE outreach_date BETWEEN ? AND ?",
        (week_start, week_end)
    ).fetchone()[0]

    new_contacts = db.execute(
        "SELECT * FROM contacts WHERE date(created_at) BETWEEN ? AND ? ORDER BY created_at DESC",
        (week_start, week_end)
    ).fetchall()

    return render_template("weekly_report.html",
        week_start=week_start, week_end=week_end,
        total_attempts=total_attempts, unique_contacts=unique_contacts,
        by_method=by_method, by_outcome=by_outcome, by_team=by_team,
        followups_due=followups_due, overdue_followups=overdue_followups,
        donation_total=donation_total, new_contacts=new_contacts,
    )


# ---------------------------------------------------------------------------
# CSV Exports
# ---------------------------------------------------------------------------

@app.route("/export/contacts")
@login_required
def export_contacts():
    db = get_db()
    rows = db.execute("SELECT * FROM contacts ORDER BY last_name, first_name").fetchall()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["id","first_name","last_name","contact_type","phone","email","organization","status","notes","created_at","updated_at"])
    for r in rows:
        writer.writerow(list(r))
    return Response(output.getvalue(), mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=contacts.csv"})


@app.route("/export/outreach")
@login_required
def export_outreach():
    db = get_db()
    rows = db.execute("""
        SELECT ol.id, c.first_name||' '||c.last_name, ol.outreach_date, ol.team_member,
               ol.method, ol.outcome, ol.donation_amount, ol.follow_up_date, ol.notes, ol.created_at
        FROM outreach_logs ol JOIN contacts c ON c.id=ol.contact_id
        ORDER BY ol.outreach_date DESC
    """).fetchall()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["id","contact_name","outreach_date","team_member","method","outcome","donation_amount","follow_up_date","notes","created_at"])
    for r in rows:
        writer.writerow(list(r))
    return Response(output.getvalue(), mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=outreach_logs.csv"})


@app.route("/export/weekly")
@login_required
def export_weekly():
    db = get_db()
    week_start, week_end = week_bounds()
    rows = db.execute("""
        SELECT ol.outreach_date, c.first_name||' '||c.last_name AS contact_name,
               c.contact_type, ol.team_member, ol.method, ol.outcome,
               ol.donation_amount, ol.follow_up_date, ol.notes
        FROM outreach_logs ol JOIN contacts c ON c.id=ol.contact_id
        WHERE ol.outreach_date BETWEEN ? AND ?
        ORDER BY ol.outreach_date
    """, (week_start, week_end)).fetchall()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["outreach_date","contact_name","contact_type","team_member","method","outcome","donation_amount","follow_up_date","notes"])
    for r in rows:
        writer.writerow(list(r))
    return Response(output.getvalue(), mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename=weekly_report_{week_start}.csv"})


# ---------------------------------------------------------------------------
# How to Use
# ---------------------------------------------------------------------------

@app.route("/how-to-use")
@login_required
def how_to_use():
    return render_template("how_to_use.html")


# ---------------------------------------------------------------------------
# Admin — Clear All Data
# TEMPORARY ROUTE: Delete this route after you have used it once.
# ---------------------------------------------------------------------------

@app.route("/admin/clear-data", methods=["GET", "POST"])
@login_required
def admin_clear_data():
    if request.method == "POST":
        db = get_db()
        db.execute("DELETE FROM outreach_logs")
        db.execute("DELETE FROM contacts")
        db.commit()
        flash("All contacts and outreach logs have been permanently deleted.", "success")
        return redirect(url_for("dashboard"))
    return render_template("admin_clear.html")


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app.run(debug=True, port=5000)
