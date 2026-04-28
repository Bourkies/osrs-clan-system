FROM python:3.14-slim

# Install cron
RUN apt-get update && apt-get install -y cron && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements from the build context (root) and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application code
COPY backend_auditor/ ./backend_auditor/

# Setup cron jobs for 4x daily runs (AEST times mapped to UTC)
# Silent runs at 1 AM (15:00 UTC), 6 AM (20:00 UTC), and 7 PM (09:00 UTC)
RUN echo "5 9,15,20 * * * root /usr/local/bin/python /app/backend_auditor/run_auditor.py --no-webhook >> /var/log/cron.log 2>&1" > /etc/cron.d/auditor-cron
# Webhook report run at 2 PM AEST (04:00 UTC)
RUN echo "5 4 * * * root /usr/local/bin/python /app/backend_auditor/run_auditor.py >> /var/log/cron.log 2>&1" >> /etc/cron.d/auditor-cron
RUN chmod 0644 /etc/cron.d/auditor-cron
RUN touch /var/log/cron.log

# Dump environment variables for cron and start the daemon
CMD printenv > /etc/environment && cron && tail -f /var/log/cron.log