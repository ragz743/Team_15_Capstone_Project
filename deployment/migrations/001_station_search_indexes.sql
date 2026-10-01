CREATE INDEX IF NOT EXISTS live_index_station_day_idx
    ON live_index ((metadata->>'id'), (left(metadata->>'timestamp', 10)));
CREATE INDEX IF NOT EXISTS forecast_index_station_idx
    ON forecast_index ((metadata->>'id'));
