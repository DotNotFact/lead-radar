-- По запросу владельца: отслеживание собственных откликов на hh.ru и их статусов.
-- Требует OAuth-токен от личного аккаунта владельца - публичный API вакансий (Фаза 1) для
-- этого не подходит, у чужих откликов другой уровень доступа.

CREATE TABLE IF NOT EXISTS hh_applications (
    id TEXT PRIMARY KEY,           -- id отклика/переговоров от hh.ru
    vacancy_id TEXT,
    vacancy_title TEXT,
    vacancy_url TEXT,
    state TEXT,                    -- response | invitation | discard | ... (по данным hh.ru)
    hh_created_at TIMESTAMP,
    hh_updated_at TIMESTAMP,
    last_synced_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_notified_state TEXT
);

CREATE INDEX IF NOT EXISTS idx_hh_applications_state ON hh_applications(state);
