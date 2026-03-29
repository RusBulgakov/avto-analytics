FROM python:3.11-slim

WORKDIR /app

# Install system dependencies for psycopg2 and other tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements from the parent parsers directory
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy all parsers code
COPY . .

# Default command (will be overridden by environment variable or docker-compose)
CMD ["python", "-m", "kolesa.parser"]
