WITH bodies AS (
    SELECT price_id, string_agg(body_group, ' + ' ORDER BY body_group COLLATE "C") AS body_group
    FROM core.price_body_groups GROUP BY price_id
)
SELECT p.price_id, p.loading_date, p.loading_city_gcid, p.unloading_city_gcid,
    p.distance, p.total_weight, p.total_volume, p.weight_category, p.volume_category,
    p.price_rub::double precision AS price_rub,
    p.is_fact, p.price_type, p.complex, p.outlier_mark,
    origin.region AS origin_region, destination.region AS destination_region,
    origin.latitude AS origin_latitude, origin.longitude AS origin_longitude,
    destination.latitude AS destination_latitude, destination.longitude AS destination_longitude,
    b.body_group
FROM core.prices p
JOIN core.cities origin ON origin.gc_id = p.loading_city_gcid
JOIN core.cities destination ON destination.gc_id = p.unloading_city_gcid
JOIN bodies b ON b.price_id = p.price_id
WHERE p.loading_date >= %(train_start)s AND NOT p.complex
ORDER BY p.loading_date, p.price_id;
