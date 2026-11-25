# -*- coding: utf-8 -*-
"""
生成 Tableau 可直接打开的工作簿：
  bi/tableau/ERP经营分析.twb    —— 明文工作簿（可用"文件 > 打开"直接打开）
  bi/tableau/ERP经营分析.twbx   —— 打包工作簿（含 Data/ 数据副本，双击即用，可另存）

数据源：bi/data/*.csv（UTF-8 with BOM，与 Excel / Power BI 口径完全一致）
口径：docs/数据字典与业务口径.md

用法： python bi/tableau/build_twb.py
"""
from __future__ import annotations

import csv
import datetime as dt
import shutil
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "bi" / "data"
OUT = ROOT / "bi" / "tableau"

# ----------------------------------------------------------------------------
# 类型推断
# ----------------------------------------------------------------------------
TYPE_MAP = {
    "integer": dict(remote=20, local="integer", agg="Sum", debug="I8", role="measure", t="quantitative"),
    "real": dict(remote=5, local="real", agg="Sum", debug="R8", role="measure", t="quantitative"),
    "string": dict(remote=129, local="string", agg="Count", debug="WSTR", role="dimension", t="nominal"),
    "date": dict(remote=133, local="date", agg="Year", debug="Date", role="dimension", t="ordinal"),
    "boolean": dict(remote=11, local="boolean", agg="Count", debug="Bool", role="dimension", t="nominal"),
}


def infer_type(name: str, samples: list[str]) -> str:
    """按列名语义 + 取值推断 Tableau 列类型。"""
    n = name.lower()
    if n in ("date", "full_date", "order_date", "snapshot_date", "created_date", "contract_date",
             "launch_date", "hire_date"):
        return "date"
    if n.startswith("is_") or n in ("ai_assisted", "ai_handled"):
        return "boolean"
    vals = [s for s in samples if s not in ("", None)]
    if not vals:
        return "string"
    def _num(v):
        try:
            float(v)
            return True
        except ValueError:
            return False
    if all(_num(v) for v in vals):
        dec = any("." in v for v in vals)
        return "real" if dec else "integer"
    return "string"


def read_csv_info(path: Path):
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        rdr = csv.reader(f)
        header = next(rdr)
        rows = []
        for i, row in enumerate(rdr):
            if i >= 500:
                break
            rows.append(row)
    cols = []
    for idx, h in enumerate(header):
        samples = [r[idx] for r in rows if idx < len(r)]
        t = infer_type(h, samples)
        cols.append(dict(name=h, type=t))
    return cols


# ----------------------------------------------------------------------------
# XML 片段
# ----------------------------------------------------------------------------
def esc(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
             .replace('"', "&quot;").replace("'", "&apos;"))


def ds_id(caption: str, i: int) -> str:
    return f"federated.{caption[:4]}{i:02d}x9k2"


def conn_id(caption: str, i: int) -> str:
    return f"textscan.{caption[:4]}{i:02d}x9k2"


def meta_records(caption: str, cols: list[dict]) -> str:
    out = []
    for ordinal, c in enumerate(cols):
        t = TYPE_MAP[c["type"]]
        agg = "Count" if c["type"] in ("string",) else t["agg"]
        out.append(
            f"""<metadata-record class='column'>
            <remote-name>{esc(c['name'])}</remote-name>
            <remote-type>{t['remote']}</remote-type>
            <local-name>[{esc(c['name'])}]</local-name>
            <parent-name>[{esc(caption)}]</parent-name>
            <remote-alias>{esc(c['name'])}</remote-alias>
            <ordinal>{ordinal}</ordinal>
            <local-type>{t['local']}</local-type>
            <aggregation>{agg}</aggregation>
            <contains-null>true</contains-null>
            <attributes>
              <attribute datatype='string' name='DebugRemoteType'>&quot;{t['debug']}&quot;</attribute>
            </attributes>
          </metadata-record>"""
        )
    return "\n".join(out)


