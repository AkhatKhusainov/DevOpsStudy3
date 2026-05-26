from __future__ import annotations

import json
import os
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class VaultConfigurationError(RuntimeError):
    pass


def _normalize_secret_payload(payload: dict[str, Any]) -> dict[str, str]:
    data = payload.get("data")
    if not isinstance(data, dict):
        raise VaultConfigurationError("Vault response does not contain a data object.")

    if isinstance(data.get("data"), dict):
        data = data["data"]

    return {str(key): str(value) for key, value in data.items()}


def load_secret_from_vault(address: str, token: str, secret_path: str, timeout_seconds: float = 5.0) -> dict[str, str]:
    request = Request(
        f"{address.rstrip('/')}/v1/{secret_path.lstrip('/')}",
        headers={
            "Accept": "application/json",
            "X-Vault-Token": token,
        },
        method="GET",
    )

    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        raise VaultConfigurationError(f"Vault returned HTTP {error.code} for secret path {secret_path}.") from error
    except URLError as error:
        raise VaultConfigurationError(f"Could not reach Vault at {address}.") from error
    except json.JSONDecodeError as error:
        raise VaultConfigurationError("Vault response is not valid JSON.") from error

    return _normalize_secret_payload(payload)


def load_secret_from_vault_env(
    required: bool = False,
    *,
    address_env: str = "VAULT_ADDR",
    token_env: str = "VAULT_TOKEN",
    secret_path_env: str = "VAULT_SECRET_PATH",
) -> dict[str, str] | None:
    env = os.environ
    address = env.get(address_env)
    token = env.get(token_env)
    secret_path = env.get(secret_path_env)

    configured = any((address, token, secret_path))
    if not configured:
        return None

    missing = [
        key
        for key, value in (
            (address_env, address),
            (token_env, token),
            (secret_path_env, secret_path),
        )
        if not value
    ]
    if missing:
        if required:
            raise VaultConfigurationError("Missing Vault configuration variables: " + ", ".join(sorted(missing)))
        return None

    timeout_seconds = float(env.get("VAULT_TIMEOUT_SECONDS", "5"))
    return load_secret_from_vault(address, token, secret_path, timeout_seconds=timeout_seconds)