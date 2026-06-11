from src.schemas import ModelTrainingRequest


def train_anomaly_detection_model(request: ModelTrainingRequest) -> dict[str, object]:
    """
    Placeholder for the anomaly detection training pipeline.
    """
    return {
        "implemented": False,
        "model_task": "anomaly_detection",
        "message": "Anomaly detection training pipeline is not implemented yet.",
    }
