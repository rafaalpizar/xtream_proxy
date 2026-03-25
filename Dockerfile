# Dockerfile
FROM python:3.11-slim

# Prepare application limited user
RUN mkdir /app
RUN groupadd -r tvuser && useradd -r -s /bin/false -g tvuser tvuser
WORKDIR /app

# Install dependencies
COPY requirements.txt .

# Configure pyhon
RUN pip install --no-cache-dir -r requirements.txt

# Configure TLS
RUN openssl req -x509 -nodes -days 3650 -newkey rsa:2048 -keyout privkey.pem -out cert.pem \
	-subj "/C=US/ST=Oregon/L=Bend/O=xap/OU=ipv/CN=ipv/emailAddress=ipv@test.net";

# Install main program
COPY gunicorn.conf.py xtream_proxy.py ./

# Set limited user
RUN chown -R tvuser:tvuser /app
USER tvuser

# mount xtream_proxy.conf -v xtream_proxy.conf:/app/xtream_proxy.conf

# Expose internal port for Gunicorn
EXPOSE 9090

# Run Flask app with Gunicorn
CMD ["gunicorn", \
    "--config", "gunicorn.conf.py", \
    "xtream_proxy:app"]
