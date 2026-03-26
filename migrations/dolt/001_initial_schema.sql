-- Dolt schema for HydraFlow state persistence.
-- Applied automatically by DoltBackend._ensure_repo().

CREATE TABLE IF NOT EXISTS state (
    id INT PRIMARY KEY DEFAULT 1,
    data JSON NOT NULL,
    updated_at DATETIME NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    session_id VARCHAR(255) PRIMARY KEY,
    repo VARCHAR(255) NOT NULL,
    data JSON NOT NULL,
    started_at DATETIME NOT NULL,
    ended_at DATETIME,
    status VARCHAR(32) NOT NULL DEFAULT 'active'
);

-- Dedup tracking (replaces proposed_categories.json, filed_patterns.json, adr_sources.json)
CREATE TABLE IF NOT EXISTS dedup_sets (
    set_name VARCHAR(64) NOT NULL,
    value VARCHAR(512) NOT NULL,
    PRIMARY KEY (set_name, value)
);
