# 通过 Excel COM 生成真实数据透视表（工作簿由 build_workbook.py 先生成）
# 用法：powershell -ExecutionPolicy Bypass -File scripts\build_pivot.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$src = Join-Path $root "excel\ERP经营分析_数据源.xlsx"
$dst = Join-Path $root "excel\ERP经营分析_透视表.xlsx"

if (-not (Test-Path $src)) { throw "先执行 python excel/build_workbook.py 生成源工作簿" }

# Excel 常量
$xlDatabase = 1
$xlRowField = 1
$xlColumnField = 2
$xlPageField = 3
$xlDataField = 4
$xlSum = -4157
$xlCount = -4112
$xlOpenXMLWorkbook = 51

$xl = New-Object -ComObject Excel.Application
$xl.Visible = $false
$xl.DisplayAlerts = $false
$xl.ScreenUpdating = $false

try {
    Write-Output "opening workbook..."
    $wb = $xl.Workbooks.Open($src)

    function New-PivotSheet($sheetName, $sourceSheet, $rows, $dataFields, $pageFields) {
        $ws = $wb.Worksheets.Add()
        $ws.Name = $sheetName
        $used = $wb.Worksheets.Item($sourceSheet).UsedRange
        $src_addr = "'" + $sourceSheet + "'!" + $used.Address($true, $true, 1, $true)
        $cache = $wb.PivotCaches().Create($xlDatabase, $src_addr, 6)
        $pt = $cache.CreatePivotTable($ws.Range("A3"), ("pt_" + $sheetName))
        $i = 1
        foreach ($r in $rows) {
            $pf = $pt.PivotFields($r)
            $pf.Orientation = $xlRowField
            $pf.Position = $i
            $i++
        }
        foreach ($p in $pageFields) {
            $pf = $pt.PivotFields($p)
            $pf.Orientation = $xlPageField
            $pf.Position = 1
        }
        foreach ($d in $dataFields) {
            $df = $pt.AddDataField($pt.PivotFields($d.Field), $d.Name, $d.Func)
            if ($d.Format) { $df.NumberFormat = $d.Format }
        }
        $pt.TableStyle2 = "PivotStyleMedium9"
        Write-Output ("  pivot ready: " + $sheetName)
        return $pt
    }

    # 1) 品类营收透视（行：品类；值：营收合计、销量合计）
    New-PivotSheet -sheetName "透视_品类营收" -sourceSheet "商品销售明细" `
        -rows @("category") `
        -dataFields @(
            @{ Field = "revenue_amount"; Name = "营收"; Func = $xlSum; Format = "#,##0" },
            @{ Field = "qty"; Name = "销量"; Func = $xlSum; Format = "#,##0" }
        ) -pageFields @() | Out-Null

    # 2) 客户层级透视（行：客户层级、行业；值：营收、订单数）
    New-PivotSheet -sheetName "透视_客户结构" -sourceSheet "订单明细表" `
        -rows @("customer_tier", "customer_industry") `
        -dataFields @(
            @{ Field = "net_amount"; Name = "营收"; Func = $xlSum; Format = "#,##0" },
            @{ Field = "order_no"; Name = "订单数"; Func = $xlCount; Format = "#,##0" }
        ) -pageFields @("quarter") | Out-Null

    # 3) 月度营收透视（行：年-月；值：营收、订单数）
    New-PivotSheet -sheetName "透视_月度趋势" -sourceSheet "订单明细表" `
        -rows @("year_month") `
        -dataFields @(
            @{ Field = "net_amount"; Name = "营收"; Func = $xlSum; Format = "#,##0" },
            @{ Field = "order_id"; Name = "订单数"; Func = $xlCount; Format = "#,##0" }
        ) -pageFields @() | Out-Null

    # 4) 销售漏斗与 AI 对照透视（行：阶段；值：商机数、成单数；筛选：AI 辅助标记）
    New-PivotSheet -sheetName "透视_漏斗与AI" -sourceSheet "线索商机" `
        -rows @("stage") `
        -dataFields @(
            @{ Field = "lead_id"; Name = "商机数"; Func = $xlCount; Format = "#,##0" },
            @{ Field = "actual_amount"; Name = "成单金额"; Func = $xlSum; Format = "#,##0" }
        ) -pageFields @("ai_assisted") | Out-Null

    # 校验：读取公式页的计算结果
    $calc = $wb.Worksheets.Item("透视预分析")
    Write-Output "--- 公式页校验（品类营收 SUMIFS）---"
    for ($r = 3; $r -le 10; $r++) {
        $cat = $calc.Cells.Item($r, 1).Text
        $rev = $calc.Cells.Item($r, 2).Value2
        $mar = $calc.Cells.Item($r, 4).Value2
        if ($cat) { Write-Output ("  {0}: 营收 {1}  毛利率 {2}" -f $cat, $rev, $mar) }
    }

    $wb.SaveAs($dst, $xlOpenXMLWorkbook)
    $wb.Close($false)
    Write-Output ("saved: " + $dst)
}
finally {
    $xl.Quit()
    [System.Runtime.InteropServices.Marshal]::ReleaseComObject($xl) | Out-Null
    [GC]::Collect()
}
