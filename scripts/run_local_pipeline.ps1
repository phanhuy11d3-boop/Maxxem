# Chạy pipeline local theo Task Scheduler (cadence 1 phút, đường A).
# Nạp .env vào process env (main.py không tự đọc .env) rồi chạy main.py,
# output dồn vào storage/local_cron.log (tự xoay khi quá 5MB).
$repo = 'c:\Tool\crypto-sentinel'
Set-Location $repo

Get-Content "$repo\.env" | ForEach-Object {
    if ($_ -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$') {
        [Environment]::SetEnvironmentVariable($Matches[1], $Matches[2].Trim('"'), 'Process')
    }
}

$log = "$repo\storage\local_cron.log"
if ((Test-Path $log) -and (Get-Item $log).Length -gt 5MB) {
    Move-Item $log "$log.1" -Force
}

Add-Content $log "=== run $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') ==="
cmd /c "py -3 main.py >> `"$log`" 2>&1"
Add-Content $log "=== exit $LASTEXITCODE ==="
