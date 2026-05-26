from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import pandas as pd
from sqlalchemy.exc import OperationalError

from wine_quality_mlops.database import DatabaseConfigurationError, SqlAlchemyPredictionStore, build_prediction_store_from_env
from wine_quality_mlops.schema import ALL_COLUMNS


DB_READY_ATTEMPTS = 15
DB_READY_DELAY_SECONDS = 3


def _normalize_frame(frame: pd.DataFrame) -> pd.DataFrame:
    missing_columns = sorted(set(ALL_COLUMNS) - set(frame.columns))
    if missing_columns:
        raise ValueError(f"Dataset is missing required columns: {missing_columns}")
    return frame.loc[:, list(ALL_COLUMNS)].copy()


def _build_store_with_retry() -> SqlAlchemyPredictionStore:
    last_error: Exception | None = None
    for attempt in range(DB_READY_ATTEMPTS):
        try:
            store = build_prediction_store_from_env(required=True)
            if not isinstance(store, SqlAlchemyPredictionStore):
                raise DatabaseConfigurationError("A SQLAlchemy-backed database store is required for seeding.")

            store.ensure_schema()
            return store
        except DatabaseConfigurationError as exc:
            last_error = exc
            if attempt == DB_READY_ATTEMPTS - 1:
                raise
        except OperationalError as exc:
            last_error = exc
            if attempt == DB_READY_ATTEMPTS - 1:
                raise

        time.sleep(DB_READY_DELAY_SECONDS)

    if last_error is not None:
        raise last_error


def seed_database(train_path: str | Path, test_path: str | Path) -> dict[str, object]:
    store = _build_store_with_retry()
    train_frame = _normalize_frame(pd.read_csv(train_path))
    test_frame = _normalize_frame(pd.read_csv(test_path))

    train_count = store.replace_samples("train", train_frame.to_dict(orient="records"))
    test_count = store.replace_samples("test", test_frame.to_dict(orient="records"))

    return {
        "train_records": train_count,
        "test_records": test_count,
        "dataset_summary": store.dataset_summary(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed PostgreSQL with prepared train and test datasets.")
    parser.add_argument("--train-path", required=True)
    parser.add_argument("--test-path", required=True)
    args = parser.parse_args()

    summary = seed_database(args.train_path, args.test_path)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()