import os
from celery import Celery

redis_url = os.getenv("REDIS_URL", "redis://redis:6379/0")

celery_app = Celery(
    "dmp_tasks",
    broker=redis_url,
    backend=redis_url
)

@celery_app.task
def test_ml_pipeline():
    """Dummy task to ensure the worker is consuming from the queue"""
    return "Pipeline execution started"
