CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS checks (
    check_id VARCHAR(64) PRIMARY KEY,
    caption TEXT,
    phash VARCHAR(16),
    card_data JSONB NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_checks_phash ON checks (phash) WHERE phash IS NOT NULL;

CREATE TABLE IF NOT EXISTS claim_embeddings (
    id SERIAL PRIMARY KEY,
    check_id VARCHAR(64) NOT NULL REFERENCES checks(check_id) ON DELETE CASCADE,
    claim_text TEXT NOT NULL,
    embedding VECTOR(384) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_claim_embeddings_hnsw 
ON claim_embeddings USING hnsw (embedding vector_cosine_ops);