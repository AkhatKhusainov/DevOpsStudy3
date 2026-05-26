from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol

from sqlalchemy import DateTime, Float, Integer, JSON, String, create_engine, delete, func, select, text
from sqlalchemy.engine import URL
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from wine_quality_mlops.vault import VaultConfigurationError, load_secret_from_vault_env


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class PredictionResultRecord(Base):
    __tablename__ = "prediction_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    model_version: Mapped[str] = mapped_column(String(32), nullable=False)
    predicted_quality: Mapped[float] = mapped_column(Float, nullable=False)
    request_payload: Mapped[dict[str, float]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)


class PredictionEventRecord(Base):
    __tablename__ = "prediction_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    prediction_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    model_version: Mapped[str] = mapped_column(String(32), nullable=False)
    predicted_quality: Mapped[float] = mapped_column(Float, nullable=False)
    request_payload: Mapped[dict[str, float]] = mapped_column(JSON, nullable=False)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)


class WineSampleRecord(Base):
    __tablename__ = "wine_samples"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    split_name: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    fixed_acidity: Mapped[float] = mapped_column(Float, nullable=False)
    volatile_acidity: Mapped[float] = mapped_column(Float, nullable=False)
    citric_acid: Mapped[float] = mapped_column(Float, nullable=False)
    residual_sugar: Mapped[float] = mapped_column(Float, nullable=False)
    chlorides: Mapped[float] = mapped_column(Float, nullable=False)
    free_sulfur_dioxide: Mapped[float] = mapped_column(Float, nullable=False)
    total_sulfur_dioxide: Mapped[float] = mapped_column(Float, nullable=False)
    density: Mapped[float] = mapped_column(Float, nullable=False)
    ph: Mapped[float] = mapped_column(Float, nullable=False)
    sulphates: Mapped[float] = mapped_column(Float, nullable=False)
    alcohol: Mapped[float] = mapped_column(Float, nullable=False)
    quality: Mapped[int] = mapped_column(Integer, nullable=False)


class DatabaseConfigurationError(RuntimeError):
    pass


@dataclass(frozen=True)
class StoredPrediction:
    id: int
    predicted_quality: float
    model_version: str
    request_payload: dict[str, float]
    created_at: str


@dataclass(frozen=True)
class StoredPredictionEvent:
    id: int
    event_id: str
    prediction_id: int | None
    predicted_quality: float
    model_version: str
    request_payload: dict[str, float]
    published_at: str
    consumed_at: str


class PredictionStore(Protocol):
    @property
    def enabled(self) -> bool:
        ...

    def ensure_schema(self) -> None:
        ...

    def healthcheck(self) -> dict[str, bool]:
        ...

    def save_prediction(
        self,
        request_payload: dict[str, float],
        prediction: float,
        model_version: str,
    ) -> StoredPrediction | None:
        ...

    def get_latest_prediction(self) -> StoredPrediction | None:
        ...

    def save_prediction_event(
        self,
        *,
        event_id: str,
        prediction_id: int | None,
        request_payload: dict[str, float],
        prediction: float,
        model_version: str,
        published_at: str,
    ) -> StoredPredictionEvent | None:
        ...

    def get_latest_prediction_event(self) -> StoredPredictionEvent | None:
        ...

    def replace_samples(self, split_name: str, samples: list[dict[str, float]]) -> int:
        ...

    def dataset_summary(self) -> dict[str, int]:
        ...


class NullPredictionStore:
    @property
    def enabled(self) -> bool:
        return False

    def ensure_schema(self) -> None:
        return None

    def healthcheck(self) -> dict[str, bool]:
        return {"enabled": False, "connected": False}

    def save_prediction(
        self,
        request_payload: dict[str, float],
        prediction: float,
        model_version: str,
    ) -> StoredPrediction | None:
        return None

    def get_latest_prediction(self) -> StoredPrediction | None:
        return None

    def save_prediction_event(
        self,
        *,
        event_id: str,
        prediction_id: int | None,
        request_payload: dict[str, float],
        prediction: float,
        model_version: str,
        published_at: str,
    ) -> StoredPredictionEvent | None:
        return None

    def get_latest_prediction_event(self) -> StoredPredictionEvent | None:
        return None

    def replace_samples(self, split_name: str, samples: list[dict[str, float]]) -> int:
        return 0

    def dataset_summary(self) -> dict[str, int]:
        return {}


