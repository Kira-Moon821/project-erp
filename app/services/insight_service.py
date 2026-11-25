"""自动洞察服务：把统计结果翻译成「可执行的经营结论」。

每条洞察都带证据 SQL，体现「结论必须可回溯到查询」的原则——
这也是 AI 产品能不能卖出去的核心：不能解释来源的结论，客户不敢用。
"""
from __future__ import annotations

from datetime import date
from typing import Any, Dict, List

from sqlalchemy.orm import Session

from app.repositories import analytics_repo

EV_SQL = {
    "inventory_shortage": """
SELECT p.product_name, s.warehouse, s.on_hand_qty, s.safety_stock
FROM fact_inventory_snapshot s JOIN dim_product p ON p.product_id = s.product_id
WHERE s.date_id = (SELECT MAX(date_id) FROM fact_inventory_snapshot)
  AND s.on_hand_qty < s.safety_stock ORDER BY (s.safety_stock - s.on_hand_qty) DESC;""",
    "turnover": """
SELECT ROUND(SUM(s.inventory_value), 2) AS 期末库存金额,
       ROUND(SUM(o.cost_amount) / 90.0, 2) AS 日均销售成本
FROM fact_inventory_snapshot s
JOIN fact_sales_order o ON o.order_date_id BETWEEN 20251001 AND 20251231 AND o.status = '已完成'
WHERE s.date_id = (SELECT MAX(date_id) FROM fact_inventory_snapshot);""",
    "ai_leads": """
SELECT ai_assisted, COUNT(*) AS 商机数,
       ROUND(AVG(CASE WHEN stage = '成单' THEN 1.0 ELSE 0 END), 4) AS 成单率,
       ROUND(AVG(cycle_days), 1) AS 平均销售周期
FROM fact_lead_opportunity GROUP BY ai_assisted;""",
    "ai_ticket": """
SELECT ai_handled, COUNT(*) AS 工单数,
       ROUND(AVG(first_response_minutes), 1) AS 平均首响分钟,
       ROUND(AVG(satisfaction), 2) AS 平均满意度
FROM fact_customer_ticket GROUP BY ai_handled;""",
    "rfm_churn": """
-- RFM 中「重要流失预警」客户（近期无成交但历史贡献高）
SELECT COUNT(*) FROM (
  SELECT customer_id FROM fact_sales_order WHERE status = '已完成'
  GROUP BY customer_id) t
WHERE t.customer_id NOT IN (
  SELECT customer_id FROM fact_sales_order WHERE status = '已完成'
    AND order_date_id >= 20251001);""",
    "marketing": """
SELECT channel, ROUND(SUM(cost_amount), 2) AS 成本, SUM(leads_count) AS 线索数,
       ROUND(SUM(cost_amount) / SUM(leads_count), 2) AS CAC,
       ROUND(SUM(revenue_attributed) / SUM(cost_amount), 2) AS ROAS
FROM fact_marketing_spend GROUP BY channel ORDER BY ROAS DESC;""",
}


