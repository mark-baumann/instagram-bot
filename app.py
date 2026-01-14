from __future__ import annotations

import os
import json
from datetime import datetime
from flask import Flask, request, redirect, url_for, session, render_template_string, Response
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
def get_client() -> Client:
    """Lädt den Client aus der Session oder loggt neu ein."""
    cl = Client()
    ig_settings = session.get("ig_settings")
    if ig_settings:
        cl.set_settings(ig_settings)
    
    if not cl.user_id:
        username = session.get("ig_username")
        password = session.get("ig_password")
        if username and password:
            cl.login(username, password)
            session["ig_settings"] = cl.get_settings()
        else:
            raise LoginRequired("Session abgelaufen oder nicht vorhanden.")
            
    return cl

def thread_title(thread) -> str:
    """Erzeugt einen Titel für den Chat (Usernamen der Teilnehmer)."""
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
                file_content = file.read().decode("utf-8")
                settings = json.loads(file_content)
                cl.set_settings(settings)
                cl.get_timeline_feed() 
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
    <body style="font-family: sans-serif; max-width: 500px; margin: 50px auto; background: #fafafa;">
      <div style="background: white; border: 1px solid #ddd; padding: 30px; border-radius: 8px;">
          <h2>IG DM Login</h2>
          <form method="post" enctype="multipart/form-data">
            <h3>Variante A: session.json upload</h3>
            <input type="file" name="session_file" accept=".json"><br><br>
            <hr>
            <h3>Variante B: Credentials</h3>
            <input name="username" placeholder="Username" style="width:100%; margin-bottom: 10px; padding: 8px;">
            <input name="password" type="password" placeholder="Password" style="width:100%; margin-bottom: 20px; padding: 8px;">
            <button type="submit" style="width:100%; padding: 10px; background: #0095f6; color: white; border: none; border-radius: 4px; cursor: pointer;">Login</button>
          </form>
          {% if error %}<p style="color:red;">{{ error }}</p>{% endif %}
      </div>
    </body></html>
    """, error=error)

@app.route("/download_session")
def download_session():
    """Erlaubt den Download der aktuellen Session-Daten als JSON-Datei."""
    settings = session.get("ig_settings")
    if not settings:
        return "Keine Session gefunden. Bitte erst einloggen.", 404
    
    return Response(
        json.dumps(settings, indent=4),
        mimetype="application/json",
        headers={"Content-Disposition": "attachment;filename=session.json"}
    )

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
          <div style="display: flex; justify-content: space-between; align-items: center;">
              <h2>Deine Chats</h2>
              <div>
                  <a href="{{ url_for('download_session') }}" style="background: #34a853; color: white; padding: 8px 12px; text-decoration: none; border-radius: 4px; font-size: 14px; margin-right: 10px;">💾 session.json herunterladen</a>
                  <a href="{{ url_for('logout') }}" style="color: #666;">Logout</a>
              </div>
          </div>
          <ul style="list-style: none; padding: 0; margin-top: 20px;">
            {% for t in threads %}
              <li style="padding: 15px; border-bottom: 1px solid #eee;">
                <a href="{{ url_for('thread_view', thread_id=t.id) }}" style="text-decoration: none; color: #0095f6; font-weight: bold; font-size: 18px;">
                  {{ titles[t.id] }}
                </a>
              </li>
            {% endfor %}
          </ul>
        </body></html>
        """, threads=threads_list, titles={t.id: thread_title(t) for t in threads_list})
    except Exception as e:
        return f"Fehler: {e} <br><a href='/login'>Neu einloggen</a>"

