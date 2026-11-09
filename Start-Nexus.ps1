param(
[switch]$Stop
)
$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$BackendRoot = Join-Path $ProjectRoot "backend"
$FrontendRoot = Join-Path $ProjectRoot "frontend"
$VenvPython = Join-Path $BackendRoot ".venv\Scripts\python.exe"
$VenvConfig = Join-Path $BackendRoot ".venv\pyvenv.cfg"
$VenvSitePackages = Join-Path $BackendRoot ".venv\Lib\site-packages"
if (-not (Test-Path $VenvPython)) {
$FallbackPython = "C:\Users\Kunal Singh\Documents\NexusAI\backend\.venv\Scripts\python.exe"
if (Test-Path $FallbackPython) {
$VenvPython = $FallbackPython
$VenvConfig = "C:\Users\Kunal Singh\Documents\NexusAI\backend\.venv\pyvenv.cfg"
$VenvSitePackages = "C:\Users\Kunal Singh\Documents\NexusAI\backend\.venv\Lib\site-packages"
}
}
$ViteEntry = Join-Path $FrontendRoot "node_modules\vite\bin\vite.js"
$StateRoot = Join-Path $env:LOCALAPPDATA "NexusAI"
$LogRoot = Join-Path $StateRoot "logs"
$StateFile = Join-Path $StateRoot "servers.json"
$BackendPort = 8000
function Get-Listener([int]$Port) {
return Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue |
Select-Object -First 1
}
function Test-PortAvailable([int]$Port) {
$listener = [System.Net.Sockets.TcpListener]::new(
[System.Net.IPAddress]::Loopback,
$Port
)
try {
$listener.Start()
return $true
} catch {
return $false
} finally {
$listener.Stop()
}
}
function Stop-ProcessAndWait([int]$ProcessId) {
if (-not (Get-Process -Id $ProcessId -ErrorAction SilentlyContinue)) {
return
}
Stop-Process -Id $ProcessId -ErrorAction Stop
for ($attempt = 0; $attempt -lt 50; $attempt++) {
if (-not (Get-Process -Id $ProcessId -ErrorAction SilentlyContinue)) {
return
}
Start-Sleep -Milliseconds 100
}
throw "Process $ProcessId did not stop within five seconds."
}
function Stop-TrackedServers {
if (-not (Test-Path $StateFile)) {
Write-Host "No Nexus launcher state found; nothing to stop."
return
}
$state = Get-Content -Raw $StateFile | ConvertFrom-Json
if ($state.project -ne $ProjectRoot) {
throw "Launcher state belongs to another project ($($state.project)); leaving it untouched."
}
$remaining = @()
$failures = @()
foreach ($server in @($state.servers)) {
if (-not $server.started_by_launcher) { continue }
$process = Get-CimInstance Win32_Process -Filter "ProcessId=$($server.pid)" -ErrorAction SilentlyContinue
if (-not $process) {
Write-Host "$($server.name) is already stopped."
continue
}
$expectedPath = if ($server.name -eq "backend") { $BackendRoot } else { $FrontendRoot }
if ($process.CommandLine -notlike "*$expectedPath*") {
$message = "PID $($server.pid) no longer matches this Nexus $($server.name); leaving it untouched."
Write-Warning $message
$remaining += $server
$failures += $message
continue
}
try {
Stop-ProcessAndWait -ProcessId ([int]$server.pid)
if ($server.port) {
for ($attempt = 0; $attempt -lt 50; $attempt++) {
$listener = Get-Listener ([int]$server.port)
if (-not $listener -or $listener.OwningProcess -ne [int]$server.pid) {
break
}
Start-Sleep -Milliseconds 100
}
$listener = Get-Listener ([int]$server.port)
if ($listener -and $listener.OwningProcess -eq [int]$server.pid) {
throw "Listener on port $($server.port) did not stop."
}
}
Write-Host "Stopped $($server.name) (PID $($server.pid))."
} catch {
$message = "Could not stop $($server.name) (PID $($server.pid)): $($_.Exception.Message)"
Write-Warning $message
$remaining += $server
$failures += $message
}
}
if ($remaining.Count) {
@{ project = $ProjectRoot; servers = $remaining } |
ConvertTo-Json -Depth 4 |
Set-Content -LiteralPath $StateFile -Encoding utf8
} else {
Remove-Item -LiteralPath $StateFile -Force
}
if ($failures.Count) {
throw ($failures -join [Environment]::NewLine)
}
}
if ($Stop) {
Stop-TrackedServers
exit 0
}
foreach ($required in @("python", "node", "npm")) {
if (-not (Get-Command $required -ErrorAction SilentlyContinue)) {
throw "Required tool '$required' was not found on PATH."
}
}
if (-not (Test-Path $VenvPython -PathType Leaf) -or
-not (Test-Path $VenvConfig -PathType Leaf) -or
-not (Test-Path $VenvSitePackages -PathType Container)) {
throw "Backend virtual environment is incomplete. Create it and install backend\requirements.txt explicitly."
}
$pythonExecutableSetting = Get-Content $VenvConfig |
Where-Object { $_ -match '^\s*executable\s*=' } |
Select-Object -First 1
if ($pythonExecutableSetting -and
$pythonExecutableSetting -match '^\s*executable\s*=\s*(.+?)\s*$') {
$Python = $Matches[1].Trim('"')
} else {
$pythonHomeSetting = Get-Content $VenvConfig |
Where-Object { $_ -match '^\s*home\s*=' } |
Select-Object -First 1
if ($pythonHomeSetting -and
$pythonHomeSetting -match '^\s*home\s*=\s*(.+?)\s*$') {
$Python = Join-Path $Matches[1].Trim('"') "python.exe"
} else {
throw "Could not resolve the CPython executable from $VenvConfig."
}
}
if (-not (Test-Path $Python -PathType Leaf)) {
throw "The CPython executable configured by the virtual environment is missing: $Python"
}
if (-not (Test-Path (Join-Path $FrontendRoot "node_modules") -PathType Container) -or
-not (Test-Path $ViteEntry -PathType Leaf)) {
throw "Frontend dependencies are missing. Run npm install in frontend after reviewing package-lock.json."
}
$previousPythonPath = $env:PYTHONPATH
$env:PYTHONPATH = if ($previousPythonPath) {
"$VenvSitePackages;$previousPythonPath"
} else {
$VenvSitePackages
}
try {
$pythonVersion = & $Python --version 2>&1
& $Python -c "import fastapi, httpx, pydantic, uvicorn" 2>$null
if ($LASTEXITCODE -ne 0) {
throw "Backend dependencies are not importable from $VenvSitePackages."
}
} finally {
if ($null -eq $previousPythonPath) {
Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
} else {
$env:PYTHONPATH = $previousPythonPath
}
}
$nodeVersion = & node --version
$npmVersion = & npm --version
Write-Host "Python: $pythonVersion"
Write-Host "Node:   $nodeVersion"
Write-Host "npm:    $npmVersion"
$ollama = Get-Command ollama -ErrorAction SilentlyContinue
if (-not $ollama) {
Write-Warning "Ollama CLI is not on PATH. The app can start, but local model chat may be unavailable."
} else {
try {
$ollamaModels = & $ollama.Source list 2>&1
$modelFound = @($ollamaModels | Where-Object { "$_" -match "qwen2\.5-coder:7b" }).Count -gt 0
if ($LASTEXITCODE -ne 0 -or -not $modelFound) {
Write-Warning "Ollama is installed but qwen2.5-coder:7b was not found. Install it explicitly with: ollama pull qwen2.5-coder:7b"
} else {
Write-Host "Ollama model qwen2.5-coder:7b is installed."
}
} catch {
Write-Warning "Could not query Ollama: $($_.Exception.Message)"
}
}
New-Item -ItemType Directory -Path $LogRoot -Force | Out-Null
$servers = @()
$backendStarted = $false
$frontendStarted = $false
$backendLog = Join-Path $LogRoot "backend.log"
$backendErrorLog = Join-Path $LogRoot "backend-error.log"
$frontendLog = Join-Path $LogRoot "frontend.log"
$frontendErrorLog = Join-Path $LogRoot "frontend-error.log"
$backendHealth = $null
$candidatePorts = @(8001, 8002, 8080, 8000)
foreach ($port in $candidatePorts) {
if (-not (Test-PortAvailable $port)) {
try {
$health = Invoke-RestMethod -Uri "http://127.0.0.1:$port/api/health" -TimeoutSec 2
if ($health.PSObject.Properties.Name -contains "model_installed" -and $health.service -ne "CampusConnect API") {
$backendHealth = $health
$BackendPort = $port
Write-Host "Reusing existing Nexus backend on http://127.0.0.1:$port."
break
}
} catch {}
} else {
$BackendPort = $port
break
}
}
if ($null -ne $backendHealth) {
# Existing backend is healthy and reused
} elseif ($false) {
try {
$backendHealth = Invoke-RestMethod -Uri "http://127.0.0.1:$BackendPort/api/health" -TimeoutSec 3
if (-not ($backendHealth.PSObject.Properties.Name -contains "model_installed")) {
throw "Port $BackendPort is serving a different application."
}
Write-Host "Reusing existing Nexus backend on http://127.0.0.1:$BackendPort."
} catch {
throw "Port $BackendPort is already occupied and is not a reachable Nexus API. No server was started. $($_.Exception.Message)"
}
} else {
$previousPythonPath = $env:PYTHONPATH
$env:PYTHONPATH = if ($previousPythonPath) {
"$VenvSitePackages;$previousPythonPath"
} else {
$VenvSitePackages
}
try {
$pythonProcess = Start-Process -FilePath $Python -ArgumentList @("-m", "uvicorn", "main:app", "--app-dir", "`"$BackendRoot`"", "--host", "127.0.0.1", "--port", "$BackendPort") -WorkingDirectory $BackendRoot -RedirectStandardOutput $backendLog -RedirectStandardError $backendErrorLog -WindowStyle Hidden -PassThru
} finally {
if ($null -eq $previousPythonPath) {
Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
} else {
$env:PYTHONPATH = $previousPythonPath
}
}
$backendStarted = $true
$servers += [PSCustomObject]@{
name = "backend"
pid = $pythonProcess.Id
port = $BackendPort
started_by_launcher = $true
}
$ready = $false
for ($attempt = 0; $attempt -lt 30; $attempt++) {
Start-Sleep -Milliseconds 500
try {
$backendHealth = Invoke-RestMethod -Uri "http://127.0.0.1:$BackendPort/api/health" -TimeoutSec 2
$listener = Get-Listener $BackendPort
$ready = ($null -ne $backendHealth -and ($backendHealth.status -eq 'ok' -or $backendHealth.status -eq 'degraded'))
if ($ready) { break }
} catch {
$pythonProcess.Refresh()
if ($pythonProcess.HasExited) { break }
}
}
if (-not $ready) {
$details = ""
if (Test-Path $backendErrorLog) {
$details = (Get-Content $backendErrorLog -Tail 30) -join "`n"
}
Stop-ProcessAndWait -ProcessId $pythonProcess.Id
throw "Backend failed to start. Log: $backendErrorLog`n$details"
}
}
if (-not $backendHealth.model_installed) {
Write-Warning "Backend is running, but the configured Ollama model is unavailable: $($backendHealth.message)"
}
$frontendUrl = $null
$existingFrontend = Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
Where-Object { $_.LocalPort -ge 5173 -and $_.LocalPort -le 5199 } |
ForEach-Object {
$processInfo = Get-CimInstance Win32_Process -Filter "ProcessId=$($_.OwningProcess)" -ErrorAction SilentlyContinue
if ($processInfo -and $processInfo.CommandLine -like "*$FrontendRoot*" -and
$processInfo.CommandLine -like "*vite*") {
[PSCustomObject]@{
Port = $_.LocalPort
Address = $_.LocalAddress
Process = $processInfo
}
}
} | Select-Object -First 1
if ($existingFrontend) {
$frontendHost = if ($existingFrontend.Address -eq "::1") { "localhost" } else { "127.0.0.1" }
$frontendUrl = "http://${frontendHost}:$($existingFrontend.Port)"
try {
$null = Invoke-WebRequest -Uri $frontendUrl -TimeoutSec 3 -UseBasicParsing
} catch {
throw "An existing Vite process was found but is not responding at ${frontendUrl}."
}
Write-Host "Reusing existing Nexus frontend at $frontendUrl."
} else {
$frontendPort = $null
foreach ($port in 5173..5199) {
if (Test-PortAvailable $port) {
$frontendPort = $port
break
}
}
if (-not $frontendPort) {
if ($backendStarted) {
Stop-ProcessAndWait -ProcessId $servers[0].pid
}
throw "No available frontend port was found between 5173 and 5199."
}
$node = (Get-Command node.exe -ErrorAction Stop).Source
try {
$nodeProcess = Start-Process -FilePath $node -ArgumentList @("`"$ViteEntry`"", "--host", "127.0.0.1", "--port", "$frontendPort", "--strictPort") -WorkingDirectory $FrontendRoot -RedirectStandardOutput $frontendLog -RedirectStandardError $frontendErrorLog -WindowStyle Hidden -PassThru
} catch {
if ($backendStarted) {
Stop-ProcessAndWait -ProcessId $servers[0].pid
}
throw "Could not start Vite: $($_.Exception.Message)"
}
$frontendStarted = $true
$servers += [PSCustomObject]@{
name = "frontend"
pid = $nodeProcess.Id
port = $frontendPort
started_by_launcher = $true
}
$ready = $false
for ($attempt = 0; $attempt -lt 30; $attempt++) {
Start-Sleep -Milliseconds 500
try {
$null = Invoke-WebRequest -Uri "http://127.0.0.1:$frontendPort" -TimeoutSec 2 -UseBasicParsing
$listener = Get-Listener $frontendPort
$ready = $true
if ($ready) { break }
} catch {
$nodeProcess.Refresh()
if ($nodeProcess.HasExited) { break }
}
}
if (-not $ready) {
$details = ""
if (Test-Path $frontendErrorLog) {
$details = (Get-Content $frontendErrorLog -Tail 30) -join "`n"
}
if ($backendStarted) {
Stop-ProcessAndWait -ProcessId $servers[0].pid
}
Stop-ProcessAndWait -ProcessId $nodeProcess.Id
throw "Frontend failed to start. Log: $frontendErrorLog`n$details"
}
$frontendUrl = "http://127.0.0.1:$frontendPort"
}
if ($servers.Count -gt 0) {
New-Item -ItemType Directory -Path $StateRoot -Force | Out-Null
@{ project = $ProjectRoot; servers = $servers } |
ConvertTo-Json -Depth 4 |
Set-Content -LiteralPath $StateFile -Encoding utf8
}
Write-Host ""
Write-Host "Nexus AI is ready: $frontendUrl" -ForegroundColor Green
Write-Host "Backend: http://127.0.0.1:$BackendPort"
Write-Host "Logs:    $LogRoot"
Write-Host "Stop launcher-managed servers with: .\Start-Nexus.ps1 -Stop"
