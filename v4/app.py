import os
import logging # Added
from flask import Flask, request, render_template, jsonify, session, redirect, url_for, flash
from dotenv import load_dotenv
from google import genai
from google.genai import types
from google.cloud import firestore
from datetime import datetime
import pytz
import bcrypt

# Set up basic logging for now, can be enhanced later with JSONFormatter
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
app_logger = logging.getLogger(__name__)

# Load environment variables (for local development)
load_dotenv()

# --- Flask App Initialization ---
app = Flask(__name__)
# IMPORTANT: Use a strong, random key in production, set via environment variable
app.secret_key = os.getenv("FLASK_SECRET_KEY")
if not app.secret_key:
    app_logger.error("FLASK_SECRET_KEY not set. This is a security risk in production!")

# Disable debug mode for production
app.config['DEBUG'] = False 
if os.getenv('FLASK_ENV') == 'development':
    app.config['DEBUG'] = True
    app_logger.info("Running in development mode.")

# --- Firebase Admin SDK Initialization ---
import firebase_admin
from firebase_admin import credentials

try:
    # Prioritize ApplicationDefault credentials for Cloud Run
    # Cloud Run's default service account, if properly configured, will provide these.
    cred = credentials.ApplicationDefault()
    firebase_admin.initialize_app(cred)
    app_logger.info("Firebase Admin SDK initialized with Application Default Credentials.")
except Exception as e:
    app_logger.warning(f"Failed to initialize Firebase with Application Default Credentials: {e}")
    # Fallback to FIREBASE_CRED_PATH for local development or specific deployments
    cred_path = os.environ.get('FIREBASE_CRED_PATH')
    if cred_path:
        try:
            cred = credentials.Certificate(cred_path)
            firebase_admin.initialize_app(cred)
            app_logger.info(f"Firebase Admin SDK initialized with credentials from {cred_path}.")
        except Exception as e_path:
            app_logger.error(f"Error initializing Firebase Admin SDK from FIREBASE_CRED_PATH ({cred_path}): {e_path}")
            # If Firebase fails to initialize, Firestore operations will fail
            # Consider exiting or raising an error here in production.
    else:
        app_logger.critical("No Firebase credentials found. Firestore will not work!")
        # In production, you might want to exit the application here
        # import sys; sys.exit(1)


# --- Initialize Gemini and Firestore Clients ---
try:
    client = genai.Client()
    app_logger.info("Gemini client initialized successfully.")
except Exception as e:
    app_logger.error(f"Error initializing Gemini client: {e}")
    client = None # Set to None so later calls can check if it's available

try:
    db = firestore.Client()
    app_logger.info("Firestore client initialized successfully.")
except Exception as e:
    app_logger.error(f"Error initializing Firestore client: {e}")
    # In production, if DB connection fails on startup, it's critical.
    # import sys; sys.exit(1)


# Set Timezone
LOCAL_TIMEZONE = 'America/Los_Angeles' 

# --- Admin-controlled allowed usernames (for pre-registration or check) ---
ALLOWED_USERNAMES = ["change this"]

# --- Helper function to get/create/manage user profile including credentials ---
# This now specifically interacts with the 'users' collection
def get_user_data(username):
    """Fetches user data including hashed_password from Firestore's 'users' collection."""
    user_doc_ref = db.collection("users").document(username)
    user_doc = user_doc_ref.get()
    if user_doc.exists:
        return user_doc.to_dict()
    return None

