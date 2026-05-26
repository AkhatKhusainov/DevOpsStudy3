# Wine Quality MLOps

Учебный проект для задания по CI/CD для ML-модели на датасете Wine Quality.

## Что реализовано

- подготовка данных для `winequality-red.csv`;
- регрессионная модель `RandomForestRegressor` для предсказания `quality`;
- API-сервис на FastAPI с методами `/predict`, `/predictions/latest`, `/training-data/summary`;
- PostgreSQL для хранения предсказаний и обучающей выборки;
- HashiCorp Vault как отдельный контейнер для хранения секретов БД;
- Kafka producer в API и отдельный Kafka consumer-контейнер для сохранения событий предсказаний;
- endpoint `/prediction-events/latest` для проверки последнего обработанного Kafka event;
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

Lab4 со стеком Kafka:

```powershell
docker compose up -d --build postgres vault kafka api kafka-consumer
docker compose --profile seed run --rm db-seed
docker compose exec -T api python tests/functional/run_scenario.py --scenario /app/scenario_lab4.json --base-url http://127.0.0.1:8000 --report /app/artifacts/functional-test-report.json
```

Остановить стенд:

```powershell
docker compose down -v
```

Что происходит в Lab3-стеке:

- `vault` поднимается как отдельный контейнер и сам заполняет секрет `secret/wine-quality/database`;
- `api` и `db-seed` получают только `VAULT_ADDR`, `VAULT_TOKEN`, `VAULT_SECRET_PATH` и читают креды БД из Vault;
- `postgres` хранит таблицы `prediction_results` и `wine_samples`.

Что происходит в Lab4-стеке:

- `vault` дополнительно создает секрет `secret/wine-quality/kafka` с `KAFKA_BOOTSTRAP_SERVERS`, `KAFKA_PREDICTIONS_TOPIC` и `KAFKA_CONSUMER_GROUP`;
- `api` сохраняет результат предсказания в PostgreSQL и публикует `PredictionEvent` в Kafka;
- `kafka-consumer` читает сообщения из Kafka и пишет их в таблицу `prediction_events` через тот же Vault-backed доступ к БД;
- сценарий `scenario_lab4.json` проверяет не только `/predict` и `/predictions/latest`, но и `/prediction-events/latest`.

Для локального Windows-стенда надежнее запускать `scenario_lab4.json` изнутри контейнера `api`, как в команде выше. Это убирает зависимость от занятого хостового порта `127.0.0.1:8000`.

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

Для Lab4 с Kafka добавлены отдельные pipeline файлы:

- `jenkins/lab4-ci.Jenkinsfile`
- `jenkins/lab4-cd.Jenkinsfile`

Как создавать jobs в Jenkins:

- Job type: `Pipeline`
- Definition: `Pipeline script from SCM`
- SCM: `Git`
- Script Path для CI: `jenkins/lab3-ci.Jenkinsfile`
- Script Path для CD: `jenkins/lab3-cd.Jenkinsfile`

Для Lab4 создай отдельные Jenkins jobs с `Script Path`:

- CI: `jenkins/lab4-ci.Jenkinsfile`
- CD: `jenkins/lab4-cd.Jenkinsfile`

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

Что делают Jenkins Lab4 pipelines:

- `lab4-ci` прогоняет `dvc repro`, `pytest`, собирает `api` и `vault`, поднимает `postgres + vault + kafka + api + kafka-consumer`, выполняет `db-seed`, запускает `scenario_lab4.json` внутри контейнера `api`, затем при необходимости пушит Docker image и триггерит `lab4-cd`;
- `lab4-cd` подготавливает или подтягивает нужный API image, собирает `vault`, поднимает Lab4-стек и заново прогоняет `scenario_lab4.json` внутри контейнера `api`.

Если Jenkins работает на той же машине, что и Docker Desktop, дополнительных секретов БД для job не нужно: Vault сам поднимается в dev-режиме и сам же создает секрет `secret/wine-quality/database`.

## GitHub и DockerHub

Перед использованием workflows нужно задать secrets:

- `DOCKERHUB_USERNAME`
- `DOCKERHUB_TOKEN`

## Цитирование датасета

P. Cortez, A. Cerdeira, F. Almeida, T. Matos and J. Reis.
Modeling wine preferences by data mining from physicochemical properties.
Decision Support Systems, Elsevier, 47(4):547-553, 2009.
