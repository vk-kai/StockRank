Write-Host "Stopping port 8000 and 5173..."
$ports = 8000, 5173
foreach ($port in $ports) {
    $proc = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    if ($proc) {
        Stop-Process -Id $proc.OwningProcess -Force -ErrorAction SilentlyContinue
    }
}
Write-Host "Done."
