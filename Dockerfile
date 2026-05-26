FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app/src

WORKDIR /app

COPY requirements.runtime.txt ./
RUN pip install --no-cache-dir --upgrade pip && pip install --no-cache-dir -r requirements.runtime.txt

COPY config.ini ./
COPY dvc.yaml ./
COPY scenario.json ./
COPY scenario_lab3.json ./
COPY scripts ./scripts
COPY src ./src
COPY tests ./tests
COPY data ./data

RUN python scripts/prepare_data.py --input data/raw/winequality-red.csv --output-dir data/processed --config config.ini && \
    python scripts/train_model.py --train-path data/processed/train.csv --test-path data/processed/test.csv --artifacts-dir artifacts --config config.ini

EXPOSE 8000

CMD ["uvicorn", "wine_quality_mlops.app:app", "--host", "0.0.0.0", "--port", "8000"]