def col_map(caption: str, cols: list[dict]) -> str:
    return "\n".join(
        f"            <map key='[{esc(c['name'])}]' value='[{esc(caption)}.{esc(c['name'])}]' />"
        for c in cols
    )


def field_dep(cols: list[dict], calcs: list[dict]) -> str:
    """datasource-dependencies 片段：原始列 + 计算字段 + column-instance"""
    by_name = {c["name"]: c for c in cols}
    parts = []
    for c in cols:
        t = TYPE_MAP[c["type"]]
        parts.append(
            f"""          <column datatype='{t['local']}' name='[{esc(c['name'])}]' role='{t['role']}' type='{t['t']}' />
        <column-instance column='[{esc(c['name'])}]' derivation='{'None' if c['type'] in ('string','date','boolean') else 'Sum'}' name='[{'none' if c['type'] in ('string','date','boolean') else 'sum'}:{esc(c['name'])}:{'nk' if c['type'] in ('string','boolean') else ('ok' if c['type']=='date' else 'qk')}]' pivot='key' type='{t['t']}' />"""
        )
    for cal in calcs:
        parts.append(
            f"""          <column caption='{esc(cal['caption'])}' datatype='real' name='[{cal['name']}]' role='measure' type='quantitative'>
            <calculation class='tableau' formula='{esc(cal['formula'])}' />
          </column>
        <column-instance column='[{cal['name']}]' derivation='None' name='[none:{cal['name']}:qk]' pivot='key' type='quantitative' />"""
        )
    return "\n".join(parts)


# ----------------------------------------------------------------------------
# 引用构造
# ----------------------------------------------------------------------------
def ref(datasource: str, kind: str, name: str) -> str:
    """kind: raw(str/date 列, 离散) | agg(数值列, 求和) | calc(自定义计算字段)
    返回完整引用： [datasource.X].[none:col:nk]"""
    return f"[datasource.{datasource}].[{ref_dep(kind, name)}]"


def ref_dep(kind: str, name: str) -> str:
    """返回字段实例名（不带方括号）：none:col:nk / sum:col:qk"""
    if kind == "raw":
        return f"none:{name}:nk"
    if kind == "agg":
        return f"sum:{name}:qk"
    return f"none:{name}:qk"


