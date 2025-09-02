import os
from flask import Flask, request, render_template, jsonify, session, redirect, url_for
from dotenv import load_dotenv
from google import genai
from google.cloud import firestore
from datetime import datetime

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "replace-this-in-prod")

# Load known users
KNOWN_USERNAMES = ["replace this"]
USERS = {}
for username in KNOWN_USERNAMES:
    env_var = f"USER_{username.upper()}_PASSWORD"
    password = os.getenv(env_var)
    if password:
        USERS[username] = password

# Init Gemini and Firestore
client = genai.Client()
db = firestore.Client()

@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        if username in USERS and USERS[username] == password:
            session["authenticated"] = True
            session["username"] = username
            return redirect(url_for("chat_page"))
        return render_template("login.html", error="Invalid username or password.")
    return render_template("login.html")

@app.route("/chat")
def chat_page():
    if not session.get("authenticated"):
        return redirect(url_for("login"))

    username = session.get("username")

    # Get last 10 messages (ordered oldest first)
    messages_ref = (
        db.collection("default")
        .document(username)
        .collection("messages")
        .order_by("timestamp", direction=firestore.Query.DESCENDING)
        .limit(10)
    )
    messages = []
    for doc in reversed(list(messages_ref.stream())):
        data = doc.to_dict()
        # Format timestamp into human-readable form
        ts = data.get("timestamp")
        data["timestamp"] = ts.strftime("%b %d, %I:%M %p") if ts else ""
        messages.append(data)

    return render_template("index.html", username=username, history=messages)

@app.route("/chat", methods=["POST"])
def chat():
    if not session.get("authenticated"):
        return jsonify({"error": "Unauthorized"}), 401

    user_input = request.json.get("message", "")
    username = session.get("username", "unknown_user")

    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash-lite",
            contents=user_input
        )
        ai_response = response.text

        # Save to Firestore
        db.collection("default").document(username).collection("messages").add({
            "user": username,
            "user_message": user_input,
            "ai_response": ai_response,
            "timestamp": firestore.SERVER_TIMESTAMP
        })

        return jsonify({"response": ai_response})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/clear-history", methods=["POST"])
def clear_history():
    if not session.get("authenticated"):
        return jsonify({"error": "Unauthorized"}), 401

    username = session.get("username")

    try:
        messages_ref = db.collection("default").document(username).collection("messages")
        for doc in messages_ref.stream():
            doc.reference.delete()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/logout")
def logout():
    session.pop("authenticated", None)
    session.pop("username", None)
    return redirect(url_for("login"))

if __name__ == "__main__":
    app.run(debug=True)
