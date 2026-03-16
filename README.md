# Alfred

Alfred is a personal AI chatbot web application built with Python and Flask. It uses Google Gemini as its AI backend and is designed to be deployed on Google Cloud Run.

## What it does

- Provides a web-based chat interface where authenticated users can have conversations with an AI assistant
- Stores chat history in Firestore so conversations persist across sessions
- Supports voice chat via Google Cloud Speech-to-Text and Text-to-Speech
- Lets each user customize the AI's persona, goal, and special instructions through a settings page
- Includes an admin panel for creating and managing users

## Tech stack

- Python, Flask, Gunicorn
- Google Gemini (google-genai) for AI responses
- Google Cloud Firestore for chat history and user data
- Google Cloud Speech-to-Text and Text-to-Speech for voice chat
- bcrypt for password hashing
- Docker for containerisation, deployed on Google Cloud Run

## Project structure

The repository contains versioned snapshots of the application as it was developed:

- `v1` - Initial MVP: basic chat interface with Gemini
- `v2` - Added Firestore for chat history, clear history, and last 10 messages
- `v2.1` through `v5.1` - Iterative improvements including authentication, voice chat, per-user settings, and admin tooling

The `Dockerfile` and `DockerSteps.txt` at the root are for building and deploying the application.

## Deployment

See `DockerSteps.txt` for instructions on building the Docker image and deploying to Google Cloud Run.

Key environment variables required:

- `GEMINI_API_KEY` - Google Gemini API key
- `FLASK_SECRET_KEY` - Secret key for Flask sessions
- `USER_<USERNAME>_PASSWORD` (v1-v4) or Firestore user records (v5+) for authentication
- Google Application Default Credentials for Firestore and Cloud speech services