# ----------------------------------------------------------------------------
# 工作表
# ----------------------------------------------------------------------------
def build_worksheet(w: dict, ds_caps: dict[str, str]) -> str:
    cap = w["datasource"]
    dsid = ds_caps[cap]
    filters = ""
    if w.get("filters"):
        items = []
        for col, members in w["filters"]:
            member_xml = "\n".join(
                f"""<groupfilter function='member' level='[none:{col}:nk]' member='&quot;{esc(str(m))}&quot;' />"""
                for m in members
            )
            items.append(
                f"""<filter class='categorical' column='[datasource.{dsid}].[none:{col}:nk]'>
          <groupfilter function='union' user:ui-domain='relevant' user:ui-enumeration='inclusive' user:ui-marker='enumerate'>
          {member_xml}
          </groupfilter>
        </filter>"""
            )
        filters = "\n          ".join(items)

    slices = []
    for kind, name in w.get("slices", []):
        slices.append(f"<column>[datasource.{dsid}].[{ref_dep(kind, name)}]</column>")
    slices_xml = "\n              ".join(slices)

    enc = []
    for role in ("text", "color", "size", "shape", "label", "tooltip"):
        if role in w.get("encodings", {}):
            k, n = w["encodings"][role]
            enc.append(f"<{role} column='[datasource.{dsid}].[{ref_dep(k, n)}]' />")
    enc_xml = "\n              ".join(enc)

    rows = "\n                ".join(
        f"<column>[datasource.{dsid}].[{ref_dep(k, n)}]</column>" for k, n in w.get("rows", [])
    )
    cols = "\n                ".join(
        f"<column>[datasource.{dsid}].[{ref_dep(k, n)}]</column>" for k, n in w.get("cols", [])
    )

    marks = w.get("marks", "Automatic")
    mark_extra = ""
    if marks == "Bar":
        mark_extra = ""
    style = """<style>
          <style-rule element='mark'>
            <encoding attr='color' field='[none:Calculation_x:qk]' type='palette' />
          </style-rule>
        </style>"""

    dep_cols = w.get("dep_cols", [])
    deps = "\n        ".join(
        f"<column datatype='{TYPE_MAP[dep_cols[0][1]]['local'] if False else dep_cols[0][0]}' name='[{dep_cols[0][1]}]' role='dimension' type='nominal' />"
        for _ in [0]
    ) if False else ""

    # 依赖列（精确声明用到的字段）
    used = {}
    for kind, name in w.get("rows", []) + w.get("cols", []) + w.get("slices", []):
        used.setdefault((kind, name), None)
    for role, (kind, name) in w.get("encodings", {}).items():
        used.setdefault((kind, name), None)
    for col, _ in w.get("filters", []):
        used.setdefault(("raw", col), None)
    dep_xml = []
    for kind, name in used:
        if kind == "calc":
            dep_xml.append(
                f"""<column caption='{esc(w['calc_captions'][name])}' datatype='real' name='[{name}]' role='measure' type='quantitative'>
          <calculation class='tableau' formula='{esc(w['calc_formulas'][name])}' />
        </column>
        <column-instance column='[{name}]' derivation='None' name='[none:{name}:qk]' pivot='key' type='quantitative' />"""
            )
        else:
            t = w["col_types"][name]
            info = TYPE_MAP[t]
            deriv = "None" if t in ("string", "date", "boolean") else "Sum"
            tag = "nk" if t in ("string", "boolean") else ("ok" if t == "date" else "qk")
            dep_xml.append(
                f"""<column datatype='{info['local']}' name='[{esc(name)}]' role='{info['role']}' type='{info['t']}' />
        <column-instance column='[{esc(name)}]' derivation='{deriv}' name='[{deriv.lower()}:{esc(name)}:{tag}]' pivot='key' type='{info['t']}' />"""
            )
    dep_block = "\n        ".join(dep_xml)

    title_xml = ""
    if w.get("title"):
        title_xml = f"""
        <repository-location derived-from='{esc(w['title'])}' id='{esc(w['title'])}' path='/worksheets/{esc(w['title'])}' revision='' />"""

    return f"""<worksheet name='{esc(w['title'])}'>
      <repository-location derived-from='{esc(w['title'])}' id='{esc(w['title'])}' path='/worksheets/{esc(w['title'])}' revision='' />
      <table>
        <view>
          <datasources>
            <datasource caption='{esc(cap)}' name='{dsid}' />
          </datasources>
          <datasource-dependencies datasource='{dsid}'>
        {dep_block}
          </datasource-dependencies>
          {filters}
          <slices>
              {slices_xml}
          </slices>
        </view>
        <style />
        <panes>
          <pane id='1' selection-relaxation-option='selection-relaxation-allow'>
            <view>
              <breakdown value='auto' />
            </view>
            <mark class='{marks}' />
            <encodings>
              {enc_xml}
            </encodings>
            <customized-tooltip>
              <formatted-text>
                <run bold='false'>{w.get('tooltip', '指标')}</run>
              </formatted-text>
            </customized-tooltip>
          </pane>
        </panes>
        <rows>
                {rows}
        </rows>
        <cols>
                {cols}
        </cols>
      </table>
      <simple-id uuid='{{{w.get("uuid", "00000000-0000-0000-0000-000000000000")[:8]}-{w.get("uuid", "0000")[:4]}-4000-8000-000000000000"}}' />
    </worksheet>"""


