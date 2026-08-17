# Запускает Lead Radar (планировщик hh.ru/Kwork/RSS + Telegram catch-up/realtime + бот) в
# текущем окне PowerShell. Для автозапуска в фоне при входе в систему используйте
# scripts\install_windows_task.ps1.

$ErrorActionPreference = "Stop"
$ProjectRoot = $PSScriptRoot
$PythonExe = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$EnvFile = Join-Path $ProjectRoot ".env"

if (-not (Test-Path $PythonExe)) {
    Write-Error "venv не найден. Сначала выполните .\setup.ps1"
    exit 1
}
if (-not (Test-Path $EnvFile)) {
    Write-Error ".env не найден. Скопируйте .env.example в .env и заполните значения (см. README.md)."
    exit 1
}

Set-Location $ProjectRoot
& $PythonExe -m src.main
