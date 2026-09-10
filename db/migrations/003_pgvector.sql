-- ============================================================================
-- Elastic Web — 003_pgvector.sql
-- Phase A1: pgvector support.
--
-- Enables the pgvector extension IF available, and adds a vector column +
-- index to the capabilities table for vector retrieval. Preserves the JSONB
-- fallback: if pgvector is not installed, the migration is a no-op and the
-- existing JSONB embedding storage continues to work.
--
-- Idempotent (CREATE EXTENSION IF NOT EXISTS / ADD COLUMN IF NOT EXISTS).
-- ============================================================================

-- Enable pgvector if available (tolerant — does not fail if unavailable).
DO $$
BEGIN
    CREATE EXTENSION IF NOT EXISTS vector;
EXCEPTION
    WHEN OTHERS THEN
        RAISE NOTICE 'pgvector extension not available (%): %', SQLSTATE, SQLERRM;
        RAISE NOTICE 'Embeddings will continue to use JSONB arrays (fallback).';
END
$$;

-- Add a vector column to capabilities for dense embeddings (if pgvector is
-- present). The column is nullable so rows without embeddings are fine.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector') THEN
        ALTER TABLE capabilities ADD COLUMN IF NOT EXISTS embedding vector(384);
    END IF;
EXCEPTION
    WHEN OTHERS THEN
        RAISE NOTICE 'Could not add embedding column (%): %', SQLSTATE, SQLERRM;
END
$$;

-- Add a vector index for fast similarity search (HNSW, if pgvector present).
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector') THEN
        CREATE INDEX IF NOT EXISTS idx_capabilities_embedding
            ON capabilities USING hnsw (embedding vector_cosine_ops);
    END IF;
EXCEPTION
    WHEN OTHERS THEN
        RAISE NOTICE 'Could not create vector index (%): %', SQLSTATE, SQLERRM;
END
$$;
