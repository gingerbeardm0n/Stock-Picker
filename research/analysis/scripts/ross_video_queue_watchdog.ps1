# Watchdog for ross_video_queue.py. Run by a Windows scheduled task at logon (+2 min) and every hour, with
# "multiple instances: parallel" so the hourly run fires while the queue's own instance is still running.
#   - log contains QUEUE DONE                                   -> nothing to do
#   - queue running, log written in the last 90 min              -> leave it alone (a YouTube backoff is 60 min)
#   - queue running, log silent > 90 min (hung)                  -> kill it (and ffmpeg) and restart
#   - queue not running                                          -> start it (it resumes; finished items are skipped)
# Usage:
#   pwsh -NoProfile -ExecutionPolicy Bypass -File ross_video_queue_watchdog.ps1 -WorkDir <dir> -Python <ocr venv python.exe>
# <dir> holds queue.log and queue/ (downloads, census frames).
param(
    [Parameter(Mandatory)] [string] $WorkDir,
    [Parameter(Mandatory)] [string] $Python
)
$log = Join-Path $WorkDir 'queue.log'
$queue = Join-Path $PSScriptRoot 'ross_video_queue.py'
function Say($m) { Add-Content $log "$(Get-Date -Format 'MM-dd HH:mm:ss') $m" }

if ((Test-Path $log) -and (Select-String -Path $log -Pattern 'QUEUE DONE' -Quiet)) { exit 0 }
$running = Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -like '*ross_video_queue.py*' }
if ($running) {
    $age = (New-TimeSpan -Start (Get-Item $log).LastWriteTime -End (Get-Date)).TotalMinutes
    if ($age -lt 90) { exit 0 }
    Say ("watchdog: log silent {0:N0} min, killing hung queue" -f $age)
    $running | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    Get-CimInstance Win32_Process -Filter "Name='ffmpeg.exe'" | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    Start-Sleep 5
}
Remove-Item (Join-Path $WorkDir 'queue/dl/*') -ErrorAction SilentlyContinue
Say 'restarted by scheduled task'
Set-Location $WorkDir
& $Python -I $queue (Join-Path $WorkDir 'queue') *>> $log
