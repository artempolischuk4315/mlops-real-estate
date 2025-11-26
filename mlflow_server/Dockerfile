FROM python:3.11-slim

# Встановлюємо системні залежності для збірки psycopg2 (Postgres драйвер)
RUN apt-get update && apt-get install -y libpq-dev gcc && rm -rf /var/lib/apt/lists/*

# Встановлюємо MLflow та залежності для AWS/Postgres
RUN pip install mlflow==2.13.2 boto3 psycopg2-binary

# Порт за замовчуванням
EXPOSE 5000