from datetime import date, timedelta

import numpy as np
import pandas as pd

CATEGORICAL = [
    "loading_city_gcid", "unloading_city_gcid", "origin_region", "destination_region",
    "body_group", "weight_category", "volume_category",
]
NUMERIC = [
    "distance", "total_weight", "total_volume", "origin_latitude", "origin_longitude",
    "destination_latitude", "destination_longitude",
]


def time_boundaries(as_of: date) -> tuple[date, date]:
    return (pd.Timestamp(as_of) - pd.DateOffset(months=3)).date(), as_of - timedelta(weeks=3)


def split_samples(frame: pd.DataFrame, as_of: date) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    train_start, test_start = time_boundaries(as_of)
    dates = pd.to_datetime(frame["loading_date"])
    eligible = (
        frame["is_fact"] & frame["price_type"].isin([1, 2, 3, 4, 5, 9])
        & ~frame["complex"] & ~frame["outlier_mark"] & frame["price_rub"].gt(0)
    )
    train = eligible & dates.ge(pd.Timestamp(train_start)) & dates.lt(pd.Timestamp(test_start))
    test = eligible & dates.ge(pd.Timestamp(test_start)) & dates.le(pd.Timestamp(as_of))
    future = dates.gt(pd.Timestamp(as_of)) & ~frame["complex"]
    return tuple(frame.loc[mask].sort_values(["loading_date", "price_id"]).copy()
                 for mask in (train, test, future))


def make_features(frame: pd.DataFrame) -> pd.DataFrame:
    # An allowlist prevents new source/target columns from silently entering the model.
    features = frame[NUMERIC].astype(float).copy()
    for column in CATEGORICAL:
        features[column] = frame[column].fillna("Не указан").astype(str)
    dates = pd.to_datetime(frame["loading_date"])
    features["year"] = dates.dt.year
    features["month"] = dates.dt.month
    features["weekday"] = dates.dt.dayofweek
    features["day_of_year"] = dates.dt.dayofyear
    for name, values, period in (
        ("month", dates.dt.month - 1, 12),
        ("weekday", dates.dt.dayofweek, 7),
        ("day_of_year", dates.dt.dayofyear - 1, 365.25),
    ):
        features[f"{name}_sin"] = np.sin(2 * np.pi * values / period)
        features[f"{name}_cos"] = np.cos(2 * np.pi * values / period)
    return features
