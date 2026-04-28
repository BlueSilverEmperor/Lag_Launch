# syntax=docker/dockerfile:1
FROM python:3.12-slim

# Install system dependencies for OpenCV and video processing
RUN apt-get update && \
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    ffmpeg \
    ca-certificates \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements first for better caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application
COPY . .

# Expose the Flask port
EXPOSE 9000

# Set environment variables
ENV FLASK_APP=server_reloaded.py
ENV MONGO_URI=mongodb://mongodb:27017/
ENV QDRANT_HOST=qdrant

# Run the server
CMD ["python", "server_reloaded.py"]
