CREATE TEMP TABLE route_aggregates ON COMMIT DROP AS
WITH months AS (
    SELECT price_id, date_trunc('month', price_date)::date AS month, max(price_date) AS last_date
    FROM core.price_dates
    WHERE price_date <= %(as_of)s
    GROUP BY price_id, date_trunc('month', price_date)::date
)
SELECT d.month, p.loading_city_gcid, p.unloading_city_gcid, b.body_group, p.weight_category,
    percentile_cont(ARRAY[0.25, 0.5, 0.75]) WITHIN GROUP (ORDER BY p.price_rub) AS trip,
    avg(p.price_rub) AS avg_trip,
    percentile_cont(ARRAY[0.25, 0.5, 0.75])
        WITHIN GROUP (ORDER BY p.price_rub / nullif(p.distance, 0)) AS km,
    count(DISTINCT p.price_id) AS trips_count,
    count(DISTINCT p.organization_id) FILTER (WHERE p.price_type IN (3, 9)) AS carriers_count,
    stddev_samp(p.price_rub) / nullif(avg(p.price_rub), 0) AS cv_rate,
    max(d.last_date) AS last_price_date
FROM core.prices p
JOIN months d ON d.price_id = p.price_id
JOIN core.price_body_groups b ON b.price_id = p.price_id
WHERE p.is_fact AND p.price_type IN (1, 2, 3, 4, 5, 9)
  AND NOT p.complex AND NOT p.outlier_mark AND p.price_rub > 0 AND p.distance > 0
GROUP BY d.month, p.loading_city_gcid, p.unloading_city_gcid, b.body_group, p.weight_category;
CREATE UNIQUE INDEX ON route_aggregates
    (loading_city_gcid, unloading_city_gcid, body_group, weight_category, month);
ANALYZE route_aggregates;

DELETE FROM mart.market_corridor;
INSERT INTO mart.market_corridor
SELECT current.month, current.loading_city_gcid, current.unloading_city_gcid,
    current.body_group, current.weight_category,
    current.trip[1], current.trip[2], current.trip[3], current.avg_trip,
    current.km[1], current.km[2], current.km[3], current.trips_count, current.carriers_count,
    current.cv_rate,
    (current.trip[2] / nullif(previous.trip[2], 0) - 1) * 100,
    (current.trip[2] / nullif(year_ago.trip[2], 0) - 1) * 100,
    current.last_price_date,
    CASE WHEN current.trips_count >= 30 AND current.carriers_count >= 5
                   AND %(as_of)s::date - current.last_price_date <= 30 THEN 'HIGH'
         WHEN current.trips_count >= 10 THEN 'MEDIUM' ELSE 'LOW_DATA' END,
    %(as_of)s
FROM route_aggregates current
LEFT JOIN route_aggregates previous
    ON (previous.loading_city_gcid, previous.unloading_city_gcid, previous.body_group, previous.weight_category)
     = (current.loading_city_gcid, current.unloading_city_gcid, current.body_group, current.weight_category)
    AND previous.month = (current.month - interval '1 month')::date
LEFT JOIN route_aggregates year_ago
    ON (year_ago.loading_city_gcid, year_ago.unloading_city_gcid, year_ago.body_group, year_ago.weight_category)
     = (current.loading_city_gcid, current.unloading_city_gcid, current.body_group, current.weight_category)
    AND year_ago.month = (current.month - interval '1 year')::date;
