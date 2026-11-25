"""AI 产品销售思考 · ROI 测算脚本

用法：
    python scripts/AI产品销售思考_ROI测算.py

基线数字全部从 data/erp.db 实测（对应 docs/AI产品销售思考_取数脚本.sql 的查询编号），
假设项集中在 ASSUMPTIONS 字典中，POC 阶段须用客户真实数据替换。

设计原则：
  1. 收益只算【可归因且可验证】的部分，对观察相关性做保守折减（attr_rate）。
  2. 收益统一折算到【毛利】口径，而非营收 —— 营收增加不等于利润增加。
  3. 必须输出敏感性分析：若核心假设不成立，方案是否还成立。
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

DB = Path(__file__).resolve().parent.parent / 'data' / 'erp.db'

# ---------------------------------------------------------------- 假设（需 POC 校准）
ASSUMPTIONS = {
    'hourly_cost': 60.0,        # 元/人时：销售运营岗综合人力成本（含社保与管理费）
    'attr_rate': 0.30,          # 可归因比例：观察到的组间差值中能归因给产品的部分
    'target_ai_cover': 0.70,    # AI 商机覆盖率目标（现状 35.0%）
    'target_q_per_user': 700,   # 人均年查询次数目标（现状 6432/17 ≈ 378）
    'target_accept': 0.85,      # 采纳率目标（现状 70.20%）
    'stockout_loss_rate': 0.30, # 缺货导致的需求流失比例
    'avoid_rate': 0.50,         # 提前备货可避免的比例
    'mkt_cut_rate': 0.40,       # 低效渠道预算削减比例
    'mkt_roas_lift': 0.15,      # 转移预算的边际 ROAS 提升
}


def load_baseline() -> dict:
    c = sqlite3.connect(DB)
    g = lambda s: c.execute(s).fetchone()[0]
    b = {
        # 营收与利润（Q36）
        'rev_2025': g("""SELECT SUM(o.net_amount) FROM fact_sales_order o
            JOIN dim_date d ON d.date_id=o.order_date_id
            WHERE o.status='已完成' AND d.year=2025"""),
        'gm_2025': g("""SELECT SUM(o.gross_profit)*1.0/SUM(o.net_amount) FROM fact_sales_order o
            JOIN dim_date d ON d.date_id=o.order_date_id
            WHERE o.status='已完成' AND d.year=2025"""),
        # 线索与 AI 效果（Q86、Q92）
        'leads_2025': g("""SELECT COUNT(*) FROM fact_lead_opportunity l
            JOIN dim_date d ON d.date_id=l.created_date_id WHERE d.year=2025"""),
        'ai_leads_2025': g("""SELECT COUNT(*) FROM fact_lead_opportunity l
            JOIN dim_date d ON d.date_id=l.created_date_id
            WHERE d.year=2025 AND l.ai_assisted=1"""),
        'ai_win_2025': g("""SELECT 100.0*SUM(CASE WHEN l.stage='成单' THEN 1 ELSE 0 END)/COUNT(*)
            FROM fact_lead_opportunity l JOIN dim_date d ON d.date_id=l.created_date_id
            WHERE d.year=2025 AND l.ai_assisted=1"""),
        'man_win_2025': g("""SELECT 100.0*SUM(CASE WHEN l.stage='成单' THEN 1 ELSE 0 END)/COUNT(*)
            FROM fact_lead_opportunity l JOIN dim_date d ON d.date_id=l.created_date_id
            WHERE d.year=2025 AND l.ai_assisted=0"""),
        'won_avg_2025': g("""SELECT AVG(l.actual_amount) FROM fact_lead_opportunity l
            JOIN dim_date d ON d.date_id=l.created_date_id
            WHERE d.year=2025 AND l.stage='成单'"""),
        # AI 助手效率（Q19、Q20、Q21）
        'q_2025': g("""SELECT SUM(u.query_count) FROM fact_ai_usage u
            JOIN dim_date d ON d.date_id=u.date_id WHERE d.year=2025"""),
        'acc_2025': g("""SELECT SUM(u.accepted_count) FROM fact_ai_usage u
            JOIN dim_date d ON d.date_id=u.date_id WHERE d.year=2025"""),
        'rate_2025': g("""SELECT 100.0*SUM(u.accepted_count)/SUM(u.query_count) FROM fact_ai_usage u
            JOIN dim_date d ON d.date_id=u.date_id WHERE d.year=2025"""),
        'hours_2025': g("""SELECT SUM(u.minutes_saved)/60.0 FROM fact_ai_usage u
            JOIN dim_date d ON d.date_id=u.date_id WHERE d.year=2025"""),
        'min_per_accepted': g("""SELECT SUM(minutes_saved)*1.0/SUM(accepted_count) FROM fact_ai_usage"""),
        # 营销（Q17、Q18）
        'mkt_2025': g("""SELECT SUM(m.cost_amount) FROM fact_marketing_spend m
            JOIN dim_date d ON d.date_id=m.date_id WHERE d.year=2025"""),
        'low_eff_2025': g("""SELECT SUM(m.cost_amount) FROM fact_marketing_spend m
            JOIN dim_date d ON d.date_id=m.date_id
            WHERE d.year=2025 AND m.channel IN ('外呼中心','内容营销')"""),
        # 库存（Q28、Q26、Q30）
        'stock_rev_2025': g("""SELECT SUM(i.revenue_amount) FROM fact_sales_order_item i
            JOIN fact_sales_order o ON o.order_id=i.order_id
            JOIN dim_date d ON d.date_id=o.order_date_id
            WHERE o.status='已完成' AND d.year=2025 AND i.product_id IN
            (SELECT product_id FROM dim_product WHERE sku IN ('SKU-0041','SKU-0043'))"""),
        'stock_months_2025': g("""SELECT COUNT(DISTINCT d.full_date) FROM fact_inventory_snapshot s
            JOIN dim_product p ON p.product_id=s.product_id
            JOIN dim_date d ON d.date_id=s.date_id
            WHERE p.status='在售' AND s.on_hand_qty<s.safety_stock AND d.full_date LIKE '2025-%'"""),
        'inv_value': g("""SELECT SUM(inventory_value) FROM fact_inventory_snapshot
            WHERE date_id=(SELECT date_id FROM dim_date WHERE full_date='2025-12-31')"""),
        # 规模（Q43、Q19）
        'emp': g("SELECT COUNT(*) FROM dim_employee"),
        'ai_users': g("SELECT COUNT(DISTINCT employee_id) FROM fact_ai_usage"),
    }
    c.close()
    return b


def calc(b: dict, **kw) -> dict:
    a = {**ASSUMPTIONS, **kw}
    gap = (b['ai_win_2025'] - b['man_win_2025']) / 100.0
    new_ai = round(b['leads_2025'] * a['target_ai_cover']) - b['ai_leads_2025']

    # A1 自然语言经营问答：省人时
    inc_acc = b['emp'] * a['target_q_per_user'] * a['target_accept'] - b['acc_2025']
    a1 = inc_acc * b['min_per_accepted'] / 60.0 * a['hourly_cost']

    # A2 需求预测与智能补货：减少缺货损失（折毛利）
    stock_month_rev = b['stock_rev_2025'] / 12.0
    loss = stock_month_rev * b['stock_months_2025'] * a['stockout_loss_rate']
    a2 = loss * a['avoid_rate'] * b['gm_2025']

    # A3 客户洞察与跟进建议：提升大单转化（折毛利）
    extra_won = new_ai * gap * a['attr_rate']
    a3 = extra_won * b['won_avg_2025'] * b['gm_2025']

    # A4 营销止损（模块二/三的副产品）
    cut = b['low_eff_2025'] * a['mkt_cut_rate']
    a4 = cut + cut * a['mkt_roas_lift'] * b['gm_2025']

    return {'A1': a1, 'A2': a2, 'A3': a3, 'A4': a4, 'total': a1 + a2 + a3 + a4,
            'extra_won': extra_won, 'inc_acc': inc_acc, 'new_ai': new_ai}


PRICING = [
    ('模块一单点切入（自然语言问答 + 日报）', 48_000, 20_000),
    ('全量三模块（主推）', 168_000, 60_000),
    ('私有化三模块高配', 360_000, 120_000),
]


def main() -> None:
    b = load_baseline()
    print('=' * 78)
    print('一、基线（全部实测自 data/erp.db，查询编号见 docs/AI产品销售思考_取数脚本.sql）')
    for k, v in b.items():
        print(f'  {k:20s} = {v:,.4f}' if isinstance(v, float) else f'  {k:20s} = {v:,}')
    print('\n二、假设（POC 阶段须用客户真实数据替换）')
    for k, v in ASSUMPTIONS.items():
        print(f'  {k:20s} = {v}')

    print('\n' + '=' * 78)
    print('三、中性情景收益测算')
    r = calc(b)
    print(f"  [A1] 自然语言经营问答：增量采纳 {r['inc_acc']:,.0f} 次 × "
          f"{b['min_per_accepted']:.2f} 分钟/次 → {r['A1']:,.0f} 元/年")
    print(f"  [A2] 需求预测与智能补货：缺货损失规避 → {r['A2']:,.0f} 元/年")
    print(f"  [A3] 客户洞察与跟进建议：AI 覆盖 +{r['new_ai']} 条 → 额外成单 {r['extra_won']:.1f} 单 "
          f"→ {r['A3']:,.0f} 元/年")
    print(f"  [A4] 营销止损：{r['A4']:,.0f} 元/年")
    print(f"\n  年收益合计 = {r['total']:,.0f} 元  "
          f"（占年营收 {r['total']/b['rev_2025']*100:.2f}%）")
    print(f"  收益结构：A1 {r['A1']/r['total']*100:.1f}% | A2 {r['A2']/r['total']*100:.1f}% | "
          f"A3 {r['A3']/r['total']*100:.1f}% | A4 {r['A4']/r['total']*100:.1f}%")

    print('\n' + '=' * 78)
    print('四、定价与 ROI（年费 + 一次性实施）')
    for name, fee, impl in PRICING:
        net = r['total'] - fee - impl
        print(f"  {name}: 年费 {fee:,} + 实施 {impl:,} → 首年净收益 {net:,.0f} 元 | "
              f"ROI {net/(fee+impl)*100:.0f}% | 回收期 {(fee+impl)/r['total']*12:.1f} 个月")

    print('\n' + '=' * 78)
    print('五、敏感性分析：A3 归因折减率（最脆弱假设）')
    for a in (0.10, 0.20, 0.30, 0.40, 0.50):
        s = calc(b, attr_rate=a)
        fee, impl = 168_000, 60_000
        print(f"  attr_rate={a:.0%}: 年收益 {s['total']:>10,.0f} | A3 占比 {s['A3']/s['total']:>5.1%} | "
              f"ROI {(s['total']-fee-impl)/(fee+impl):>6.0%} | 回收 {(fee+impl)/s['total']*12:>4.1f} 月")

    print('\n' + '=' * 78)
    print('六、三档情景')
    scen = {
        '保守': dict(attr_rate=0.10, target_ai_cover=0.50, target_q_per_user=400, target_accept=0.75,
                     mkt_cut_rate=0.20, stockout_loss_rate=0.20, avoid_rate=0.30),
        '中性': dict(),
        '乐观': dict(attr_rate=0.50, target_ai_cover=0.85, target_q_per_user=1000, target_accept=0.90,
                     mkt_cut_rate=0.60, stockout_loss_rate=0.40, avoid_rate=0.60),
    }
    for name, kw in scen.items():
        s = calc(b, **kw)
        fee, impl = 168_000, 60_000
        print(f"  {name}: 合计 {s['total']:>10,.0f} | 占营收 {s['total']/b['rev_2025']:>5.2%} | "
              f"ROI {(s['total']-fee-impl)/(fee+impl):>6.0%} | 回收 {(fee+impl)/s['total']*12:>4.1f} 月")

    s0 = calc(b, attr_rate=0.0)
    fee, impl = 168_000, 60_000
    print('\n' + '=' * 78)
    print('七、反向检验：若 AI 组成单率优势完全消失（A3 = 0）')
    print(f"  年收益 {s0['total']:,.0f} 元 → ROI {(s0['total']-fee-impl)/(fee+impl):.0%}")
    print('  结论：ROI 的成败高度依赖 A3（成单转化增益）。因此 A3 必须做分层验证 + 保守归因，')
    print('        销售材料中不得把 A3 写成承诺收益；应以 A1（省人时）+ A4（营销止损）作为保底价值。')

    print('\n' + '=' * 78)
    print('八、参考基线')
    print(f"  年营收 {b['rev_2025']:,.0f} 元 | 年营销投入 {b['mkt_2025']:,.0f} 元 | "
          f"人均年营收 {b['rev_2025']/b['emp']:,.0f} 元")
    print(f"  年末库存 {b['inv_value']:,.0f} 元 = 年营收的 {b['inv_value']/b['rev_2025']*100:.1f}%")
    print(f"  AI 节省 {b['hours_2025']:.1f} 小时/年 | 每次采纳省 {b['min_per_accepted']:.2f} 分钟 | "
          f"使用人数 {b['ai_users']}/{b['emp']}")


if __name__ == '__main__':
    main()
