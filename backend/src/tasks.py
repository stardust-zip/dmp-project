from celery import Celery
from src.core.config import settings

redis_url = settings.REDIS_URL

celery_app = Celery("dmp_tasks", broker=redis_url, backend=redis_url)


@celery_app.task
def test_ml_pipeline():
    """Dummy task to ensure the worker is consuming from the queue"""
    return "Pipeline execution started"
