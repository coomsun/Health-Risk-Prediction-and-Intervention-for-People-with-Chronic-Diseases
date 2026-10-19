<#
.SYNOPSIS
    启动《慢性病患者健康风险预测与干预》后端服务（FastAPI + Uvicorn，端口默认 8000）。

.DESCRIPTION
    自动定位工程根目录与虚拟环境 Python；缺库时给出提示（服务仍可启动，
    /api/v1/health 会返回 status=degraded）。
    文件以 UTF-8 BOM 保存，保证 Windows PowerShell 5.1 正确解析中文注释与提示。

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\start_api.ps1

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\start_api.ps1 -Port 8000 -Reload
#>
[CmdletBinding()]
param(
    [int]$Port = 8000,
    [string]$BindHost = "0.0.0.0",
    [string]$Python = "",
    [switch]$Reload
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

if (-not $Python) {
    $Candidates = @(
        (Join-Path $Root ".venv\Scripts\python.exe"),
        "D:\期末作业\.venv\Scripts\python.exe"
    )
    $Python = $Candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
    if (-not $Python) { $Python = "python" }
}

if ($Python -ne "python" -and -not (Test-Path $Python)) {
    throw "找不到 Python 解释器：$Python（可用 -Python 参数显式指定）"
}

if (-not $env:CHRONIC_RISK_DB) {
    $env:CHRONIC_RISK_DB = Join-Path $Root "db\chronic_risk.db"
}
if (-not (Test-Path $env:CHRONIC_RISK_DB)) {
    Write-Warning "未找到数据库 $env:CHRONIC_RISK_DB，请先运行 python pipeline\06_build_db.py（服务仍会启动，/api/v1/health 返回 degraded）"
}

Write-Host "工程根目录 : $Root"
Write-Host "Python     : $Python"
Write-Host "数据库     : $env:CHRONIC_RISK_DB"
Write-Host "监听地址   : http://$($BindHost):$Port"
Write-Host "Swagger    : http://127.0.0.1:$Port/docs"
Write-Host "健康检查   : http://127.0.0.1:$Port/api/v1/health"

$UvicornArgs = @("-m", "uvicorn", "api.main:app", "--host", $BindHost, "--port", "$Port")
if ($Reload) { $UvicornArgs += "--reload" }

& $Python @UvicornArgs
