# Registers a Windows scheduled task that refreshes the dashboard data every Monday at 08:00.
# Run once:  powershell -ExecutionPolicy Bypass -File scripts\register_weekly_task.ps1
# Remove:    schtasks /Delete /TN TokenElasticityWeekly /F
param(
    [string]$TaskName = "TokenElasticityWeekly",
    [string]$Time = "08:00"
)

$runner = Join-Path $PSScriptRoot "run_build.cmd"
if (-not (Test-Path $runner)) { throw "Missing $runner" }

schtasks /Create /TN $TaskName /SC WEEKLY /D MON /ST $Time /TR "`"$runner`"" /F
if ($LASTEXITCODE -eq 0) {
    Write-Host "Registered '$TaskName' (Mondays $Time). Runs even if you start the PC later only when 'Run task as soon as possible after a scheduled start is missed' is enabled in Task Scheduler."
    schtasks /Query /TN $TaskName /FO LIST
}