@app.route("/thread/<thread_id>", methods=["GET", "POST"])
def thread_view(thread_id):
    try:
        cl = get_client()
        
        # POST: Nachricht im Hintergrund empfangen
        if request.method == "POST":
            text = request.form.get("message")
            if text:
                cl.direct_send(text, thread_ids=[thread_id])
            # Wir antworten nur mit "OK", damit die Seite nicht neu lädt
            return {"status": "success"}, 200

        # Thread-Details & Nachrichten laden
        thread = cl.direct_thread(thread_id)
        user_map = {str(u.pk): u.username for u in thread.users}
        user_map[str(cl.user_id)] = "Du"

        msgs = cl.direct_messages(thread_id, amount=MSGS_PER_THREAD) or []
        msgs_sorted = sorted(msgs, key=lambda m: getattr(m, "timestamp", datetime.min))
        
        return render_template_string("""
        <html>
        <head>
            <meta charset="utf-8">
            <title>Chat</title>
            <meta name="viewport" content="width=device-width, initial-scale=1">
        </head>
        <body style="font-family: sans-serif; max-width: 800px; margin: 40px auto; background: #f0f2f5; padding: 10px;">
          <a href="{{ url_for('threads') }}" style="text-decoration: none; color: #666; font-weight: bold;">← Zurück</a>
          <h3>Chat mit {{ title }}</h3>
          
          <div id="chat-window" style="background: white; padding: 15px; border: 1px solid #ddd; height: 500px; overflow-y: scroll; display: flex; flex-direction: column; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">
            {% for m in msgs %}
              <div class="msg-bubble" style="margin-bottom: 15px; max-width: 85%; {{ 'align-self: flex-end; text-align: right;' if m.user_id|string == my_id|string else 'align-self: flex-start;' }}">
                <small style="color: #999; display: block; margin-bottom: 2px;">
                    {{ user_names.get(m.user_id|string, 'Unbekannt') }} • {{ m.timestamp.strftime('%H:%M') if m.timestamp else '' }}
                </small> 
                <div style="display: inline-block; padding: 10px 14px; border-radius: 18px; 
                            {{ 'background: #0084ff; color: white;' if m.user_id|string == my_id|string else 'background: #e4e6eb; color: black;' }}">
                    {{ m.text or '[Media/Anhang]' }}
                </div>
              </div>
            {% endfor %}
          </div>

          <form id="message-form" style="margin-top: 20px; display: flex; gap: 10px;">
              <input name="message" id="msg-input" placeholder="Nachricht schreiben..." style="flex-grow: 1; padding: 12px; border: 1px solid #ccc; border-radius: 25px; outline: none;" required autocomplete="off">
              <button type="submit" style="padding: 10px 25px; background: #0084ff; color: white; border: none; border-radius: 25px; cursor: pointer; font-weight: bold;">Senden</button>
          </form>

          <script>
            const chatWindow = document.getElementById("chat-window");
            const messageForm = document.getElementById("message-form");
            const msgInput = document.getElementById("msg-input");

            // Scrollt nach ganz unten
            function scrollToBottom() {
                chatWindow.scrollTop = chatWindow.scrollHeight;
            }

            // Beim ersten Laden nach unten scrollen
            window.onload = scrollToBottom;

            // Nachricht absenden ohne Reload
            messageForm.onsubmit = async (e) => {
                e.preventDefault(); // Verhindert den Seiten-Reload!
                
                const text = msgInput.value;
                if(!text) return;

                // 1. Nachricht sofort im UI anzeigen (für Speed-Gefühl)
                const now = new Date().toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'});
                const newMsg = `
                    <div style="margin-bottom: 15px; max-width: 85%; align-self: flex-end; text-align: right;">
                        <small style="color: #999; display: block; margin-bottom: 2px;">Du • ${now}</small> 
                        <div style="display: inline-block; padding: 10px 14px; border-radius: 18px; background: #0084ff; color: white;">
                            ${text}
                        </div>
                    </div>`;
                chatWindow.innerHTML += newMsg;
                scrollToBottom();
                
                // Input leeren
                msgInput.value = "";

                // 2. Nachricht im Hintergrund an den Server senden
                const formData = new FormData();
                formData.append('message', text);

                try {
                    await fetch(window.location.href, {
                        method: 'POST',
                        body: formData
                    });
                } catch (err) {
                    alert("Fehler beim Senden!");
                }
            };
          </script>

        </body></html>
        """, 
        msgs=msgs_sorted, 
        my_id=cl.user_id, 
        user_names=user_map, 
        title=thread_title(thread))
    except Exception as e:
        return f"Fehler: {e}"

if __name__ == "__main__":
    app.run(debug=True)