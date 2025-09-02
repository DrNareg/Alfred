import os
from flask import Flask, request, render_template, jsonify, session, redirect, url_for
from dotenv import load_dotenv
from google import genai

# Load environment variables from .env file
load_dotenv()

# Initialize Flask app
app = Flask(__name__)
# IMPORTANT: Replace "replace-this-in-prod" in your .env file
# with a strong, random string generated for security.
# The default here is a fallback for development only.
app.secret_key = os.getenv("FLASK_SECRET_KEY", "replace-this-in-prod")

# Define the known usernames. Passwords will be fetched from .env
# This list helps in iterating and fetching corresponding passwords from environment variables.
KNOWN_USERNAMES = ["replace with usernames"]

# Dynamically load user credentials from environment variables.
# WARNING: This approach stores and loads plain text passwords, which is HIGHLY INSECURE.
# This is used here based on your explicit request for a very small, fixed user base
# and should NOT be used in production or for sensitive data.
USERS = {}
for username in KNOWN_USERNAMES:
    env_var_name = f"USER_{username.upper()}_PASSWORD"
    password = os.getenv(env_var_name)
    if password:
        USERS[username] = password
    else:
        print(f"WARNING: Password for user '{username}' not found in environment variable '{env_var_name}'. "
              f"Please ensure it's set in your .env file or environment.")

# Set up Google Gemini client using API key from environment
# The API key is loaded from the GEMINI_API_KEY environment variable.
client = genai.Client()

# Route for user login
@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")

        # Authenticate user by comparing provided credentials with loaded USERS dictionary.
        if username in USERS and USERS[username] == password:
            session["authenticated"] = True
            session["username"] = username  # Store the logged-in username in the session
            return redirect(url_for("chat_page")) # Redirect to the chat page on successful login
        else:
            # Render login page with an error message for invalid credentials
            return render_template("login.html", error="Invalid username or password.")
    # For GET requests, simply render the login page
    return render_template("login.html")

# Route for the chat interface (requires authentication)
@app.route("/chat")
def chat_page():
    # Check if the user is authenticated. If not, redirect to the login page.
    if not session.get("authenticated"):
        return redirect(url_for("login"))
    
    # Render the chat page, passing the logged-in username to the template
    return render_template("index.html", username=session.get("username"))

# POST route for handling chatbot messages
@app.route("/chat", methods=["POST"])
def chat():
    # Ensure the user is authenticated before processing chat messages
    if not session.get("authenticated"):
        return jsonify({"error": "Unauthorized"}), 401

    user_input = request.json.get("message", "")
    # Get the current username from the session for logging or potential future features
    current_username = session.get("username", "unknown_user") 

    print(f"Chat message from {current_username}: {user_input}")

    try:
        # Use the Gemini API to generate a response
        response = client.models.generate_content(
            model="gemini-2.5-flash-lite", # Using a lightweight Gemini model
            contents=user_input
        )
        # Return the AI's response as JSON
        return jsonify({"response": response.text})
    except Exception as e:
        # Handle any errors during API interaction and return an error message
        return jsonify({"error": str(e)}), 500

# Route for logging out the user
@app.route("/logout")
def logout():
    # Clear session variables related to authentication
    session.pop("authenticated", None)
    session.pop("username", None)
    # Redirect to the login page after logging out
    return redirect(url_for("login"))

# Main entry point for running the Flask application
if __name__ == "__main__":
    # Run the app in debug mode.
    # In production, debug=False and use a production-ready WSGI server (e.g., Gunicorn, uWSGI).
    app.run(debug=True)
