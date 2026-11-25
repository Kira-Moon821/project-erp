# -*- coding: utf-8 -*-
"""
PBIP 项目结构自检（不依赖第三方库）。

校验项：
  1. .pbip / definition.pbism / definition.pbir / report.json 均为合法 JSON
  2. TMDL：每张表声明的列在 partition 的 TransformColumnTypes 里都出现，类型一一对应
  3. TMDL：度量值引用的 表[列] 都能在对应表中找到；被引用的表都存在
  4. TMDL：关系的 fromColumn / toColumn 都能在对应表中找到
  5. report.json：每个视觉对象的 query/config/dataTransforms 都是合法 JSON 字符串；
     引用的实体名与度量值名能在模型里找到
  6. CSV 表头 == TMDL 列名（防止改名后不同步）

用法： python bi/powerbi/verify_pbip.py
"""
from __future__ import annotations

import csv
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PBI = ROOT / "bi" / "powerbi"
NAME = "ERP经营分析"
TMDL_PATH = PBI / f"{NAME}.SemanticModel" / "definition" / "model.tmdl"
REPORT_PATH = PBI / f"{NAME}.Report" / "definition" / "report.json"
DATA = ROOT / "bi" / "data"

errors: list[str] = []


def err(m):
    errors.append(m)


def main() -> int:
    # ---- 1. JSON 合法性 ----
    for p in [PBI / f"{NAME}.pbip",
              PBI / f"{NAME}.SemanticModel" / "definition.pbism",
              PBI / f"{NAME}.Report" / "definition.pbir",
              REPORT_PATH]:
        if not p.exists():
            err(f"缺文件: {p.relative_to(ROOT)}")
            continue
        try:
            json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:
            err(f"{p.name} JSON 非法: {e}")
    print("✅ 1. JSON 文件合法性检查完成")

    tmdl = TMDL_PATH.read_text(encoding="utf-8")
    lines = tmdl.splitlines()

    # ---- 解析表 / 列 / 度量 / 关系 ----
    tables: dict[str, dict[str, str]] = {}
    measures: dict[str, str] = {}
    relations: list[tuple[str, str, str, str]] = []
    cur_table = None
    cur_col = None
    for ln in lines:
        s = ln.strip()
        if s.startswith("table "):
            cur_table = s.split(" ", 1)[1].strip()
            tables.setdefault(cur_table, {})
            cur_col = None
        elif s.startswith("column "):
            cur_col = s.split("'", 2)[1]
            if cur_table:
                tables[cur_table][cur_col] = ""
        elif s.startswith("dataType: "):
            if cur_table and cur_col:
                tables[cur_table][cur_col] = s.split(": ", 1)[1]
        elif s.startswith("measure "):
            cap = s.split("'", 2)[1]
            expr = s.split("=", 1)[1].strip()
            measures[cap] = expr
        elif s.startswith("relationship "):
            relations.append([None, None, None, None])
        elif s.startswith("fromColumn: "):
            if relations:
                t, _, c = s.split(": ", 1)[1].partition(".")
                relations[-1][0], relations[-1][1] = t, c
        elif s.startswith("toColumn: "):
            if relations:
                t, _, c = s.split(": ", 1)[1].partition(".")
                relations[-1][2], relations[-1][3] = t, c
    for r in relations:
        if not r[0] or not r[1]:
            err(f"关系定义不完整: {r}")
    print(f"✅ 2. TMDL 解析完成：{len(tables)} 表 / {len(measures)} 度量 / {len(relations)} 关系")

    # ---- 3. TransformColumnTypes 类型与列一致 ----
    for m in re.finditer(r'table (\w+).*?partition \1 = m.*?Table\.TransformColumnTypes\(.*?,\{(.*?)\}\),',
                         tmdl, re.S):
        tname, block = m.group(1), m.group(2)
        pairs = re.findall(r'\{"([^"]+)",\s*([\w.]+)\}', block)
        declared = dict(pairs)
        cols = tables.get(tname, {})
        for c in cols:
            if c not in declared:
                err(f"[{tname}] 列 {c} 未出现在 TransformColumnTypes 中")
        for c, t in declared.items():
            if c not in cols:
                err(f"[{tname}] TransformColumnTypes 中的 {c} 未在列定义里出现")
            elif cols[c] and not t.lower().startswith(cols[c].lower()):
                err(f"[{tname}] 列 {c} 类型不一致：TMDL={cols[c]} vs M={t}")
    print("✅ 3. TMDL 列与 M 类型映射检查完成")

    # ---- 4. 度量值引用的表/列存在 ----
    def ref_cols(expr: str):
        return re.findall(r"([A-Za-z_][\w]*)\[([^\]]+)\]", expr)

    for cap, expr in measures.items():
        for t, c in ref_cols(expr):
            if t not in tables:
                err(f"度量值 [{cap}] 引用了不存在的表 {t}")
            elif c not in tables[t] and c not in measures:
                err(f"度量值 [{cap}] 引用了 {t} 中不存在的列 {c}")
    print("✅ 4. 度量值引用检查完成")

    # ---- 5. 关系引用存在 ----
    for ft, fc, tt, tc in relations:
        for t, c in ((ft, fc), (tt, tc)):
            if t not in tables:
                err(f"关系引用了不存在的表 {t}")
            elif c not in tables[t]:
                err(f"关系引用了 {t} 中不存在的列 {c}")
    print("✅ 5. 关系引用检查完成")

    # ---- 6. report.json 视觉对象 ----
    if REPORT_PATH.exists():
        rep = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
        for pname, page in rep.get("pages", {}).items():
            for vc in page.get("visualContainers", []):
                for key in ("config", "query", "dataTransforms"):
                    try:
                        json.loads(vc[key])
                    except Exception as e:
                        err(f"[{pname}/{vc.get('name')}] {key} 不是合法 JSON: {e}")
                q = json.loads(vc["query"])
                for frm in q.get("From", []):
                    if frm["Entity"] not in tables:
                        err(f"[{pname}/{vc.get('name')}] 引用了不存在的表 {frm['Entity']}")
                for s in q.get("Select", []):
                    prop = s["Column"]["Property"]
                    ent = s["Name"].split(".")[0]
                    if ent in tables and prop not in tables[ent] and prop not in measures:
                        err(f"[{pname}/{vc.get('name')}] 引用了 {ent} 中不存在的字段 {prop}")
        print(f"✅ 6. report.json 检查完成：{len(rep.get('pages', {}))} 页 / "
              f"{sum(len(p.get('visualContainers', [])) for p in rep.get('pages', {}).values())} 个视觉对象")

    # ---- 7. CSV 表头 vs TMDL 列 ----
    csv2tbl = {
        "dim_date": "dim_date", "dim_customer": "dim_customer", "dim_employee": "dim_employee",
        "dim_product": "dim_product", "dim_supplier": "dim_supplier",
        "fact_sales_order_flat": "fact_sales_order",
        "fact_sales_order_item_flat": "fact_sales_order_item",
        "fact_inventory_snapshot_flat": "fact_inventory_snapshot",
        "fact_lead_opportunity_flat": "fact_lead_opportunity",
        "fact_customer_ticket_flat": "fact_customer_ticket",
        "fact_marketing_spend_flat": "fact_marketing_spend",
        "fact_ai_usage_flat": "fact_ai_usage",
    }
    for csv_name, tname in csv2tbl.items():
        p = DATA / f"{csv_name}.csv"
        if not p.exists():
            continue
        with p.open("r", encoding="utf-8-sig", newline="") as f:
            header = next(csv.reader(f))
        cols = set(tables.get(tname, {}))
        if set(header) != cols:
            err(f"{csv_name}: CSV 表头与 TMDL 表 {tname} 列不一致 "
                f"缺={sorted(set(header)-cols)} 多={sorted(cols-set(header))}")
    print("✅ 7. CSV 表头与 TMDL 列一致性检查完成")

    if errors:
        print(f"\n❌ 校验未通过，共 {len(errors)} 个问题：")
        for e in errors:
            print("   -", e)
        return 1
    print("\n🎉 PBIP 项目结构校验全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
