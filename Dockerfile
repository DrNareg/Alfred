# Stage 1: Build dependencies
FROM python:3.10-slim-buster AS builder

WORKDIR /app

COPY requirements.txt .
RUN pip wheel --no-cache-dir --wheel-dir=/wheels -r requirements.txt

# Stage 2: Create final image
FROM python:3.10-slim-buster

WORKDIR /app

# Copy built wheels from builder stage
COPY --from=builder /wheels /wheels
COPY --from=builder /app/requirements.txt .
RUN pip install --no-cache-dir --find-links=/wheels -r requirements.txt

# Copy your application code
COPY . .

# Ensure app is not running in debug mode
ENV FLASK_ENV=production

# Set the port Cloud Run expects
ENV PORT=8080
EXPOSE 8080

# Create a non-root user for security
RUN adduser --system --group appuser
USER appuser

# Command to run the application using Gunicorn
# 'app:app' means look for an 'app' Flask instance in 'app.py'
CMD ["gunicorn", "-b", "0.0.0.0:8080", "app:app"]