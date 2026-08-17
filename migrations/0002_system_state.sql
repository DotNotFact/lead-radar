-- Фаза 2: простое key-value хранилище состояния системы (пауза сбора и т.п.)

CREATE TABLE IF NOT EXISTS system_state (
    key TEXT PRIMARY KEY,
    value TEXT
);
