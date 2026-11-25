#Requires -Version 5.1
<#
.SYNOPSIS
    ERP 经营分析实验室 · 启动开发服务器
.DESCRIPTION
    自动使用 .venv 下的 Python 启动 uvicorn，并先做一次数据库可用性自检。
.EXAMPLE
    .\scripts\run.ps1
    .\scripts\run.ps1 -Port 8080 -Reload
#>
param(
    [int]$Port = 8000,
    [string]$Host_ = "127.0.0.1",
    [switch]$Reload
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$venvPy = Join-Path $root ".venv\Scripts\python.exe"
if (Test-Path $venvPy) {
    $py = $venvPy
} else {
    Write-Host "[!] 未找到 .venv，使用系统 python（如未装依赖请先运行 .\scripts\setup.ps1）" -ForegroundColor Yellow
    $py = "python"
}

Write-Host "=== 数据库自检 ===" -ForegroundColor Cyan
& $py -c @"
import os, sys
sys.path.insert(0, r'$root')
from app.core.config import get_settings
s = get_settings()
print('  DATABASE_URL =', s.database_url)
from app.db.session import build_engine, create_all
from sqlalchemy import text
e = build_engine(s.database_url)
with e.connect() as c:
    print('  连接成功:', c.execute(text('select 1')).scalar())
    n = c.execute(text('select count(*) from fact_sales_order')).scalar()
    print('  订单数:', n)
"@
if ($LASTEXITCODE -ne 0) {
    Write-Host "[!] 数据库不可用，请先运行 .\scripts\setup.ps1" -ForegroundColor Red
    exit 1
}

$reloadArg = ""
if ($Reload) { $reloadArg = "--reload" }

Write-Host "`n=== 启动 uvicorn  http://$Host_`:$Port ===" -ForegroundColor Green
Write-Host "  登录账号： analyst / Analyst@123456" -ForegroundColor Green
& $py -m uvicorn app.main:app --host $Host_ --port $Port $reloadArg
