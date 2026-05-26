#!/bin/sh
set -eu

export VAULT_ADDR="http://127.0.0.1:8200"
export VAULT_TOKEN="root"

vault server \
  -dev \
  -dev-root-token-id="$VAULT_TOKEN" \
  -dev-listen-address="0.0.0.0:8200" \
  &

vault_pid=$!

until vault status >/dev/null 2>&1; do
  sleep 1
done

vault kv put secret/wine-quality/database \
  DATABASE_HOST=postgres \
  DATABASE_PORT=5432 \
  DATABASE_NAME=wine_quality \
  DATABASE_USER=wine_user \
  DATABASE_PASSWORD=wine_password \
  DATABASE_DRIVER=postgresql+psycopg

vault kv put secret/wine-quality/kafka \
  KAFKA_BOOTSTRAP_SERVERS=kafka:19092 \
  KAFKA_PREDICTIONS_TOPIC=wine-quality.predictions \
  KAFKA_CONSUMER_GROUP=wine-quality-consumer

wait "$vault_pid"