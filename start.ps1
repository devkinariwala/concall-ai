$ErrorActionPreference = "Stop"

$RootDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $RootDir

$VenvPython = Join-Path $RootDir ".venv\Scripts\python.exe"
if (-not (Test-Path $VenvPython)) {
    Write-Error "Virtual environment not found at $VenvPython. Create .venv and install backend/requirements.txt first."
    exit 1
}

$env:PYTHONPATH = "backend"

Write-Host "Starting ConcallAI backend (FastAPI + Background Watcher + WebSocket) on http://localhost:8000 ..." -ForegroundColor Cyan
$BackendProc = Start-Process -FilePath $VenvPython `
    -ArgumentList "-m", "uvicorn", "app.main:app", "--app-dir", "backend", "--port", "8000" `
    -PassThru -NoNewWindow

try {
    Start-Sleep -Seconds 2
    Write-Host "Starting ConcallAI frontend (Vite) on http://localhost:5173 ..." -ForegroundColor Green
    Push-Location (Join-Path $RootDir "frontend")
    npm run dev
}
finally {
    Pop-Location -ErrorAction SilentlyContinue
    if ($BackendProc -and -not $BackendProc.HasExited) {
        Write-Host "`nStopping ConcallAI backend..." -ForegroundColor Yellow
        Stop-Process -Id $BackendProc.Id -Force -ErrorAction SilentlyContinue
    }
}