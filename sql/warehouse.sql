CREATE SCHEMA IF NOT EXISTS core;
CREATE SCHEMA IF NOT EXISTS mart;

CREATE TABLE IF NOT EXISTS core.cities (
    gc_id integer PRIMARY KEY,
    source_id bigint NOT NULL,
    name text NOT NULL,
    region text NOT NULL,
    latitude double precision,
    longitude double precision
);

CREATE TABLE IF NOT EXISTS core.prices (
    price_id bigint PRIMARY KEY,
    loading_date date NOT NULL,
    created_at timestamp,
    loading_city_gcid integer NOT NULL,
    unloading_city_gcid integer NOT NULL,
    distance double precision NOT NULL CHECK (distance > 0),
    total_weight double precision NOT NULL CHECK (total_weight >= 0),
    total_volume double precision NOT NULL CHECK (total_volume >= 0),
    weight_category text NOT NULL,
    volume_category text NOT NULL,
    organization_id integer,
    price_type smallint NOT NULL,
    is_fact boolean NOT NULL,
    complex boolean NOT NULL,
    outlier_mark boolean NOT NULL,
    price numeric NOT NULL,
    currency_code text NOT NULL,
    nearest_rate_date date,
    exchange_rate numeric NOT NULL CHECK (exchange_rate > 0),
    price_rub numeric NOT NULL CHECK (price_rub > 0)
);
CREATE INDEX IF NOT EXISTS core_prices_loading_date ON core.prices (loading_date);

CREATE TABLE IF NOT EXISTS core.price_body_groups (
    price_id bigint REFERENCES core.prices ON DELETE CASCADE,
    body_group text NOT NULL,
    PRIMARY KEY (price_id, body_group)
);
CREATE TABLE IF NOT EXISTS core.price_dates (
    price_id bigint REFERENCES core.prices ON DELETE CASCADE,
    price_date date NOT NULL,
    PRIMARY KEY (price_id, price_date)
);
CREATE INDEX IF NOT EXISTS core_price_dates_date ON core.price_dates (price_date);

CREATE TABLE IF NOT EXISTS core.dq_quarantine_prices (
    price_id bigint PRIMARY KEY,
    loading_date date NOT NULL,
    reasons text[] NOT NULL CHECK (cardinality(reasons) > 0),
    source_row jsonb NOT NULL
);
CREATE INDEX IF NOT EXISTS quarantine_loading_date ON core.dq_quarantine_prices (loading_date);

CREATE TABLE IF NOT EXISTS mart.market_corridor (
    month date NOT NULL,
    loading_city_gcid integer NOT NULL,
    unloading_city_gcid integer NOT NULL,
    body_group text NOT NULL,
    weight_category text NOT NULL,
    p25_trip double precision NOT NULL,
    median_trip double precision NOT NULL,
    p75_trip double precision NOT NULL,
    avg_trip numeric NOT NULL,
    p25_km double precision NOT NULL,
    median_km double precision NOT NULL,
    p75_km double precision NOT NULL,
    trips_count bigint NOT NULL,
    carriers_count bigint NOT NULL,
    cv_rate numeric,
    mom_pct double precision,
    yoy_pct double precision,
    last_price_date date NOT NULL,
    reliability_level text NOT NULL,
    as_of date NOT NULL,
    PRIMARY KEY (month, loading_city_gcid, unloading_city_gcid, body_group, weight_category)
);
CREATE INDEX IF NOT EXISTS market_corridor_route ON mart.market_corridor
    (loading_city_gcid, unloading_city_gcid, body_group, weight_category, month);

CREATE TABLE IF NOT EXISTS mart.ml_model_runs (
    as_of date PRIMARY KEY,
    model_name text NOT NULL,
    train_start date NOT NULL,
    test_start date NOT NULL,
    train_count integer NOT NULL,
    test_count integer NOT NULL,
    future_count integer NOT NULL,
    feature_names jsonb NOT NULL,
    parameters jsonb NOT NULL,
    metrics jsonb NOT NULL,
    trained_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS mart.ml_price_predictions (
    as_of date NOT NULL,
    price_id bigint NOT NULL,
    loading_date date NOT NULL,
    loading_city_gcid integer NOT NULL,
    unloading_city_gcid integer NOT NULL,
    body_group text NOT NULL,
    sample text NOT NULL CHECK (sample IN ('test', 'future')),
    actual_price_rub double precision,
    predicted_price_rub double precision NOT NULL CHECK (predicted_price_rub > 0),
    abs_error_rub double precision,
    ape_pct double precision,
    model_name text NOT NULL,
    scored_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (as_of, price_id),
    CHECK (sample <> 'future' OR
        (actual_price_rub IS NULL AND abs_error_rub IS NULL AND ape_pct IS NULL))
);
