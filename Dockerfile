FROM python:3.11-slim

# Prevent python buffer streams from writing blockages
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONPATH=/app

WORKDIR /app

# Install system dependencies (build-essential needed for any C-extension compilations)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy pyproject.toml and files first for caching
COPY pyproject.toml /app/
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir psycopg2-binary boto3 && \
    pip install --no-cache-dir -e .

# Copy codebase
COPY src /app/src
COPY data /app/data
COPY worker.py /app/worker.py

CMD ["python", "worker.py"]