# ----------------------------------------------------------------------------
# 数据源定义
# ----------------------------------------------------------------------------
def build_datasource(cap: str, cols: list[dict], calcs: list[dict], idx: int) -> str:
    dsid = ds_id(cap, idx)
    cid = conn_id(cap, idx)
    calc_cols = "\n      ".join(
        f"""<column caption='{esc(c['caption'])}' datatype='real' name='[{c['name']}]' role='measure' type='quantitative'>
        <calculation class='tableau' formula='{esc(c['formula'])}' />
      </column>
      <column-instance column='[{c['name']}]' derivation='None' name='[none:{c['name']}:qk]' pivot='key' type='quantitative' />"""
        for c in calcs
    )
    return f"""<datasource caption='{esc(cap)}' inline='true' name='{dsid}' version='18.1'>
      <connection class='federated'>
        <named-connections>
          <named-connection caption='{esc(cap)}' name='{cid}'>
            <connection class='textscan' directory='Data' filename='{esc(cap)}.csv' password='' server='' />
          </named-connection>
        </named-connections>
        <relation connection='{cid}' name='{esc(cap)}' table='[{esc(cap)}]' type='table' />
        <cols>
{col_map(cap, cols)}
        </cols>
        <metadata-records>
{chr(10).join('          ' + r for r in meta_records(cap, cols).splitlines())}
        </metadata-records>
      </connection>
      <column-instance column='[{esc(cols[0]['name'])}]' derivation='None' name='[none:{esc(cols[0]['name'])}:nk]' pivot='key' type='nominal' />
{calc_cols}
      <layout dim-ordering='alphabetic' dim-percentage='0.5' measure-ordering='alphabetic' measure-percentage='0.4' show-structure='true' />
    </datasource>"""


