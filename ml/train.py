import hashlib
import json
import os
from datetime import date

import numpy as np
import pandas as pd
from catboost import CatBoostRegressor
from psycopg.types.json import Jsonb
from sklearn.metrics import mean_absolute_error, mean_absolute_percentage_error, r2_score
from sklearn.metrics import root_mean_squared_error

from etl.db import SQL_DIR
from ml.features import CATEGORICAL, make_features, split_samples, time_boundaries


def load_dataset(connection, as_of: date) -> pd.DataFrame:
    train_start, _ = time_boundaries(as_of)
    rows = connection.execute(
        (SQL_DIR / "ml_dataset.sql").read_text(encoding="utf-8"), {"train_start": train_start}
    ).fetchall()
    if not rows:
        raise ValueError("No ML data; load the training window first")
    return pd.DataFrame.from_records(rows)


def fit_and_score(frame: pd.DataFrame, as_of: date, *, iterations=None):
    train, test, future = split_samples(frame, as_of)
    if len(train) < 2 or len(test) < 2:
        raise ValueError("Training and test windows must each contain at least two eligible deals")
    features = make_features(train)
    parameters = {
        "iterations": iterations or int(os.getenv("MODEL_ITERATIONS", "500")),
        "depth": 6,
        "learning_rate": 0.06,
        "loss_function": "RMSE",
        "random_seed": int(os.getenv("RANDOM_SEED", "42")),
        "thread_count": int(os.getenv("MODEL_THREADS", "4")),
        "has_time": True,
        "allow_writing_files": False,
        "verbose": False,
    }
    fingerprint = hashlib.sha256(
        pd.util.hash_pandas_object(features, index=False).values.tobytes()
        + train["price_rub"].to_numpy(dtype="float64").tobytes()
        + json.dumps(parameters, sort_keys=True).encode()
    ).hexdigest()[:12]
    model_name = f"catboost-1.2.8-{fingerprint}"
    model = CatBoostRegressor(**parameters)
    # Test is never used as eval_set: neither fitting nor stopping depends on held-out targets.
    model.fit(features, train["price_rub"], cat_features=CATEGORICAL)
    scored = pd.concat([test.assign(sample="test"), future.assign(sample="future")], ignore_index=True)
    predicted = np.maximum(1.0, model.predict(make_features(scored)))
    actual = scored["price_rub"].to_numpy(dtype=float)
    historical = scored["sample"].eq("test").to_numpy()
    metrics = {
        "r2": float(r2_score(actual[historical], predicted[historical])),
        "mape_pct": float(mean_absolute_percentage_error(actual[historical], predicted[historical]) * 100),
        "rmse_rub": float(root_mean_squared_error(actual[historical], predicted[historical])),
        "mae_rub": float(mean_absolute_error(actual[historical], predicted[historical])),
    }
    output = scored[["price_id", "loading_date", "loading_city_gcid", "unloading_city_gcid",
                     "body_group", "sample"]].copy()
    output["actual_price_rub"] = np.where(historical, actual, np.nan)
    output["predicted_price_rub"] = predicted
    output["abs_error_rub"] = np.where(historical, np.abs(actual - predicted), np.nan)
    output["ape_pct"] = np.where(historical, np.abs(actual - predicted) / actual * 100, np.nan)
    output["model_name"] = model_name
    summary = {
        "model_name": model_name, "train_count": len(train), "test_count": len(test),
        "future_count": len(future), "metrics": metrics,
        "parameters": parameters, "feature_names": list(features.columns),
    }
    return output, summary


def save_predictions(connection, output: pd.DataFrame, summary: dict, as_of: date):
    train_start, test_start = time_boundaries(as_of)
    with connection.transaction():
        connection.execute("DELETE FROM mart.ml_price_predictions WHERE as_of = %s", (as_of,))
        with connection.cursor() as cursor:
            with cursor.copy(
                "COPY mart.ml_price_predictions (as_of, price_id, loading_date, loading_city_gcid, "
                "unloading_city_gcid, body_group, sample, actual_price_rub, predicted_price_rub, "
                "abs_error_rub, ape_pct, model_name) FROM STDIN"
            ) as copy:
                for row in output.itertuples(index=False, name=None):
                    copy.write_row((as_of, *(None if pd.isna(value) else value for value in row)))
        connection.execute("DELETE FROM mart.ml_model_runs WHERE as_of = %s", (as_of,))
        connection.execute(
            "INSERT INTO mart.ml_model_runs (as_of, model_name, train_start, test_start, "
            "train_count, test_count, future_count, feature_names, parameters, metrics) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (as_of, summary["model_name"], train_start, test_start, summary["train_count"],
             summary["test_count"], summary["future_count"], Jsonb(summary["feature_names"]),
             Jsonb(summary["parameters"]), Jsonb(summary["metrics"])),
        )


def run_model(connection, as_of: date) -> dict:
    frame = load_dataset(connection, as_of)
    output, summary = fit_and_score(frame, as_of)
    save_predictions(connection, output, summary, as_of)
    return summary
