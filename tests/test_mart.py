from datetime import date

import psycopg
import pytest

from etl.load import load_core, refresh_market

START, END, AS_OF = date(2025, 1, 1), date(2027, 1, 1), date(2026, 10, 26)


def test_multimonth_multibody_prices_do_not_multiply_within_a_cell(db, add_price):
    first = add_price(price=10000)
    add_price(price=20000, price_type=1, organization_id=99)
    add_price(price=30000, price_type=9, organization_id=2)
    add_price(price=999000, outlier_mark=True)
    add_price(price=999000, complex=True)
    add_price(price=999000, price_type=6, is_fact=False)
    db.execute("INSERT INTO raw.price_body_types(price_id,body_type_id) VALUES "
               "(%s,56),(%s,57),(%s,61),(%s,15)", (first,) * 4)
    db.execute("INSERT INTO raw.price_dates(price_id,price_date) VALUES "
               "(%s,'2026-10-20'),(%s,'2026-09-10'),(%s,'2026-11-10')", (first,) * 3)
    load_core(db, START, END)
    refresh_market(db, AS_OF)
    cells = db.execute("SELECT * FROM mart.market_corridor ORDER BY month,body_group").fetchall()
    assert len(cells) == 4
    tent = next(row for row in cells if row["month"] == date(2026, 10, 1) and row["body_group"] == "Тент")
    assert tent["trips_count"] == 3
    assert tent["carriers_count"] == 2
    assert (tent["p25_trip"], tent["median_trip"], tent["p75_trip"]) == (15000, 20000, 25000)
    assert (tent["p25_km"], tent["median_km"], tent["p75_km"]) == (150, 200, 250)
    assert float(tent["cv_rate"]) == pytest.approx(0.5)
    assert tent["last_price_date"] == date(2026, 10, 20)
    assert all(row["month"] <= AS_OF for row in cells)


def test_mom_and_yoy_use_calendar_months_not_previous_available_row(db, add_price):
    add_price(price=10000, loading_date=date(2025, 10, 10))
    add_price(price=15000, loading_date=date(2026, 8, 10))
    add_price(price=20000, loading_date=date(2026, 10, 10))
    load_core(db, START, END)
    refresh_market(db, AS_OF)
    october = db.execute("SELECT * FROM mart.market_corridor WHERE month='2026-10-01'").fetchone()
    assert october["mom_pct"] is None
    assert october["yoy_pct"] == pytest.approx(100)
    assert october["cv_rate"] is None
    add_price(price=16000, loading_date=date(2026, 9, 10))
    load_core(db, date(2026, 9, 1), date(2026, 10, 1))
    refresh_market(db, AS_OF)
    assert db.execute("SELECT mom_pct FROM mart.market_corridor WHERE month='2026-10-01'").fetchone()["mom_pct"] == pytest.approx(25)


def test_reliability_requires_volume_carriers_and_freshness(db, add_price):
    for day, count, carriers in [(date(2026, 10, 10), 30, 5), (date(2026, 9, 10), 30, 5),
                                 (date(2026, 8, 10), 10, 1), (date(2026, 7, 10), 9, 5)]:
        for i in range(count):
            add_price(loading_date=day, organization_id=i % carriers)
    load_core(db, START, END)
    refresh_market(db, AS_OF)
    levels = db.execute("SELECT reliability_level FROM mart.market_corridor ORDER BY month DESC").fetchall()
    assert [row["reliability_level"] for row in levels] == ["HIGH", "MEDIUM", "MEDIUM", "LOW_DATA"]


def test_failed_refresh_preserves_previous_mart(db, add_price):
    add_price()
    load_core(db, START, END)
    refresh_market(db, AS_OF)
    original = db.execute("SELECT * FROM mart.market_corridor").fetchall()
    db.execute("ALTER TABLE mart.market_corridor ADD CONSTRAINT reject_changes CHECK (trips_count=1)")
    try:
        add_price()
        load_core(db, START, END)
        with pytest.raises(psycopg.errors.CheckViolation):
            refresh_market(db, AS_OF)
        assert db.execute("SELECT * FROM mart.market_corridor").fetchall() == original
    finally:
        db.execute("ALTER TABLE mart.market_corridor DROP CONSTRAINT reject_changes")
