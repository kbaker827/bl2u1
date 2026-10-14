FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Run as an unprivileged user; it only needs to write uploads/ and inventory/.
RUN useradd --create-home --uid 1000 app
COPY --chown=app:app . .
RUN mkdir -p uploads inventory && chown app:app uploads inventory
USER app

EXPOSE 8080

# Keep --workers 1: upload sessions and their download names are held in
# memory, so a second worker process would not see the first one's sessions.
# Scale with --threads instead.
# Hosting platforms such as Render provide the port via $PORT
# "exec" makes gunicorn PID 1 so it receives stop signals and shuts down cleanly.
CMD ["sh", "-c", "exec gunicorn --bind 0.0.0.0:${PORT:-8080} --workers 1 --threads 8 --timeout 120 app:app"]
