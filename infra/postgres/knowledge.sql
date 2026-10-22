-- Additive migration for an existing PostgreSQL 16 volume; run as DB administrator.
CREATE EXTENSION IF NOT EXISTS vector;
ALTER EXTENSION vector UPDATE;
CREATE SCHEMA IF NOT EXISTS knowledge AUTHORIZATION harness_app;
