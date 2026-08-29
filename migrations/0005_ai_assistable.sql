-- Метка "лид можно закрыть с помощью ИИ" для /ai_leads и значка 🤖 в уведомлении.
ALTER TABLE leads ADD COLUMN ai_assistable INTEGER NOT NULL DEFAULT 0;

CREATE INDEX IF NOT EXISTS idx_leads_ai_assistable ON leads(ai_assistable);
