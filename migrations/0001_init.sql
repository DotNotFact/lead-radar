-- Фаза 0: начальная схема БД.

CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- источники и их здоровье
CREATE TABLE IF NOT EXISTS sources (
    id TEXT PRIMARY KEY,
    tier INTEGER NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    last_ok_at TIMESTAMP,
    last_error TEXT,
    consecutive_failures INTEGER NOT NULL DEFAULT 0
);

-- сырые лиды
CREATE TABLE IF NOT EXISTS leads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id TEXT NOT NULL REFERENCES sources(id),
    external_id TEXT NOT NULL,
    url TEXT,
    title TEXT,
    text TEXT,
    published_at TIMESTAMP,
    collected_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    budget_min INTEGER,
    budget_max INTEGER,
    budget_currency TEXT,
    budget_confidence REAL,
    stack_tags TEXT,           -- JSON-массив
    content_hash TEXT,
    duplicate_of INTEGER REFERENCES leads(id),
    score REAL,
    author_handle TEXT,        -- вырезается при экспорте
    raw_meta TEXT,              -- JSON
    UNIQUE(source_id, external_id)
);

-- воронка: заполняется владельцем через бота
CREATE TABLE IF NOT EXISTS lead_outcomes (
    lead_id INTEGER PRIMARY KEY REFERENCES leads(id),
    notified_at TIMESTAMP,
    replied_at TIMESTAMP,
    outcome TEXT,               -- ignored | replied | negotiating | won | lost
    amount INTEGER,
    notes TEXT
);

-- очередь действий владельца
CREATE TABLE IF NOT EXISTS actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    description TEXT,
    priority INTEGER NOT NULL,  -- 1 = критично
    due_date DATE,
    recurrence TEXT,
    status TEXT NOT NULL DEFAULT 'pending',  -- pending | done | snoozed | dropped
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP,
    snooze_count INTEGER NOT NULL DEFAULT 0,
    expected_value TEXT
);

CREATE INDEX IF NOT EXISTS idx_leads_published_at ON leads(published_at);
CREATE INDEX IF NOT EXISTS idx_leads_source_published ON leads(source_id, published_at);
CREATE INDEX IF NOT EXISTS idx_leads_content_hash ON leads(content_hash);
CREATE INDEX IF NOT EXISTS idx_actions_status_due ON actions(status, due_date);
