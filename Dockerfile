FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn

COPY . .

RUN mkdir -p uploads inventory

EXPOSE 8080

# Hosting platforms such as Render provide the port via $PORT
CMD gunicorn --bind "0.0.0.0:${PORT:-8080}" --workers 1 --threads 8 --timeout 120 app:app
