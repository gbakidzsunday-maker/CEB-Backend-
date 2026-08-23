FROM python:3.12-slim

# Prevents Python from buffering stdout/stderr (so Render's logs show up live)
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# SQLite file lives here. Mount a Render persistent disk at /app/data
# if you want data to survive redeploys/restarts; otherwise it resets
# on every deploy (fine for a prototype/demo).
RUN mkdir -p /app/data

EXPOSE 8000

# Render sets $PORT; default to 8000 for local `docker run`.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
