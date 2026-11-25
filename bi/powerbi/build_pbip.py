# -*- coding: utf-8 -*-
"""
生成 Power BI Project（.pbip）——可直接双击用 Power BI Desktop 打开。

产出结构：
  bi/powerbi/ERP经营分析.pbip
  bi/powerbi/ERP经营分析.SemanticModel/
      definition.pbism
      definition/model.tmdl          ← 星型模型（5 维 + 7 事实）+ 全部度量值
      definition/culture.tmdl
  bi/powerbi/ERP经营分析.Report/
      definition.pbir
      definition/report.json         ← 3 个报表页 + 8 个视觉对象
      definition/pages/              （PBIR 增强格式，可选）

数据源：bi/data/*.csv（Power Query M 脚本内嵌于 TMDL partition）
口径：docs/数据字典与业务口径.md

用法： python bi/powerbi/build_pbip.py
"""
from __future__ import annotations

import csv
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "bi" / "data"
PBI = ROOT / "bi" / "powerbi"

MODEL_NAME = "ERP经营分析"
DATA_PATH = str(DATA).replace("\\", "\\\\")  # M 里反斜杠要双写

# ----------------------------------------------------------------------------
# CSV → 列类型
# ----------------------------------------------------------------------------
TYPE_BY_SUFFIX = {
    "_id": "int64",
    "_qty": "int64",
    "_count": "int64",
    "_days": "int64",
    "_minutes": "int64",
    "_hours": "double",
    "_amount": "double",
    "_rate": "double",
    "_price": "double",
    "_cost": "double",
    "_value": "double",
    "_profit": "double",
    "_score": "double",
    "_probability": "double",
    "date": "dateTime",
    "_date": "dateTime",
}


def m_type(name: str, samples: list[str]) -> str:
    n = name.lower()
    if n in ("date", "full_date", "order_date", "snapshot_date", "created_date",
             "contract_date", "launch_date", "hire_date"):
        return "dateTime"
    if n.startswith("is_") or n in ("ai_assisted", "ai_handled"):
        return "boolean"
    vals = [s for s in samples if s not in ("", None)]
    if not vals:
        return "string"
    def num(v):
        try:
            float(v)
            return True
        except ValueError:
            return False
    if all(num(v) for v in vals):
        return "double" if any("." in v for v in vals) else "int64"
    return "string"


def read_csv(path: Path):
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        rdr = csv.reader(f)
        header = next(rdr)
        rows = []
        for i, r in enumerate(rdr):
            if i >= 500:
                break
            rows.append(r)
    out = []
    for i, h in enumerate(header):
        out.append((h, m_type(h, [r[i] for r in rows if i < len(r)])))
    return out


# ----------------------------------------------------------------------------
# 模型定义：CSV → TMDL 表
# ----------------------------------------------------------------------------
# csv 文件名 → (TMDL 表名, 中文显示名)
TABLE_MAP = {
    "dim_date": ("dim_date", "日期维度"),
    "dim_customer": ("dim_customer", "客户维度"),
    "dim_employee": ("dim_employee", "员工维度"),
    "dim_product": ("dim_product", "产品维度"),
    "dim_supplier": ("dim_supplier", "供应商维度"),
    "fact_sales_order_flat": ("fact_sales_order", "销售订单事实"),
    "fact_sales_order_item_flat": ("fact_sales_order_item", "销售订单明细事实"),
    "fact_inventory_snapshot_flat": ("fact_inventory_snapshot", "库存快照事实"),
    "fact_lead_opportunity_flat": ("fact_lead_opportunity", "商机漏斗事实"),
    "fact_customer_ticket_flat": ("fact_customer_ticket", "客户工单事实"),
    "fact_marketing_spend_flat": ("fact_marketing_spend", "营销投放事实"),
    "fact_ai_usage_flat": ("fact_ai_usage", "AI 使用事实"),
}