class SqlAlchemyPredictionStore:
    def __init__(self, database_url: str) -> None:
        self._engine = create_engine(database_url, future=True, pool_pre_ping=True)
        self._session_factory = sessionmaker(bind=self._engine, expire_on_commit=False)

    @property
    def enabled(self) -> bool:
        return True

    def ensure_schema(self) -> None:
        Base.metadata.create_all(self._engine)

    def healthcheck(self) -> dict[str, bool]:
        try:
            with self._engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            return {"enabled": True, "connected": True}
        except SQLAlchemyError:
            return {"enabled": True, "connected": False}

    def save_prediction(
        self,
        request_payload: dict[str, float],
        prediction: float,
        model_version: str,
    ) -> StoredPrediction:
        with self._session_factory() as session:
            record = PredictionResultRecord(
                model_version=model_version,
                predicted_quality=prediction,
                request_payload=request_payload,
            )
            session.add(record)
            session.commit()
            session.refresh(record)
            return _to_stored_prediction(record)

    def get_latest_prediction(self) -> StoredPrediction | None:
        with self._session_factory() as session:
            record = session.scalar(
                select(PredictionResultRecord).order_by(PredictionResultRecord.id.desc()).limit(1)
            )
            if record is None:
                return None
            return _to_stored_prediction(record)

    def save_prediction_event(
        self,
        *,
        event_id: str,
        prediction_id: int | None,
        request_payload: dict[str, float],
        prediction: float,
        model_version: str,
        published_at: str,
    ) -> StoredPredictionEvent:
        with self._session_factory() as session:
            existing_record = session.scalar(
                select(PredictionEventRecord).where(PredictionEventRecord.event_id == event_id).limit(1)
            )
            if existing_record is not None:
                return _to_stored_prediction_event(existing_record)

            record = PredictionEventRecord(
                event_id=event_id,
                prediction_id=prediction_id,
                model_version=model_version,
                predicted_quality=prediction,
                request_payload=request_payload,
                published_at=_parse_datetime(published_at),
            )
            session.add(record)
            session.commit()
            session.refresh(record)
            return _to_stored_prediction_event(record)

    def get_latest_prediction_event(self) -> StoredPredictionEvent | None:
        with self._session_factory() as session:
            record = session.scalar(select(PredictionEventRecord).order_by(PredictionEventRecord.id.desc()).limit(1))
            if record is None:
                return None
            return _to_stored_prediction_event(record)

    def replace_samples(self, split_name: str, samples: list[dict[str, float]]) -> int:
        with self._session_factory() as session:
            session.execute(delete(WineSampleRecord).where(WineSampleRecord.split_name == split_name))
            session.add_all(WineSampleRecord(split_name=split_name, **sample) for sample in samples)
            session.commit()
        return len(samples)

    def dataset_summary(self) -> dict[str, int]:
        with self._session_factory() as session:
            rows = session.execute(
                select(WineSampleRecord.split_name, func.count(WineSampleRecord.id)).group_by(
                    WineSampleRecord.split_name
                )
            ).all()
        return {split_name: count for split_name, count in rows}


def _to_stored_prediction(record: PredictionResultRecord) -> StoredPrediction:
    return StoredPrediction(
        id=record.id,
        predicted_quality=record.predicted_quality,
        model_version=record.model_version,
        request_payload=dict(record.request_payload),
        created_at=record.created_at.astimezone(timezone.utc).isoformat(),
    )


def _to_stored_prediction_event(record: PredictionEventRecord) -> StoredPredictionEvent:
    return StoredPredictionEvent(
        id=record.id,
        event_id=record.event_id,
        prediction_id=record.prediction_id,
        predicted_quality=record.predicted_quality,
        model_version=record.model_version,
        request_payload=dict(record.request_payload),
        published_at=record.published_at.astimezone(timezone.utc).isoformat(),
        consumed_at=record.consumed_at.astimezone(timezone.utc).isoformat(),
    )


def _parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def build_database_url_from_env(required: bool = False) -> str | None:
    env = os.environ
    if env.get("DATABASE_URL"):
        return env["DATABASE_URL"]

    vault_secret = load_secret_from_vault_env(required=False)
    if vault_secret:
        if vault_secret.get("DATABASE_URL"):
            return vault_secret["DATABASE_URL"]

        env = {**vault_secret, **env}

    required_keys = (
        "DATABASE_HOST",
        "DATABASE_PORT",
        "DATABASE_NAME",
        "DATABASE_USER",
        "DATABASE_PASSWORD",
    )
    missing = [key for key in required_keys if not env.get(key)]

    if missing:
        if required:
            if vault_secret is None and os.environ.get("VAULT_ADDR"):
                raise DatabaseConfigurationError("Vault is configured, but database secrets could not be loaded.")
            raise DatabaseConfigurationError("Missing database configuration variables: " + ", ".join(sorted(missing)))
        return None

    query: dict[str, str] = {}
    if env.get("DATABASE_SSLMODE"):
        query["sslmode"] = env["DATABASE_SSLMODE"]

    return URL.create(
        drivername=env.get("DATABASE_DRIVER", "postgresql+psycopg"),
        username=env["DATABASE_USER"],
        password=env["DATABASE_PASSWORD"],
        host=env["DATABASE_HOST"],
        port=int(env["DATABASE_PORT"]),
        database=env["DATABASE_NAME"],
        query=query,
    ).render_as_string(hide_password=False)


def _database_configuration_requested() -> bool:
    keys = (
        "DATABASE_URL",
        "DATABASE_HOST",
        "DATABASE_PORT",
        "DATABASE_NAME",
        "DATABASE_USER",
        "DATABASE_PASSWORD",
        "VAULT_ADDR",
        "VAULT_TOKEN",
        "VAULT_SECRET_PATH",
    )
    return any(os.environ.get(key) for key in keys)


def build_prediction_store_from_env(required: bool = False) -> PredictionStore:
    strict_mode = required or _database_configuration_requested()

    try:
        database_url = build_database_url_from_env(required=strict_mode)
    except VaultConfigurationError as error:
        raise DatabaseConfigurationError(str(error)) from error

    if database_url is None:
        return NullPredictionStore()
    return SqlAlchemyPredictionStore(database_url)