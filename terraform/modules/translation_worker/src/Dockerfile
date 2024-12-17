FROM python:3.9-slim
WORKDIR /app
# Install build dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    && rm -rf /var/lib/apt/lists/*
# Copy requirements first for better caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# Copy application code
COPY . .
# Set environment variables
ENV PORT=8080
ENV PYTHONUNBUFFERED=1
ENV GUNICORN_CMD_ARGS="--workers=1 --threads=8 --timeout=0 --bind=:$PORT --log-level=info"
# Use gunicorn for production
CMD exec gunicorn translation_worker:app
