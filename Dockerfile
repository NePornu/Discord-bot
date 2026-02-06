FROM python:3.9-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements
# We construct a requirements list based on analysis since requirements.txt is incomplete
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir \
    fastapi \
    uvicorn \
    jinja2 \
    python-multipart \
    pydantic \
    httpx \
    requests \
    itsdangerous

COPY . .

# Default command (can be overridden in docker-compose)
CMD ["python", "bot/main.py"]
