from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import requests


def execute_step(
    base_url: str,
    step: dict[str, object],
    retries: int,
    retry_delay: float,
    session: requests.Session,
) -> dict[str, object]:
    method = str(step["method"]).upper()
    path = str(step["path"])
    url = f"{base_url.rstrip('/')}{path}"
    last_error: Exception | None = None

    for attempt in range(retries):
        try:
            response = session.request(method, url, json=step.get("json"), timeout=15)
            response_body: object

            try:
                response_body = response.json()
            except ValueError:
                response_body = response.text

            if response.status_code != int(step["expected_status"]):
                raise AssertionError(
                    f"{step['name']}: expected status {step['expected_status']}, got {response.status_code}"
                )

            if "expected_keys" in step:
                if not isinstance(response_body, dict):
                    raise AssertionError(f"{step['name']}: response is not JSON object")
                missing_keys = sorted(set(step["expected_keys"]) - set(response_body))
                if missing_keys:
                    raise AssertionError(f"{step['name']}: missing keys {missing_keys}")

            if "response_contains" in step:
                if not isinstance(response_body, dict):
                    raise AssertionError(f"{step['name']}: response is not JSON object")
                for key, value in dict(step["response_contains"]).items():
                    if response_body.get(key) != value:
                        raise AssertionError(
                            f"{step['name']}: expected {key}={value}, got {response_body.get(key)}"
                        )

            return {
                "name": step["name"],
                "status_code": response.status_code,
                "response": response_body,
            }
        except (requests.RequestException, AssertionError) as error:
            last_error = error
            if attempt < retries - 1:
                time.sleep(retry_delay)

    raise AssertionError(str(last_error))


def main() -> None:
    parser = argparse.ArgumentParser(description="Run functional scenario against a running container.")
    parser.add_argument("--scenario", required=True)
    parser.add_argument("--base-url", default=None)
    parser.add_argument("--report", default="functional-test-report.json")
    parser.add_argument("--retries", type=int, default=10)
    parser.add_argument("--retry-delay", type=float, default=1.0)
    args = parser.parse_args()

    scenario = json.loads(Path(args.scenario).read_text(encoding="utf-8"))
    base_url = args.base_url or scenario["base_url"]
    report_path = Path(args.report)

    results: list[dict[str, object]] = []
    overall_status = "passed"
    session = requests.Session()
    session.trust_env = False

    try:
        for step in scenario["steps"]:
            results.append(execute_step(base_url, step, args.retries, args.retry_delay, session))
    except Exception as error:  # noqa: BLE001
        overall_status = "failed"
        results.append({"name": "failure", "error": str(error)})
        report_path.write_text(
            json.dumps({"status": overall_status, "results": results}, indent=2),
            encoding="utf-8",
        )
        print(json.dumps({"status": overall_status, "results": results}, indent=2))
        sys.exit(1)

    report_path.write_text(
        json.dumps({"status": overall_status, "results": results}, indent=2),
        encoding="utf-8",
    )
    print(json.dumps({"status": overall_status, "results": results}, indent=2))
    session.close()


if __name__ == "__main__":
    main()