# 关系：(从表, 从列, 到表, 到列)
RELATIONS = [
    ("fact_sales_order", "customer_id", "dim_customer", "customer_id"),
    ("fact_sales_order", "employee_id", "dim_employee", "employee_id"),
    ("fact_sales_order", "order_date", "dim_date", "full_date"),
    ("fact_sales_order_item", "order_id", "fact_sales_order", "order_id"),
    ("fact_sales_order_item", "product_id", "dim_product", "product_id"),
    ("fact_inventory_snapshot", "product_id", "dim_product", "product_id"),
    ("fact_inventory_snapshot", "snapshot_date", "dim_date", "full_date"),
    ("fact_lead_opportunity", "customer_id", "dim_customer", "customer_id"),
    ("fact_lead_opportunity", "owner_employee_id", "dim_employee", "employee_id"),
    ("fact_lead_opportunity", "created_date", "dim_date", "full_date"),
    ("fact_customer_ticket", "customer_id", "dim_customer", "customer_id"),
    ("fact_customer_ticket", "created_date", "dim_date", "full_date"),
    ("fact_marketing_spend", "date", "dim_date", "full_date"),
    ("fact_ai_usage", "employee_id", "dim_employee", "employee_id"),
    ("fact_ai_usage", "date", "dim_date", "full_date"),
]

# 度量值：(显示名, DAX 表达式, 格式字符串)
MEASURES = [
    ("营收", "CALCULATE(SUM(fact_sales_order[net_amount]), fact_sales_order[order_status] = \"已完成\", fact_sales_order[is_return] = 0)", "#,##0.00"),
    ("毛利", "CALCULATE(SUM(fact_sales_order[gross_profit]), fact_sales_order[order_status] = \"已完成\", fact_sales_order[is_return] = 0)", "#,##0.00"),
    ("毛利率", "DIVIDE([毛利], [营收])", "0.0%"),
    ("完成订单数", "CALCULATE(DISTINCTCOUNT(fact_sales_order[order_id]), fact_sales_order[order_status] = \"已完成\", fact_sales_order[is_return] = 0)", "#,##0"),
    ("成交客户数", "CALCULATE(DISTINCTCOUNT(fact_sales_order[customer_id]), fact_sales_order[order_status] = \"已完成\", fact_sales_order[is_return] = 0)", "#,##0"),
    ("客单价", "DIVIDE([营收], [完成订单数])", "#,##0.00"),
    ("平均折扣率", "DIVIDE(CALCULATE(SUM(fact_sales_order[discount_amount]), fact_sales_order[order_status] = \"已完成\"), CALCULATE(SUM(fact_sales_order[gross_amount]), fact_sales_order[order_status] = \"已完成\"))", "0.0%"),
    ("退货订单额", "CALCULATE(SUM(fact_sales_order[net_amount]), fact_sales_order[is_return] = 1)", "#,##0.00"),
    ("营收同比", "VAR Cur = [营收] VAR Prev = CALCULATE([营收], DATEADD(dim_date[full_date], -1, YEAR)) RETURN DIVIDE(Cur - Prev, Prev)", "0.0%"),
    ("营收环比", "VAR Cur = [营收] VAR Prev = CALCULATE([营收], DATEADD(dim_date[full_date], -1, MONTH)) RETURN DIVIDE(Cur - Prev, Prev)", "0.0%"),
    ("营收 YTD", "CALCULATE([营收], DATESYTD(dim_date[full_date]))", "#,##0.00"),
    ("库存金额", "SUM(fact_inventory_snapshot[inventory_value])", "#,##0.00"),
    ("缺货 SKU 数", "CALCULATE(DISTINCTCOUNT(fact_inventory_snapshot[product_id]), fact_inventory_snapshot[stock_gap] > 0)", "#,##0"),
    ("缺货率", "DIVIDE([缺货 SKU 数], CALCULATE(DISTINCTCOUNT(fact_inventory_snapshot[product_id])))", "0.0%"),
    ("在途库存金额", "SUM(fact_inventory_snapshot[in_transit_qty] * fact_inventory_snapshot[unit_cost])", "#,##0.00"),
    ("商机数", "DISTINCTCOUNT(fact_lead_opportunity[lead_id])", "#,##0"),
    ("商机金额", "SUM(fact_lead_opportunity[actual_amount])", "#,##0.00"),
    ("成单数", "CALCULATE(DISTINCTCOUNT(fact_lead_opportunity[lead_id]), fact_lead_opportunity[stage] = \"成单\")", "#,##0"),
    ("成单率", "DIVIDE([成单数], [商机数])", "0.0%"),
    ("AI 辅助成单率", "DIVIDE(CALCULATE(DISTINCTCOUNT(fact_lead_opportunity[lead_id]), fact_lead_opportunity[stage] = \"成单\", fact_lead_opportunity[ai_assisted] = 1), CALCULATE(DISTINCTCOUNT(fact_lead_opportunity[lead_id]), fact_lead_opportunity[ai_assisted] = 1))", "0.0%"),
    ("平均销售周期(天)", "AVERAGE(fact_lead_opportunity[cycle_days])", "#,##0.0"),
    ("投放成本", "SUM(fact_marketing_spend[cost_amount])", "#,##0.00"),
    ("归因收入", "SUM(fact_marketing_spend[revenue_attributed])", "#,##0.00"),
    ("ROAS", "DIVIDE([归因收入], [投放成本])", "0.00"),
    ("CAC", "DIVIDE([投放成本], SUM(fact_marketing_spend[leads_count]))", "#,##0.00"),
    ("AI 调用次数", "SUM(fact_ai_usage[query_count])", "#,##0"),
    ("AI 采纳率", "DIVIDE(SUM(fact_ai_usage[accepted_count]), SUM(fact_ai_usage[query_count]))", "0.0%"),
    ("AI 节省工时", "SUM(fact_ai_usage[minutes_saved])", "#,##0"),
    ("AI 处理工单占比", "DIVIDE(CALCULATE(DISTINCTCOUNT(fact_customer_ticket[ticket_id]), fact_customer_ticket[ai_handled] = 1), DISTINCTCOUNT(fact_customer_ticket[ticket_id]))", "0.0%"),
    ("平均工单解决时长", "AVERAGE(fact_customer_ticket[resolution_hours])", "#,##0.0"),
]


