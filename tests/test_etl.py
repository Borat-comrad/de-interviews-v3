from datetime import date
from decimal import Decimal

import pytest

from etl.load import load_core, refresh_market

START, END, AS_OF = date(2025, 1, 1), date(2027, 1, 1), date(2026, 10, 26)


@pytest.mark.parametrize("change,reason", [
    ({"price": 0}, "INVALID_PRICE"),
    ({"price": -10}, "INVALID_PRICE"),
    ({"price": 1000}, "RUB_PRICE_TOO_LOW"),
    ({"distance": 0}, "INVALID_DISTANCE"),
    ({"total_weight": -1}, "INVALID_WEIGHT"),
    ({"total_volume": -1}, "INVALID_VOLUME"),
    ({"loading_city_gcid": 999}, "UNKNOWN_ORIGIN"),
    ({"unloading_city_gcid": 999}, "UNKNOWN_DESTINATION"),
    ({"currency_code": "840"}, "MISSING_FX_RATE"),
    ({"currency_code": "999"}, "UNKNOWN_CURRENCY"),
    ({"price": float("nan")}, "INVALID_PRICE"),
    ({"distance": float("inf")}, "INVALID_DISTANCE"),
])
def test_invalid_rows_are_quarantined(db, add_price, change, reason):
    price_id = add_price(**change)
    counts = load_core(db, START, END)
    assert counts["loaded"] == 0 and counts["quarantined"] == 1
    rejected = db.execute("SELECT * FROM core.dq_quarantine_prices").fetchone()
    assert rejected["price_id"] == price_id
    assert reason in rejected["reasons"]


@pytest.mark.parametrize("weight,category", [
    (0, "OTH"), (0.45, "L5T"), (2.45, "5T"), (4.95, "10T"),
    (9.95, "FTL"), (10, "FTL"), (29.95, "G20T"), (30, "G20T"),
])
def test_rounded_weight_boundaries(db, add_price, weight, category):
    add_price(total_weight=weight, total_volume=120)
    load_core(db, START, END)
    result = db.execute("SELECT weight_category,volume_category FROM core.prices").fetchone()
    assert result == {"weight_category": category, "volume_category": "FTL"}


def test_exact_fx_city_dedup_and_body_fallback(db, add_price):
    db.execute("INSERT INTO raw.exchange_rates(num_code,value,setting_date) VALUES "
               "('840',90,'2026-10-01'),('840',100,'2026-10-10')")
    price_id = add_price(price=500, currency_code="840", nearest_rate_date=date(2026, 10, 1),
                         body_type=1, unloading_city_gcid=1, total_volume=0)
    load_core(db, START, END)
    payment = db.execute("SELECT * FROM core.prices").fetchone()
    assert payment["price_rub"] == Decimal(45000)
    assert payment["volume_category"] == "OTH"
    assert db.execute("SELECT count(*) AS n FROM core.cities").fetchone()["n"] == 2
    assert db.execute("SELECT region FROM core.cities WHERE gc_id=1").fetchone()["region"] == "Татарстан"
    assert db.execute("SELECT body_group FROM core.price_body_groups WHERE price_id=%s", (price_id,)
                      ).fetchone()["body_group"] == "Борт"


def test_reloads_replace_invalid_deleted_and_moved_records(db, add_price):
    first = add_price()
    corrected = add_price(price=0)
    moved = add_price(loading_date=date(2026, 9, 1))
    load_core(db, START, END)
    refresh_market(db, AS_OF)
    before = db.execute("SELECT * FROM mart.market_corridor ORDER BY month").fetchall()
    load_core(db, START, END)
    refresh_market(db, AS_OF)
    assert db.execute("SELECT * FROM mart.market_corridor ORDER BY month").fetchall() == before
    db.execute("UPDATE raw.prices SET price=20000 WHERE id=%s", (corrected,))
    db.execute("DELETE FROM raw.prices WHERE id=%s", (first,))
    db.execute("UPDATE raw.prices SET loading_date='2026-10-20' WHERE id=%s", (moved,))
    load_core(db, date(2026, 10, 1), date(2026, 11, 1))
    assert db.execute("SELECT count(*) AS n FROM core.dq_quarantine_prices").fetchone()["n"] == 0
    rows = db.execute("SELECT price_id,loading_date FROM core.prices ORDER BY price_id").fetchall()
    assert [row["price_id"] for row in rows] == [corrected, moved]
    assert rows[1]["loading_date"] == date(2026, 10, 20)


def test_missing_exact_rate_does_not_use_another_day(db, add_price):
    db.execute("INSERT INTO raw.exchange_rates(num_code,value,setting_date) VALUES ('978',100,'2026-10-01')")
    add_price(currency_code="978", nearest_rate_date=date(2026, 10, 2))
    counts = load_core(db, START, END)
    assert counts["reasons"] == {"MISSING_FX_RATE": 1}
    db.execute("INSERT INTO raw.exchange_rates(num_code,value,setting_date) VALUES ('978',110,'2026-10-02')")
    assert load_core(db, START, END)["loaded"] == 1
    assert db.execute("SELECT price_rub FROM core.prices").fetchone()["price_rub"] == Decimal(1100000)
    assert db.execute("SELECT count(*) AS n FROM core.dq_quarantine_prices").fetchone()["n"] == 0


def test_missing_body_and_existing_categories_are_preserved(db, add_price):
    add_price(body_type=None, total_weight=35, weight_category="FTL", total_volume=120.1)
    load_core(db, START, END)
    assert db.execute("SELECT body_group FROM core.price_body_groups").fetchone()["body_group"] == "Не указан"
    assert db.execute("SELECT weight_category,volume_category FROM core.prices").fetchone() == {
        "weight_category": "FTL", "volume_category": "OTH",
    }
