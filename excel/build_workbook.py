"""生成 Excel 作品集工作簿（事实表 + 字段字典 + 公式预分析）。

用法：
    python excel/build_workbook.py

产出：
    excel/ERP经营分析_数据源.xlsx
        · 说明页（口径来源、复现命令、账号）
        · 字段字典页
        · 各维度表 / 事实表（带表头样式、冻结首行、自动筛选）
        · 透视预分析页（用 SUMIFS / COUNTIFS 公式实现，无需透视表即可看到结果）
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path
from typing import Dict, List

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.table import Table, TableStyleInfo

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "excel" / "data"
OUT = ROOT / "excel" / "ERP经营分析_数据源.xlsx"

HEADER_FILL = PatternFill("solid", fgColor="1F3864")
HEADER_FONT = Font(color="FFFFFF", bold=True, size=10.5)
TITLE_FONT = Font(bold=True, size=13, color="1F3864")
BORDER = Border(*[Side(style="thin", color="D9D9D9")] * 4)

SHEETS = [
    ("fact_sales_order_flat", "订单明细表", "销售订单主表（已展平客户/销售/日期维度）"),
    ("fact_sales_order_item_flat", "商品销售明细", "订单行级明细，含品类/品牌/数量/收入/成本"),
    ("fact_inventory_snapshot_flat", "库存快照", "月末库存：在手、安全库存、缺口、库存金额"),
    ("fact_lead_opportunity_flat", "线索商机", "线索→成单漏斗，含 AI 辅助标记与销售周期"),
    ("fact_customer_ticket_flat", "客服工单", "工单响应、满意度与转商机"),
    ("fact_marketing_spend_flat", "营销投放", "渠道成本、线索、CAC、ROAS"),
    ("fact_ai_usage_flat", "AI使用记录", "AI 助手查询、采纳与节省工时"),
    ("dim_customer", "客户维度", "客户分层、行业、区域、客户经理"),
    ("dim_product", "商品维度", "SKU、品类、品牌、成本与标价"),
    ("dim_employee", "员工维度", "销售团队与角色"),
    ("dim_date", "日期维度", "年/季/月/周/是否周末"),
]

MONEY_HINT = ("amount", "revenue", "cost", "profit", "value", "price", "spend", "cac", "roas")
RATIO_HINT = ("rate", "margin", "probability")


def read_csv(name: str) -> tuple[List[str], List[List[str]]]:
    path = DATA_DIR / f"{name}.csv"
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.reader(fh)
        headers = next(reader)
        rows = [r for r in reader]
    return headers, rows


def style_sheet(ws, headers: List[str], rows: List[List[str]], freeze: str = "A2") -> None:
    ws.append(headers)
    for cell in ws[1]:
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = BORDER
    for row in rows:
        ws.append(row)
    ws.freeze_panes = freeze
    ws.auto_filter.ref = ws.dimensions
    ws.row_dimensions[1].height = 22

    for idx, name in enumerate(headers, start=1):
        lower = name.lower()
        width = 14
        if any(k in lower for k in ("name", "名称", "客户", "商品")):
            width = 26
        elif any(k in lower for k in MONEY_HINT):
            width = 16
        elif any(k in lower for k in RATIO_HINT) or lower.endswith("pct"):
            width = 12
        elif lower.endswith("_id") or lower.endswith("date") or lower in ("year", "month", "quarter"):
            width = 15
        ws.column_dimensions[get_column_letter(idx)].width = width
        col = get_column_letter(idx)
        if any(k in lower for k in MONEY_HINT):
            for r in range(2, min(ws.max_row, 200) + 1):
                ws[f"{col}{r}"].number_format = "#,##0.00"
        elif any(k in lower for k in RATIO_HINT) or lower.endswith("pct"):
            for r in range(2, min(ws.max_row, 200) + 1):
                ws[f"{col}{r}"].number_format = "0.00%"


def build() -> Path:
    wb = Workbook()

    # ---------------- 说明页 ----------------
    ws = wb.active
    ws.title = "说明"
    ws.column_dimensions["A"].width = 22
    ws.column_dimensions["B"].width = 104
    rows = [
        ("工作簿", "ERP Analytics Lab · 经营分析数据源（Excel 透视表作品集）"),
        ("业务背景", "工业自动化零部件 B2B 经销商，24 个月模拟经营数据（2024-01-01 ~ 2025-12-31）"),
        ("数据性质", "确定性模拟数据（随机种子 42），任何机器执行 python scripts/seed_db.py 生成的结果完全一致"),
        ("口径来源", "docs/数据字典与业务口径.md —— 本工作簿所有指标口径与该文档一致"),
        ("营收口径", "net_amount 求和，仅统计 status = '已完成'；已退款订单不计入营收"),
        ("毛利口径", "gross_profit 求和；毛利率 = 毛利 ÷ 营收"),
        ("库存对账", "期初建账 + 采购入库 − 销售出库 + 退货入库 − 报废 = 月末快照（差异为 0）"),
        ("透视表操作", "见 excel/pivot_guide.md；或直接看「透视预分析」页的 SUMIFS 公式结果"),
        ("BI 对应", "bi/powerbi（Power Query M + DAX）与 bi/tableau（计算字段 + 工作表规格）使用同一套 CSV"),
        ("复现命令", "pip install -r requirements.txt && python scripts/seed_db.py --reset && python excel/build_workbook.py"),
        ("演示账号", "analyst / Analyst@123456（只读分析）；sales / Sales@123456（可下单）"),
        ("生成时间", ""),
    ]
    from datetime import datetime
    rows[-1] = ("生成时间", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    ws.append(["项", "说明"])
    for cell in ws[1]:
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
    for k, v in rows:
        ws.append([k, v])
    for r in range(2, ws.max_row + 1):
        ws[f"A{r}"].font = Font(bold=True, color="1F3864")
        ws[f"A{r}"].alignment = Alignment(vertical="center")
        ws[f"B{r}"].alignment = Alignment(wrap_text=True, vertical="center")
        ws.row_dimensions[r].height = 30

    # ---------------- 字段字典页 ----------------
    ws = wb.create_sheet("字段字典")
    dict_rows: List[List[str]] = []
    for name, sheet_name, desc in SHEETS:
        headers, _ = read_csv(name)
        for h in headers:
            dtype = "文本"
            if any(k in h.lower() for k in MONEY_HINT):
                dtype = "数值(金额)"
            elif any(k in h.lower() for k in RATIO_HINT):
                dtype = "数值(比率)"
            elif h.lower().endswith("_id") or h.lower().endswith("id"):
                dtype = "整数(键)"
            elif "date" in h.lower() or h.lower().endswith("_at"):
                dtype = "日期"
            dict_rows.append([sheet_name, h, dtype, desc])
    ws.append(["工作表", "字段", "类型", "说明"])
    for cell in ws[1]:
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
    for r in dict_rows:
        ws.append(r)
    for col, w in zip("ABCD", (22, 30, 14, 52)):
        ws.column_dimensions[col].width = w
    ws.freeze_panes = "A2"

    # ---------------- 数据页 ----------------
    for name, sheet_name, desc in SHEETS:
        headers, rows = read_csv(name)
        ws = wb.create_sheet(sheet_name[:31])
        style_sheet(ws, headers, rows)
        ws["A1"].comment = None

    # ---------------- 透视预分析页（公式实现） ----------------
    # 列字母从真实表头动态推导，避免手写字母错位
    item_head, _ = read_csv("fact_sales_order_item_flat")
    order_head, _ = read_csv("fact_sales_order_flat")
    lead_head, _ = read_csv("fact_lead_opportunity_flat")

    def col(headers, field):
        return get_column_letter(headers.index(field) + 1)

    ITEM, ORDER, LEAD = "'商品销售明细'", "'订单明细表'", "'线索商机'"
    i_cat, i_rev, i_cost = col(item_head, "category"), col(item_head, "revenue_amount"), col(item_head, "cost_amount")
    o_tier, o_net = col(order_head, "customer_tier"), col(order_head, "net_amount")
    o_quarter, o_status = col(order_head, "quarter"), col(order_head, "order_status")
    l_stage, l_ai = col(lead_head, "stage"), col(lead_head, "ai_assisted")
    ws = wb.create_sheet("透视预分析")
    ws.column_dimensions["A"].width = 24
    ws.column_dimensions["B"].width = 18
    ws.column_dimensions["C"].width = 18
    ws.column_dimensions["D"].width = 18
    ws.append(["维度：品类营收（SUMIFS 透视等价）", "", "", ""])
    ws["A1"].font = TITLE_FONT
    ws.append(["品类", "营收", "毛利", "毛利率"])
    for c in ws[2]:
        c.fill = HEADER_FILL
        c.font = HEADER_FONT
    cats = ["工业传感器", "伺服电机", "PLC控制器", "精密减速机", "变频器", "气动元件", "工业交换机", "电源模块"]
    for i, cat in enumerate(cats, start=3):
        ws.cell(i, 1, cat)
        ws.cell(i, 2, f'=SUMIFS({ITEM}!{i_rev}:{i_rev},{ITEM}!{i_cat}:{i_cat},$A{i})')
        ws.cell(i, 3, f'=SUMIFS({ITEM}!{i_cost}:{i_cost},{ITEM}!{i_cat}:{i_cat},$A{i})')
        ws.cell(i, 4, f'=IFERROR((B{i}-C{i})/B{i},0)')
        ws.cell(i, 2).number_format = "#,##0.00"
        ws.cell(i, 3).number_format = "#,##0.00"
        ws.cell(i, 4).number_format = "0.00%"

    start = len(cats) + 5
    ws.cell(start, 1, "维度：客户层级（COUNTIFS / SUMIFS 透视等价）").font = TITLE_FONT
    ws.append(["层级", "订单数", "营收", "客单价"])
    for c in ws[start + 1]:
        c.fill = HEADER_FILL
        c.font = HEADER_FONT
    for i, tier in enumerate(["A", "B", "C"], start=start + 2):
        ws.cell(i, 1, tier)
        ws.cell(i, 2, f'=COUNTIFS({ORDER}!{o_tier}:{o_tier},$A{i},{ORDER}!{o_status}:{o_status},"已完成")')
        ws.cell(i, 3, f'=SUMIFS({ORDER}!{o_net}:{o_net},{ORDER}!{o_tier}:{o_tier},$A{i},{ORDER}!{o_status}:{o_status},"已完成")')
        ws.cell(i, 4, f'=IFERROR(C{i}/B{i},0)')
        ws.cell(i, 3).number_format = "#,##0.00"
        ws.cell(i, 4).number_format = "#,##0.00"

    mstart = start + 7
    ws.cell(mstart, 1, "维度：季度营收（透视等价）").font = TITLE_FONT
    ws.append(["季度", "营收", "订单数", "环比"])
    for c in ws[mstart + 1]:
        c.fill = HEADER_FILL
        c.font = HEADER_FONT
    quarters = ["2024Q1", "2024Q2", "2024Q3", "2024Q4", "2025Q1", "2025Q2", "2025Q3", "2025Q4"]
    for i, q in enumerate(quarters, start=mstart + 2):
        ws.cell(i, 1, q)
        ws.cell(i, 2, f'=SUMIFS({ORDER}!{o_net}:{o_net},{ORDER}!{o_quarter}:{o_quarter},$A{i},{ORDER}!{o_status}:{o_status},"已完成")')
        ws.cell(i, 3, f'=COUNTIFS({ORDER}!{o_quarter}:{o_quarter},$A{i},{ORDER}!{o_status}:{o_status},"已完成")')
        if i > mstart + 2:
            ws.cell(i, 4, f'=IFERROR((B{i}-B{i-1})/B{i-1},0)')
            ws.cell(i, 4).number_format = "0.00%"
        ws.cell(i, 2).number_format = "#,##0.00"

    astart = mstart + len(quarters) + 4
    ws.cell(astart, 1, "AI 辅助商机对照（SUMIFS 透视等价）").font = TITLE_FONT
    ws.append(["AI 辅助", "商机数", "成单数", "成单率"])
    for c in ws[astart + 1]:
        c.fill = HEADER_FILL
        c.font = HEADER_FONT
    for i, (label, flag) in enumerate([("AI 辅助", 1), ("对照组", 0)], start=astart + 2):
        ws.cell(i, 1, label)
        ws.cell(i, 2, f'=COUNTIFS({LEAD}!{l_ai}:{l_ai},{flag})')
        ws.cell(i, 3, f'=COUNTIFS({LEAD}!{l_ai}:{l_ai},{flag},{LEAD}!{l_stage}:{l_stage},"成单")')
        ws.cell(i, 4, f'=IFERROR(C{i}/B{i},0)')
        ws.cell(i, 4).number_format = "0.00%"

    add_pivot_result_sheets(wb)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    wb.save(OUT)
    return OUT


# ============================================================================
# 透视结果页（静态预聚合 + 合计行 + 占比列）
# 说明：本机 Excel 许可过期处于只读模式，无法用 COM 生成真正的数据透视表对象。
# 这里用与 SQL 完全一致的口径在 Python 侧预聚合成「透视结果」静态页；
# 同时保留「透视预分析」页的 SUMIFS 公式作为交叉验证；
# 激活 Office 后可运行 excel/pivot_macro.bas 一键生成 4 个真实数据透视表对象。
# ============================================================================
def add_pivot_result_sheets(wb: Workbook) -> None:
    from collections import defaultdict

    order_headers, order_rows = read_csv("fact_sales_order_flat")
    item_headers, item_rows = read_csv("fact_sales_order_item_flat")
    lead_headers, lead_rows = read_csv("fact_lead_opportunity_flat")

    def idx(headers, field):
        return headers.index(field)

    # ---- 品类营收 ----
    agg = defaultdict(lambda: {"revenue": 0.0, "cost": 0.0, "qty": 0})
    for row in item_rows:
        cat = row[idx(item_headers, "category")]
        agg[cat]["revenue"] += float(row[idx(item_headers, "revenue_amount")])
        agg[cat]["cost"] += float(row[idx(item_headers, "cost_amount")])
        agg[cat]["qty"] += int(float(row[idx(item_headers, "qty")]))
    total_rev = sum(v["revenue"] for v in agg.values()) or 1

    ws = wb.create_sheet("透视结果_品类营收")
    ws.append(["品类", "营收", "销量", "营收占比", "毛利率"])
    for c in ws[1]:
        c.fill = HEADER_FILL
        c.font = HEADER_FONT
    for cat, v in sorted(agg.items(), key=lambda kv: -kv[1]["revenue"]):
        ws.append([cat, round(v["revenue"], 2), v["qty"], v["revenue"] / total_rev,
                    (v["revenue"] - v["cost"]) / v["revenue"] if v["revenue"] else 0])
    ws.append(["合计", round(total_rev, 2), sum(v["qty"] for v in agg.values()), 1.0,
                sum(v["revenue"] - v["cost"] for v in agg.values()) / total_rev])
    for c in ws[ws.max_row]:
        c.font = Font(bold=True, color="1F3864")
    for r in range(2, ws.max_row + 1):
        ws.cell(r, 2).number_format = "#,##0.00"
        ws.cell(r, 3).number_format = "#,##0"
        ws.cell(r, 4).number_format = "0.00%"
        ws.cell(r, 5).number_format = "0.00%"
    for col, w in zip("ABCDE", (20, 18, 12, 12, 12)):
        ws.column_dimensions[col].width = w

    # ---- 客户层级 × 行业 ----
    agg2 = defaultdict(lambda: {"revenue": 0.0, "orders": 0})
    for row in order_rows:
        if row[idx(order_headers, "order_status")] != "已完成":
            continue
        key = (row[idx(order_headers, "customer_tier")], row[idx(order_headers, "customer_industry")])
        agg2[key]["revenue"] += float(row[idx(order_headers, "net_amount")])
        agg2[key]["orders"] += 1
    ws = wb.create_sheet("透视结果_客户结构")
    ws.append(["客户层级", "行业", "营收", "订单数", "客单价"])
    for c in ws[1]:
        c.fill = HEADER_FILL
        c.font = HEADER_FONT
    for (tier, industry), v in sorted(agg2.items(), key=lambda kv: (kv[0][0], -kv[1]["revenue"])):
        ws.append([tier, industry, round(v["revenue"], 2), v["orders"],
                   round(v["revenue"] / v["orders"], 2) if v["orders"] else 0])
    for r in range(2, ws.max_row + 1):
        ws.cell(r, 3).number_format = "#,##0.00"
        ws.cell(r, 5).number_format = "#,##0.00"
    for col, w in zip("ABCDE", (14, 20, 18, 12, 14)):
        ws.column_dimensions[col].width = w

    # ---- 月度趋势（含同比/环比） ----
    months = sorted({row[idx(order_headers, "year_month")] for row in order_rows})
    monthly = {}
    for row in order_rows:
        if row[idx(order_headers, "order_status")] != "已完成":
            continue
        ym = row[idx(order_headers, "year_month")]
        rec = monthly.setdefault(ym, {"revenue": 0.0, "orders": 0})
        rec["revenue"] += float(row[idx(order_headers, "net_amount")])
        rec["orders"] += 1
    ws = wb.create_sheet("透视结果_月度趋势")
    ws.append(["年月", "营收", "订单数", "环比", "同比"])
    for c in ws[1]:
        c.fill = HEADER_FILL
        c.font = HEADER_FONT
    for i, ym in enumerate(months):
        rec = monthly.get(ym, {"revenue": 0.0, "orders": 0})
        ym_prev = months[i - 1] if i > 0 else None
        ym_yoy = f"{int(ym[:4]) - 1}-{ym[5:]}"
        mom = ""
        if ym_prev and monthly.get(ym_prev, {}).get("revenue"):
            mom = (rec["revenue"] - monthly[ym_prev]["revenue"]) / monthly[ym_prev]["revenue"]
        yoy = ""
        if ym_yoy in monthly and monthly[ym_yoy]["revenue"]:
            yoy = (rec["revenue"] - monthly[ym_yoy]["revenue"]) / monthly[ym_yoy]["revenue"]
        ws.append([ym, round(rec["revenue"], 2), rec["orders"], mom, yoy])
    for r in range(2, ws.max_row + 1):
        ws.cell(r, 2).number_format = "#,##0.00"
        ws.cell(r, 4).number_format = "0.00%"
        ws.cell(r, 5).number_format = "0.00%"
    for col, w in zip("ABCDE", (14, 18, 12, 12, 12)):
        ws.column_dimensions[col].width = w

    # ---- 漏斗与 AI 对照 ----
    stage_stat = defaultdict(lambda: {"count": 0, "won": 0, "ai": 0, "cycle": 0.0, "amount": 0.0})
    for row in lead_rows:
        st = row[idx(lead_headers, "stage")]
        rec = stage_stat[st]
        rec["count"] += 1
        rec["ai"] += int(row[idx(lead_headers, "ai_assisted")])
        rec["cycle"] += float(row[idx(lead_headers, "cycle_days")])
        if st == "成单":
            rec["won"] += 1
            rec["amount"] += float(row[idx(lead_headers, "actual_amount")])
    ws = wb.create_sheet("透视结果_漏斗与AI")
    ws.append(["阶段", "商机数", "成单数", "成单率", "AI辅助占比", "平均周期(天)"])
    for c in ws[1]:
        c.fill = HEADER_FILL
        c.font = HEADER_FONT
    for st in ["线索", "需求确认", "方案演示", "商务谈判", "成单", "输单"]:
        rec = stage_stat.get(st)
        if not rec:
            continue
        ws.append([st, rec["count"], rec["won"], rec["won"] / rec["count"],
                   rec["ai"] / rec["count"], round(rec["cycle"] / rec["count"], 1)])
    for r in range(2, ws.max_row + 1):
        ws.cell(r, 4).number_format = "0.00%"
        ws.cell(r, 5).number_format = "0.00%"
        ws.cell(r, 6).number_format = "0.0"
    for col, w in zip("ABCDEF", (16, 12, 12, 12, 14, 16)):
        ws.column_dimensions[col].width = w


if __name__ == "__main__":
    path = build()
    print(f"generated: {path}")
