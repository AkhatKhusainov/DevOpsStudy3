from __future__ import annotations

from pathlib import Path

from wine_quality_mlops.consumer import consume_prediction_events
from wine_quality_mlops.database import SqlAlchemyPredictionStore
from wine_quality_mlops.messaging import PredictionEvent


class _FakeRecord:
    def __init__(self, value: dict[str, object]) -> None:
        self.value = value


class _FakeConsumer:
    def __init__(self, event: PredictionEvent) -> None:
        self._event = event
        self._served = False

    def poll(self, timeout_ms: int) -> dict[object, list[_FakeRecord]]:
        if self._served:
            return {}
        self._served = True
        return {("wine-quality.predictions", 0): [_FakeRecord(self._event.to_dict())]}

    def close(self) -> None:
        return None


def test_consumer_persists_prediction_event(tmp_path: Path) -> None:
    database_path = tmp_path / "predictions.db"
    prediction_store = SqlAlchemyPredictionStore(f"sqlite:///{database_path.as_posix()}")
    prediction_store.ensure_schema()

    event = PredictionEvent.create(
        prediction_id=1,
        predicted_quality=5.7,
        model_version="0.1.0",
        request_payload={
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

    processed_messages = consume_prediction_events(
        _FakeConsumer(event),
        prediction_store,
        max_messages=1,
        max_idle_polls=1,
    )

    stored_event = prediction_store.get_latest_prediction_event()

    assert processed_messages == 1
    assert stored_event is not None
    assert stored_event.event_id == event.event_id
    assert stored_event.prediction_id == 1
    assert stored_event.predicted_quality == 5.7
    assert stored_event.request_payload["alcohol"] == 9.4