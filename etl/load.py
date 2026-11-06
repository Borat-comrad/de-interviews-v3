from datetime import date

from etl.db import execute_file


def load_core(connection, start_date: date, end_date: date) -> dict:
    if start_date >= end_date:
        raise ValueError("start_date must be before end_date (exclusive)")
    with connection.transaction():
        connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        execute_file(connection, "load_core.sql", {"start_date": start_date, "end_date": end_date})
        counts = connection.execute(
            "SELECT count(*) AS read, count(*) FILTER (WHERE cardinality(reasons)=0) AS loaded, "
            "count(*) FILTER (WHERE cardinality(reasons)>0) AS quarantined FROM stage_prices"
        ).fetchone()
        reasons = connection.execute(
            "SELECT reason, count(*) AS count FROM stage_prices, unnest(reasons) reason GROUP BY reason"
        ).fetchall()
    return {**counts, "reasons": {row["reason"]: row["count"] for row in reasons}}


def refresh_market(connection, as_of: date) -> int:
    with connection.transaction():
        execute_file(connection, "market_corridor.sql", {"as_of": as_of})
        count = connection.execute("SELECT count(*) AS n FROM mart.market_corridor").fetchone()["n"]
    return count
