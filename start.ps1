# ChatInsight 一键启动：后端 API + 前端 Web
$ErrorActionPreference = "Stop"

$ProjectRoot = $PSScriptRoot
$WebDir = Join-Path $ProjectRoot "web"
$ApiPort = 8767
$WebPort = 5173

function Test-PortInUse([int]$Port) {
    return [bool](Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
}

function Get-DevCommand([string]$WebRoot) {
    $node = (Get-Command node -ErrorAction SilentlyContinue).Source
    if (-not $node) {
        throw "未找到 node，请先安装 Node.js"
    }

    # Start-Process 无法可靠启动 npm/pnpm（.cmd/.ps1 会立刻退出），直接跑 Vite。
    $viteJs = Join-Path $WebRoot "node_modules\vite\bin\vite.js"
    if (Test-Path $viteJs) {
        return @{ File = $node; Args = @($viteJs, "--host", "0.0.0.0") }
    }

    $npmCmd = (Get-Command npm.cmd -ErrorAction SilentlyContinue).Source
    if ($npmCmd) {
        return @{ File = $npmCmd; Args = @("run", "dev", "--", "--host", "0.0.0.0") }
    }
    throw "未找到 vite，请先在 web 目录执行 npm install"
}

function Wait-PortReady([int]$Port, [int]$TimeoutSec = 30) {
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        if (Test-PortInUse $Port) { return $true }
        Start-Sleep -Milliseconds 500
    }
    return $false
}

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    throw "未找到 python，请先安装 Python 3.10+"
}

if (-not (Test-Path (Join-Path $WebDir "node_modules"))) {
    Write-Host "[!] 前端依赖未安装，正在执行 npm install ..." -ForegroundColor Yellow
    Push-Location $WebDir
    npm install
    Pop-Location
}

if (Test-PortInUse $ApiPort) {
    Write-Host "[!] 端口 $ApiPort 已被占用，跳过后端启动" -ForegroundColor Yellow
    $apiProcess = $null
} else {
    Write-Host "启动后端 API (http://localhost:$ApiPort) ..." -ForegroundColor Green
    $apiProcess = Start-Process -FilePath "python" `
        -ArgumentList @("-m", "uvicorn", "api.server:app", "--host", "0.0.0.0", "--port", "$ApiPort") `
        -WorkingDirectory $ProjectRoot `
        -PassThru `
        -WindowStyle Minimized
}

if (Test-PortInUse $WebPort) {
    Write-Host "[!] 端口 $WebPort 已被占用，跳过前端启动" -ForegroundColor Yellow
    $webProcess = $null
} else {
    $dev = Get-DevCommand $WebDir
    Write-Host "启动前端 Web (http://localhost:$WebPort) ..." -ForegroundColor Green
    $webProcess = Start-Process -FilePath $dev.File `
        -ArgumentList $dev.Args `
        -WorkingDirectory $WebDir `
        -PassThru `
        -WindowStyle Minimized
    if (-not (Wait-PortReady $WebPort)) {
        Write-Host "[!] 前端未在 30 秒内就绪，请检查 web 目录依赖或手动访问 http://localhost:$WebPort" -ForegroundColor Yellow
    }
}

if (Test-PortInUse $WebPort) {
    Start-Process "http://localhost:$WebPort"
} else {
    Write-Host "[!] 前端端口 $WebPort 未监听，浏览器未自动打开" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host " ChatInsight 已启动" -ForegroundColor Cyan
Write-Host " 前端: http://localhost:$WebPort" -ForegroundColor Cyan
Write-Host " 后端: http://localhost:$ApiPort" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "按 Ctrl+C 或关闭此窗口可停止服务" -ForegroundColor Yellow

try {
    if ($apiProcess) { $apiProcess.WaitForExit() }
    elseif ($webProcess) { $webProcess.WaitForExit() }
    else { Read-Host "按 Enter 退出" }
} finally {
    if ($apiProcess -and -not $apiProcess.HasExited) {
        Stop-Process -Id $apiProcess.Id -Force -ErrorAction SilentlyContinue
    }
    if ($webProcess -and -not $webProcess.HasExited) {
        Stop-Process -Id $webProcess.Id -Force -ErrorAction SilentlyContinue
    }
}