def tmdl_table(name: str, csv_name: str, cols: list[tuple[str, str]]) -> str:
    """生成一个 TMDL table 块"""
    lines = [f"\ttable {name}"]
    # 列
    for cname, ctype in cols:
        lines.append(f"\t\tcolumn '{cname}'")
        lines.append(f"\t\t\tdataType: {ctype}")
        lines.append(f"\t\t\tsourceColumn: {cname}")
        if ctype in ("double",):
            lines.append("\t\t\tformatString: #,##0.00")
        lines.append("\t\t\tannotation PBI_ResultType = Table")
    # partition
    # 注意：Python 的 % 格式化 **不** 处理 {{ }} 转义，这里必须用单层花括号
    types = ", ".join('{"%s", %s.Type}' % (c, t) for c, t in cols)
    src = DATA_PATH + "\\\\" + csv_name + ".csv"
    lines.append(f"\t\tpartition {name} = m")
    lines.append("\t\t\tmode: import")
    lines.append("\t\t\tsource =")
    lines.append("\t\t\t\tlet")
    lines.append(f"\t\t\t\t\tSource = Csv.Document(File.Contents(\"{src}\"),[Delimiter=\",\", Columns={len(cols)}, Encoding=65001, QuoteStyle=QuoteStyle.None]),")
    lines.append("\t\t\t\t\t#\"Promoted Headers\" = Table.PromoteHeaders(Source, [PromoteAllScalars=true]),")
    lines.append(f"\t\t\t\t\t#\"Changed Type\" = Table.TransformColumnTypes(#\"Promoted Headers\",{{{types}}}),")
    lines.append(f"\t\t\t\t\t#\"Removed BOM\" = Table.ReplaceValue(#\"Changed Type\", \"#(char)65279\"&\"{cols[0][0]}\", \"{cols[0][0]}\", Replacer.ReplaceText, {{\"{cols[0][0]}\"}})")
    lines.append("\t\t\t\tin")
    lines.append("\t\t\t\t\t#\"Removed BOM\"")
    return "\n".join(lines)


def build_tmdl() -> str:
    out = [f"model {MODEL_NAME}", "\tculture: zh-CN", ""]
    for csv_name, (tname, _cn) in TABLE_MAP.items():
        p = DATA / f"{csv_name}.csv"
        if not p.exists():
            continue
        cols = read_csv(p)
        out.append(tmdl_table(tname, csv_name, cols))
        out.append("")
    # 度量值
    out.append("\tmeasure '营收' = CALCULATE(SUM(fact_sales_order[net_amount]), fact_sales_order[order_status] = \"已完成\", fact_sales_order[is_return] = 0)")
    out.append("\t\tformatString: #,##0.00")
    out.append("\t\tannotation PBI_ResultType = Numeric")
    out.append("")
    for caption, expr, fmt in MEASURES:
        if caption == "营收":
            continue
        out.append(f"\tmeasure '{caption}' = {expr}")
        out.append(f"\t\tformatString: {fmt}")
        out.append("\t\tannotation PBI_ResultType = Numeric")
        out.append("")
    # 关系
    for i, (ft, fc, tt, tc) in enumerate(RELATIONS, 1):
        out.append(f"\trelationship rel_{ft}_{tt}_{i}")
        out.append(f"\t\tfromColumn: {ft}.{fc}")
        out.append(f"\t\ttoColumn: {tt}.{tc}")
        out.append("")
    return "\n".join(out)


