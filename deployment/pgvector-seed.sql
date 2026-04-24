-- SQL Script to Run when pgvector container is initialized

-- Switch to vectorstore, then set up schema
\c vectorstore

-- enable pgvector extension included in image
CREATE EXTENSION IF NOT EXISTS vector;

-- daily index table
CREATE TABLE IF NOT EXISTS daily_index (
    id BIGSERIAL PRIMARY KEY,   -- auto inc vector id
    embedding VECTOR(768),  -- vector width is hardcoded into _BaseEmbedding class
    document TEXT,          -- document text to be retrieved during search
    metadata JSONB          -- arbitrary sized json metadata for storing filtering fields
);

-- live index table
-- Will hold only the most up to date information
-- for each station (entry with maximum timestamp)
CREATE TABLE IF NOT EXISTS live_index (
    id BIGSERIAL PRIMARY KEY, -- station UNIT_ID == vector id
    embedding VECTOR(768),  -- vector width is hardcoded into _BaseEmbedding class
    document TEXT,          -- document text to be retrieved during search
    metadata JSONB          -- arbitrary sized json metadata for storing filtering fields
);

-- forecast index table
-- will hold on the most up to date forecast information
-- forecasts cover X number of days into the future with an
-- hourly precision, always keep the newest set of forecasts
-- for each station
CREATE TABLE IF NOT EXISTS forecast_index (
    id BIGSERIAL PRIMARY KEY, -- station UNIT_ID == vector id
    embedding VECTOR(768),  -- vector width is hardcoded into _BaseEmbedding class
    document TEXT,          -- document text to be retrieved during search
    metadata JSONB          -- arbitrary sized json metadata for storing filtering fields
);