def create_or_update_user(username, plain_password, user_profile_data=None):
    """
    Creates or updates a user in Firestore's 'users' collection with a hashed password.
    Should be called by an admin or a restricted script.
    """
    if username not in ALLOWED_USERNAMES:
        app_logger.warning(f"Attempted to create unauthorized user: {username}")
        return False, "Unauthorized username."

    hashed_password = bcrypt.hashpw(plain_password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    
    user_doc_ref = db.collection("users").document(username)
    
    # Merge default profile with provided or existing data
    existing_profile = get_user_data(username)
    profile_to_set = existing_profile.copy() if existing_profile else {}
    
    default_profile_parts = {
        "agent_persona": "You are a helpful and friendly AI assistant.",
        "agent_goal": "Answer questions and engage in natural conversation.",
        "special_instructions": "",
        "user_display_name": username,
    }
    
    for key, value in default_profile_parts.items():
        if key not in profile_to_set:
            profile_to_set[key] = value

    if user_profile_data:
        profile_to_set.update(user_profile_data)

    profile_to_set["hashed_password"] = hashed_password
    profile_to_set["last_updated_at"] = firestore.SERVER_TIMESTAMP
    if "created_at" not in profile_to_set:
        profile_to_set["created_at"] = firestore.SERVER_TIMESTAMP

    try:
        user_doc_ref.set(profile_to_set) # Use set to create or overwrite
        app_logger.info(f"User '{username}' created/updated successfully in Firestore.")
        return True, "User created/updated successfully."
    except Exception as e:
        app_logger.error(f"Error creating/updating user {username} in Firestore: {e}")
        return False, f"Firestore error: {e}"

# --- Helper function to get user profile (excluding password) ---
# This now specifically interacts with the 'users' collection
def get_user_profile_data(username):
    """Fetches user profile data from Firestore's 'users' collection, excluding sensitive fields."""
    user_doc_ref = db.collection("users").document(username)
    user_doc = user_doc_ref.get()
    if user_doc.exists:
        profile_data = user_doc.to_dict()
        profile_data.pop("hashed_password", None) # Remove hashed password
        profile_data.pop("last_updated_at", None) # Remove internal field
        profile_data.pop("created_at", None) # Remove internal field
        return profile_data
    else:
        app_logger.warning(f"Profile for authenticated user {username} not found in 'users' collection. Creating default.")
        default_profile = {
            "agent_persona": "You are a helpful and friendly AI assistant.",
            "agent_goal": "Answer questions and engage in natural conversation.",
            "special_instructions": "",
            "user_display_name": username,
            "created_at": firestore.SERVER_TIMESTAMP
        }
        db.collection("users").document(username).set(default_profile, merge=True)
        return default_profile


@app.route("/", methods=["GET", "POST"])
def login():
    if session.get("authenticated"):
        return redirect(url_for("chat_page"))

    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")

        user_data = get_user_data(username)

        if user_data and "hashed_password" in user_data:
            if bcrypt.checkpw(password.encode('utf-8'), user_data["hashed_password"].encode('utf-8')):
                session["authenticated"] = True
                session["username"] = username
                app_logger.info(f"User '{username}' logged in successfully.")
                flash("Logged in successfully!", "success")
                return redirect(url_for("chat_page"))
            else:
                app_logger.warning(f"Failed login attempt for user '{username}': Invalid password.")
                flash("Invalid username or password.", "danger")
        else:
            app_logger.warning(f"Failed login attempt: User '{username}' not found or no password set.")
            flash("Invalid username or password.", "danger")

    return render_template("login.html")

@app.route("/admin/create-user", methods=["GET", "POST"])
def admin_create_user():
    # In a real app, this route would be heavily secured
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        if username and password:
            success, message = create_or_update_user(username, password)
            if success:
                flash(f"User '{username}' created/updated: {message}", "success")
            else:
                flash(f"Error creating/updating user '{username}': {message}", "danger")
        else:
            flash("Username and password are required.", "danger")
    
    users_ref = db.collection("users")
    user_list = []
    try:
        for doc in users_ref.stream():
            data = doc.to_dict()
            data.pop("hashed_password", None)
            user_list.append(data)
    except Exception as e:
        app_logger.error(f"Error fetching user list for admin page: {e}")
        flash(f"Error fetching user list: {e}", "danger")

    return render_template("admin_create_user.html", allowed_usernames=ALLOWED_USERNAMES, users=user_list)


@app.route("/chat")
def chat_page():
    if not session.get("authenticated"):
        return redirect(url_for("login"))

    username = session.get("username")

    messages_ref = (
        db.collection("default")
        .document(username)
        .collection("messages")
        .order_by("timestamp", direction=firestore.Query.DESCENDING)
        .limit(10)
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
        app_logger.error(f"Error processing messages for user '{username}': {e}") 
        flash("Error loading chat history.", "danger")

    return render_template("index.html", username=username, history=messages)

@app.route("/chat", methods=["POST"])
def chat():
    if not session.get("authenticated"):
        return jsonify({"error": "Unauthorized"}), 401

    user_input = request.json.get("message", "")
    username = session.get("username", "unknown_user")

    if not client: # Check if Gemini client failed to initialize
        app_logger.error("Gemini client is not initialized.")
        return jsonify({"error": "AI service not available. Please check server logs."}), 503

    try:
        user_profile = get_user_profile_data(username) 
        
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
        
        history_ref = (
            db.collection("default")
            .document(username)
            .collection("messages")
            .order_by("timestamp", direction=firestore.Query.DESCENDING)
            .limit(10)
        )
        current_conversation = []
        for doc in reversed(list(history_ref.stream())):
            data = doc.to_dict()
            if data.get("user_message"):
                current_conversation.append({"role": "user", "parts": [{"text": data["user_message"]}]})
            if data.get("ai_response"):
                current_conversation.append({"role": "model", "parts": [{"text": data["ai_response"]}]})

        current_conversation.append({"role": "user", "parts": [{"text": user_input}]})

        generation_config = types.GenerateContentConfig(
            system_instruction={"parts": [{"text": system_instruction_text}]}
        )

        response = client.models.generate_content(
            model="gemini-2.5-flash-lite",
            contents=current_conversation,
            config=generation_config
        )
        ai_response = response.text

        db.collection("default").document(username).collection("messages").add({
            "user": username,
            "user_message": user_input,
            "ai_response": ai_response,
            "timestamp": firestore.SERVER_TIMESTAMP
        })
        app_logger.info(f"Chat message processed and saved for user '{username}'.")

        return jsonify({"response": ai_response})
    except Exception as e:
        app_logger.error(f"Error during Gemini API call or Firestore save for user '{username}': {e}", exc_info=True) # exc_info=True logs traceback
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
        app_logger.info(f"Cleared {deleted_count} messages for user '{username}'.")
        return jsonify({"success": True, "deleted_count": deleted_count})
    except Exception as e:
        app_logger.error(f"Error clearing history for user '{username}': {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500

@app.route("/logout")
def logout():
    username = session.get("username")
    session.pop("authenticated", None)
    session.pop("username", None)
    app_logger.info(f"User '{username}' logged out.")
    flash("You have been logged out.", "info")
    return redirect(url_for("login"))

@app.route("/settings", methods=["GET", "POST"])
def agent_settings():
    if not session.get("authenticated"):
        return redirect(url_for("login"))

    username = session.get("username")
    user_profile = get_user_profile_data(username) 

    if request.method == "POST":
        updated_persona = request.form.get("agent_persona", "").strip()
        updated_goal = request.form.get("agent_goal", "").strip()
        updated_instructions = request.form.get("special_instructions", "").strip()
        updated_display_name = request.form.get("user_display_name", "").strip()

        user_doc_ref = db.collection("users").document(username)
        try:
            user_doc_ref.update({
                "agent_persona": updated_persona,
                "agent_goal": updated_goal,
                "special_instructions": updated_instructions,
                "user_display_name": updated_display_name
            })
            user_profile = get_user_profile_data(username) 
            app_logger.info(f"User '{username}' updated settings.")
            flash("Settings saved!", "success")
            return render_template("settings.html", user_profile=user_profile, username=username)
        except Exception as e:
            app_logger.error(f"Error updating user profile for '{username}': {e}", exc_info=True)
            flash(f"Failed to save settings: {e}", "danger")
            return render_template("settings.html", user_profile=user_profile, username=username)
    
    return render_template("settings.html", user_profile=user_profile, username=username)
