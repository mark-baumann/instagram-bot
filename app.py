from __future__ import annotations

import os
import json
from datetime import datetime
from flask import Flask, request, redirect, url_for, session, render_template_string
from instagrapi import Client
from instagrapi.exceptions import LoginRequired

# -----------------------------
# Config
# -----------------------------
# WICHTIG: Setze in Vercel eine lange FLASK_SECRET Variable!
APP_SECRET = os.environ.get("FLASK_SECRET", "völlig-geheimes-passwort-123")
THREADS_PER_PAGE = 30
MSGS_PER_THREAD = 50

app = Flask(__name__)
app.secret_key = APP_SECRET

# -----------------------------
# Helpers
# -----------------------------
def fmt_dt(dt) -> str:
    if not dt: return "?"
    return dt.astimezone().strftime("%Y-%m-%d %H:%M:%S")

def get_client() -> Client:
    """
    Lädt den Client direkt aus den im Flask-Cookie gespeicherten Settings.
    Es wird keine Datei auf Disk benötigt.
    """
    cl = Client()
    
    # Versuche die Settings aus dem Cookie (Session) zu laden
    ig_settings = session.get("ig_settings")
    if ig_settings:
        cl.set_settings(ig_settings)
    
    # Falls wir Username/Passwort haben, aber keine Session oder Session abgelaufen
    if not cl.user_id:
        username = session.get("ig_username")
        password = session.get("ig_password")
        if username and password:
            cl.login(username, password)
            # Nach Login neue Settings im Cookie speichern
            session["ig_settings"] = cl.get_settings()
        else:
            raise LoginRequired("Session abgelaufen oder nicht vorhanden.")
            
    return cl

def thread_title(thread) -> str:
    users = getattr(thread, "users", None) or []
    title = ", ".join([getattr(u, "username", "?") for u in users]).strip()
    return title if title else f"(ID: {getattr(thread,'id','?')})"

# -----------------------------
# Routes
# -----------------------------
@app.route("/")
def index():
    if "ig_settings" in session or "ig_username" in session:
        return redirect(url_for("threads"))
    return redirect(url_for("login"))

@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        file = request.files.get("session_file")
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()

        try:
            cl = Client()
            if file and file.filename.endswith(".json"):
                # Datei im Speicher lesen (nicht auf Disk speichern!)
                file_content = file.read().decode("utf-8")
                settings = json.loads(file_content)
                cl.set_settings(settings)
                cl.get_timeline_feed() # Test
                session["ig_settings"] = settings
                return redirect(url_for("threads"))

            elif username and password:
                cl.login(username, password)
                session["ig_username"] = username
                session["ig_password"] = password
                session["ig_settings"] = cl.get_settings()
                return redirect(url_for("threads"))
        except Exception as e:
            error = f"Fehler: {e}"

    return render_template_string("""
    <html><head><meta charset="utf-8"><title>Login</title></head>
    <body style="font-family: sans-serif; max-width: 500px; margin: 50px auto;">
      <h2>IG DM Login (Vercel Ready)</h2>
      <form method="post" enctype="multipart/form-data" style="border: 1px solid #ccc; padding: 20px;">
        <h3>Variante A: session.json</h3>
        <input type="file" name="session_file" accept=".json"><br><br>
        <hr>
        <h3>Variante B: Credentials</h3>
        <input name="username" placeholder="Username" style="width:100%"><br><br>
        <input name="password" type="password" placeholder="Password" style="width:100%"><br><br>
        <button type="submit" style="width:100%; padding: 10px;">Login</button>
      </form>
      {% if error %}<p style="color:red;">{{ error }}</p>{% endif %}
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
        threads_list = cl.direct_threads(amount=THREADS_PER_PAGE)
        return render_template_string("""
        <html><body style="font-family: sans-serif; max-width: 800px; margin: 40px auto;">
          <h2>Deine Chats</h2>
          <a href="{{ url_for('logout') }}">Logout</a><br><br>
          <ul style="list-style: none; padding: 0;">
            {% for t in threads %}
              <li style="padding: 10px; border-bottom: 1px solid #eee;">
                <a href="{{ url_for('thread_view', thread_id=t.id) }}" style="text-decoration: none; color: #0095f6; font-weight: bold;">
                  {{ titles[t.id] }}
                </a>
              </li>
            {% endfor %}
          </ul>
        </body></html>
        """, threads=threads_list, titles={t.id: thread_title(t) for t in threads_list})
    except Exception as e:
        return f"Fehler: {e} <br><a href='/login'>Neu einloggen</a>"

@app.route("/thread/<thread_id>")
def thread_view(thread_id):
    try:
        cl = get_client()
        msgs = cl.direct_messages(thread_id, amount=MSGS_PER_THREAD) or []
        msgs_sorted = sorted(msgs, key=lambda m: getattr(m, "timestamp", datetime.min))
        
        return render_template_string("""
        <html><body style="font-family: sans-serif; max-width: 800px; margin: 40px auto;">
          <a href="{{ url_for('threads') }}">← Zurück</a>
          <h3>Chat</h3>
          <div style="background: #f9f9f9; padding: 15px; border: 1px solid #ddd;">
            {% for m in msgs %}
              <div style="margin-bottom: 10px;">
                <small style="color: #999;">{{ m.timestamp.strftime('%H:%M') if m.timestamp else '' }}</small> 
                <strong>{{ 'Du' if m.user_id|string == my_id|string else 'Partner' }}:</strong> 
                {{ m.text or '[Media]' }}
              </div>
            {% endfor %}
          </div>
        </body></html>
        """, msgs=msgs_sorted, my_id=cl.user_id)
    except Exception as e:
        return f"Fehler: {e}"

if __name__ == "__main__":
    app.run(debug=True)