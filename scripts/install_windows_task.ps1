# Регистрирует Lead Radar как задачу планировщика Windows: старт при входе в систему,
# автоматический перезапуск при сбое. Запускать один раз из PowerShell в этой директории
# (права администратора обычно не нужны - задача создаётся для текущего пользователя).
#
# Использование:  .\scripts\install_windows_task.ps1
# Удаление:        Unregister-ScheduledTask -TaskName LeadRadar -Confirm:$false

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$PythonExe = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$TaskName = "LeadRadar"

if (-not (Test-Path $PythonExe)) {
    Write-Error "Не найден venv: $PythonExe. Сначала создайте venv и установите зависимости (pip install -e `".[dev]`"), см. CLAUDE.md."
    exit 1
}

if (-not (Test-Path (Join-Path $ProjectRoot ".env"))) {
    Write-Warning ".env не найден в $ProjectRoot - заполните его перед запуском задачи (см. .env.example)."
}

$Action = New-ScheduledTaskAction -Execute $PythonExe -Argument "-m src.main" -WorkingDirectory $ProjectRoot
$Trigger = New-ScheduledTaskTrigger -AtLogOn
$Settings = New-ScheduledTaskSettingsSet `
    -RestartCount 5 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -StartWhenAvailable

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger $Trigger `
    -Settings $Settings `
    -Description "Lead Radar - персональная система поиска заказов" `
    -Force | Out-Null

Write-Host "Задача '$TaskName' зарегистрирована (старт при входе, до 5 перезапусков при сбое)."
Write-Host ""
Write-Host "Управление:"
Write-Host "  Start-ScheduledTask -TaskName $TaskName"
Write-Host "  Stop-ScheduledTask -TaskName $TaskName"
Write-Host "  Get-ScheduledTaskInfo -TaskName $TaskName"
Write-Host "  Unregister-ScheduledTask -TaskName $TaskName -Confirm:`$false"
Write-Host ""
Write-Host "Или через графический Планировщик заданий (taskschd.msc), папка задач - в корне."
