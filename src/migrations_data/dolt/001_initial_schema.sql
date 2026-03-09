-- HydraFlow Dolt initial schema
-- All tables used by the repository layer.

CREATE TABLE IF NOT EXISTS issues (
    issue_number INT NOT NULL,
    field VARCHAR(64) NOT NULL,
    value TEXT,
    PRIMARY KEY (issue_number, field)
);

CREATE TABLE IF NOT EXISTS prs (
    pr_number INT PRIMARY KEY,
    status VARCHAR(32)
);

CREATE TABLE IF NOT EXISTS baseline_audit (
    id INT AUTO_INCREMENT PRIMARY KEY,
    issue_number INT,
    change_type VARCHAR(32),
    reason TEXT,
    pr_number INT,
    changed_files TEXT,
    approver VARCHAR(128),
    commit_sha VARCHAR(64),
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX(issue_number)
);

CREATE TABLE IF NOT EXISTS lifetime_stats (
    id INT PRIMARY KEY,
    issues_completed INT DEFAULT 0,
    prs_merged INT DEFAULT 0,
    issues_created INT DEFAULT 0,
    total_quality_fix_rounds INT DEFAULT 0,
    total_ci_fix_rounds INT DEFAULT 0,
    total_hitl_escalations INT DEFAULT 0,
    total_review_request_changes INT DEFAULT 0,
    total_review_approvals INT DEFAULT 0,
    total_reviewer_fixes INT DEFAULT 0,
    total_implementation_seconds DOUBLE DEFAULT 0.0,
    total_review_seconds DOUBLE DEFAULT 0.0,
    merge_durations TEXT,
    retries_per_stage TEXT,
    total_outcomes_merged INT DEFAULT 0,
    total_outcomes_already_satisfied INT DEFAULT 0,
    total_outcomes_hitl_closed INT DEFAULT 0,
    total_outcomes_hitl_skipped INT DEFAULT 0,
    total_outcomes_failed INT DEFAULT 0,
    total_outcomes_manual_close INT DEFAULT 0,
    total_outcomes_hitl_approved INT DEFAULT 0,
    fired_thresholds TEXT
);

CREATE TABLE IF NOT EXISTS session_counters (
    id INT PRIMARY KEY,
    triaged INT DEFAULT 0,
    planned INT DEFAULT 0,
    implemented INT DEFAULT 0,
    reviewed INT DEFAULT 0,
    merged INT DEFAULT 0,
    session_start VARCHAR(64) DEFAULT ''
);

CREATE TABLE IF NOT EXISTS active_crate (
    id INT PRIMARY KEY,
    crate_number INT
);

CREATE TABLE IF NOT EXISTS bg_workers (
    name VARCHAR(128) PRIMARY KEY,
    state_json TEXT,
    heartbeat_json TEXT,
    enabled TINYINT DEFAULT 1,
    interval_seconds INT
);

CREATE TABLE IF NOT EXISTS events (
    id INT AUTO_INCREMENT PRIMARY KEY,
    event_type VARCHAR(64),
    data_json TEXT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX(timestamp)
);

CREATE TABLE IF NOT EXISTS runs (
    run_id VARCHAR(128) PRIMARY KEY,
    issue_number INT,
    started_at DATETIME,
    ended_at DATETIME,
    manifest_json TEXT,
    INDEX(issue_number)
);

CREATE TABLE IF NOT EXISTS sessions (
    session_id VARCHAR(128) PRIMARY KEY,
    data_json TEXT,
    started_at DATETIME,
    ended_at DATETIME
);

CREATE TABLE IF NOT EXISTS context_cache (
    cache_key VARCHAR(256) PRIMARY KEY,
    value TEXT,
    source_mtime DOUBLE
);

CREATE TABLE IF NOT EXISTS metrics_snapshots (
    id INT AUTO_INCREMENT PRIMARY KEY,
    snapshot_json TEXT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS review_records (
    id INT AUTO_INCREMENT PRIMARY KEY,
    data_json TEXT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS harness_failures (
    id INT AUTO_INCREMENT PRIMARY KEY,
    data_json TEXT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS retrospectives (
    id INT AUTO_INCREMENT PRIMARY KEY,
    data_json TEXT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS curated_manifest (
    file_path VARCHAR(512) PRIMARY KEY,
    data_json TEXT
);

CREATE TABLE IF NOT EXISTS inferences (
    id INT AUTO_INCREMENT PRIMARY KEY,
    data_json TEXT,
    source VARCHAR(64),
    session_id VARCHAR(128),
    pr_number INT,
    issue_number INT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX(timestamp),
    INDEX(session_id),
    INDEX(pr_number),
    INDEX(issue_number),
    INDEX(source)
);

CREATE TABLE IF NOT EXISTS inference_stats (
    stat_key VARCHAR(128) PRIMARY KEY,
    data_json TEXT
);

CREATE TABLE IF NOT EXISTS model_pricing (
    model_id VARCHAR(128) PRIMARY KEY,
    input_cost_per_million DOUBLE,
    output_cost_per_million DOUBLE,
    cache_write_cost_per_million DOUBLE DEFAULT 0,
    cache_read_cost_per_million DOUBLE DEFAULT 0,
    aliases TEXT
);

CREATE TABLE IF NOT EXISTS epic_states (
    epic_id VARCHAR(128) PRIMARY KEY,
    state_json TEXT
);

CREATE TABLE IF NOT EXISTS releases (
    release_id VARCHAR(128) PRIMARY KEY,
    data_json TEXT
);

CREATE TABLE IF NOT EXISTS pending_reports (
    id INT AUTO_INCREMENT PRIMARY KEY,
    data_json TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS active_issues (
    issue_number INT PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS memory_state (
    id INT PRIMARY KEY,
    issue_ids TEXT,
    digest_hash VARCHAR(128),
    last_synced VARCHAR(64)
);

CREATE TABLE IF NOT EXISTS manifest_state (
    id INT PRIMARY KEY,
    hash VARCHAR(128),
    last_updated VARCHAR(64),
    issue_number INT,
    snapshot_hash VARCHAR(128)
);

CREATE TABLE IF NOT EXISTS metrics_state (
    id INT PRIMARY KEY,
    issue_number INT,
    last_snapshot_hash VARCHAR(128),
    last_synced VARCHAR(64)
);

CREATE TABLE IF NOT EXISTS learnings (
    id INT AUTO_INCREMENT PRIMARY KEY,
    data_json TEXT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS troubleshooting_patterns (
    id INT AUTO_INCREMENT PRIMARY KEY,
    language VARCHAR(64),
    pattern_name VARCHAR(256),
    data_json TEXT,
    frequency INT DEFAULT 1,
    UNIQUE KEY (language, pattern_name)
);

CREATE TABLE IF NOT EXISTS proposed_categories (
    domain VARCHAR(64) NOT NULL,
    category VARCHAR(256) NOT NULL,
    proposed_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (domain, category)
);
