from __future__ import annotations

from typing import Any, Protocol

from wine_quality_mlops.database import DatabaseConfigurationError, PredictionStore, build_prediction_store_from_env
from wine_quality_mlops.messaging import PredictionEvent, build_kafka_consumer_from_env


class ConsumerRecord(Protocol):
    value: dict[str, Any]


class SupportsPollingConsumer(Protocol):
    def poll(self, timeout_ms: int) -> dict[object, list[ConsumerRecord]]:
        ...

    def close(self) -> None:
        ...


def persist_prediction_event(prediction_store: PredictionStore, event: PredictionEvent) -> None:
    prediction_store.save_prediction_event(
        event_id=event.event_id,
        prediction_id=event.prediction_id,
        request_payload=event.request_payload,
        prediction=event.predicted_quality,
        model_version=event.model_version,
        published_at=event.published_at,
    )


def consume_prediction_events(
    consumer: SupportsPollingConsumer,
    prediction_store: PredictionStore,
    *,
    max_messages: int | None = None,
    poll_timeout_ms: int = 1000,
    max_idle_polls: int | None = None,
) -> int:
    processed_messages = 0
    idle_polls = 0

    while max_messages is None or processed_messages < max_messages:
        batches = consumer.poll(timeout_ms=poll_timeout_ms)
        if not batches:
            idle_polls += 1
            if max_idle_polls is not None and idle_polls >= max_idle_polls:
                return processed_messages
            continue

        idle_polls = 0
        for records in batches.values():
            for record in records:
                event = PredictionEvent.from_dict(record.value)
                persist_prediction_event(prediction_store, event)
                processed_messages += 1
                if max_messages is not None and processed_messages >= max_messages:
                    return processed_messages

    return processed_messages


def run_prediction_consumer() -> None:
    prediction_store = build_prediction_store_from_env(required=True)
    if not prediction_store.enabled:
        raise DatabaseConfigurationError("A database-backed prediction store is required for Kafka consumption.")

    prediction_store.ensure_schema()
    consumer = build_kafka_consumer_from_env(required=True)
    if consumer is None:
        raise RuntimeError("Kafka consumer could not be created from the current environment.")

    try:
        consume_prediction_events(consumer, prediction_store)
    finally:
        consumer.close()