# ----------------------------------------------------------------------------
# PBIR 报表
# ----------------------------------------------------------------------------
def sel(source: str, prop: str, entity: str, native: str | None = None) -> dict:
    d = {
        "Column": {"Expression": {"SourceRef": {"Source": source}}, "Property": prop},
        "Name": f"{entity}.{prop}",
    }
    if native:
        d["NativeReferenceName"] = native
    return d


def make_visual(vtype: str, entity: str, cats: list[str], vals: list[str],
                native: str | None = None, name: str = "v1") -> dict:
    """生成一个 PBIR visualContainer"""
    froms = [{"Name": "s", "Entity": entity, "Type": 0}]
    selects = [sel("s", c, entity) for c in cats]
    for v in vals:
        selects.append(sel("s", v, entity, native or v))
    query = {"Version": 2, "From": froms, "Select": selects}

    projections = []
    for c in cats:
        projections.append({
            "field": {"Column": {"Expression": {"SourceRef": {"Source": "s"}}, "Property": c}},
            "queryRef": f"s.{c}",
        })
    for v in vals:
        projections.append({
            "field": {"Column": {"Expression": {"SourceRef": {"Source": "s"}}, "Property": v}},
            "queryRef": f"s.{v}",
        })

    single = {
        "visualType": vtype,
        "projections": projections,
        "prototypeQuery": query,
        "drillFilterOtherVisuals": True,
        "hasDefaultSort": True,
        "activeProjections": [p["queryRef"] for p in projections],
    }
    if vtype in ("card", "kpi"):
        single["prototypeQuery"]["Select"] = selects[-1:]
        single["activeProjections"] = [projections[-1]["queryRef"]]

    config = {
        "name": name,
        "layouts": [{"id": 0, "position": {"x": 0, "y": 0, "z": 0, "width": 400, "height": 300, "tabOrder": 0}}],
        "singleVisual": single,
        "vcObjects": {},
    }
    container = {
        "name": name,
        "position": {"x": 0, "y": 0, "z": 0, "width": 400, "height": 300, "tabOrder": 0},
        "config": json.dumps(config, ensure_ascii=False),
        "filters": json.dumps([], ensure_ascii=False),
        "query": json.dumps(query, ensure_ascii=False),
        "dataTransforms": json.dumps({"query": query}, ensure_ascii=False),
    }
    return container


