# LearnHub — container image.
#
# Works on any host that runs a container (Render, Railway, Fly, Cloud Run, a
# VPS). The app binds to $PORT because every one of those platforms assigns it
# rather than letting the process choose.

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Dependencies first, so a code change does not reinstall the world.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# Uploaded videos and notes. On a host with no persistent disk this is wiped on
# every deploy -- see the deployment notes in the README before relying on it.
RUN mkdir -p /app/uploads/videos /app/uploads/notes

EXPOSE 8000

# Shell form on purpose: $PORT has to be expanded at runtime, not at build.
CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
