FROM ghcr.io/mlflow/mlflow:v3.13.0
RUN for i in 1 2 3; do pip install --no-cache-dir psycopg2-binary && break || sleep $((i * 5)); done
