# Dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .

# Configure pyhon
RUN pip install --no-cache-dir -r requirements.txt

# Configure TLS
RUN openssl req -x509 -nodes -days 3650 -newkey rsa:2048 -keyout privkey.pem -out cert.pem \
	-subj "/C=US/ST=Oregon/L=Bend/O=xap/OU=ipv/CN=ipv/emailAddress=ipv@test.net";

# Install main program
COPY xtream_proxy.py .

# mount xtream_proxy.conf -v xtream_proxy.conf:/app/xtream_proxy.conf

# Expose internal port for Gunicorn
EXPOSE 9090

# Run Flask app with Gunicorn
CMD ["gunicorn", \
    "--keyfile", "privkey.pem", \
    "--certfile", "cert.pem", \
    "-b", "0.0.0.0:9090", \
    "xtream_proxy:app"]
