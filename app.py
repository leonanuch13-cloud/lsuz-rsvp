"""
LSUZ July 26 Celebration — RSVP App
Run:  pip install -r requirements.txt
      python app.py
Visit http://localhost:5000
Admin roster: http://localhost:5000/admin  (passcode below)

DATA STORAGE:
If a DATABASE_URL environment variable is set (Render Postgres), that is used
so signups survive restarts/redeploys. Otherwise it falls back to a local
rsvp.db SQLite file for quick local testing — note that on Render's free
tier, local disk is wiped on every restart, so DATABASE_URL is required
for production use there.
"""

from flask import Flask, request, redirect, url_for, session, render_template_string, send_file
import sqlite3, os, io
from datetime import datetime
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(APP_DIR, "rsvp.db")
ADMIN_PASSCODE = "LSUZ2026"   # <-- change this

DATABASE_URL = os.environ.get("DATABASE_URL")
IS_PG = bool(DATABASE_URL)

if IS_PG:
    import psycopg2
    import psycopg2.extras

app = Flask(__name__)
app.secret_key = "lsuz-july26-change-this-secret-key"

# ---------- Database ----------
def q(sql):
    """Translate sqlite-style '?' placeholders to psycopg2-style '%s' when on Postgres."""
    return sql.replace("?", "%s") if IS_PG else sql

def get_conn():
    if IS_PG:
        return psycopg2.connect(DATABASE_URL, sslmode="require")
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def db_execute(conn, sql, params=()):
    """Run an INSERT/UPDATE/DDL statement and commit."""
    if IS_PG:
        cur = conn.cursor()
        cur.execute(q(sql), params)
        conn.commit()
        cur.close()
    else:
        conn.execute(sql, params)
        conn.commit()

def db_fetchall(conn, sql, params=()):
    if IS_PG:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(q(sql), params)
        rows = cur.fetchall()
        cur.close()
        return rows
    return conn.execute(sql, params).fetchall()

def db_fetchone(conn, sql, params=()):
    if IS_PG:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(q(sql), params)
        row = cur.fetchone()
        cur.close()
        return row
    return conn.execute(sql, params).fetchone()

