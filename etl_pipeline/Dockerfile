FROM python:3.14-slim

# Install cron
RUN apt-get update && apt-get install -y cron && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements from the build context (root) and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application code
COPY etl_pipeline/ ./etl_pipeline/

# Setup cron job to run every 15 minutes, offset by 1 minute (e.g., 1:01, 1:16, 1:31)
RUN echo "1,16,31,46 * * * * root /usr/local/bin/python /app/etl_pipeline/src/run_etl.py >> /var/log/cron.log 2>&1" > /etc/cron.d/etl-cron
RUN chmod 0644 /etc/cron.d/etl-cron
RUN touch /var/log/cron.log

# Dump environment variables for cron and start the daemon
CMD printenv > /etc/environment && cron && tail -f /var/log/cron.log