-- ============================================================
-- 题目：近 24 个月销售营收、订单、客单价的月度趋势，以及同比/环比增长与季节性规律
-- 口径：营收 = fact_sales_order.net_amount 求和，仅统计 status='已完成'（已退款/已取消/处理中一律排除）；
--       订单数 = 已完成订单行数；客单价 AOV = 营收 ÷ 订单数；毛利率 = SUM(gross_profit) ÷ 营收；
--       折扣率 = SUM(discount_amount) ÷ SUM(gross_amount)；业务窗口 dim_date.full_date BETWEEN '2024-01-01' AND '2025-12-31'。
--       月份序列用递归 CTE 补齐 2024-01 ~ 2025-12 共 24 期，避免缺失月份被跳过。
-- 考察点：递归 CTE 生成连续月份轴 + LEFT JOIN 补齐日期序列；窗口函数 LAG(offset=1/12) 计算环比与同比；
--          条件聚合 + NULLIF 防除零；ROUND 控制展示精度。
-- 预期结果：
--   共 24 行；列：ym, order_cnt, customer_cnt, revenue, gross_amount, discount_amount, discount_rate, aov, gross_margin_rate, mom_growth_rate, yoy_growth_rate, cum_revenue
--     2024-01 | 140 | 44 | 1,726,852.78 | 1,887,281.74 | 160,428.96 | 0.085 | 12,334.66 | 0.1517 | NULL | NULL | 1,726,852.78
--     2024-02 | 126 | 42 | 1,443,343.08 | 1,578,210.82 | 134,867.74 | 0.0855 | 11,455.1 | 0.1463 | -0.1642 | NULL | 3,170,195.86
--     2024-03 | 207 | 51 | 2,440,587.45 | 2,656,719.46 | 216,132.01 | 0.0814 | 11,790.28 | 0.1359 | 0.6909 | NULL | 5,610,783.31
--     2024-04 | 198 | 55 | 2,823,019.11 | 3,099,775.4 | 276,756.29 | 0.0893 | 14,257.67 | 0.1373 | 0.1567 | NULL | 8,433,802.42
--     2024-05 | 219 | 56 | 3,156,688.24 | 3,471,363.03 | 314,674.79 | 0.0906 | 14,414.1 | 0.1674 | 0.1182 | NULL | 11,590,490.66
--     2024-06 | 199 | 54 | 2,824,442.69 | 3,087,869.02 | 263,426.33 | 0.0853 | 14,193.18 | 0.1657 | -0.1053 | NULL | 14,414,933.35
--     2024-07 | 205 | 55 | 2,707,076.69 | 2,942,157.67 | 235,080.98 | 0.0799 | 13,205.25 | 0.1492 | -0.0416 | NULL | 17,122,010.04
--     2024-08 | 215 | 54 | 2,576,373.68 | 2,828,367.39 | 251,993.71 | 0.0891 | 11,983.13 | 0.1445 | -0.0483 | NULL | 19,698,383.72
--     ...（其余 16 行略）
-- ============================================================
WITH RECURSIVE
-- 递归 CTE：生成 2024-01 ~ 2025-12 的连续月份序列（日期序列补齐）
months(ym) AS (
    SELECT '2024-01'
    UNION ALL
    SELECT strftime('%Y-%m', date(ym || '-01', '+1 month'))
    FROM months
    WHERE ym < '2025-12'
),
-- 只保留已完成订单的月度汇总
monthly AS (
    SELECT
        d.year_month                                   AS ym,
        COUNT(*)                                       AS order_cnt,
        COUNT(DISTINCT o.customer_id)                  AS customer_cnt,
        SUM(o.gross_amount)                            AS gross_amount,
        SUM(o.discount_amount)                         AS discount_amount,
        SUM(o.net_amount)                              AS revenue,
        SUM(o.cost_amount)                             AS cost_amount,
        SUM(o.gross_profit)                            AS gross_profit
    FROM fact_sales_order o
    JOIN dim_date d ON d.date_id = o.order_date_id
    WHERE d.full_date BETWEEN '2024-01-01' AND '2025-12-31'
      AND o.status = '已完成'
    GROUP BY d.year_month
)
SELECT
    m.ym                                                            AS ym,
    COALESCE(x.order_cnt, 0)                                        AS order_cnt,
    COALESCE(x.customer_cnt, 0)                                     AS customer_cnt,
    ROUND(COALESCE(x.revenue, 0), 2)                                AS revenue,
    ROUND(COALESCE(x.gross_amount, 0), 2)                           AS gross_amount,
    ROUND(COALESCE(x.discount_amount, 0), 2)                        AS discount_amount,
    ROUND(COALESCE(x.discount_amount, 0) * 1.0
          / NULLIF(x.gross_amount, 0), 4)                           AS discount_rate,
    ROUND(COALESCE(x.revenue, 0) * 1.0
          / NULLIF(x.order_cnt, 0), 2)                              AS aov,
    ROUND(COALESCE(x.gross_profit, 0) * 1.0
          / NULLIF(x.revenue, 0), 4)                                AS gross_margin_rate,
    -- 环比：与上一期（LAG 1）比
    ROUND((COALESCE(x.revenue, 0)
           - LAG(COALESCE(x.revenue, 0), 1) OVER (ORDER BY m.ym)) * 1.0
          / NULLIF(LAG(COALESCE(x.revenue, 0), 1) OVER (ORDER BY m.ym), 0), 4)
                                                                 AS mom_growth_rate,
    -- 同比：与去年同期（LAG 12）比，2024 年无 2023 年基期故为 NULL
    ROUND((COALESCE(x.revenue, 0)
           - LAG(COALESCE(x.revenue, 0), 12) OVER (ORDER BY m.ym)) * 1.0
          / NULLIF(LAG(COALESCE(x.revenue, 0), 12) OVER (ORDER BY m.ym), 0), 4)
                                                                 AS yoy_growth_rate,
    -- 累计营收（窗口累加）
    ROUND(SUM(COALESCE(x.revenue, 0)) OVER (ORDER BY m.ym), 2)      AS cum_revenue
FROM months m
LEFT JOIN monthly x ON x.ym = m.ym
ORDER BY m.ym;
