#Requires -Version 5.1
<#
.SYNOPSIS
    ERP 经营分析实验室 · 一键环境搭建（Windows PowerShell）
.DESCRIPTION
    1) 创建虚拟环境 .venv
    2) 安装 requirements.txt
    3) 生成 .env（从 .env.example 复制）
    4) 建库 + 灌 24 个月确定性种子数据
    5) 导出 BI CSV（bi/data 与 excel/data）
    6) 生成 Excel 工作簿
    7) 生成 Power BI PBIP 项目 与 Tableau 工作簿
    8) 运行全部结构自检脚本
.EXAMPLE
    .\scripts\setup.ps1
    .\scripts\setup.ps1 -SkipExcel
#>
param(
    [switch]$SkipExcel,
    [switch]$SkipBi,
    [string]$PythonExe = "python"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

function Step($msg) { Write-Host "`n=== $msg ===" -ForegroundColor Cyan }
function Ok($msg)   { Write-Host "  [OK] $msg" -ForegroundColor Green }
function Warn($msg) { Write-Host "  [!]  $msg" -ForegroundColor Yellow }

Step "1/8 检查 Python"
if (-not (Get-Command $PythonExe -ErrorAction SilentlyContinue)) {
    throw "找不到 $PythonExe，请先安装 Python 3.11+ 并加入 PATH"
}
& $PythonExe --version
Ok "Python 可用"

Step "2/8 创建虚拟环境 .venv"
if (-not (Test-Path ".venv")) {
    & $PythonExe -m venv .venv
    Ok ".venv 已创建"
} else {
    Ok ".venv 已存在，跳过"
}
$venvPy = Join-Path $root ".venv\Scripts\python.exe"

Step "3/8 安装依赖"
& $venvPy -m pip install --upgrade pip --quiet
& $venvPy -m pip install -r requirements.txt --quiet
Ok "依赖安装完成"

Step "4/8 准备 .env"
if (-not (Test-Path ".env")) {
    if (Test-Path ".env.example") {
        Copy-Item ".env.example" ".env"
        Ok ".env 已由 .env.example 生成"
    } else {
        Warn ".env.example 不存在，跳过（将使用内置默认配置）"
    }
} else {
    Ok ".env 已存在，跳过"
}

Step "5/8 建库 + 灌种子数据"
& $venvPy "scripts\seed_db.py" --reset
if ($LASTEXITCODE -ne 0) { throw "种子数据生成失败" }

Step "6/8 导出 BI / Excel CSV"
& $venvPy "scripts\export_bi_csv.py"
if ($LASTEXITCODE -ne 0) { Warn "CSV 导出失败（不阻塞）" }

if (-not $SkipExcel) {
    Step "7/8 生成 Excel 工作簿"
    & $venvPy "excel\build_workbook.py"
    if ($LASTEXITCODE -ne 0) { Warn "Excel 工作簿生成失败（不阻塞）" }
} else {
    Step "7/8 跳过 Excel 工作簿（-SkipExcel）"
}

if (-not $SkipBi) {
    Step "7b/8 生成 BI 工程文件"
    & $venvPy "bi\powerbi\build_pbip.py"
    & $venvPy "bi\tableau\build_twb.py"
    Ok "PBIP 与 TWB/TWBX 已生成"
} else {
    Step "7b/8 跳过 BI 工程文件（-SkipBi）"
}

Step "8/8 结构自检"
& $venvPy "bi\tableau\verify_twb.py"
& $venvPy "bi\powerbi\verify_pbip.py"

Write-Host "`n================================================" -ForegroundColor Green
Write-Host "  环境搭建完成" -ForegroundColor Green
Write-Host "  启动服务： .\scripts\run.ps1" -ForegroundColor Green
Write-Host "  登录账号： analyst / Analyst@123456" -ForegroundColor Green
Write-Host "================================================" -ForegroundColor Green
