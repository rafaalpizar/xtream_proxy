# Dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Expose internal port for Gunicorn
EXPOSE 9090

# Run Flask app with Gunicorn
CMD ["gunicorn", "-b", "0.0.0.0:9090", "xtream_proxy:app"]
