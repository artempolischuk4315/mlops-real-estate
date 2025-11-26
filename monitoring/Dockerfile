FROM python:3.11-slim

WORKDIR /var/task

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir awslambdaric

COPY requirements.txt .

RUN pip install \
    "numpy<2" \
    "pyarrow" \
    "pydantic==1.10.13" \
    "fastapi==0.99.1" \
    "typing_extensions==4.5.0" \
    --only-binary=:all: --no-cache-dir

RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .

ENTRYPOINT [ "/usr/local/bin/python", "-m", "awslambdaric" ]
CMD [ "main.lambda_handler" ]