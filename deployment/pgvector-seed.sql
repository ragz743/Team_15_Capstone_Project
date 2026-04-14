-- SQL Script to Run when pgvector container is initialized

-- Switch to vectorstore, then set up schema
\c vectorstore

-- enable pgvector extension included in image
CREATE EXTENSION IF NOT EXISTS vector;

-- daily index table
CREATE TABLE IF NOT EXISTS daily_index (
    id BIGSERIAL PRIMARY KEY,   -- auto inc vector id
    embedding VECTOR(128),  -- vector width is hardcoded into _BaseEmbedding class
    metadata JSONB          -- arbitrary sized json metadata for storing filtering fields
);
