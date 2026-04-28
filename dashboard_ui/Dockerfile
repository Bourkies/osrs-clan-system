FROM python:3.14-slim

WORKDIR /app

# Copy requirements from the build context (root) and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application code
COPY dashboard_ui/ ./dashboard_ui/

EXPOSE 8501

CMD ["streamlit", "run", "dashboard_ui/Home.py", "--server.port=8501", "--server.address=0.0.0.0"]