def build_insights(session: Session, start: date, end: date) -> List[Dict[str, Any]]:
    insights: List[Dict[str, Any]] = []
    kpi = analytics_repo.kpis(session, start, end)
    inv = analytics_repo.inventory_health(session)
    ai = analytics_repo.ai_value(session, start, end)
    marketing = analytics_repo.marketing_efficiency(session, start, end)
    rfm = analytics_repo.rfm(session, end)

    # 1) 营收同比
    if kpi["prev_revenue"]:
        yoy = (kpi["revenue"] - kpi["prev_revenue"]) / kpi["prev_revenue"] * 100
        insights.append({
            "code": "revenue_yoy", "severity": "info" if yoy >= 0 else "warning",
            "title": f"营收较上一等长周期{'增长' if yoy >= 0 else '下滑'} {abs(yoy):.1f}%",
            "detail": f"本期营收 {kpi['revenue']:,.0f}，上一等长周期 {kpi['prev_revenue']:,.0f}；"
                      f"订单数 {kpi['orders']:,}，客单价 {kpi['aov']:,.0f}，毛利率 {kpi['gross_margin']:.1%}。",
            "metric": {"revenue": kpi["revenue"], "prev_revenue": kpi["prev_revenue"], "yoy_pct": round(yoy, 2)},
            "evidence_sql": "SELECT SUM(net_amount) FROM fact_sales_order WHERE status='已完成' GROUP BY YEAR(order_date_id);",
            "suggestion": "若增长主要来自单一客户或单一渠道，需评估集中度风险；建议同时看 Top 客户占比与渠道结构。",
        })

    # 2) 库存缺货
    if inv["shortage_skus"]:
        insights.append({
            "code": "inventory_shortage", "severity": "critical",
            "title": f"{inv['shortage_skus']} 个 SKU 低于安全库存",
            "detail": f"末月库存快照中 {inv['shortage_skus']} 个 SKU 的在手量低于安全库存，"
                      f"涉及 SKU 总数 {inv['sku_count']} 个，存在断货与丢单风险。",
            "metric": {"shortage_skus": inv["shortage_skus"], "sku_count": inv["sku_count"]},
            "evidence_sql": EV_SQL["inventory_shortage"],
            "suggestion": "用近 90 天需求重算安全库存（当前固定 14 天需求口径），对缺口 SKU 生成补货建议单。",
        })

    # 3) 库存周转
    if inv["turnover_days"] > 150:
        insights.append({
            "code": "inventory_turnover", "severity": "warning",
            "title": f"库存周转天数 {inv['turnover_days']} 天，资金占用偏高",
            "detail": f"期末库存金额 {inv['inventory_value']:,.0f}，按成本口径日均销售成本折算，"
                      f"周转约 {inv['turnover_days']} 天；滞销 SKU（近 90 天无动销且有库存）{inv['slow_moving_skus']} 个。",
            "metric": {"turnover_days": inv["turnover_days"], "inventory_value": inv["inventory_value"],
                       "slow_moving_skus": inv["slow_moving_skus"]},
            "evidence_sql": EV_SQL["turnover"],
            "suggestion": "对滞销 SKU 做清仓/退供谈判，把周转目标压到 120 天以内，并按 ABC 分类差异化备货。",
        })

    # 4) AI 辅助商机
    leads = ai["leads"]
    if 1 in leads and 0 in leads:
        ai_row, ctrl_row = leads[1], leads[0]
        ai_rate = ai_row["won"] / ai_row["count"] if ai_row["count"] else 0
        ctrl_rate = ctrl_row["won"] / ctrl_row["count"] if ctrl_row["count"] else 0
        insights.append({
            "code": "ai_lead_uplift", "severity": "info",
            "title": f"AI 辅助商机成单率 {ai_rate:.1%}，对照组 {ctrl_rate:.1%}",
            "detail": f"AI 辅助组平均销售周期 {ai_row['avg_cycle_days']} 天，对照组 {ctrl_row['avg_cycle_days']} 天；"
                      f"平均赢率 {ai_row['avg_win_prob']:.1%} vs {ctrl_row['avg_win_prob']:.1%}。",
            "metric": {"ai_win_rate": round(ai_rate, 4), "control_win_rate": round(ctrl_rate, 4),
                       "ai_cycle_days": ai_row["avg_cycle_days"], "control_cycle_days": ctrl_row["avg_cycle_days"]},
            "evidence_sql": EV_SQL["ai_leads"],
            "suggestion": "把 AI 辅助（话术草稿 + 客户洞察摘要）纳入标准销售流程，形成可复制的 SOP 与培训材料。",
        })

    # 5) AI 工单
    tickets = ai["tickets"]
    if 1 in tickets and 0 in tickets:
        ai_t, ctrl_t = tickets[1], tickets[0]
        insights.append({
            "code": "ai_ticket_uplift", "severity": "info",
            "title": f"AI 处理工单首响 {ai_t['avg_first_response_min']} 分钟 vs 人工 {ctrl_t['avg_first_response_min']} 分钟",
            "detail": f"AI 处理工单满意度 {ai_t['avg_satisfaction']}，人工 {ctrl_t['avg_satisfaction']}；"
                      f"AI 处理单转化为商机比例更高（{ai_t['converted']}/{ai_t['count']} vs {ctrl_t['converted']}/{ctrl_t['count']}）。",
            "metric": {"ai_first_response": ai_t["avg_first_response_min"],
                       "manual_first_response": ctrl_t["avg_first_response_min"],
                       "ai_satisfaction": ai_t["avg_satisfaction"], "manual_satisfaction": ctrl_t["avg_satisfaction"]},
            "evidence_sql": EV_SQL["ai_ticket"],
            "suggestion": "把高频工单类型（数据导出/报表需求）做成自助问答，人工只处理例外，释放售前工时。",
        })

    # 6) AI 采纳率
    usage = ai["usage"]
    if usage["queries"]:
        insights.append({
            "code": "ai_adoption", "severity": "info",
            "title": f"内部 AI 助手采纳率 {usage['acceptance_rate']:.1%}，累计节省 {usage['hours_saved']:.0f} 小时",
            "detail": f"共发起 {usage['queries']:,} 次查询，{usage['accepted']:,} 次结果被采纳，"
                      f"覆盖 {usage['active_users']} 名员工（自然语言取数 / 经营日报 / 客户洞察）。",
            "metric": usage,
            "evidence_sql": "SELECT SUM(query_count), SUM(accepted_count), SUM(minutes_saved) FROM fact_ai_usage;",
            "suggestion": "采纳率是 AI 产品续费的关键指标：低于 60% 说明口径或体验有问题，需要回到指标治理。",
        })

    # 7) 营销效率
    if marketing:
        best = max(marketing, key=lambda m: m["roas"])
        worst = min(marketing, key=lambda m: m["roas"])
        insights.append({
            "code": "marketing_efficiency", "severity": "warning" if worst["roas"] < 2 else "info",
            "title": f"渠道效率分化：{best['channel']} ROAS {best['roas']}，{worst['channel']} ROAS {worst['roas']}",
            "detail": f"CAC 最高为 {max(marketing, key=lambda m: m['cac'])['channel']}"
                      f"（{max(marketing, key=lambda m: m['cac'])['cac']:,.0f} 元/线索），"
                      f"最低 {min(marketing, key=lambda m: m['cac'])['channel']}"
                      f"（{min(marketing, key=lambda m: m['cac'])['cac']:,.0f} 元/线索）。",
            "metric": {"best_channel": best["channel"], "best_roas": best["roas"],
                       "worst_channel": worst["channel"], "worst_roas": worst["roas"]},
            "evidence_sql": EV_SQL["marketing"],
            "suggestion": "按 CAC×转化率重排预算；对 ROAS < 2 的渠道做小预算 A/B 测试，保留可归因路径。",
        })

    # 8) 客户流失预警
    churn = [c for c in rfm if c["segment"] == "重要流失预警"]
    if churn:
        amount = sum(c["monetary"] for c in churn)
        insights.append({
            "code": "customer_churn_risk", "severity": "warning",
            "title": f"{len(churn)} 个高价值客户近期无成交预警",
            "detail": f"这些客户历史成交金额合计 {amount:,.0f}，但最近成交明显滞后，"
                      f"平均 recency {sum(c['recency_days'] for c in churn) / len(churn):.0f} 天。",
            "metric": {"churn_customers": len(churn), "historical_amount": round(amount, 2)},
            "evidence_sql": EV_SQL["rfm_churn"],
            "suggestion": "生成跟进清单（含历史采购品类与联系人），由 AI 起草回访话术，销售只做关系判断。",
        })

    order = {"critical": 0, "warning": 1, "info": 2}
    insights.sort(key=lambda i: order.get(i["severity"], 3))
    return insights
