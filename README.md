# Emerging 100 Outreach

A lightweight CRM for the Emerging 100 team to track outreach to donors, volunteers, and organizations. Built with Python, Flask, and SQLite.

---

## Features

- **Dashboard** — weekly stat cards and recent outreach activity
- **Contacts** — add, edit, search, and filter donors and volunteers
- **Outreach Logs** — log every call, text, email, and in-person visit
- **Weekly Report** — outreach by method, outcome, and team member
- **CSV Exports** — export contacts, outreach logs, and weekly reports
- **How to Use** — plain-English help guide for the whole team

---

## Running Locally

### Requirements

- Python 3.10 or higher
- pip

### Setup

```bash
# 1. Clone the repository
git clone https://github.com/sntimmons/donor-outreach-crm.git
cd donor-outreach-crm

# 2. Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Run the app
python app.py
```

Open http://localhost:5000 in your browser.

The SQLite database (`crm.db`) is created automatically on first run and populated with sample data.

---

## Project Structure

```
donor-outreach-crm/
├── app.py                  # Flask app, all routes, database logic
├── requirements.txt        # Python dependencies
├── Procfile                # Railway / Heroku start command
├── .gitignore
├── crm.db                  # SQLite database (auto-created, not in git)
├── static/
│   └── styles.css
└── templates/
    ├── base.html
    ├── dashboard.html
    ├── contacts.html
    ├── contact_form.html
    ├── contact_detail.html
    ├── outreach_logs.html
    ├── weekly_report.html
    └── how_to_use.html
```

---

## Deployment on Railway

### Step 1 — Push your code to GitHub

Make sure your latest changes are committed and pushed:

```bash
git add .
git commit -m "Your message"
git push origin main
```

### Step 2 — Create a new Railway project

1. Go to [railway.app](https://railway.app) and log in.
2. Click **New Project** and select **Deploy from GitHub repo**.
3. Choose the `donor-outreach-crm` repository.
4. Railway will detect the `Procfile` and deploy automatically.

### Step 3 — Set environment variables

In the Railway project settings, under the **Variables** tab, add:

| Variable | Description | Example |
|---|---|---|
| `SECRET_KEY` | A long random string used to secure sessions. Do not share this. | `a9f2c...` |
| `DATABASE_PATH` | Path to the SQLite database file. See the note below. | `/data/crm.db` |

To generate a secure `SECRET_KEY`, run this in your terminal:

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

### Step 4 — Build and start commands

Railway will use these automatically from the `Procfile`, but if you need to set them manually:

- **Build command:** `pip install -r requirements.txt`
- **Start command:** `gunicorn app:app --bind 0.0.0.0:$PORT`

### Important note on SQLite and Railway

Railway's filesystem is **ephemeral** by default. This means the SQLite database will be reset every time the app redeploys or restarts.

To keep your data between deploys, you have two options:

**Option A — Railway Volume (recommended for SQLite)**
1. In Railway, add a **Volume** to your service.
2. Mount it at a path like `/data`.
3. Set the `DATABASE_PATH` environment variable to `/data/crm.db`.
4. Your data will now persist across deploys.

**Option B — Migrate to PostgreSQL (recommended for larger teams)**
If your team grows or you need more reliability, consider migrating to PostgreSQL.
Railway offers a free PostgreSQL add-on. This would require updating `app.py` to use
`psycopg2` instead of `sqlite3`, which is a moderate code change.

---

## Environment Variables Reference

| Variable | Required | Default | Description |
|---|---|---|---|
| `SECRET_KEY` | Yes (in production) | `dev-secret-change-in-production` | Flask session security key |
| `DATABASE_PATH` | No | `crm.db` | Path to the SQLite database file |
| `PORT` | Set by Railway | — | Port the server listens on (set automatically by Railway) |

---

## Local Development Notes

- The app runs in debug mode locally (`python app.py`).
- Debug mode is **not** used when running via gunicorn in production.
- The database seeds sample contacts and outreach logs on first run if the tables are empty.
- To reset the database, delete `crm.db` and restart the app.
