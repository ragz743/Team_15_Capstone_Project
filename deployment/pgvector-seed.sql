-- SQL Script to Run when pgvector container is initialized

CREATE EXTENSION vector; -- enable pgvector extension included in image

-- dummy table to make sure pgvector ext works...
CREATE TABLE items (id bigserial PRIMARY KEY, embedding vector(3));
