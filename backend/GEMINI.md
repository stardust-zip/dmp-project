# DMP Backend Architecture & Development Guide

Welcome to the DMP (Smart City AI Platform) backend. This project is structured to follow SOLID principles, ensuring it's scalable, performant, and easy to maintain.

## Project Structure

```text
backend/src/
├── api/            # API Layer (FastAPI Routers)
│   └── v1/         # API Version 1
│       ├── endpoints/ # Specific API logic
│       └── router.py  # Main v1 router
├── core/           # Core Configuration & Utilities
│   ├── config.py    # Pydantic Settings (env vars)
│   ├── exceptions.py# Custom Exceptions & Global Handler
│   └── logging.py   # Loguru structured logging
├── middleware/     # Custom FastAPI Middlewares
├── models.py       # SQLAlchemy Database Models
├── schemas.py      # Pydantic Schemas (Request/Response)
├── database.py     # DB Connection & Session Management
└── main.py         # App Entry Point
```

## How to add a new API

If you are an AI Engineer adding a new Forecasting or Anomaly Detection API:

1.  **Define the Schema**: Add your Request/Response Pydantic models in `src/schemas.py`.
2.  **Create the Endpoint**:
    - Create a new file in `src/api/v1/endpoints/your_module.py`.
    - Use `APIRouter()` and define your routes.
3.  **Register the Router**:
    - Import your router in `src/api/v1/router.py` and include it in `api_router`.
4.  **Implement Logic**:
    - For complex logic, create a service class in a new `src/services/` directory (optional but recommended for SOLID).

## Best Practices

### 1. Configuration

Always use `src.core.config.settings` for environment variables. Do NOT use `os.getenv` directly in your code.

### 2. Logging

Use `loguru` for logging. It's already configured to output logs.

```python
from loguru import logger
logger.info("Processing forecasting job...")
```

### 3. Error Handling

Raise `DMPException` (or its subclasses) for business logic errors. They will be automatically caught and returned as a standard JSON response.

```python
from src.core.exceptions import NotFoundException
if not model_id:
    raise NotFoundException("Model not found")
```

### 4. Database

Use the `get_db` dependency to get a database session.

```python
@router.get("/")
def get_something(db: Session = Depends(get_db)):
    ...
```

## Running Tests

Run tests from the `backend/` directory:

```bash
PYTHONPATH=. pytest tests/
```
