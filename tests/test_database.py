from __future__ import annotations

import json
from io import BytesIO

from wine_quality_mlops.database import build_database_url_from_env


class _FakeResponse(BytesIO):
    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()


def test_build_database_url_from_vault_secret(monkeypatch) -> None:
    secret_payload = {
        "data": {
            "data": {
                "DATABASE_HOST": "postgres",
                "DATABASE_PORT": "5432",
                "DATABASE_NAME": "wine_quality",
                "DATABASE_USER": "wine_user",
                "DATABASE_PASSWORD": "wine_password",
            }
        }
    }

    monkeypatch.setenv("VAULT_ADDR", "http://vault:8200")
    monkeypatch.setenv("VAULT_TOKEN", "root")
    monkeypatch.setenv("VAULT_SECRET_PATH", "secret/data/wine-quality/database")
    monkeypatch.delenv("DATABASE_HOST", raising=False)
    monkeypatch.delenv("DATABASE_PORT", raising=False)
    monkeypatch.delenv("DATABASE_NAME", raising=False)
    monkeypatch.delenv("DATABASE_USER", raising=False)
    monkeypatch.delenv("DATABASE_PASSWORD", raising=False)

    def fake_urlopen(request, timeout):
        assert request.full_url == "http://vault:8200/v1/secret/data/wine-quality/database"
        assert request.headers["X-vault-token"] == "root"
        assert timeout == 5.0
        return _FakeResponse(json.dumps(secret_payload).encode("utf-8"))

    monkeypatch.setattr("wine_quality_mlops.vault.urlopen", fake_urlopen)

    database_url = build_database_url_from_env(required=True)

    assert database_url == "postgresql+psycopg://wine_user:wine_password@postgres:5432/wine_quality"