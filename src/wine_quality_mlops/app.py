from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

from wine_quality_mlops.database import (
    PredictionStore,
    StoredPrediction,
    StoredPredictionEvent,
    build_prediction_store_from_env,
)
from wine_quality_mlops.messaging import PredictionEvent, PredictionPublisher, build_prediction_publisher_from_env
from wine_quality_mlops.predict import ModelService


DEFAULT_MODEL_PATH = Path("artifacts/model.joblib")
DEFAULT_METADATA_PATH = Path("artifacts/model_metadata.json")
DEFAULT_METRICS_PATH = Path("artifacts/metrics.json")


class PredictionRequest(BaseModel):
    fixed_acidity: float = Field(..., ge=0)
    volatile_acidity: float = Field(..., ge=0)
    citric_acid: float = Field(..., ge=0)
    residual_sugar: float = Field(..., ge=0)
    chlorides: float = Field(..., ge=0)
    free_sulfur_dioxide: float = Field(..., ge=0)
    total_sulfur_dioxide: float = Field(..., ge=0)
    density: float = Field(..., ge=0)
    ph: float = Field(..., ge=0)
    sulphates: float = Field(..., ge=0)
    alcohol: float = Field(..., ge=0)


class PredictionResponse(BaseModel):
    predicted_quality: float
    model_version: str
    prediction_id: int | None = None
    stored_in_db: bool
    published_to_kafka: bool


class StoredPredictionResponse(BaseModel):
    prediction_id: int
    predicted_quality: float
    model_version: str
    request_payload: dict[str, float]
    created_at: str


class StoredPredictionEventResponse(BaseModel):
    event_id: str
    prediction_id: int | None
    predicted_quality: float
    model_version: str
    request_payload: dict[str, float]
    published_at: str
    consumed_at: str


def _artifact_path(env_name: str, default_path: Path) -> Path:
    return Path(os.getenv(env_name, default_path.as_posix()))


def get_model_service(request: Request) -> ModelService:
    return request.app.state.model_service


def get_prediction_store(request: Request) -> PredictionStore:
    return request.app.state.prediction_store


def get_prediction_publisher(request: Request) -> PredictionPublisher:
    return request.app.state.prediction_publisher


def _serialize_prediction(record: StoredPrediction) -> StoredPredictionResponse:
    return StoredPredictionResponse(
        prediction_id=record.id,
        predicted_quality=record.predicted_quality,
        model_version=record.model_version,
        request_payload=record.request_payload,
        created_at=record.created_at,
    )


def _serialize_prediction_event(record: StoredPredictionEvent) -> StoredPredictionEventResponse:
    return StoredPredictionEventResponse(
        event_id=record.event_id,
        prediction_id=record.prediction_id,
        predicted_quality=record.predicted_quality,
        model_version=record.model_version,
        request_payload=record.request_payload,
        published_at=record.published_at,
        consumed_at=record.consumed_at,
    )


def create_app(
    service: ModelService | None = None,
    prediction_store: PredictionStore | None = None,
    prediction_publisher: PredictionPublisher | None = None,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.model_service = service or ModelService.from_paths(
            model_path=_artifact_path("MODEL_PATH", DEFAULT_MODEL_PATH),
            metadata_path=_artifact_path("METADATA_PATH", DEFAULT_METADATA_PATH),
            metrics_path=_artifact_path("METRICS_PATH", DEFAULT_METRICS_PATH),
        )
        app.state.prediction_store = prediction_store or build_prediction_store_from_env()
        app.state.prediction_publisher = prediction_publisher or build_prediction_publisher_from_env()
        app.state.prediction_store.ensure_schema()
        yield

    app = FastAPI(title="Wine Quality MLOps API", version="0.1.0", lifespan=lifespan)

    @app.get("/health")
    def healthcheck(
        prediction_store: PredictionStore = Depends(get_prediction_store),
        prediction_publisher: PredictionPublisher = Depends(get_prediction_publisher),
    ) -> dict[str, object]:
        return {
            "status": "ok",
            "database_status": prediction_store.healthcheck(),
            "kafka_status": prediction_publisher.healthcheck(),
        }

    @app.get("/model-info")
    def model_info(model_service: ModelService = Depends(get_model_service)) -> dict[str, object]:
        return {
            "model_type": model_service.metadata.get("model_type"),
            "feature_columns": list(model_service.feature_columns),
            "metrics": model_service.metrics,
        }

    @app.get("/training-data/summary")
    def training_data_summary(prediction_store: PredictionStore = Depends(get_prediction_store)) -> dict[str, object]:
        if not prediction_store.enabled:
            raise HTTPException(status_code=503, detail="Database persistence is not configured.")
        return {"splits": prediction_store.dataset_summary()}

    @app.get("/predictions/latest", response_model=StoredPredictionResponse)
    def latest_prediction(
        prediction_store: PredictionStore = Depends(get_prediction_store),
    ) -> StoredPredictionResponse:
        if not prediction_store.enabled:
            raise HTTPException(status_code=503, detail="Database persistence is not configured.")

        stored_prediction = prediction_store.get_latest_prediction()
        if stored_prediction is None:
            raise HTTPException(status_code=404, detail="No predictions stored yet.")

        return _serialize_prediction(stored_prediction)

    @app.get("/prediction-events/latest", response_model=StoredPredictionEventResponse)
    def latest_prediction_event(
        prediction_store: PredictionStore = Depends(get_prediction_store),
    ) -> StoredPredictionEventResponse:
        if not prediction_store.enabled:
            raise HTTPException(status_code=503, detail="Database persistence is not configured.")

        stored_event = prediction_store.get_latest_prediction_event()
        if stored_event is None:
            raise HTTPException(status_code=404, detail="No Kafka prediction events stored yet.")

        return _serialize_prediction_event(stored_event)

    @app.post("/predict", response_model=PredictionResponse)
    def predict(
        request: PredictionRequest,
        model_service: ModelService = Depends(get_model_service),
        prediction_store: PredictionStore = Depends(get_prediction_store),
        prediction_publisher: PredictionPublisher = Depends(get_prediction_publisher),
    ) -> PredictionResponse:
        request_payload = request.model_dump()
        prediction = model_service.predict(request_payload)
        model_version = str(model_service.metadata.get("version", "0.1.0"))
        stored_prediction = prediction_store.save_prediction(
            request_payload=request_payload,
            prediction=prediction,
            model_version=model_version,
        )
        prediction_event = PredictionEvent.create(
            prediction_id=stored_prediction.id if stored_prediction else None,
            predicted_quality=prediction,
            model_version=model_version,
            request_payload=request_payload,
        )
        prediction_publisher.publish_prediction(prediction_event)

        return PredictionResponse(
            predicted_quality=prediction,
            model_version=model_version,
            prediction_id=stored_prediction.id if stored_prediction else None,
            stored_in_db=stored_prediction is not None,
            published_to_kafka=prediction_publisher.enabled,
        )

    return app


app = create_app()
