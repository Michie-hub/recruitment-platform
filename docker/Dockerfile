FROM python:3.13-slim

# Prevents Python from writing .pyc files and buffers stdout — standard for containerized Python
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /code

# Install system deps needed for psycopg2 (Postgres driver) to compile
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first (separate layer) so Docker caches installed deps
# and doesn't reinstall them every time app code changes
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY ./app ./app
COPY alembic.ini .
COPY ./alembic ./alembic

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
