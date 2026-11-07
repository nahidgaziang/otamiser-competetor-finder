# Point THIS PowerShell window at the disposable otamiser_test database (for the automated tests).
# Usage, from the otamiser-prototype folder:   . .\scripts\use-test-db.ps1
# Reads .env, swaps the database name, and clears API keys so tests can never spend money.

$envFile = Join-Path $PSScriptRoot "..\.env"
if (-not (Test-Path $envFile)) { throw ".env not found at $envFile" }

foreach ($line in Get-Content $envFile) {
    if ($line -match '^\s*#' -or $line -notmatch '=') { continue }
    $name, $value = $line -split '=', 2
    $name = $name.Trim(); $value = $value.Trim().Trim('"')
    if ($name -like 'DATABASE_URL*') { $value = $value -replace '/otamiser_local', '/otamiser_test' }
    Set-Item -Path "Env:$name" -Value $value
}
$env:ANTHROPIC_API_KEY = ''
$env:TAVILY_API_KEY = ''
$env:EXA_API_KEY = ''
$env:WEBFLOW_MODE = 'off'
Write-Host "This window now uses otamiser_test (API keys cleared). Close the window to go back to normal."
