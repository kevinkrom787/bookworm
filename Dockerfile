FROM python:3.11-slim

WORKDIR /app

# System deps (no build tools needed for this stack)
RUN apt-get update && apt-get install -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Image cache dir must exist inside the container (static file serving)
RUN mkdir -p app/static/img_cache

EXPOSE 8080

CMD ["gunicorn", "run:app", \
     "--workers", "1", \
     "--threads", "4", \
     "--worker-class", "gthread", \
     "--timeout", "120", \
     "--bind", "0.0.0.0:8080", \
     "--access-logfile", "-"]
