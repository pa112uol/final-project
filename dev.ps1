$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$BackendDir = "$Root\backend"
$FrontendDir = "$Root\frontend"
$Python = "$BackendDir\.venv\Scripts\python.exe"

# Bootstrap venv if missing
if (-not (Test-Path $Python)) {
    Write-Host "[backend] Creating virtual environment..."
    python -m venv "$BackendDir\.venv"
    Write-Host "[backend] Installing dependencies..."
    & "$BackendDir\.venv\Scripts\pip.exe" install -r "$BackendDir\requirements.txt" --quiet
}

$backendJob = Start-Job -Name Backend -ScriptBlock {
    param($dir, $py)
    Set-Location $dir
    & $py manage.py runserver
} -ArgumentList $BackendDir, $Python

$frontendJob = Start-Job -Name Frontend -ScriptBlock {
    param($dir)
    Set-Location $dir
    npm install --silent
    npm run dev
} -ArgumentList $FrontendDir

try {
    while ($backendJob.State -eq 'Running' -or $frontendJob.State -eq 'Running') {
        Receive-Job $backendJob | ForEach-Object { "[backend] $_" }
        Receive-Job $frontendJob | ForEach-Object { "[frontend] $_" }
        Start-Sleep -Milliseconds 200
    }
    Receive-Job $backendJob | ForEach-Object { "[backend] $_" }
    Receive-Job $frontendJob | ForEach-Object { "[frontend] $_" }
} finally {
    Stop-Job $backendJob, $frontendJob -ErrorAction SilentlyContinue
    Remove-Job $backendJob, $frontendJob -ErrorAction SilentlyContinue
}
