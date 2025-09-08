import os
from flask import Flask, request, render_template, jsonify, session, redirect, url_for
from dotenv import load_dotenv
from google import genai
from google.genai import types
from google.cloud import firestore
from datetime import datetime
import pytz

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

# Set Timezone
LOCAL_TIMEZONE = 'America/Los_Angeles' 

# --- Helper function to get/create user profile ---
def get_or_create_user_profile(username):
    user_profile_ref = db.collection("default").document(username).collection("user_data").document("profile")
    profile_doc = user_profile_ref.get()

    if profile_doc.exists:
        return profile_doc.to_dict()
    else:
        # Default profile for a new user
        default_profile = {
            "agent_persona": "You are a helpful and friendly AI assistant.",
            "agent_goal": "Answer questions and engage in natural conversation.",
            "special_instructions": "",
            "user_display_name": username, # Can be updated later by user if desired
            "created_at": firestore.SERVER_TIMESTAMP
        }
        user_profile_ref.set(default_profile)
        return default_profile

@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        if username in USERS and USERS[username] == password:
            session["authenticated"] = True
            session["username"] = username
            
            # --- Initialize/Get user profile on successful login ---
            get_or_create_user_profile(username) 

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
        .limit(10) # Updated to 10 for consistency, fetching pairs.
    )
    messages = []
    try:
        local_tz = pytz.timezone(LOCAL_TIMEZONE) 
        for doc in reversed(list(messages_ref.stream())):
            data = doc.to_dict()
            ts_utc = data.get("timestamp") 

            if ts_utc:
                ts_local = ts_utc.astimezone(local_tz)
                formatted_ts = ts_local.strftime("%b %d, %I:%M %p")
            else:
                formatted_ts = ""

            messages.append({
                "user_message": data.get("user_message", ""),
                "ai_response": data.get("ai_response", ""),
                "timestamp": formatted_ts
            })
    except Exception as e:
        print(f"Error processing messages: {e}") 
        pass

    return render_template("index.html", username=username, history=messages)

@app.route("/chat", methods=["POST"])
def chat():
    if not session.get("authenticated"):
        return jsonify({"error": "Unauthorized"}), 401

    user_input = request.json.get("message", "")
    username = session.get("username", "unknown_user")

    try:
        user_profile = get_or_create_user_profile(username)

        # --- Constructing a more robust system instruction ---
        agent_name = "Alfred" 
        user_display_name = user_profile.get('user_display_name', username) 

        system_instruction_parts = [
            f"{user_profile.get('agent_persona', 'You are a helpful and friendly AI assistant.')}",
            f"Your name is {agent_name}.",
            f"{user_profile.get('agent_goal', 'Answer questions and engage in natural conversation.')}",
        ]
        
        if user_profile.get('special_instructions'):
            system_instruction_parts.append(user_profile['special_instructions'])

        system_instruction_parts.append(f"The user you are interacting with is named {user_display_name}.")

        system_instruction_text = " ".join(part for part in system_instruction_parts if part).strip()
        
        # 1. Retrieve the last 'N' messages from Firestore for conversational context
        history_ref = (
            db.collection("default")
            .document(username)
            .collection("messages")
            .order_by("timestamp", direction=firestore.Query.DESCENDING)
            .limit(10) # Keep at 10 to fetch 5 user+AI turns for context
        )
        current_conversation = []
        for doc in reversed(list(history_ref.stream())):
            data = doc.to_dict()
            if data.get("user_message"):
                current_conversation.append({"role": "user", "parts": [{"text": data["user_message"]}]})
            if data.get("ai_response"):
                current_conversation.append({"role": "model", "parts": [{"text": data["ai_response"]}]})

        # 2. Add the current user's message to the conversation context
        current_conversation.append({"role": "user", "parts": [{"text": user_input}]})

        # --- Pass system_instruction using config as per Google's documentation ---
        generation_config = types.GenerateContentConfig(
            system_instruction={"parts": [{"text": system_instruction_text}]}
        )

        # 3. Send the entire conversation and system instruction (via config) to Gemini
        response = client.models.generate_content(
            model="gemini-2.5-flash-lite",
            contents=current_conversation,
            config=generation_config
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
        print(f"Error during Gemini API call or Firestore save: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/clear-history", methods=["POST"])
def clear_history():
    if not session.get("authenticated"):
        return jsonify({"error": "Unauthorized"}), 401

    username = session.get("username")

    try:
        messages_ref = db.collection("default").document(username).collection("messages")
        docs = messages_ref.limit(50).stream()
        deleted_count = 0
        while True:
            batch = db.batch()
            count_in_batch = 0
            for doc in docs:
                batch.delete(doc.reference)
                count_in_batch += 1
            if count_in_batch == 0:
                break
            batch.commit()
            deleted_count += count_in_batch
            if count_in_batch < 50:
                break
            docs = messages_ref.limit(50).stream()

        return jsonify({"success": True, "deleted_count": deleted_count})
    except Exception as e:
        print(f"Error clearing history: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/logout")
def logout():
    session.pop("authenticated", None)
    session.pop("username", None)
    return redirect(url_for("login"))

# --- New Route for Agent Settings ---
@app.route("/settings", methods=["GET", "POST"])
def agent_settings():
    if not session.get("authenticated"):
        return redirect(url_for("login"))

    username = session.get("username")
    user_profile = get_or_create_user_profile(username) # Get current profile

    if request.method == "POST":
        # Update profile based on form submission
        updated_persona = request.form.get("agent_persona", "").strip()
        updated_goal = request.form.get("agent_goal", "").strip()
        updated_instructions = request.form.get("special_instructions", "").strip()
        
        # You can add validation here if needed
        
        user_profile_ref = db.collection("default").document(username).collection("user_data").document("profile")
        try:
            user_profile_ref.update({
                "agent_persona": updated_persona,
                "agent_goal": updated_goal,
                "special_instructions": updated_instructions
            })
            return render_template("settings.html", user_profile=user_profile, success_message="Settings saved!", username=username)
        except Exception as e:
            print(f"Error updating user profile: {e}")
            return render_template("settings.html", user_profile=user_profile, error_message="Failed to save settings.", username=username)
    
    # For GET request, render the settings page with current data
    return render_template("settings.html", user_profile=user_profile, username=username)

if __name__ == "__main__":
    app.run(debug=True)
