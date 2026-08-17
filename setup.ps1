# Первоначальная настройка Lead Radar: виртуальное окружение, зависимости, .env, миграции БД.
# Запускать один раз из корня проекта:  .\setup.ps1

$ErrorActionPreference = "Stop"
$ProjectRoot = $PSScriptRoot
$VenvPath = Join-Path $ProjectRoot ".venv"
$PythonExe = Join-Path $VenvPath "Scripts\python.exe"

if (-not (Test-Path $VenvPath)) {
    Write-Host "Создаю виртуальное окружение (.venv)..."
    python -m venv $VenvPath
}

Write-Host "Устанавливаю зависимости..."
& $PythonExe -m pip install --upgrade pip -q
& $PythonExe -m pip install -e "$ProjectRoot[dev]" -q

$EnvFile = Join-Path $ProjectRoot ".env"
$EnvExample = Join-Path $ProjectRoot ".env.example"
if (-not (Test-Path $EnvFile)) {
    Copy-Item $EnvExample $EnvFile
    Write-Host ""
    Write-Host "Создан .env из .env.example - заполните его перед запуском (см. README.md)."
} else {
    Write-Host ".env уже существует, не трогаю."
}

Write-Host "Применяю миграции БД..."
& $PythonExe -c "import asyncio; from src.core.config import get_settings; from src.core.db import apply_migrations; s = get_settings(); asyncio.run(apply_migrations(s.db_path, s.migrations_dir))"

Write-Host ""
Write-Host "Готово. Дальше:"
Write-Host "  1. Заполните .env (BOT_TOKEN уже должен быть на месте; остальное - по README.md)"
Write-Host "  2. Настройте профиль бота:  python -m scripts.setup_bot"
Write-Host "  3. Запустите:  .\run.ps1"
