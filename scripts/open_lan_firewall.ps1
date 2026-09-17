# Allow inbound TCP for the ChatInsight web UI and API.
# Run as Administrator once if start.ps1 could not add the rules.
param(
    [int[]]$Ports = @(5173, 8767)
)

$ErrorActionPreference = "Stop"

function Ensure-ChatInsightFirewallRule([int]$Port) {
    $name = "ChatInsight TCP $Port"
    $existing = Get-NetFirewallRule -DisplayName $name -ErrorAction SilentlyContinue
    if ($existing) {
        Set-NetFirewallRule -DisplayName $name -Enabled True -Profile Any -ErrorAction SilentlyContinue | Out-Null
        Get-NetFirewallPortFilter -AssociatedNetFirewallRule $existing -ErrorAction SilentlyContinue |
            ForEach-Object { $_ } | Out-Null
        Write-Host "已存在: $name" -ForegroundColor Green
        return
    }
    New-NetFirewallRule `
        -DisplayName $name `
        -Direction Inbound `
        -Action Allow `
        -Protocol TCP `
        -LocalPort $Port `
        -Profile Any `
        -ErrorAction Stop | Out-Null
    Write-Host "已放行: $name" -ForegroundColor Green
}

foreach ($port in $Ports) {
    Ensure-ChatInsightFirewallRule $port
}

Write-Host ""
Write-Host "其它电脑可用浏览器打开本机局域网地址，端口 $Ports。" -ForegroundColor Cyan
