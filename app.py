from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

from flask import Flask, request, redirect, url_for, session, render_template_string, abort
from instagrapi import Client
from instagrapi.exceptions import LoginRequired

# -----------------------------
# Config
# -----------------------------
APP_SECRET = os.environ.get("FLASK_SECRET", "change-me-please")  # für session cookie
SESSION_FILE = Path("ig_session.json")  # instagrapi settings/session persistenz
THREADS_PER_PAGE = 50
MSGS_PER_THREAD = 200

app = Flask(__name__)
app.secret_key = APP_SECRET  # Flask: secret key für Sessions [web:55]

# -----------------------------
# Helpers
# -----------------------------
def fmt_dt(dt) -> str:
    if not dt:
        return "?"
    return dt.astimezone().strftime("%Y-%m-%d %H:%M:%S")

def get_client() -> Client:
    """
    Client aus Flask-session bauen (Username/Passwort aus session),
    instagrapi settings aus Datei laden (damit nicht jedes Mal "neues Gerät").
    """
    if "ig_username" not in session or "ig_password" not in session:
        raise LoginRequired("Not logged in")

    cl = Client()
    if SESSION_FILE.exists():
        cl.load_settings(str(SESSION_FILE))

    cl.login(session["ig_username"], session["ig_password"])
    cl.dump_settings(str(SESSION_FILE))
    return cl

def thread_title(thread) -> str:
    users = getattr(thread, "users", None) or []
    title = ", ".join([getattr(u, "username", "?") for u in users]).strip()
    return title if title else f"(thread {getattr(thread,'id','?')})"

# -----------------------------
# Routes
# -----------------------------
@app.route("/", methods=["GET"])
def index():
    if "ig_username" in session:
        return redirect(url_for("threads"))
    return redirect(url_for("login"))

@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        session["ig_username"] = request.form.get("username", "").strip()
        session["ig_password"] = request.form.get("password", "").strip()
        try:
            cl = get_client()
            # Session validieren (Best-Practice Idee): timeline feed abfragen
            cl.get_timeline_feed()
            return redirect(url_for("threads"))
        except Exception as e:
            error = f"{type(e).__name__}: {e}"

    return render_template_string("""
    <html><head><meta charset="utf-8"><title>IG DM Viewer</title></head>
    <body style="font-family: sans-serif; max-width: 900px; margin: 40px auto;">
      <h2>Instagram Login</h2>
      <form method="post">
        <label>Username</label><br>
        <input name="username" style="width: 320px" required><br><br>
        <label>Password</label><br>
        <input name="password" type="password" style="width: 320px" required><br><br>
        <button type="submit">Login</button>
      </form>
      {% if error %}
        <p style="color: #b00;"><b>Fehler:</b> {{ error }}</p>
      {% endif %}
      <p style="color:#666;">
        Hinweis: Credentials werden in der Flask-Session (Cookie-gesigned) gehalten; nutze das nur lokal.
      </p>
    </body></html>
    """, error=error)

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route("/threads")
def threads():
    try:
        cl = get_client()
        # Get all threads from inbox [web:37]
        threads = cl.direct_threads(amount=THREADS_PER_PAGE)
    except Exception as e:
        return render_template_string("""
        <p>Login/Fetch fehlgeschlagen: <b>{{err}}</b></p>
        <p><a href="{{url_for('login')}}">Zurück zum Login</a></p>
        """, err=f"{type(e).__name__}: {e}")

    return render_template_string("""
    <html><head><meta charset="utf-8"><title>Threads</title></head>
    <body style="font-family: sans-serif; max-width: 1100px; margin: 40px auto;">
      <div style="display:flex; justify-content: space-between; align-items:center;">
        <h2>Chats ({{ threads|length }})</h2>
        <div>
          <a href="{{ url_for('logout') }}">Logout</a>
        </div>
      </div>

      <table border="1" cellpadding="8" cellspacing="0" style="border-collapse: collapse; width: 100%;">
        <tr style="background:#f3f3f3;">
          <th align="left">Chat</th>
          <th align="left">Thread-ID</th>
        </tr>
        {% for t in threads %}
          <tr>
            <td><a href="{{ url_for('thread_view', thread_id=t.id) }}">{{ titles[t.id] }}</a></td>
            <td style="font-family: monospace;">{{ t.id }}</td>
          </tr>
        {% endfor %}
      </table>
    </body></html>
    """, threads=threads, titles={t.id: thread_title(t) for t in threads})

@app.route("/thread/<int:thread_id>")
def thread_view(thread_id: int):
    try:
        cl = get_client()
        # Get only Messages in Thread [web:37]
        msgs = cl.direct_messages(thread_id, amount=MSGS_PER_THREAD) or []
    except Exception as e:
        return render_template_string("""
        <p>Thread konnte nicht geladen werden: <b>{{err}}</b></p>
        <p><a href="{{url_for('threads')}}">Zurück</a></p>
        """, err=f"{type(e).__name__}: {e}")

    msgs_sorted = sorted(msgs, key=lambda m: getattr(m, "timestamp", datetime.min))

    def sender_label(m):
        uid = getattr(m, "user_id", None)
        if not uid:
            return "system/unknown"
        if uid == cl.user_id:
            return "you"
        return str(uid)  # bewusst kein user_info() (bei dir gab es KeyError 'data')

    def msg_text(m):
        txt = getattr(m, "text", None)
        if txt:
            return txt
        return f"[{getattr(m, 'item_type', 'non-text')}]"

    view = [{
        "ts": fmt_dt(getattr(m, "timestamp", None)),
        "sender": sender_label(m),
        "text": msg_text(m),
    } for m in msgs_sorted]

    return render_template_string("""
    <html><head><meta charset="utf-8"><title>Thread {{thread_id}}</title></head>
    <body style="font-family: sans-serif; max-width: 1100px; margin: 40px auto;">
      <div style="display:flex; justify-content: space-between; align-items:center;">
        <h2>Thread {{ thread_id }}</h2>
        <div>
          <a href="{{ url_for('threads') }}">← zurück</a>
        </div>
      </div>

      <div style="font-family: monospace; white-space: pre-wrap; border: 1px solid #ddd; padding: 12px;">
{% for m in msgs %}
[{{m.ts}}] {{m.sender}}: {{m.text}}
{% endfor %}
      </div>
    </body></html>
    """, thread_id=thread_id, msgs=view)

if __name__ == "__main__":
    # lokal starten
    app.run(host="127.0.0.1", port=5000, debug=True)
