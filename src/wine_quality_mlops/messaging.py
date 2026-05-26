from __future__ import annotations

import json
import os
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol

from kafka import KafkaConsumer, KafkaProducer

from wine_quality_mlops.vault import VaultConfigurationError, load_secret_from_vault_env


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class MessagingConfigurationError(RuntimeError):
    pass


@dataclass(frozen=True)
class KafkaSettings:
    bootstrap_servers: tuple[str, ...]
    topic: str
    consumer_group: str


@dataclass(frozen=True)
class PredictionEvent:
    event_id: str
    prediction_id: int | None
    predicted_quality: float
    model_version: str
    request_payload: dict[str, float]
    published_at: str = field(default_factory=_utcnow_iso)

    @classmethod
    def create(
        cls,
        *,
        prediction_id: int | None,
        predicted_quality: float,
        model_version: str,
        request_payload: dict[str, float],
    ) -> "PredictionEvent":
        return cls(
            event_id=str(uuid.uuid4()),
            prediction_id=prediction_id,
            predicted_quality=predicted_quality,
            model_version=model_version,
            request_payload=dict(request_payload),
        )

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "PredictionEvent":
        return cls(
            event_id=str(payload["event_id"]),
            prediction_id=int(payload["prediction_id"]) if payload.get("prediction_id") is not None else None,
            predicted_quality=float(payload["predicted_quality"]),
            model_version=str(payload["model_version"]),
            request_payload={
                str(key): float(value) for key, value in dict(payload["request_payload"]).items()
            },
            published_at=str(payload["published_at"]),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class PredictionPublisher(Protocol):
    @property
    def enabled(self) -> bool:
        ...

    def healthcheck(self) -> dict[str, bool]:
        ...

    def publish_prediction(self, event: PredictionEvent) -> None:
        ...


class NullPredictionPublisher:
    @property
    def enabled(self) -> bool:
        return False

    def healthcheck(self) -> dict[str, bool]:
        return {"enabled": False, "connected": False}

    def publish_prediction(self, event: PredictionEvent) -> None:
        return None


class KafkaPredictionPublisher:
    def __init__(self, settings: KafkaSettings) -> None:
        self._settings = settings
        self._producer = KafkaProducer(
            bootstrap_servers=list(settings.bootstrap_servers),
            key_serializer=lambda value: value.encode("utf-8"),
            value_serializer=lambda value: json.dumps(value).encode("utf-8"),
            acks="all",
        )

    @property
    def enabled(self) -> bool:
        return True

    def healthcheck(self) -> dict[str, bool]:
        return {"enabled": True, "connected": self._producer.bootstrap_connected()}

    def publish_prediction(self, event: PredictionEvent) -> None:
        result = self._producer.send(self._settings.topic, key=event.event_id, value=event.to_dict())
        result.get(timeout=10)
        self._producer.flush()


def _kafka_configuration_requested() -> bool:
    keys = (
        "KAFKA_BOOTSTRAP_SERVERS",
        "KAFKA_PREDICTIONS_TOPIC",
        "KAFKA_CONSUMER_GROUP",
        "KAFKA_SECRET_PATH",
    )
    return any(os.environ.get(key) for key in keys)


def load_kafka_settings_from_env(required: bool = False) -> KafkaSettings | None:
    env = os.environ
    vault_secret = load_secret_from_vault_env(required=False, secret_path_env="KAFKA_SECRET_PATH")
    if vault_secret:
        env = {**vault_secret, **env}

    required_keys = (
        "KAFKA_BOOTSTRAP_SERVERS",
        "KAFKA_PREDICTIONS_TOPIC",
        "KAFKA_CONSUMER_GROUP",
    )
    missing = [key for key in required_keys if not env.get(key)]

    if missing:
        if required:
            if vault_secret is None and os.environ.get("KAFKA_SECRET_PATH"):
                raise MessagingConfigurationError("Vault is configured, but Kafka settings could not be loaded.")
            raise MessagingConfigurationError("Missing Kafka configuration variables: " + ", ".join(sorted(missing)))
        return None

    bootstrap_servers = tuple(part.strip() for part in env["KAFKA_BOOTSTRAP_SERVERS"].split(",") if part.strip())
    if not bootstrap_servers:
        if required:
            raise MessagingConfigurationError("KAFKA_BOOTSTRAP_SERVERS is configured, but no brokers were provided.")
        return None

    return KafkaSettings(
        bootstrap_servers=bootstrap_servers,
        topic=env["KAFKA_PREDICTIONS_TOPIC"],
        consumer_group=env["KAFKA_CONSUMER_GROUP"],
    )


def build_prediction_publisher_from_env(required: bool = False) -> PredictionPublisher:
    strict_mode = required or _kafka_configuration_requested()

    try:
        settings = load_kafka_settings_from_env(required=strict_mode)
    except VaultConfigurationError as error:
        raise MessagingConfigurationError(str(error)) from error

    if settings is None:
        return NullPredictionPublisher()
    return KafkaPredictionPublisher(settings)


def build_kafka_consumer_from_env(required: bool = False) -> KafkaConsumer | None:
    strict_mode = required or _kafka_configuration_requested()

    try:
        settings = load_kafka_settings_from_env(required=strict_mode)
    except VaultConfigurationError as error:
        raise MessagingConfigurationError(str(error)) from error

    if settings is None:
        return None

    return KafkaConsumer(
        settings.topic,
        bootstrap_servers=list(settings.bootstrap_servers),
        group_id=settings.consumer_group,
        auto_offset_reset="earliest",
        enable_auto_commit=True,
        value_deserializer=lambda value: json.loads(value.decode("utf-8")),
    )