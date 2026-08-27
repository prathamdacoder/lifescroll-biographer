FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend ./backend
COPY frontend ./frontend
ENV PORT=8080 DATA_DIR=/tmp/lifescroll
EXPOSE 8080
CMD gunicorn --bind 0.0.0.0:$PORT --workers 2 --threads 8 --timeout 600 backend.app:app
