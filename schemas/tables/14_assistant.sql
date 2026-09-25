-- Root-only assistant persistence. All application and LangGraph data lives in
-- the existing project database. Apply explicitly; application startup does no DDL.
-- JSON payloads use validated LONGTEXT: MySQL native JSON can round nested doubles
-- during normalization. Preserve the exact original event/configuration text.
USE magic_auth;
SET NAMES utf8mb4 COLLATE utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS assistant_settings (
    owner VARCHAR(64) COLLATE utf8mb4_bin NOT NULL,
    data LONGTEXT NOT NULL,
    CONSTRAINT chk_assistant_settings_data_json CHECK (JSON_VALID(data)),
    PRIMARY KEY (owner)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS assistant_profiles (
    owner VARCHAR(64) COLLATE utf8mb4_bin NOT NULL,
    id VARCHAR(100) COLLATE utf8mb4_bin NOT NULL,
    data LONGTEXT NOT NULL,
    CONSTRAINT chk_assistant_profiles_data_json CHECK (JSON_VALID(data)),
    secret TEXT NULL COMMENT 'Opaque Fernet ciphertext; key remains in environment',
    PRIMARY KEY (owner, id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS assistant_sessions (
    id VARCHAR(100) COLLATE utf8mb4_bin NOT NULL,
    owner VARCHAR(64) COLLATE utf8mb4_bin NOT NULL,
    title VARCHAR(160) NOT NULL,
    profile_id VARCHAR(100) COLLATE utf8mb4_bin NULL,
    created_at DOUBLE NOT NULL,
    updated_at DOUBLE NOT NULL,
    PRIMARY KEY (id),
    INDEX idx_assistant_sessions_owner (owner, updated_at, id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS assistant_runs (
    id VARCHAR(100) COLLATE utf8mb4_bin NOT NULL,
    session_id VARCHAR(100) COLLATE utf8mb4_bin NOT NULL,
    owner VARCHAR(64) COLLATE utf8mb4_bin NOT NULL,
    request_id VARCHAR(100) COLLATE utf8mb4_bin NOT NULL,
    status VARCHAR(32) COLLATE utf8mb4_bin NOT NULL,
    data LONGTEXT NOT NULL,
    CONSTRAINT chk_assistant_runs_data_json CHECK (JSON_VALID(data)),
    worker VARCHAR(100) COLLATE utf8mb4_bin NULL,
    heartbeat DOUBLE NULL,
    created_at DOUBLE NOT NULL,
    updated_at DOUBLE NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uk_assistant_runs_request (owner, request_id),
    INDEX idx_assistant_runs_session (session_id, created_at, id),
    INDEX idx_assistant_runs_heartbeat (status, heartbeat),
    CONSTRAINT fk_assistant_runs_session FOREIGN KEY (session_id)
        REFERENCES assistant_sessions(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS assistant_messages (
    id VARCHAR(100) COLLATE utf8mb4_bin NOT NULL,
    session_id VARCHAR(100) COLLATE utf8mb4_bin NOT NULL,
    run_id VARCHAR(100) COLLATE utf8mb4_bin NULL,
    role VARCHAR(32) COLLATE utf8mb4_bin NOT NULL,
    content LONGTEXT NOT NULL,
    created_at DOUBLE NOT NULL,
    PRIMARY KEY (id),
    INDEX idx_assistant_messages_session (session_id, created_at, id),
    CONSTRAINT fk_assistant_messages_session FOREIGN KEY (session_id)
        REFERENCES assistant_sessions(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS assistant_events (
    seq BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    session_id VARCHAR(100) COLLATE utf8mb4_bin NOT NULL,
    kind VARCHAR(100) COLLATE utf8mb4_bin NOT NULL,
    data LONGTEXT NOT NULL,
    CONSTRAINT chk_assistant_events_data_json CHECK (JSON_VALID(data)),
    created_at DOUBLE NOT NULL,
    PRIMARY KEY (seq),
    INDEX idx_assistant_events_session (session_id, seq),
    CONSTRAINT fk_assistant_events_session FOREIGN KEY (session_id)
        REFERENCES assistant_sessions(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS assistant_requests (
    owner VARCHAR(64) COLLATE utf8mb4_bin NOT NULL,
    request_id VARCHAR(100) COLLATE utf8mb4_bin NOT NULL,
    run_id VARCHAR(100) COLLATE utf8mb4_bin NOT NULL,
    PRIMARY KEY (owner, request_id),
    CONSTRAINT fk_assistant_requests_run FOREIGN KEY (run_id)
        REFERENCES assistant_runs(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Store locks this singleton before run admission/resume and locks the session
-- row before enforcing one active run. This also coordinates explicit imports.
CREATE TABLE IF NOT EXISTS assistant_runtime_lock (
    id TINYINT NOT NULL,
    PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
INSERT IGNORE INTO assistant_runtime_lock (id) VALUES (1);

-- Namespace hashes bound index size while preserving the original namespace.
-- There is intentionally no FK from writes: pending writes may precede a checkpoint.
CREATE TABLE IF NOT EXISTS assistant_checkpoints (
    thread_id VARCHAR(255) COLLATE utf8mb4_bin NOT NULL,
    checkpoint_ns_hash BINARY(32) NOT NULL,
    checkpoint_ns TEXT COLLATE utf8mb4_bin NOT NULL,
    checkpoint_id VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    parent_checkpoint_id VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin NULL,
    checkpoint_type VARCHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    checkpoint LONGBLOB NOT NULL,
    metadata_type VARCHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    metadata LONGBLOB NOT NULL,
    PRIMARY KEY (thread_id, checkpoint_ns_hash, checkpoint_id),
    INDEX idx_assistant_checkpoint_thread (thread_id, checkpoint_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS assistant_checkpoint_writes (
    thread_id VARCHAR(255) COLLATE utf8mb4_bin NOT NULL,
    checkpoint_ns_hash BINARY(32) NOT NULL,
    checkpoint_ns TEXT COLLATE utf8mb4_bin NOT NULL,
    checkpoint_id VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    task_id VARCHAR(255) COLLATE utf8mb4_bin NOT NULL,
    idx INT NOT NULL,
    task_path TEXT COLLATE utf8mb4_bin NOT NULL,
    channel VARCHAR(255) COLLATE utf8mb4_bin NOT NULL,
    type VARCHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    value LONGBLOB NOT NULL,
    PRIMARY KEY (thread_id, checkpoint_ns_hash, checkpoint_id, task_id, idx)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
