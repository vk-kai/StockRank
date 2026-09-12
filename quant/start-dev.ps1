Write-Host "Stopping existing processes..."
& "$PSScriptRoot\stop-dev.ps1"

$Python313Exe = Join-Path $env:LOCALAPPDATA "Programs\Python\Python313\python.exe"
$VenvDir = Join-Path $PSScriptRoot ".venv"
$VenvPythonExe = Join-Path $VenvDir "Scripts\python.exe"

function Resolve-BasePython {
    if (Test-Path $Python313Exe) {
        return $Python313Exe
    }

    $PythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if (-not $PythonCommand) {
        throw "Python 3.13 not found at $Python313Exe, and no python.exe was found on PATH."
    }
    return $PythonCommand.Source
}

$VenvHealthy = $false
if (Test-Path $VenvPythonExe) {
    & $VenvPythonExe -c "import sys" 2>$null
    $VenvHealthy = $LASTEXITCODE -eq 0
}

if (-not $VenvHealthy) {
    $BasePythonExe = Resolve-BasePython
    if (Test-Path $VenvPythonExe) {
        Write-Host "Virtual environment is not healthy. Repairing .venv with: $BasePythonExe"
        & $BasePythonExe -m venv --upgrade $VenvDir
    } else {
        Write-Host "Virtual environment not found. Creating .venv with: $BasePythonExe"
        & $BasePythonExe -m venv $VenvDir
    }
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path $VenvPythonExe)) {
        throw "Failed to create virtual environment at $VenvDir"
    }

    & $VenvPythonExe -c "import sys" 2>$null
    if ($LASTEXITCODE -ne 0) {
        throw "Virtual environment Python is still not usable at $VenvPythonExe"
    }
}

$PythonExe = $VenvPythonExe
Write-Host "Using Python: $PythonExe"

& $PythonExe -c "import uvicorn, fastapi, pandas, numpy" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Installing backend dependencies into .venv..."
    & $PythonExe -m pip install -r (Join-Path $PSScriptRoot "backend\requirements.txt")
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to install backend dependencies into .venv"
    }
}

# 拉满 CPU/IO 并发：解除默认 4/8 的封顶，让真实瓶颈只取决于核心数与各模块 max_limit
$env:TRENDZEN_CPU_WORKER_LIMIT = "64"
$env:TRENDZEN_IO_WORKER_LIMIT = "64"

Write-Host "Starting Backend (8000)..."
Start-Process $PythonExe -ArgumentList "-m", "uvicorn", "backend.main:app", "--host", "127.0.0.1", "--port", "8000" -WorkingDirectory $PSScriptRoot -NoNewWindow

Write-Host "Starting Frontend (5173)..."
Start-Process "npm.cmd" -ArgumentList "run", "dev", "--", "--host", "127.0.0.1", "--port", "5173" -WorkingDirectory "$PSScriptRoot\frontend" -NoNewWindow

Write-Host "`nAll services started:"
Write-Host "- Frontend: http://127.0.0.1:5173"
Write-Host "- Backend:  http://127.0.0.1:8000"