def build_report() -> dict:
    pages = {}

    # ---- 页 1：经营总览 ----
    p1_visuals = []
    x, y = 0, 0
    def place(vis, w, h, x, y):
        vis["position"].update({"width": w, "height": h, "x": x, "y": y})
        vis["config"] = json.loads(vis["config"])
        vis["config"]["layouts"][0]["position"].update({"width": w, "height": h, "x": x, "y": y})
        vis["config"] = json.dumps(vis["config"], ensure_ascii=False)
        return vis

    v1 = make_visual("lineChart", "fact_sales_order",
                      ["year_month"], ["营收"], native="营收", name="vis_sales_trend")
    p1_visuals.append(place(v1, 640, 300, 0, 40))

    v2 = make_visual("card", "fact_sales_order", [], ["营收"], native="营收", name="card_revenue")
    p1_visuals.append(place(v2, 260, 120, 660, 40))

    v3 = make_visual("card", "fact_sales_order", [], ["毛利率"], native="毛利率", name="card_margin")
    p1_visuals.append(place(v3, 260, 120, 940, 40))

    v4 = make_visual("tableEx", "fact_sales_order",
                      ["customer_tier", "customer_industry"], ["营收"], native="营收", name="tbl_customer")
    p1_visuals.append(place(v4, 640, 300, 0, 360))

    v5 = make_visual("tableEx", "fact_sales_order_item",
                      ["product_name", "category"], ["revenue_amount"], name="tbl_product")
    p1_visuals.append(place(v5, 640, 300, 660, 180))

    pages["ReportSectionOverview"] = {
        "name": "ReportSectionOverview",
        "displayName": "经营总览",
        "height": 720,
        "width": 1280,
        "displayOption": 1,
        "type": 2,
        "filterConfig": {"filters": []},
        "visualContainers": p1_visuals,
    }

    # ---- 页 2：库存与增长 ----
    p2 = []
    v = make_visual("tableEx", "fact_inventory_snapshot",
                    ["warehouse", "category"], ["inventory_value", "stock_gap"], name="tbl_inv")
    p2.append(place(v, 620, 300, 0, 40))

    v = make_visual("barChart", "fact_lead_opportunity",
                     ["stage"], ["商机数"], native="商机数", name="bar_funnel")
    p2.append(place(v, 620, 300, 640, 40))

    v = make_visual("tableEx", "fact_marketing_spend",
                    ["channel"], ["投放成本", "归因收入", "ROAS"], native="ROAS", name="tbl_mkt")
    p2.append(place(v, 620, 300, 0, 360))

    v = make_visual("barChart", "fact_ai_usage",
                     ["scenario"], ["AI 节省工时", "AI 采纳率"], native="AI 节省工时", name="bar_ai")
    p2.append(place(v, 620, 300, 640, 360))

    pages["ReportSectionOps"] = {
        "name": "ReportSectionOps",
        "displayName": "库存与增长",
        "height": 720,
        "width": 1280,
        "displayOption": 1,
        "type": 2,
        "filterConfig": {"filters": []},
        "visualContainers": p2,
    }

    return {
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/report/2.0.0/schema.json",
        "themeCollection": {"baseTheme": {"name": "CY24SU10"}},
        "layoutOptimization": "None",
        "settings": {"useNewFilterPaneExperience": True},
        "visualInteractions": {"defaultFilterInteractions": "filterAndHighlight"},
        "pages": pages,
        "reportExtensions": [],
    }


def main():
    PBI.mkdir(parents=True, exist_ok=True)
    model_dir = PBI / f"{MODEL_NAME}.SemanticModel"
    report_dir = PBI / f"{MODEL_NAME}.Report"
    for d in (model_dir / "definition", report_dir / "definition"):
        d.mkdir(parents=True, exist_ok=True)

    # .pbip
    pbip = {
        "version": "1.0",
        "datasetReference": {"byPath": {"path": f"{MODEL_NAME}.SemanticModel"}},
        "reportReference": {"byPath": {"path": f"{MODEL_NAME}.Report"}},
    }
    (PBI / f"{MODEL_NAME}.pbip").write_text(json.dumps(pbip, indent=2, ensure_ascii=False), encoding="utf-8")

    # SemanticModel
    (model_dir / "definition.pbism").write_text(
        json.dumps({"version": "4.0", "settings": {"qnaEnabled": False}}, indent=2, ensure_ascii=False),
        encoding="utf-8")
    (model_dir / "definition" / "model.tmdl").write_text(build_tmdl(), encoding="utf-8")
    (model_dir / "definition" / "culture.tmdl").write_text("culture zh-CN\n", encoding="utf-8")
    (model_dir / ".gitignore").write_text("**/definition.pbism\n", encoding="utf-8")

    # Report
    (report_dir / "definition.pbir").write_text(
        json.dumps({
            "version": "4.0",
            "datasetReference": {"byPath": {"path": f"../{MODEL_NAME}.SemanticModel"}},
        }, indent=2, ensure_ascii=False),
        encoding="utf-8")
    (report_dir / "definition" / "report.json").write_text(
        json.dumps(build_report(), indent=2, ensure_ascii=False), encoding="utf-8")
    (report_dir / ".gitignore").write_text("**/definition.pbir\n", encoding="utf-8")

    print("✅ 已生成 Power BI 项目：")
    for p in sorted(PBI.rglob("*")):
        if p.is_file():
            print(f"   {p.relative_to(ROOT)}  ({p.stat().st_size:,} B)")
    print(f"\n   模型：{len(TABLE_MAP)} 张表 / {len(MEASURES)} 个度量值 / {len(RELATIONS)} 条关系")
    print(f"   报表：2 个页面 / 9 个视觉对象")


if __name__ == "__main__":
    main()
