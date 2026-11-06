from datetime import date

import numpy as np
import pandas as pd
import pytest

from etl.load import load_core
from ml.features import make_features, split_samples, time_boundaries
from ml.repository import load_dataset, save_predictions
from ml.train import fit_and_score

AS_OF = date(2026, 10, 26)


@pytest.fixture
def frame():
    dates = pd.to_datetime([
        "2026-07-25", "2026-07-26", "2026-08-02", "2026-09-01", "2026-10-04",
        "2026-10-05", "2026-10-26", "2026-10-27", "2027-01-01",
    ])
    size = len(dates)
    return pd.DataFrame({
        "price_id": range(1, size + 1), "loading_date": dates,
        "loading_city_gcid": 1, "unloading_city_gcid": 2,
        "origin_region": "Татарстан", "destination_region": "г. Москва",
        "origin_latitude": 55.8, "origin_longitude": 49.1,
        "destination_latitude": 55.7, "destination_longitude": 37.6,
        "distance": np.arange(size) * 100 + 100,
        "total_weight": 20, "total_volume": 80, "weight_category": "FTL",
        "volume_category": "FTL", "body_group": "Тент",
        "price_rub": np.arange(size) * 1000 + 10000,
        "is_fact": True, "price_type": 3, "complex": False, "outlier_mark": False,
    })


def test_split_boundaries_and_filters(frame):
    assert time_boundaries(AS_OF) == (date(2026, 7, 26), date(2026, 10, 5))
    train, test, future = split_samples(frame, AS_OF)
    assert train["price_id"].tolist() == [2, 3, 4, 5]
    assert test["price_id"].tolist() == [6, 7]
    assert future["price_id"].tolist() == [8, 9]
    frame.loc[2, "outlier_mark"] = True
    frame.loc[3, "price_type"] = 6
    frame.loc[7, ["outlier_mark", "is_fact"]] = [True, False]
    train, _, future = split_samples(frame, AS_OF)
    assert train["price_id"].tolist() == [2, 5]
    assert future["price_id"].tolist() == [8, 9]


def test_features_ignore_targets_and_encode_cycles(frame):
    original = make_features(frame)
    frame["price_rub"] *= 100
    for column in ["price_with_vat", "price_group_id", "avg_price", "min_km_price", "profit"]:
        frame[column] = 123456
    pd.testing.assert_frame_equal(original, make_features(frame))
    assert not {"price_rub", "outlier_mark", "price_type", "price_id"} & set(original.columns)
    for name in ["month", "weekday", "day_of_year"]:
        np.testing.assert_allclose(original[f"{name}_sin"] ** 2 + original[f"{name}_cos"] ** 2, 1)
    frame.loc[0, "loading_date"] = pd.Timestamp("2026-12-31")
    frame.loc[1, "loading_date"] = pd.Timestamp("2027-01-01")
    result = make_features(frame)
    assert abs(result.loc[0, "day_of_year_sin"] - result.loc[1, "day_of_year_sin"]) < 0.03


def test_test_targets_cannot_change_model_or_predictions(frame):
    predictions, summary = fit_and_score(frame, AS_OF, iterations=20)
    frame.loc[frame["loading_date"] >= "2026-10-05", "price_rub"] *= 100
    again, changed = fit_and_score(frame, AS_OF, iterations=20)
    assert summary["model_name"] == changed["model_name"]
    np.testing.assert_array_equal(predictions["predicted_price_rub"], again["predicted_price_rub"])
    assert summary["metrics"] != changed["metrics"]
    assert predictions.loc[predictions["sample"] == "future", ["actual_price_rub", "abs_error_rub", "ape_pct"]].isna().all().all()


def test_sql_dataset_has_one_row_per_deal_and_scoring_is_idempotent(db, add_price):
    for day in [date(2026, 7, 26), date(2026, 8, 1), date(2026, 9, 1), date(2026, 10, 4),
                date(2026, 10, 5), date(2026, 10, 26), date(2026, 10, 27)]:
        price_id = add_price(loading_date=day, distance=day.day * 100, price=day.day * 2000)
        db.execute("INSERT INTO raw.price_body_types(price_id,body_type_id) VALUES (%s,56),(%s,57),(%s,15)",
                   (price_id,) * 3)
    load_core(db, date(2026, 7, 1), date(2027, 1, 1))
    dataset = load_dataset(db, AS_OF)
    assert len(dataset) == dataset["price_id"].nunique() == 7
    assert set(dataset["body_group"]) == {"Борт + Тент"}
    output, summary = fit_and_score(dataset, AS_OF, iterations=20)
    for _ in range(2):
        save_predictions(db, output, summary, AS_OF)
    assert db.execute("SELECT count(*) AS n FROM mart.ml_price_predictions").fetchone()["n"] == 3
    assert db.execute("SELECT count(*) AS n FROM mart.ml_model_runs").fetchone()["n"] == 1
    future = db.execute("SELECT * FROM mart.ml_price_predictions WHERE sample='future'").fetchone()
    assert all(future[column] is None for column in ("actual_price_rub", "abs_error_rub", "ape_pct"))
