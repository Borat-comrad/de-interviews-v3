from datetime import date

import pandas as pd
from psycopg.types.json import Jsonb

from etl.db import SQL_DIR
from ml.features import time_boundaries


def load_dataset(connection, as_of: date) -> pd.DataFrame:
    train_start, _ = time_boundaries(as_of)
    rows = connection.execute(
        (SQL_DIR / "ml_dataset.sql").read_text(encoding="utf-8"), {"train_start": train_start}
    ).fetchall()
    if not rows:
        raise ValueError("No ML data; load the training window first")
    return pd.DataFrame.from_records(rows)


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
