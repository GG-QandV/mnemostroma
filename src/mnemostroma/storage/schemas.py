# SPDX-License-Identifier: FSL-1.1-MIT
"""SQL table schemas for Mnemostroma."""

SCHEMA_SESSIONS = """
CREATE TABLE IF NOT EXISTS sessions (
    session_id              TEXT PRIMARY KEY,
    created_at              INTEGER,
    updated_at              INTEGER,
    importance              TEXT,
    age_signal              TEXT,
    tags                    TEXT,    -- JSON array
    brief                   TEXT,    -- max 50 symbols
    why_log                 TEXT,
    intent                  TEXT,
    conflict                INTEGER DEFAULT 0,
    content_full            TEXT,    -- optional full log
    session_type            TEXT,    -- context / content / research
    use_count               INTEGER DEFAULT 0,
    deep_use_count          INTEGER DEFAULT 0,
    last_use_ts             INTEGER,
    implicit_score          REAL    DEFAULT 0.5,
    resolution              REAL    DEFAULT 1.0,

    -- v1.3/v1.4 columns
    urgency                 TEXT    DEFAULT 'none',
    deadline_ts             INTEGER,
    urgency_active          INTEGER DEFAULT 0,
    urgency_expired         INTEGER DEFAULT 0,
    bare_entity             INTEGER DEFAULT 0,
    embedding_model_version TEXT    DEFAULT 'embeddinggemma-300m-int8-v1',
    embedding               BLOB    -- float16 768d binary
);
"""

SCHEMA_ANCHORS = """
CREATE TABLE IF NOT EXISTS anchors (
    anchor_id   TEXT PRIMARY KEY,
    session_id  TEXT REFERENCES sessions(session_id),
    type        TEXT,   -- decision/phone/address/person/number/date
    value       TEXT,
    context_tag TEXT,
    importance  TEXT,
    created_at  INTEGER
);
"""

SCHEMA_PRECISION = """
CREATE TABLE IF NOT EXISTS precision_log (
    precision_id  TEXT PRIMARY KEY,
    session_id    TEXT REFERENCES sessions(session_id),
    type          TEXT,   -- link/concept/quote/formula/data
    value         TEXT,   -- verbatim content
    context_tag   TEXT,
    importance    TEXT,
    created_at    INTEGER
);
"""

SCHEMA_CONTENT_BLOCKS = """
CREATE TABLE IF NOT EXISTS content_blocks (
    content_id   TEXT PRIMARY KEY,
    session_id   TEXT REFERENCES sessions(session_id),
    content_type TEXT,   -- function/class/chapter/scene/config
    parent_id    TEXT,
    project_id   TEXT,
    status       TEXT    -- active/completed/archived
);
"""

SCHEMA_CONTENT_VERSIONS = """
CREATE TABLE IF NOT EXISTS content_versions (
    content_id      TEXT REFERENCES content_blocks(content_id),
    version         INTEGER,
    content_hash    TEXT,
    content_raw     BLOB,     -- lz4 compressed
    content_diff    TEXT,
    content_tags    TEXT,     -- JSON array
    tags_verified   INTEGER DEFAULT 0,
    why_changed     TEXT,
    status          TEXT,     -- draft/active/rejected/archived
    rejected_reason TEXT,
    embedding       BLOB,     -- float16 768d binary
    embedding_model_version TEXT DEFAULT 'bge-m3-int8-v1',
    created_at      INTEGER,
    PRIMARY KEY (content_id, version)
);
"""

SCHEMA_MODEL_REGISTRY = """
CREATE TABLE IF NOT EXISTS embedding_model_registry (
    model_key        TEXT PRIMARY KEY,   -- 'embeddinggemma-300m-int8-v1'
    model_name       TEXT,               -- human-readable
    dim              INTEGER,            -- 768
    quantization     TEXT,               -- 'int8'
    registered_at    INTEGER,            -- unix timestamp
    is_current       INTEGER DEFAULT 0   -- 1 = текущая активная модель
);
"""

INDICES = [
    "CREATE INDEX IF NOT EXISTS idx_sessions_date ON sessions(created_at);",
    "CREATE INDEX IF NOT EXISTS idx_sessions_importance ON sessions(importance);",
    "CREATE INDEX IF NOT EXISTS idx_sessions_age ON sessions(age_signal);",
    "CREATE INDEX IF NOT EXISTS idx_sessions_type ON sessions(session_type);",
    "CREATE INDEX IF NOT EXISTS idx_sessions_urgency ON sessions(urgency_active, deadline_ts) WHERE urgency_active = 1;",
    "CREATE INDEX IF NOT EXISTS idx_sessions_principle ON sessions(importance) WHERE importance = 'principle';",
    "CREATE INDEX IF NOT EXISTS idx_anchors_type ON anchors(type);",
    "CREATE INDEX IF NOT EXISTS idx_anchors_session ON anchors(session_id);",
    "CREATE INDEX IF NOT EXISTS idx_precision_session ON precision_log(session_id);",
    "CREATE INDEX IF NOT EXISTS idx_cv_status ON content_versions(status);",
    "CREATE INDEX IF NOT EXISTS idx_cv_session ON content_versions(content_id);"
]

ALL_SCHEMAS = [
    SCHEMA_SESSIONS,
    SCHEMA_ANCHORS,
    SCHEMA_PRECISION,
    SCHEMA_CONTENT_BLOCKS,
    SCHEMA_CONTENT_VERSIONS,
    SCHEMA_MODEL_REGISTRY
] + INDICES
