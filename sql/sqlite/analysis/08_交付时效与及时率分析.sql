-- ============================================================
-- 题目：交付时效（delivery_days）与及时率分析，评估各区域/渠道的履约能力
-- 口径：交付天数取 fact_sales_order.delivery_days，仅统计 status='已完成'；
--       平均交付天数 = AVG(delivery_days)；中位数用窗口函数 ROW_NUMBER 取第 50 百分位；
--       及时率 = delivery_days ≤ 10 天的订单数 ÷ 已完成订单数（10 天为交付承诺上限，超期即违约）；
--       违约率 = delivery_days > 10 天占比；区域取 dim_customer.region，渠道取订单 channel。
-- 考察点：窗口函数 ROW_NUMBER() OVER (PARTITION BY ...) 求分位数、LAG() 做月度环比、
--          SUM(CASE WHEN ...) 条件聚合算及时率；CTE 分层聚合 + UNION ALL 合并多维度。
-- 预期结果：
--   共 32 行；列：scope, scope_value, order_cnt, avg_delivery_days, on_time_rate, late_rate, avg_days_mom_change
--     区域 | 华东 | 1846 | 8.55 | 0.6896 | 0.3104 | NULL
--     区域 | 华北 | 1196 | 13.44 | 0.2241 | 0.7759 | NULL
--     区域 | 华南 | 728 | 13.53 | 0.2005 | 0.7995 | NULL
--     区域 | 西南 | 1688 | 13.52 | 0.2257 | 0.7743 | NULL
--     月度趋势 | 2024-01 | 140 | 11.48 | 0.4071 | 0.5929 | NULL
--     月度趋势 | 2024-02 | 126 | 11.98 | 0.3254 | 0.6746 | 0.5
--     月度趋势 | 2024-03 | 207 | 12.37 | 0.3527 | 0.6473 | 0.39
--     月度趋势 | 2024-04 | 198 | 11.82 | 0.3889 | 0.6111 | -0.54
--     ...（其余 24 行略）
-- ============================================================
WITH
-- 已完成订单 + 交付日期
base AS (
    SELECT
        o.order_id,
        o.customer_id,
        o.channel,
        o.delivery_days,
        c.region
    FROM fact_sales_order o
    JOIN dim_date d ON d.date_id = o.order_date_id
    JOIN dim_customer c ON c.customer_id = o.customer_id
    WHERE o.status = '已完成'
      AND d.full_date BETWEEN '2024-01-01' AND '2025-12-31'
),
-- 月度时效（用于观察趋势与环比）
monthly AS (
    SELECT
        d.year_month                                    AS ym,
        COUNT(*)                                        AS order_cnt,
        AVG(o.delivery_days)                            AS avg_delivery_days,
        SUM(CASE WHEN o.delivery_days <= 10 THEN 1 ELSE 0 END) AS on_time_cnt,
        SUM(CASE WHEN o.delivery_days > 10 THEN 1 ELSE 0 END) AS late_cnt
    FROM fact_sales_order o
    JOIN dim_date d ON d.date_id = o.order_date_id
    WHERE o.status = '已完成'
      AND d.full_date BETWEEN '2024-01-01' AND '2025-12-31'
    GROUP BY d.year_month
),
-- 交付天数分位（按区域分组，用 ROW_NUMBER 定位中位数与 P90）
ranked AS (
    SELECT
        b.region,
        b.delivery_days,
        ROW_NUMBER() OVER (PARTITION BY b.region ORDER BY b.delivery_days) AS rn,
        COUNT(*)     OVER (PARTITION BY b.region)                          AS cnt
    FROM base b
),
region_stats AS (
    SELECT
        region,
        COUNT(*)                                                   AS order_cnt,
        AVG(delivery_days)                                         AS avg_delivery_days,
        MAX(CASE WHEN rn = CAST((cnt + 1) / 2 AS INTEGER) THEN delivery_days END) AS p50_delivery_days,
        MAX(CASE WHEN rn = CAST(cnt * 0.9 AS INTEGER) THEN delivery_days END)      AS p90_delivery_days
    FROM ranked
    GROUP BY region
),
region_on_time AS (
    SELECT
        b.region,
        SUM(CASE WHEN b.delivery_days <= 10 THEN 1 ELSE 0 END) AS on_time_cnt
    FROM base b
    GROUP BY b.region
)
SELECT
    '月度趋势'                              AS scope,
    m.ym                                    AS scope_value,
    m.order_cnt,
    ROUND(m.avg_delivery_days, 2)           AS avg_delivery_days,
    ROUND(m.on_time_cnt * 1.0 / NULLIF(m.order_cnt, 0), 4) AS on_time_rate,
    ROUND(m.late_cnt  * 1.0 / NULLIF(m.order_cnt, 0), 4) AS late_rate,
    ROUND(m.avg_delivery_days - LAG(m.avg_delivery_days) OVER (ORDER BY m.ym), 2) AS avg_days_mom_change
FROM monthly m
UNION ALL
SELECT
    '区域',
    r.region,
    r.order_cnt,
    ROUND(r.avg_delivery_days, 2),
    ROUND(ot.on_time_cnt * 1.0 / NULLIF(r.order_cnt, 0), 4),
    ROUND((r.order_cnt - ot.on_time_cnt) * 1.0 / NULLIF(r.order_cnt, 0), 4),
    NULL
FROM region_stats r
JOIN region_on_time ot ON ot.region = r.region
UNION ALL
SELECT
    '渠道',
    b.channel,
    COUNT(*),
    ROUND(AVG(b.delivery_days), 2),
    ROUND(SUM(CASE WHEN b.delivery_days <= 10 THEN 1 ELSE 0 END) * 1.0 / NULLIF(COUNT(*), 0), 4),
    ROUND(SUM(CASE WHEN b.delivery_days > 10 THEN 1 ELSE 0 END) * 1.0 / NULLIF(COUNT(*), 0), 4),
    NULL
FROM base b
GROUP BY b.channel
ORDER BY scope, scope_value;
