param([switch]$NoBrowser)
$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $root

$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
  Write-Error "Python 3 is required. Install Python, then run START-COVENIA.cmd again."
}
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
  Write-Error "Node.js with npm is required. Install it, then run START-COVENIA.cmd again."
}

if (-not (Test-Path (Join-Path $root ".env"))) {
  Copy-Item (Join-Path $root ".env.example") (Join-Path $root ".env")
  Write-Host "Created .env. JEV stays optional; add your own key there if you want to enable it."
}
if (-not (Test-Path (Join-Path $root "frontend/.env.local"))) {
  Copy-Item (Join-Path $root "frontend/.env.example") (Join-Path $root "frontend/.env.local")
}

& $python.Source -c "import fastapi, uvicorn" 2>$null
if ($LASTEXITCODE -ne 0) {
  Write-Host "Installing backend packages..."
  & $python.Source -m pip install -r (Join-Path $root "backend/requirements.txt")
  if ($LASTEXITCODE -ne 0) { throw "Backend package installation failed." }
}
if (-not (Test-Path (Join-Path $root "frontend/node_modules/vite/bin/vite.js"))) {
  Write-Host "Installing frontend packages..."
  & npm.cmd --prefix (Join-Path $root "frontend") ci
  if ($LASTEXITCODE -ne 0) { throw "Frontend package installation failed." }
}

function Test-PortFree([int]$port) {
  $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, $port)
  try {
    $listener.Start()
    return $true
  } catch {
    return $false
  } finally {
    $listener.Stop()
  }
}

$apiPort = 8000
while (-not (Test-PortFree $apiPort) -and $apiPort -lt 8010) { $apiPort++ }
if (-not (Test-PortFree $apiPort)) { throw "Ports 8000–8009 are busy. Close an existing local API and try again." }

$webPort = 4173
while (-not (Test-PortFree $webPort) -and $webPort -le 4174) { $webPort++ }
if (-not (Test-PortFree $webPort)) { throw "Ports 4173 and 4174 are busy. Close an existing local preview and try again." }

$runDir = Join-Path $root ".run"
New-Item -ItemType Directory -Force -Path $runDir | Out-Null
$apiOut = Join-Path $runDir "api.out.log"
$apiErr = Join-Path $runDir "api.err.log"
$webOut = Join-Path $runDir "web.out.log"
$webErr = Join-Path $runDir "web.err.log"
$api = Start-Process -FilePath $python.Source -ArgumentList @("-m", "uvicorn", "backend.main:app", "--app-dir", $root, "--host", "127.0.0.1", "--port", "$apiPort") -WorkingDirectory $root -WindowStyle Hidden -PassThru -RedirectStandardOutput $apiOut -RedirectStandardError $apiErr
$env:VITE_API_BASE_URL = "http://127.0.0.1:$apiPort"
$webCommand = "npm --prefix `"$root\frontend`" run dev -- --host 127.0.0.1 --port $webPort"
$web = Start-Process -FilePath "cmd.exe" -ArgumentList @("/c", $webCommand) -WorkingDirectory $root -WindowStyle Hidden -PassThru -RedirectStandardOutput $webOut -RedirectStandardError $webErr
@{ apiPid = $api.Id; webPid = $web.Id; apiPort = $apiPort; webPort = $webPort } | ConvertTo-Json | Set-Content -Encoding utf8 (Join-Path $runDir "processes.json")

$ready = $false
for ($attempt = 0; $attempt -lt 30; $attempt++) {
  Start-Sleep -Seconds 1
  try {
    $null = Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:$webPort/" -TimeoutSec 2
    $null = Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:$apiPort/api/priority" -TimeoutSec 2
    $ready = $true
    break
  } catch { }
}
if (-not $ready) {
  Write-Host "Startup did not finish. Logs are in .run/."
  throw "Covenia could not start."
}
Write-Host "Covenia is ready at http://127.0.0.1:$webPort/"
Write-Host "API: http://127.0.0.1:$apiPort/  |  JEV is optional and uses the local .env key."
if (-not $NoBrowser) { Start-Process "http://127.0.0.1:$webPort/" }