def build_dashboard(d: dict) -> str:
    zones = []
    x = 0
    y = 0
    W = 100000
    H = 100000
    # 简单布局：按给定 grid 比例摆放
    gid = 1
    for item in d["layout"]:
        cols_n, rows_n = item["grid"]
        w = int(W / d["cols"] * cols_n)
        h = int(H / d["rows"] * rows_n)
        zones.append(
            f"""<zone h='{h}' id='{gid}' type-v2='viz' w='{w}' x='{x}' y='{y}' name='{esc(item['sheet'])}'>
        <zone-style>
          <format attr='border-color' value='#000000' />
          <format attr='border-style' value='none' />
          <format attr='border-width' value='0' />
          <format attr='margin' value='4' />
        </zone-style>
      </zone>"""
        )
        x += w
        gid += 1
        if x >= W:
            x = 0
            y += h
    zone_xml = "\n      ".join(zones)
    text_zones = []
    tx = 0
    for t in d.get("texts", []):
        text_zones.append(
            f"""<zone h='8000' id='{gid}' type-v2='text' w='{int(W/len(d.get('texts',[1])))}' x='{tx}' y='0'>
        <formatted-text>
          <run bold='true' fontcolor='#1f2937' fontsize='16'>{esc(t['text'])}</run>
        </formatted-text>
        <zone-style>
          <format attr='border-color' value='#000000' />
          <format attr='border-style' value='none' />
          <format attr='border-width' value='0' />
        </zone-style>
      </zone>"""
        )
        tx += int(W / len(d.get("texts", [1])))
        gid += 1
    txt_xml = ("\n      ".join(text_zones)) if text_zones else ""
    return f"""<dashboard name='{esc(d['name'])}'>
      <repository-location derived-from='{esc(d['name'])}' id='{esc(d['name'])}' path='/dashboards/{esc(d['name'])}' revision='' />
      <style />
      <size maxheight='{d.get('h', 900)}' maxwidth='{d.get('w', 1440)}' minheight='{d.get('h', 900)}' minwidth='{d.get('w', 1440)}' />
      <zones>
      {zone_xml}
      {txt_xml}
      </zones>
    </dashboard>"""


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    files = sorted(p for p in DATA.glob("*.csv"))
    tables = {}
    for p in files:
        tables[p.stem] = read_csv_info(p)
    print("已读取数据源：")
    for k, v in tables.items():
        print(f"  - {k}: {len(v)} 列")

    json_out = ROOT / "bi" / "tableau" / "column_types.json"
    import json
    json_out.write_text(
        json.dumps({k: v for k, v in tables.items()}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # ---------------- 计算字段定义 ----------------
    calcs_sales = [
        dict(name="Calculation_sales_revenue", caption="营收(已完成)",
             formula="SUM(IF [order_status] = \"已完成\" AND [is_return] = 0 THEN [net_amount] END)"),
        dict(name="Calculation_sales_gross", caption="毛利(已完成)",
             formula="SUM(IF [order_status] = \"已完成\" AND [is_return] = 0 THEN [gross_profit] END)"),
        dict(name="Calculation_sales_margin", caption="毛利率",
             formula="SUM(IF [order_status] = \"已完成\" AND [is_return] = 0 THEN [gross_profit] END) / SUM(IF [order_status] = \"已完成\" AND [is_return] = 0 THEN [net_amount] END)"),
        dict(name="Calculation_sales_orders", caption="完成订单数",
             formula="COUNTD(IF [order_status] = \"已完成\" AND [is_return] = 0 THEN [order_id] END)"),
        dict(name="Calculation_sales_aov", caption="客单价",
             formula="SUM(IF [order_status] = \"已完成\" AND [is_return] = 0 THEN [net_amount] END) / COUNTD(IF [order_status] = \"已完成\" AND [is_return] = 0 THEN [order_id] END)"),
        dict(name="Calculation_sales_discount", caption="平均折扣率",
             formula="SUM(IF [order_status] = \"已完成\" THEN [discount_amount] END) / SUM(IF [order_status] = \"已完成\" THEN [gross_amount] END)"),
        dict(name="Calculation_sales_yoy", caption="营收同比",
             formula="SUM(IF [order_status] = \"已完成\" AND [is_return] = 0 THEN [net_amount] END) / LOOKUP(SUM(IF [order_status] = \"已完成\" AND [is_return] = 0 THEN [net_amount] END), -12)"),
        dict(name="Calculation_sales_cust", caption="成交客户数",
             formula="COUNTD(IF [order_status] = \"已完成\" AND [is_return] = 0 THEN [customer_id] END)"),
    ]
    calcs_item = [
        dict(name="Calculation_item_revenue", caption="商品营收",
             formula="SUM([revenue_amount])"),
        dict(name="Calculation_item_profit", caption="商品毛利",
             formula="SUM([gross_profit])"),
        dict(name="Calculation_item_pareto", caption="累计占比",
             formula="RUNNING_SUM(SUM([revenue_amount])) / TOTAL(SUM([revenue_amount]))"),
        dict(name="Calculation_item_qty", caption="销量",
             formula="SUM([qty])"),
    ]
    calcs_inv = [
        dict(name="Calculation_inv_value", caption="库存金额",
             formula="SUM([inventory_value])"),
        dict(name="Calculation_inv_short_sku", caption="缺货SKU数",
             formula="COUNTD(IF [stock_gap] > 0 THEN [product_id] END)"),
        dict(name="Calculation_inv_short_rate", caption="缺货率",
             formula="COUNTD(IF [stock_gap] > 0 THEN [product_id] END) / COUNTD([product_id])"),
        dict(name="Calculation_inv_turn", caption="库存周转率(期末)",
             formula="SUM([inventory_value])"),
    ]
    calcs_lead = [
        dict(name="Calculation_lead_count", caption="商机数",
             formula="COUNTD([lead_id])"),
        dict(name="Calculation_lead_amount", caption="商机金额",
             formula="SUM([actual_amount])"),
        dict(name="Calculation_lead_win", caption="成单数",
             formula="COUNTD(IF [stage] = \"成单\" THEN [lead_id] END)"),
        dict(name="Calculation_lead_rate", caption="成单率",
             formula="COUNTD(IF [stage] = \"成单\" THEN [lead_id] END) / COUNTD([lead_id])"),
        dict(name="Calculation_lead_ai_rate", caption="AI辅助成单率",
             formula="COUNTD(IF [stage] = \"成单\" AND [ai_assisted] = 1 THEN [lead_id] END) / COUNTD(IF [ai_assisted] = 1 THEN [lead_id] END)"),
        dict(name="Calculation_lead_cycle", caption="平均销售周期(天)",
             formula="AVG([cycle_days])"),
    ]
    calcs_mkt = [
        dict(name="Calculation_mkt_cost", caption="投放成本",
             formula="SUM([cost_amount])"),
        dict(name="Calculation_mkt_rev", caption="归因收入",
             formula="SUM([revenue_attributed])"),
        dict(name="Calculation_mkt_roas", caption="ROAS",
             formula="SUM([revenue_attributed]) / SUM([cost_amount])"),
        dict(name="Calculation_mkt_cac", caption="CAC",
             formula="SUM([cost_amount]) / SUM([leads_count])"),
    ]
    calcs_ai = [
        dict(name="Calculation_ai_accept", caption="AI采纳率",
             formula="SUM([accepted_count]) / SUM([query_count])"),
        dict(name="Calculation_ai_minutes", caption="节省工时(分钟)",
             formula="SUM([minutes_saved])"),
        dict(name="Calculation_ai_queries", caption="AI调用次数",
             formula="SUM([query_count])"),
    ]
    calcs_ticket = [
        dict(name="Calculation_ticket_ai_rate", caption="AI处理工单占比",
             formula="COUNTD(IF [ai_handled] = 1 THEN [ticket_id] END) / COUNTD([ticket_id])"),
        dict(name="Calculation_ticket_hours", caption="平均解决时长(小时)",
             formula="AVG([resolution_hours])"),
        dict(name="Calculation_ticket_sat", caption="平均满意度",
             formula="AVG([satisfaction])"),
    ]
    calcs = {
        "fact_sales_order_flat": calcs_sales,
        "fact_sales_order_item_flat": calcs_item,
        "fact_inventory_snapshot_flat": calcs_inv,
        "fact_lead_opportunity_flat": calcs_lead,
        "fact_marketing_spend_flat": calcs_mkt,
        "fact_ai_usage_flat": calcs_ai,
        "fact_customer_ticket_flat": calcs_ticket,
    }
    cap_formula = {}
    cap_caption = {}
    for ds, cs in calcs.items():
        for c in cs:
            cap_formula[c["name"]] = c["formula"]
            cap_caption[c["name"]] = c["caption"]

    # ---------------- 工作表 ----------------
    CT = {cap: {c["name"]: c["type"] for c in cols} for cap, cols in tables.items()}

    def ws(title, ds, rows=(), cols=(), enc=None, filters=None, slices=(), marks="Automatic", tooltip=""):
        return dict(title=title, datasource=ds, rows=list(rows), cols=list(cols),
                    encodings=enc or {}, filters=filters or [], slices=list(slices),
                    marks=marks, tooltip=tooltip, col_types=CT[ds],
                    calc_formulas=cap_formula, calc_captions=cap_caption)

    worksheets = [
        ws("销售月度趋势", "fact_sales_order_flat",
           rows=[("calc", "Calculation_sales_revenue")],
           cols=[("raw", "year_month"), ("calc", "Calculation_sales_yoy")],
           enc={"color": ("calc", "Calculation_sales_yoy")},
           filters=[("order_status", ["已完成"])],
           marks="Line", tooltip="月份营收与同比"),
        ws("渠道销售结构", "fact_sales_order_flat",
           rows=[("calc", "Calculation_sales_revenue"), ("calc", "Calculation_sales_gross")],
           cols=[("raw", "order_channel")],
           enc={"color": ("raw", "order_channel")},
           filters=[("order_status", ["已完成"])],
           marks="Bar", tooltip="各订单渠道营收与毛利"),
        ws("客户层级贡献", "fact_sales_order_flat",
           rows=[("agg", "net_amount")],
           cols=[("raw", "customer_tier"), ("raw", "customer_industry")],
           enc={"color": ("raw", "customer_tier"), "text": ("calc", "Calculation_sales_revenue")},
           filters=[("order_status", ["已完成"])],
           marks="Bar", tooltip="客户层级营收贡献"),
        ws("商品帕累托", "fact_sales_order_item_flat",
           rows=[("calc", "Calculation_item_revenue")],
           cols=[("raw", "product_name"), ("calc", "Calculation_item_pareto")],
           enc={"color": ("calc", "Calculation_item_pareto")},
           filters=[("order_status", ["已完成"])],
           marks="Bar", tooltip="商品营收与累计占比"),
        ws("客户RFM散点", "fact_sales_order_flat",
           rows=[("agg", "net_amount")],
           cols=[("calc", "Calculation_sales_orders"), ("raw", "customer_tier")],
           enc={"color": ("raw", "customer_tier"), "size": ("agg", "net_amount"),
                "label": ("raw", "customer_name")},
           filters=[("order_status", ["已完成"])],
           marks="Circle", tooltip="客户 RFM：横轴订单数、纵轴营收、大小=营收"),
        ws("商机漏斗", "fact_lead_opportunity_flat",
           rows=[("calc", "Calculation_lead_count")],
           cols=[("raw", "stage")],
           enc={"color": ("raw", "ai_assisted"), "text": ("calc", "Calculation_lead_rate")},
           marks="Bar", tooltip="商机漏斗与 AI 辅助占比"),
        ws("库存健康", "fact_inventory_snapshot_flat",
           rows=[("calc", "Calculation_inv_value")],
           cols=[("raw", "warehouse"), ("raw", "category")],
           enc={"color": ("calc", "Calculation_inv_short_rate"), "text": ("calc", "Calculation_inv_short_sku")},
           marks="Square", tooltip="各仓库各品类库存金额与缺货率"),
        ws("渠道投放效率", "fact_marketing_spend_flat",
           rows=[("calc", "Calculation_mkt_roas")],
           cols=[("raw", "channel")],
           enc={"color": ("raw", "channel"), "size": ("calc", "Calculation_mkt_cost"),
                "text": ("calc", "Calculation_mkt_cac")},
           marks="Circle", tooltip="渠道 ROAS 与 CAC"),
        ws("AI使用效能", "fact_ai_usage_flat",
           rows=[("calc", "Calculation_ai_minutes")],
           cols=[("raw", "scenario"), ("raw", "sales_team")],
           enc={"color": ("calc", "Calculation_ai_accept")},
           marks="Bar", tooltip="AI 场景节省工时与采纳率"),
        ws("工单与AI承接", "fact_customer_ticket_flat",
           rows=[("calc", "Calculation_ticket_hours")],
           cols=[("raw", "topic_type"), ("raw", "ai_handled")],
           enc={"color": ("raw", "ai_handled"), "text": ("calc", "Calculation_ticket_ai_rate")},
           marks="Bar", tooltip="工单类型与 AI 承接占比"),
    ]

    dashboards = [
        dict(name="经营总览", cols=2, rows=2, h=900, w=1440,
             layout=[dict(sheet="销售月度趋势", grid=(2, 1)),
                     dict(sheet="客户层级贡献", grid=(1, 1)),
                     dict(sheet="商品帕累托", grid=(1, 1))],
             texts=[dict(text="ERP 经营总览｜口径见 docs/数据字典与业务口径.md")]),
        dict(name="销售与客户", cols=2, rows=2, h=900, w=1440,
             layout=[dict(sheet="渠道销售结构", grid=(1, 1)),
                     dict(sheet="商机漏斗", grid=(1, 1)),
                     dict(sheet="客户RFM散点", grid=(1, 1)),
                     dict(sheet="商品帕累托", grid=(1, 1))]),
        dict(name="库存与增长", cols=2, rows=2, h=900, w=1440,
             layout=[dict(sheet="库存健康", grid=(1, 1)),
                     dict(sheet="渠道投放效率", grid=(1, 1)),
                     dict(sheet="AI使用效能", grid=(1, 1)),
                     dict(sheet="工单与AI承接", grid=(1, 1))]),
    ]

    # ---------------- 组装 XML ----------------
    ds_xml = []
    ds_caps = {}
    for i, (cap, cols) in enumerate(tables.items()):
        ds_caps[cap] = ds_id(cap, i)
        ds_xml.append(build_datasource(cap, cols, calcs.get(cap, []), i))

    ws_xml = [build_worksheet(w, ds_caps) for w in worksheets]
    db_xml = [build_dashboard(d) for d in dashboards]

    windows = []
    for w in worksheets:
        windows.append(f"""<window class='worksheet' name='{esc(w['title'])}'>
      <cards>
        <edge name='left'>
          <strip size='160'>
            <card type='pages' />
            <card type='filters' />
            <card type='marks' />
          </strip>
        </edge>
      </cards>
      <viewpoint />
    </window>""")
    for d in dashboards:
        windows.append(f"""<window class='dashboard' name='{esc(d['name'])}'>
      <viewpoints>
        <viewpoint name='销售月度趋势' />
      </viewpoints>
      <active id='-1' />
    </window>""")

    twb = f"""<?xml version='1.0' encoding='utf-8' ?>

<!--
  ERP 经营分析实验室 — Tableau 工作簿
  生成脚本：bi/tableau/build_twb.py
  数据源：bi/data/*.csv（打包在 twbx 内的 Data/ 目录）
  口径来源：docs/数据字典与业务口径.md
-->
<workbook original-version='18.1' source-build='2026.3.0 (20263.26.1120.1648)' source-platform='win' version='18.1' xmlns:user='http://www.tableausoftware.com/xml/user'>
  <document-format-change-manifest>
    <AccessibleZoneTabOrder />
    <AnimationOnByDefault />
    <AutoCreateAndUpdateDSDPhoneLayouts />
    <MapboxVectorStylesAndLayers />
    <ObjectModelTableType />
    <SchemaViewerObjectModel />
    <SetMembershipControl />
  </document-format-change-manifest>
  <preferences>
    <preference name='ui.encoding.shelf.height' value='24' />
    <preference name='ui.shelf.height' value='26' />
  </preferences>
  <style />
  <datasources>
{chr(10).join('    ' + d for d in ds_xml)}
  </datasources>
  <worksheets>
{chr(10).join('    ' + w for w in ws_xml)}
  </worksheets>
  <dashboards>
{chr(10).join('    ' + d for d in db_xml)}
  </dashboards>
  <windows source-height='30'>
{chr(10).join('    ' + w for w in windows)}
  </windows>
</workbook>
"""

    twb_path = OUT / "ERP经营分析.twb"
    twb_path.write_text(twb, encoding="utf-8")

    # 打包 twbx
    # 注意：bi/data/*.csv 是 UTF-8 **with BOM**（给 Excel 用，Excel 双击不乱码）。
    # Tableau 的 textscan 连接读 UTF-8-BOM 时可能把 BOM 残留进首列名
    # （字段名变成 "﻿order_id"），与 twb 里声明的 [order_id] 对不上导致字段全空。
    # 因此 twbx 内统一放 **无 BOM** 的 UTF-8 副本。
    twbx_path = OUT / "ERP经营分析.twbx"
    if twbx_path.exists():
        twbx_path.unlink()
    with zipfile.ZipFile(twbx_path, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(twb_path, "ERP经营分析.twb")
        for p in files:
            text = p.read_text(encoding="utf-8-sig")
            z.writestr(f"Data/{p.name}", text.encode("utf-8"))

    print(f"\n✅ 已生成：\n  {twb_path.relative_to(ROOT)}\n  {twbx_path.relative_to(ROOT)}")
    print(f"  工作表 {len(worksheets)} 个 / 仪表板 {len(dashboards)} 个 / 数据源 {len(tables)} 个")


if __name__ == "__main__":
    main()
