# Wine Quality MLOps

Учебный проект для задания по CI/CD для ML-модели на датасете Wine Quality.

## Что реализовано

- подготовка данных для `winequality-red.csv`;
- регрессионная модель `RandomForestRegressor` для предсказания `quality`;
- API-сервис на FastAPI с методами `/predict`, `/predictions/latest`, `/training-data/summary`;
- PostgreSQL для хранения предсказаний и обучающей выборки;
- HashiCorp Vault как отдельный контейнер для хранения секретов БД;
- unit и API tests на `pytest`;
- DVC pipeline для этапов `prepare` и `train`;
- Docker image и `docker-compose.yml`;
- GitHub Actions workflows для CI и CD;
- служебные файлы `config.ini`, `dev_sec_ops.yml`, `scenario.json`.

## Структура

```text
.
|-- .github/workflows/
|-- artifacts/
|-- data/
|-- docker/vault/
|-- jenkins/
|   |-- raw/
|   `-- processed/
|-- notebooks/
|-- Результаты_работы/
|-- scripts/
|-- src/wine_quality_mlops/
`-- tests/
```

## Быстрый старт

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python scripts/prepare_data.py --input data/raw/winequality-red.csv --output-dir data/processed --config config.ini
python scripts/train_model.py --train-path data/processed/train.csv --test-path data/processed/test.csv --artifacts-dir artifacts --config config.ini
pytest --cov=src/wine_quality_mlops --cov-report=xml --cov-report=term-missing
uvicorn --app-dir src wine_quality_mlops.app:app --host 0.0.0.0 --port 8000
```

В этом режиме API запускается без БД. `/predict` работает, но endpoints, завязанные на persistence, вернут `503`, пока не подняты PostgreSQL и Vault.

## DVC pipeline

```powershell
dvc repro
```

## Docker

```powershell
docker compose up -d --build postgres vault api
docker compose --profile seed run --rm db-seed
Invoke-RestMethod http://127.0.0.1:8000/health
python tests/functional/run_scenario.py --scenario scenario_lab3.json --base-url http://127.0.0.1:8000 --report functional-test-report.json
```

Остановить стенд:

```powershell
docker compose down -v
```

Что происходит в Lab3-стеке:

- `vault` поднимается как отдельный контейнер и сам заполняет секрет `secret/wine-quality/database`;
- `api` и `db-seed` получают только `VAULT_ADDR`, `VAULT_TOKEN`, `VAULT_SECRET_PATH` и читают креды БД из Vault;
- `postgres` хранит таблицы `prediction_results` и `wine_samples`.

## Vault

Сервис использует HTTP API Vault напрямую, поэтому VS Code extension не требуется для работы приложения. Для ручной проверки секрета можно использовать CLI внутри контейнера:

```powershell
docker compose exec vault vault kv get secret/wine-quality/database
```

Если хочешь посмотреть секреты через расширение HashiCorp Vault в VS Code, подключайся так:

- Address: `http://127.0.0.1:8200`
- Token: `root`
- Secret engine: `secret`
- Secret path: `wine-quality/database`

Для HTTP API внутри приложения используется путь `secret/data/wine-quality/database`, потому что контейнер работает с KV v2.

## CI/CD

- `CI`: запускается по `pull_request` в `main`, прогоняет `dvc repro`, `pytest`, собирает Docker image и отправляет его в DockerHub.
- `CD`: запускается вручную, по расписанию или после успешного `CI`, поднимает контейнер и выполняет функциональный сценарий внутри контейнера.

## Jenkins

Для Lab3 в репозитории добавлены два repo-defined pipeline файла:

- `jenkins/lab3-ci.Jenkinsfile`
- `jenkins/lab3-cd.Jenkinsfile`

Как создавать jobs в Jenkins:

- Job type: `Pipeline`
- Definition: `Pipeline script from SCM`
- SCM: `Git`
- Script Path для CI: `jenkins/lab3-ci.Jenkinsfile`
- Script Path для CD: `jenkins/lab3-cd.Jenkinsfile`

Что делает Jenkins CI pipeline:

- создает `.venv` и ставит зависимости из `requirements.txt`;
- запускает `dvc repro` и `pytest`;
- собирает `api` и `vault` через `docker compose build`;
- поднимает `postgres` и `vault`, выполняет `db-seed`;
- запускает функциональный сценарий `scenario_lab3.json`;
- опционально тегирует и пушит API image в Docker Hub.

Что делает Jenkins CD pipeline:

- при необходимости подтягивает заранее собранный API image;
- приводит его к локальному тегу `wine-quality-mlops:local`, который использует compose;
- собирает `vault`, поднимает весь Lab3-стек и повторно гоняет `scenario_lab3.json`.

Если Jenkins работает на той же машине, что и Docker Desktop, дополнительных секретов БД для job не нужно: Vault сам поднимается в dev-режиме и сам же создает секрет `secret/wine-quality/database`.

## GitHub и DockerHub

Перед использованием workflows нужно задать secrets:

- `DOCKERHUB_USERNAME`
- `DOCKERHUB_TOKEN`

## Цитирование датасета

P. Cortez, A. Cerdeira, F. Almeida, T. Matos and J. Reis.
Modeling wine preferences by data mining from physicochemical properties.
Decision Support Systems, Elsevier, 47(4):547-553, 2009.
