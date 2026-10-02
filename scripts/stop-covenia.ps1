$ErrorActionPreference = "Continue"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$processFile = Join-Path $root ".run/processes.json"
if (-not (Test-Path $processFile)) {
  Write-Host "No Covenia process record found."
  exit 0
}
$processes = Get-Content $processFile -Raw | ConvertFrom-Json
foreach ($id in @($processes.webPid, $processes.apiPid)) {
  if ($id) {
    & taskkill.exe /PID $id /T /F 2>$null | Out-Null
  }
}
Remove-Item -LiteralPath $processFile -Force -ErrorAction SilentlyContinue
Write-Host "Covenia local services stopped. Logs remain in .run/."
