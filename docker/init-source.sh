#!/bin/sh
set -eu
case "${N_PRICES:-300000}" in
    ''|*[!0-9]*) echo 'N_PRICES must be a positive integer' >&2; exit 1 ;;
esac
test "${N_PRICES:-300000}" -gt 0

if [ "$(psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "SELECT to_regclass('raw.prices') IS NOT NULL")" = t ]; then
    exit 0
fi

psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 \
    -v n_prices="${N_PRICES:-300000}" --single-transaction \
    -c 'CREATE SCHEMA IF NOT EXISTS raw' -c 'SET search_path TO raw, public' \
    -f /source/schema.sql -f /source/synthetic.sql >/dev/null
