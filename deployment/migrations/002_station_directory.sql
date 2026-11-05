BEGIN;

LOCK TABLE daily_index, live_index, forecast_index IN SHARE ROW EXCLUSIVE MODE;

CREATE TABLE indexed_stations (
    station_id text PRIMARY KEY CHECK (station_id ~ '^[0-9]+$'),
    name text NOT NULL CHECK (btrim(name) <> ''),
    county text NOT NULL,
    state text NOT NULL CHECK (state = 'WA'),
    latitude double precision NOT NULL CHECK (latitude BETWEEN 45 AND 50),
    longitude double precision NOT NULL CHECK (longitude BETWEEN -125 AND -116),
    location point GENERATED ALWAYS AS (point(longitude, latitude)) STORED
);

CREATE INDEX indexed_stations_location_idx ON indexed_stations USING gist (location);

CREATE FUNCTION station_identity(metadata jsonb) RETURNS jsonb
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
    SELECT jsonb_build_array(metadata->>'id', metadata->>'station', metadata->>'county',
                             metadata->>'state', metadata->>'latitude', metadata->>'longitude');
$$;

CREATE FUNCTION station_position(metadata jsonb) RETURNS point
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
    WITH coordinates AS (
        SELECT CASE WHEN pg_input_is_valid(metadata->>'latitude', 'double precision')
                    THEN (metadata->>'latitude')::double precision END AS latitude,
               CASE WHEN pg_input_is_valid(metadata->>'longitude', 'double precision')
                    THEN (metadata->>'longitude')::double precision END AS longitude
    )
    SELECT CASE WHEN lower(btrim(metadata->>'state')) IN ('wa', 'washington')
                    AND latitude BETWEEN 45 AND 50 AND abs(longitude) BETWEEN 116 AND 125
                THEN point(-abs(longitude), latitude) END
    FROM coordinates;
$$;

-- Used only for the initial backfill and updates to a particular station.
CREATE VIEW station_metadata_summary AS
WITH records AS (
    SELECT metadata FROM daily_index
    UNION ALL SELECT metadata FROM live_index
    UNION ALL SELECT metadata FROM forecast_index
), identities AS (
    SELECT metadata->>'id' AS station_id, btrim(metadata->>'station') AS name,
           btrim(COALESCE(metadata->>'county', '')) AS county,
           station_position(metadata) AS position
    FROM records
    WHERE metadata->>'id' ~ '^[0-9]+$' AND btrim(metadata->>'station') <> ''
)
SELECT station_id, min(name) AS name, min(county) AS county, 'WA'::text AS state,
       min(position[1]) AS latitude, min(position[0]) AS longitude
FROM identities
GROUP BY station_id
HAVING count(DISTINCT (lower(name), lower(county))) = 1
   AND count(DISTINCT (position[0], position[1])) FILTER (WHERE position IS NOT NULL) = 1;

CREATE FUNCTION refresh_indexed_station(station_key text) RETURNS void
LANGUAGE plpgsql AS $$
BEGIN
    DELETE FROM indexed_stations WHERE station_id = station_key;
    INSERT INTO indexed_stations (station_id, name, county, state, latitude, longitude)
        SELECT station_id, name, county, state, latitude, longitude
        FROM station_metadata_summary WHERE station_id = station_key;
END;
$$;

CREATE FUNCTION sync_indexed_station() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    old_id text;
    new_id text;
    station_key text;
    position point;
BEGIN
    IF TG_OP = 'UPDATE' AND station_identity(OLD.metadata) = station_identity(NEW.metadata) THEN
        RETURN NULL;
    END IF;
    IF TG_OP <> 'INSERT' THEN old_id := OLD.metadata->>'id'; END IF;
    IF TG_OP <> 'DELETE' THEN new_id := NEW.metadata->>'id'; END IF;

    FOR station_key IN SELECT DISTINCT key FROM unnest(ARRAY[old_id, new_id]) AS key
                       WHERE key ~ '^[0-9]+$' ORDER BY key LOOP
        PERFORM pg_advisory_xact_lock(hashtextextended(station_key, 0));
    END LOOP;

    IF old_id IS NOT NULL AND old_id IS DISTINCT FROM new_id THEN
        PERFORM refresh_indexed_station(old_id);
    END IF;
    IF new_id ~ '^[0-9]+$' THEN
        position := station_position(NEW.metadata);
        -- Repeated weather records with the same identity need no directory rebuild.
        IF EXISTS (
            SELECT 1 FROM indexed_stations
            WHERE station_id = new_id
              AND lower(name) = lower(btrim(NEW.metadata->>'station'))
              AND lower(county) = lower(btrim(COALESCE(NEW.metadata->>'county', '')))
              AND longitude = position[0] AND latitude = position[1]
        ) THEN RETURN NULL; END IF;
        PERFORM refresh_indexed_station(new_id);
    END IF;
    RETURN NULL;
END;
$$;

CREATE TRIGGER daily_station_directory
AFTER INSERT OR UPDATE OF metadata OR DELETE ON daily_index
FOR EACH ROW EXECUTE FUNCTION sync_indexed_station();

CREATE TRIGGER live_station_directory
AFTER INSERT OR UPDATE OF metadata OR DELETE ON live_index
FOR EACH ROW EXECUTE FUNCTION sync_indexed_station();

CREATE TRIGGER forecast_station_directory
AFTER INSERT OR UPDATE OF metadata OR DELETE ON forecast_index
FOR EACH ROW EXECUTE FUNCTION sync_indexed_station();

INSERT INTO indexed_stations (station_id, name, county, state, latitude, longitude)
    SELECT station_id, name, county, state, latitude, longitude FROM station_metadata_summary;

COMMIT;
