-- ============================================================
-- 题目：客户分层（A/B/C）的营收贡献与客单价对比，量化「A 类客单高、折扣深、贡献大」的规律
-- 口径：营收 = SUM(net_amount) 仅 status='已完成'；订单数 = 已完成订单数；客单价 AOV = 营收 ÷ 订单数；
--       客户数 = COUNT(DISTINCT customer_id)；贡献营收占比 = 该层营收 ÷ 全体营收；
--       人均营收 = 该层营收 ÷ 该层客户数；折扣率 = SUM(discount_amount) ÷ SUM(gross_amount)；
--       毛利率 = SUM(gross_profit) ÷ 营收；业务窗口 2024-01-01 ~ 2025-12-31。
-- 考察点：条件聚合 + GROUP BY 分层；窗口函数 SUM() OVER () 计算全局占比、
--          RANK() OVER (ORDER BY ...) 做分层排名、CUME_DIST() 做客户数分布位置。
-- 预期结果：
--   共 3 行；列：tier, customer_cnt, order_cnt, revenue, revenue_share_pct, aov, revenue_per_customer, orders_per_customer, discount_rate, gross_margin_rate, order_share_pct, revenue_rank, aov_rank, revenue_cume_dist, contribution_tier
--     A | 10 | 2295 | 33,436,485.34 | 0.4754 | 14,569.27 | 3,343,648.53 | 229.5 | 0.1209 | 0.2642 | 0.4205 | 1 | 1 | 1 | 重要贡献层
--     B | 20 | 1780 | 20,746,021.89 | 0.295 | 11,655.07 | 1,037,301.09 | 89 | 0.0714 | 0.0592 | 0.3261 | 2 | 3 | 0.6667 | 长尾贡献层
--     C | 30 | 1383 | 16,145,565.79 | 0.2296 | 11,674.31 | 538,185.53 | 46.1 | 0.0345 | 0.041 | 0.2534 | 3 | 2 | 0.3333 | 长尾贡献层
-- ============================================================
WITH
-- 已完成订单明细（订单 × 客户维度）
completed_orders AS (
    SELECT
        o.order_id,
        o.customer_id,
        o.net_amount,
        o.gross_amount,
        o.discount_amount,
        o.gross_profit
    FROM fact_sales_order o
    JOIN dim_date d ON d.date_id = o.order_date_id
    WHERE o.status = '已完成'
      AND d.full_date BETWEEN '2024-01-01' AND '2025-12-31'
),
-- 分层汇总
tier_agg AS (
    SELECT
        c.tier,
        COUNT(DISTINCT o.customer_id)                            AS customer_cnt,
        COUNT(o.order_id)                                        AS order_cnt,
        SUM(o.net_amount)                                        AS revenue,
        SUM(o.gross_amount)                                      AS gross_amount,
        SUM(o.discount_amount)                                   AS discount_amount,
        SUM(o.gross_profit)                                      AS gross_profit
    FROM completed_orders o
    JOIN dim_customer c ON c.customer_id = o.customer_id
    GROUP BY c.tier
)
SELECT
    t.tier,
    t.customer_cnt,
    t.order_cnt,
    ROUND(t.revenue, 2)                                          AS revenue,
    ROUND(t.revenue * 1.0 / SUM(t.revenue) OVER (), 4)            AS revenue_share_pct,
    ROUND(t.revenue * 1.0 / NULLIF(t.order_cnt, 0), 2)            AS aov,
    ROUND(t.revenue * 1.0 / NULLIF(t.customer_cnt, 0), 2)        AS revenue_per_customer,
    ROUND(t.order_cnt * 1.0 / NULLIF(t.customer_cnt, 0), 2)      AS orders_per_customer,
    ROUND(t.discount_amount * 1.0 / NULLIF(t.gross_amount, 0), 4) AS discount_rate,
    ROUND(t.gross_profit * 1.0 / NULLIF(t.revenue, 0), 4)        AS gross_margin_rate,
    ROUND(t.order_cnt * 1.0 / SUM(t.order_cnt) OVER (), 4)        AS order_share_pct,
    RANK() OVER (ORDER BY t.revenue DESC)                        AS revenue_rank,
    RANK() OVER (ORDER BY t.revenue * 1.0 / NULLIF(t.order_cnt, 0) DESC) AS aov_rank,
    ROUND(CUME_DIST() OVER (ORDER BY t.revenue), 4)               AS revenue_cume_dist,
    CASE
        WHEN t.revenue * 1.0 / SUM(t.revenue) OVER () >= 0.60 THEN '核心贡献层'
        WHEN t.revenue * 1.0 / SUM(t.revenue) OVER () >= 0.30 THEN '重要贡献层'
        ELSE '长尾贡献层'
    END                                                          AS contribution_tier
FROM tier_agg t
ORDER BY t.revenue DESC;