def init_db():
    conn = get_conn()
    if IS_PG:
        db_execute(conn, """
            CREATE TABLE IF NOT EXISTS rsvp (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                phone TEXT NOT NULL,
                guests INTEGER NOT NULL DEFAULT 1,
                note TEXT,
                attending INTEGER NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
    else:
        db_execute(conn, """
            CREATE TABLE IF NOT EXISTS rsvp (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                phone TEXT NOT NULL,
                guests INTEGER NOT NULL DEFAULT 1,
                note TEXT,
                attending INTEGER NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
    conn.close()

# Create the table immediately on import — this runs whether the app is
# started with "python app.py" (local) or "gunicorn app:app" (Render).
init_db()

def get_counts():
    conn = get_conn()
    total = db_fetchone(conn, "SELECT COUNT(*) c FROM rsvp")["c"]
    confirmed = db_fetchone(conn, "SELECT COUNT(*) c FROM rsvp WHERE attending=1")["c"]
    conn.close()
    return {"total": total, "confirmed": confirmed}

# ---------- Styling shared across pages ----------
BASE_STYLE = """
<style>
  @import url('https://fonts.googleapis.com/css2?family=Playfair+Display:wght@700;800&display=swap');
  body{margin:0;background:#FBF7EF;color:#1B1B1F;font-family:'Segoe UI',sans-serif;}
  .hero{background:#002868;color:#fff;padding:48px 24px 40px;text-align:center;}
  .hero .star{margin-bottom:18px;}
  .hero .org{text-transform:uppercase;letter-spacing:3px;font-size:12.5px;font-weight:600;
    color:rgba(255,255,255,0.75);margin:0 0 14px;}
  .hero h1{font-family:'Playfair Display',Georgia,serif;font-weight:700;font-size:42px;
    line-height:1.15;margin:0 0 16px;}
  .hero .tagline{color:rgba(255,255,255,0.85);font-size:15px;line-height:1.55;
    max-width:340px;margin:0 auto;}
  .hero p{color:rgba(255,255,255,0.8);font-size:14px;margin:0;}
  .stripes{display:flex;height:8px;}
  .stripes span{flex:1;}
  .stripes span:nth-child(odd){background:#BF0A30;}
  .stripes span:nth-child(even){background:#fff;}
  main{max-width:480px;margin:30px auto;padding:0 20px;}
  .card{background:#fff;border:1px solid #eee;border-radius:12px;padding:26px;}
  .card h2{font-family:'Playfair Display',Georgia,serif;font-size:24px;margin:0 0 8px;}
  .card .intro{color:#666;font-size:14px;line-height:1.55;margin:0 0 6px;}
  label{display:block;font-weight:600;font-size:13px;margin:14px 0 6px;}
  input[type=text],select{width:100%;padding:10px;border:1px solid #ddd;border-radius:8px;
    font-size:15px;box-sizing:border-box;background:#FBF7EF;}
  .toggle{display:flex;gap:10px;margin-top:6px;}
  .toggle label{flex:1;text-align:center;padding:12px;border:1.5px solid #ddd;border-radius:8px;
    cursor:pointer;font-weight:600;font-size:14px;margin:0;}
  .toggle input{display:none;}
  .toggle input:checked + span{color:#fff;}
  .btn{width:100%;padding:14px;border:none;border-radius:8px;background:#BF0A30;color:#fff;
    font-weight:600;font-size:15px;cursor:pointer;margin-top:18px;}
  .error{color:#BF0A30;font-size:13px;margin-top:10px;}
  .count{text-align:center;font-size:13px;color:#555;margin:20px 0;}
  table{width:100%;border-collapse:collapse;font-size:13px;margin-top:16px;}
  th{background:#002868;color:#fff;padding:8px;text-align:left;}
  td{padding:8px;border-top:1px solid #eee;}
  .summary{display:flex;gap:10px;margin-top:16px;}
  .stat{flex:1;background:#FBF7EF;border:1px solid #eee;border-radius:8px;padding:10px;text-align:center;}
  .stat b{font-size:20px;display:block;}
  a.button{display:inline-block;text-decoration:none;background:#002868;color:#fff;padding:10px 16px;
    border-radius:8px;font-size:13px;margin-top:14px;margin-right:8px;}
</style>
"""

FORM_TEMPLATE = BASE_STYLE + """
<div class="hero">
  <svg class="star" width="40" height="40" viewBox="0 0 24 24" fill="#fff" xmlns="http://www.w3.org/2000/svg">
    <path d="M12 2l2.9 6.6L22 9.3l-5 4.9 1.2 7-6.2-3.4-6.2 3.4 1.2-7-5-4.9 7.1-0.7z"/>
  </svg>
  <p class="org">Liberian Students Union &mdash; Zhuzhou</p>
  <h1>July 26<br>Roll Call</h1>
  <p class="tagline">Confirm your seat at the table. One name, one stripe, one celebration.</p>
</div>
<div class="stripes"><span></span><span></span><span></span><span></span><span></span><span></span></div>
<div class="count">{{ counts.confirmed }} confirmed of {{ counts.total }} responses</div>
<main>
  <div class="card">
    <h2>Confirm your spot</h2>
    <p class="intro">Fill this in once — your name joins the roll call above and the committee's list.</p>
    <form method="POST">
      <label>Full name</label>
      <input type="text" name="name" placeholder="e.g. Promise Cooper" required>

      <label>Phone number</label>
      <input type="text" name="phone" placeholder="e.g. 138 0000 0000" required>

      <label>Number attending (including you)</label>
      <input type="text" name="guests" value="1">

      <label>Note or message (optional)</label>
      <input type="text" name="note" placeholder="Anything you'd like us to know">
      

      <label>Will you be attending?</label>
      <div class="toggle">
        <label style="background:#002868;"><input type="radio" name="attending" value="yes" required><span>Yes, I'll be there</span></label>
        <label><input type="radio" name="attending" value="no"><span style="color:#1B1B1F;">Can't make it</span></label>
      </div>

      {% if error %}<div class="error">{{ error }}</div>{% endif %}
      <button class="btn" type="submit">Confirm my spot</button>
    </form>
    <p style="font-size:11.5px;color:#888;margin-top:14px;">
      Only the organizing committee can view individual responses.
    </p>
  </div>
</main>
"""

CONFIRM_TEMPLATE = BASE_STYLE + """
<div class="hero"><h1>Thanks, {{ name }}!</h1><p>Liberian Students Union — Zhuzhou</p></div>
<div class="stripes"><span></span><span></span><span></span><span></span><span></span><span></span></div>
<main>
  <div class="card" style="text-align:center;">
    {% if attending %}
      <h2>You're on the roster 🎉</h2>
      <p>See you at the celebration on July 26!</p>
    {% else %}
      <h2>Noted — you can't make it</h2>
      <p>Thanks for letting us know. We'll miss you!</p>
    {% endif %}
  </div>
</main>
"""

ADMIN_LOGIN_TEMPLATE = BASE_STYLE + """
<div class="hero"><h1>Committee Access</h1></div>
<main>
  <div class="card">
    <form method="POST">
      <label>Passcode</label>
      <input type="text" name="passcode" required>
      {% if error %}<div class="error">{{ error }}</div>{% endif %}
      <button class="btn" type="submit">Unlock roster</button>
    </form>
  </div>
</main>
"""

ADMIN_PANEL_TEMPLATE = BASE_STYLE + """
<div class="hero"><h1>Full Roster</h1></div>
<main>
  <div class="card">
    <div class="summary">
      <div class="stat"><b>{{ summary.confirmed }}</b>Confirmed</div>
      <div class="stat"><b>{{ summary.headcount }}</b>Total headcount</div>
      <div class="stat"><b>{{ summary.declined }}</b>Declined</div>
    </div>
    <table>
      <tr><th>Name</th><th>Phone</th><th>Guests</th><th>Note</th><th>Status</th></tr>
      {% for r in rows %}
      <tr>
        <td>{{ r.name }}</td><td>{{ r.phone }}</td><td>{{ r.guests }}</td>
        <td>{{ r.note or "" }}</td><td>{{ "Confirmed" if r.attending else "Declined" }}</td>
      </tr>
      {% endfor %}
    </table>
    <a class="button" href="{{ url_for('export_pdf') }}">Export as PDF</a>
    <a class="button" href="{{ url_for('admin_logout') }}" style="background:#BF0A30;">Log out</a>
  </div>
</main>
"""

# ---------- Routes ----------
@app.route("/", methods=["GET", "POST"])
def rsvp():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        phone = request.form.get("phone", "").strip()
        attending_raw = request.form.get("attending")
        note = request.form.get("note", "").strip()
        try:
            guests = max(1, int(request.form.get("guests", "1")))
        except ValueError:
            guests = 1

        if not name or not phone or attending_raw not in ("yes", "no"):
            return render_template_string(
                FORM_TEMPLATE, error="Please fill in your name and phone number, and pick an option.",
                counts=get_counts()
            )

        attending = 1 if attending_raw == "yes" else 0
        conn = get_conn()
        db_execute(
            conn,
            "INSERT INTO rsvp (name, phone, guests, note, attending, created_at) VALUES (?,?,?,?,?,?)",
            (name, phone, guests, note, attending, datetime.utcnow().isoformat())
        )
        conn.close()

        return render_template_string(CONFIRM_TEMPLATE, name=name.split(" ")[0], attending=attending)

    return render_template_string(FORM_TEMPLATE, error=None, counts=get_counts())


@app.route("/admin", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        if request.form.get("passcode") == ADMIN_PASSCODE:
            session["admin"] = True
            return redirect(url_for("admin_panel"))
        return render_template_string(ADMIN_LOGIN_TEMPLATE, error="Incorrect passcode — try again.")
    return render_template_string(ADMIN_LOGIN_TEMPLATE, error=None)


@app.route("/admin/panel")
def admin_panel():
    if not session.get("admin"):
        return redirect(url_for("admin_login"))
    conn = get_conn()
    rows = db_fetchall(conn, "SELECT * FROM rsvp ORDER BY created_at DESC")
    conn.close()
    confirmed = sum(1 for r in rows if r["attending"])
    declined = len(rows) - confirmed
    headcount = sum(r["guests"] for r in rows if r["attending"])
    summary = {"confirmed": confirmed, "declined": declined, "headcount": headcount}
    return render_template_string(ADMIN_PANEL_TEMPLATE, rows=rows, summary=summary)


@app.route("/admin/logout")
def admin_logout():
    session.pop("admin", None)
    return redirect(url_for("admin_login"))


@app.route("/admin/export")
def export_pdf():
    if not session.get("admin"):
        return redirect(url_for("admin_login"))
    conn = get_conn()
    rows = db_fetchall(conn, "SELECT * FROM rsvp ORDER BY created_at DESC")
    conn.close()

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    width, height = letter

    c.setFont("Helvetica-Bold", 16)
    c.drawString(50, height - 50, "LSUZ — July 26 Celebration Roster")

    confirmed = sum(1 for r in rows if r["attending"])
    headcount = sum(r["guests"] for r in rows if r["attending"])
    c.setFont("Helvetica", 10)
    c.drawString(50, height - 68, f"Confirmed: {confirmed}   Total headcount: {headcount}   Declined: {len(rows)-confirmed}")

    y = height - 95
    c.setFont("Helvetica-Bold", 10)
    c.drawString(50, y, "Name"); c.drawString(200, y, "Phone")
    c.drawString(340, y, "Guests"); c.drawString(390, y, "Note"); c.drawString(480, y, "Status")
    y -= 6
    c.line(50, y, 560, y)
    y -= 16

    c.setFont("Helvetica", 9)
    for r in rows:
        if y < 60:
            c.showPage()
            y = height - 50
            c.setFont("Helvetica", 9)
        c.drawString(50, y, str(r["name"])[:28])
        c.drawString(200, y, str(r["phone"])[:22])
        c.drawString(340, y, str(r["guests"]))
        c.drawString(390, y, str(r["note"] or "")[:15])
        c.drawString(480, y, "Confirmed" if r["attending"] else "Declined")
        y -= 16

    c.save()
    buf.seek(0)
    return send_file(buf, as_attachment=True, download_name="LSUZ_July26_Roster.pdf", mimetype="application/pdf")


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
