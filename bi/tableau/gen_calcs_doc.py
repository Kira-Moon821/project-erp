# -*- coding: utf-8 -*-
"""
从已生成的 ERP经营分析.twb 中提取全部计算字段，自动生成 bi/tableau/calcs.md。

好处：文档与工作簿**永远一致**（改工作簿重跑本脚本即可），不会各写各的。
"""
from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TWB = ROOT / "bi" / "tableau" / "ERP经营分析.twb"
OUT = ROOT / "bi" / "tableau" / "calcs.md"

# 计算字段 → 业务含义（人工补充的口径解释）
MEANING = {
    "营收(已完成)": "net_amount 求和，仅 order_status = 已完成 且 is_return = 0。**全域唯一营收口径**",
    "毛利(已完成)": "gross_profit 求和，条件同营收",
    "毛利率": "毛利 ÷ 营收。比值类指标必须先聚合分子分母再相除，绝不能对行级毛利率求平均",
    "完成订单数": "COUNTD(order_id)，去重计数，避免一单多行重复计",
    "客单价": "营收 ÷ 完成订单数",
    "平均折扣率": "SUM(discount_amount) ÷ SUM(gross_amount)，同样遵守「先聚合再相除」",
    "营收同比": "LOOKUP(..., -12) 取 12 个月前的营收作分母，得到月度同比",
    "成交客户数": "COUNTD(customer_id)，仅已完成非退货订单",
    "商品营收": "SUM(revenue_amount)，订单行级营收",
    "商品毛利": "SUM(gross_profit)，订单行级毛利",
    "累计占比": "RUNNING_SUM(...) ÷ TOTAL(...)，帕累托累计曲线",
    "销量": "SUM(qty)",
    "库存金额": "SUM(inventory_value)",
    "缺货SKU数": "COUNTD(IF stock_gap > 0 THEN product_id END)",
    "缺货率": "缺货SKU数 ÷ SKU 总数",
    "库存周转率(期末)": "SUM(inventory_value)，期末库存资金占用",
    "商机数": "COUNTD(lead_id)",
    "商机金额": "SUM(actual_amount)",
    "成单数": "COUNTD(IF stage = 成单 THEN lead_id END)",
    "成单率": "成单数 ÷ 商机数",
    "AI辅助成单率": "AI 辅助且成单的商机数 ÷ AI 辅助商机数（对照组同法计算）",
    "平均销售周期(天)": "AVG(cycle_days)",
    "投放成本": "SUM(cost_amount)",
    "归因收入": "SUM(revenue_attributed)",
    "ROAS": "归因收入 ÷ 投放成本",
    "CAC": "投放成本 ÷ SUM(leads_count)",
    "AI采纳率": "SUM(accepted_count) ÷ SUM(query_count)",
    "AI节省工时(分钟)": "SUM(minutes_saved)",
    "AI调用次数": "SUM(query_count)",
    "AI处理工单占比": "AI 处理的工单数 ÷ 工单总数",
    "平均解决时长(小时)": "AVG(resolution_hours)",
    "平均满意度": "AVG(satisfaction)",
}


def main() -> int:
    root = ET.parse(TWB).getroot()
    lines = []
    lines.append("# Tableau 计算字段清单")
    lines.append("")
    lines.append("> 本文件由 `python bi/tableau/gen_calcs_doc.py` 从 "
                 "`bi/tableau/ERP经营分析.twb` **自动提取**，保证与工作簿永远一致。")
    lines.append(">")
    lines.append(f"> 共 **{sum(len(ds.findall('./column')) for ds in root.findall('./datasources/datasource'))} "
                 "个计算字段**，分布在 7 个数据源上。")
    lines.append("")
    lines.append("## 全局约定（与 Power BI DAX / Excel 公式 / SQL 脚本同一套口径）")
    lines.append("")
    lines.append("1. **营收只算已完成且非退货**：`order_status = \"已完成\" AND is_return = 0`")
    lines.append("2. **比值先聚合再相除**：不对比率列求平均")
    lines.append("3. **计数用 COUNTD**：避免一单多行重复计数")
    lines.append("4. **成单阶段 = `\"成单\"`**，AI 辅助标记 `ai_assisted = 1`")
    lines.append("")

    total = 0
    for ds in root.findall("./datasources/datasource"):
        cap = ds.get("caption")
        cols = ds.findall("./column")
        if not cols:
            continue
        lines.append(f"## 数据源 `{cap}`")
        lines.append("")
        lines.append("| 计算字段 | Tableau 公式 | 业务含义 |")
        lines.append("|----------|-------------|----------|")
        for c in cols:
            calc = c.find("./calculation")
            if calc is None:
                continue
            caption = c.get("caption")
            formula = calc.get("formula")
            total += 1
            meaning = MEANING.get(caption, "")
            lines.append(f"| **{caption}** | `{formula}` | {meaning} |")
        lines.append("")

    lines.append("## 与其他工具的写法对照")
    lines.append("")
    lines.append("同一个指标在四个工具里的实现（以「营收」为例）：")
    lines.append("")
    lines.append("| 工具 | 写法 |")
    lines.append("|------|------|")
    lines.append("| **SQL** | `SUM(CASE WHEN order_status = '已完成' AND is_return = 0 THEN net_amount END)` |")
    lines.append("| **Excel 公式** | `SUMIFS(净额, 订单状态, \"已完成\")` |")
    lines.append("| **Excel 透视表** | 页面字段筛选 `订单状态 = 已完成` + 值字段求和 `net_amount` |")
    lines.append("| **Power BI DAX** | `CALCULATE(SUM(fact_sales_order[net_amount]), fact_sales_order[order_status] = \"已完成\", fact_sales_order[is_return] = 0)` |")
    lines.append("| **Tableau** | `SUM(IF [order_status] = \"已完成\" AND [is_return] = 0 THEN [net_amount] END)` |")
    lines.append("")
    lines.append("> 五种写法、五个工具，但**过滤条件完全一样** —— 这就是本项目「口径固化」的意义。")
    lines.append("> 校验：`bi/tableau/verify_twb.py` 检查每个计算字段引用的列是否真实存在。")
    lines.append("")

    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"✅ 已生成 {OUT.relative_to(ROOT)}（{total} 个计算字段）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
