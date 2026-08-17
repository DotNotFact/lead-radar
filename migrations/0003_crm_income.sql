-- По запросу владельца: простой CRM (компании) + учёт дохода.
-- Напоминания о касаниях компаний переиспользуют существующую очередь actions
-- (бриф, эскалация, /snooze/done уже умеют с ней работать) - отдельного движка нет.

CREATE TABLE IF NOT EXISTS companies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    contact_person TEXT,
    contact_info TEXT,
    status TEXT NOT NULL DEFAULT 'new',  -- new | contacted | negotiating | won | lost | on_hold
    result TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

ALTER TABLE actions ADD COLUMN company_id INTEGER REFERENCES companies(id);

CREATE TABLE IF NOT EXISTS payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    amount INTEGER NOT NULL,
    currency TEXT NOT NULL DEFAULT 'RUB',
    received_at DATE NOT NULL,
    lead_id INTEGER REFERENCES leads(id),
    company_id INTEGER REFERENCES companies(id),
    note TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_companies_status ON companies(status);
CREATE INDEX IF NOT EXISTS idx_actions_company_id ON actions(company_id);
CREATE INDEX IF NOT EXISTS idx_payments_received_at ON payments(received_at);
