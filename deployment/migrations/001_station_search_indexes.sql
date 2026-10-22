DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_tables WHERE schemaname = current_schema() AND tablename = 'live_index') THEN
        CREATE INDEX IF NOT EXISTS live_index_station_day_idx
            ON live_index ((metadata->>'id'), (left(metadata->>'timestamp', 10)));
    END IF;
    IF EXISTS (SELECT 1 FROM pg_tables WHERE schemaname = current_schema() AND tablename = 'forecast_index') THEN
        CREATE INDEX IF NOT EXISTS forecast_index_station_idx ON forecast_index ((metadata->>'id'));
    END IF;
END $$;
