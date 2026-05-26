from __future__ import annotations

import json
from pathlib import Path

import joblib
import pandas as pd
from fastapi.testclient import TestClient
from sklearn.ensemble import RandomForestRegressor

from wine_quality_mlops.app import create_app
from wine_quality_mlops.database import SqlAlchemyPredictionStore
from wine_quality_mlops.predict import ModelService
from wine_quality_mlops.schema import ALL_COLUMNS, FEATURE_COLUMNS, TARGET_COLUMN


def test_api_predict_endpoint_returns_prediction(tmp_path: Path) -> None:
    model_path = tmp_path / "model.joblib"
    metadata_path = tmp_path / "model_metadata.json"
    metrics_path = tmp_path / "metrics.json"
    database_path = tmp_path / "predictions.db"

    frame = pd.DataFrame(
        [
            [7.4, 0.70, 0.00, 1.9, 0.076, 11, 34, 0.9978, 3.51, 0.56, 9.4, 5],
            [7.8, 0.88, 0.00, 2.6, 0.098, 25, 67, 0.9968, 3.20, 0.68, 9.8, 5],
            [11.2, 0.28, 0.56, 1.9, 0.075, 17, 60, 0.9980, 3.16, 0.58, 9.8, 6],
            [7.9, 0.60, 0.06, 1.6, 0.069, 15, 59, 0.9964, 3.30, 0.46, 9.4, 5],
            [7.3, 0.65, 0.02, 2.1, 0.070, 10, 37, 0.9966, 3.39, 0.47, 10.0, 7],
            [7.5, 0.50, 0.36, 6.1, 0.071, 17, 102, 0.9980, 3.35, 0.80, 10.5, 7],
        ],
        columns=ALL_COLUMNS,
    )

    model = RandomForestRegressor(n_estimators=10, random_state=42)
    model.fit(frame.loc[:, FEATURE_COLUMNS], frame[TARGET_COLUMN])
    joblib.dump(model, model_path)

    metadata_path.write_text(
        json.dumps(
            {
                "feature_columns": list(FEATURE_COLUMNS),
                "target_column": TARGET_COLUMN,
                "model_type": "random_forest_regressor",
                "version": "0.1.0",
            }
        ),
        encoding="utf-8",
    )
    metrics_path.write_text(json.dumps({"mae": 0.1, "rmse": 0.2, "r2": 0.7}), encoding="utf-8")

    service = ModelService.from_paths(model_path, metadata_path, metrics_path)
    prediction_store = SqlAlchemyPredictionStore(f"sqlite:///{database_path.as_posix()}")
    prediction_store.ensure_schema()
    prediction_store.replace_samples("train", frame.to_dict(orient="records"))
    prediction_store.replace_samples("test", frame.to_dict(orient="records"))

    with TestClient(create_app(service, prediction_store=prediction_store)) as client:
        response = client.post(
            "/predict",
            json={
                "fixed_acidity": 7.4,
                "volatile_acidity": 0.7,
                "citric_acid": 0.0,
                "residual_sugar": 1.9,
                "chlorides": 0.076,
                "free_sulfur_dioxide": 11.0,
                "total_sulfur_dioxide": 34.0,
                "density": 0.9978,
                "ph": 3.51,
                "sulphates": 0.56,
                "alcohol": 9.4,
            },
        )
        latest_prediction_response = client.get("/predictions/latest")
        dataset_summary_response = client.get("/training-data/summary")
        health_response = client.get("/health")

        assert health_response.status_code == 200
        assert health_response.json()["database_status"] == {"enabled": True, "connected": True}
        assert response.status_code == 200
        payload = response.json()
        assert "predicted_quality" in payload
        assert payload["model_version"] == "0.1.0"
        assert payload["stored_in_db"] is True
        assert isinstance(payload["prediction_id"], int)

        assert latest_prediction_response.status_code == 200
        latest_payload = latest_prediction_response.json()
        assert latest_payload["prediction_id"] == payload["prediction_id"]
        assert latest_payload["model_version"] == "0.1.0"
        assert latest_payload["request_payload"]["alcohol"] == 9.4

        assert dataset_summary_response.status_code == 200
        assert dataset_summary_response.json()["splits"] == {"test": 6, "train": 6}
