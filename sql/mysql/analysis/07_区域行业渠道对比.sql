-- ============================================================
-- 题目：区域 / 行业 / 渠道三个维度的经营绩效横向对比，找出高效与低效市场
-- 口径：营收 = SUM(net_amount) 仅 status='已完成'；客户数 = COUNT(DISTINCT customer_id)；
--       客单价 = 营收 ÷ 订单数；毛利率 = SUM(gross_profit) ÷ 营收；折扣率 = SUM(discount_amount) ÷ SUM(gross_amount)；
--       渠道取 fact_sales_order.channel（订单渠道），区域/行业取 dim_customer 对应属性；
--       三个维度用 UNION ALL 汇总为同一张对比表，行级用 dim_type 标注来源维度。
-- 考察点：UNION ALL 纵向合并多维度结果集；窗口函数 RANK() OVER (PARTITION BY dim_type ...) 做维度内排名、
--          SUM() OVER (PARTITION BY dim_type) 计算维度内占比；CASE WHEN 划分绩效等级。
-- 预期结果：
--   共 16 行；列：dim_type, dim_value, customer_cnt, order_cnt, revenue, revenue_share_in_dim, aov, gross_margin_rate, discount_rate, avg_delivery_days, revenue_rank_in_dim, margin_rank_in_dim, perf_level
--     区域 | 西南 | 15 | 1688 | 23,096,649.32 | 0.3284 | 13,682.85 | 0.1994 | 0.1018 | 13.52 | 1 | 1 | 高毛利-重点经营
--     区域 | 华东 | 20 | 1846 | 22,522,524.56 | 0.3202 | 12,200.72 | 0.151 | 0.0883 | 8.55 | 2 | 2 | 中毛利-稳定经营
--     区域 | 华北 | 13 | 1196 | 15,716,069.95 | 0.2235 | 13,140.53 | 0.1449 | 0.0857 | 13.44 | 3 | 3 | 中毛利-稳定经营
--     区域 | 华南 | 12 | 728 | 8,992,829.19 | 0.1279 | 12,352.79 | 0.0493 | 0.0524 | 13.53 | 4 | 4 | 低毛利-需优化定价与折扣
--     渠道 | 直销 | 24 | 2169 | 28,105,214.63 | 0.3996 | 12,957.68 | 0.1491 | 0.0881 | 11.48 | 1 | 3 | 中毛利-稳定经营
--     渠道 | 经销 | 23 | 2151 | 27,803,937.43 | 0.3953 | 12,926.05 | 0.1552 | 0.0882 | 12.27 | 2 | 2 | 中毛利-稳定经营
--     渠道 | 电商 | 7 | 750 | 10,210,107.57 | 0.1452 | 13,613.48 | 0.1939 | 0.098 | 11.72 | 3 | 1 | 高毛利-重点经营
--     渠道 | OEM | 6 | 388 | 4,208,813.39 | 0.0598 | 10,847.46 | 0.0571 | 0.0578 | 11.48 | 4 | 4 | 低毛利-需优化定价与折扣
--     ...（其余 8 行略）
-- ============================================================
WITH
-- 已完成订单 + 客户属性
base AS (
    SELECT
        o.order_id,
        o.customer_id,
        o.channel,
        o.net_amount,
        o.gross_amount,
        o.discount_amount,
        o.gross_profit,
        o.delivery_days,
        c.region,
        c.industry
    FROM fact_sales_order o
    JOIN dim_date d ON d.date_id = o.order_date_id
    JOIN dim_customer c ON c.customer_id = o.customer_id
    WHERE o.status = '已完成'
      AND d.full_date BETWEEN '2024-01-01' AND '2025-12-31'
),
-- 三个维度纵向合并
unioned AS (
    SELECT '区域' AS dim_type, region AS dim_value, base.* FROM base
    UNION ALL
    SELECT '行业', industry, base.* FROM base
    UNION ALL
    SELECT '渠道', channel, base.* FROM base
),
-- 各维度各取值汇总
dim_agg AS (
    SELECT
        u.dim_type,
        u.dim_value,
        COUNT(DISTINCT u.customer_id)                              AS customer_cnt,
        COUNT(u.order_id)                                          AS order_cnt,
        SUM(u.net_amount)                                          AS revenue,
        SUM(u.gross_amount)                                        AS gross_amount,
        SUM(u.discount_amount)                                     AS discount_amount,
        SUM(u.gross_profit)                                        AS gross_profit,
        AVG(CAST(u.delivery_days AS DOUBLE))                                       AS avg_delivery_days
    FROM unioned u
    GROUP BY u.dim_type, u.dim_value
)
SELECT
    a.dim_type,
    a.dim_value,
    a.customer_cnt,
    a.order_cnt,
    ROUND(a.revenue, 2)                                            AS revenue,
    ROUND(a.revenue * 1.0 / SUM(a.revenue) OVER (PARTITION BY a.dim_type), 4) AS revenue_share_in_dim,
    ROUND(a.revenue * 1.0 / NULLIF(a.order_cnt, 0), 2)              AS aov,
    ROUND(a.gross_profit * 1.0 / NULLIF(a.revenue, 0), 4)            AS gross_margin_rate,
    ROUND(a.discount_amount * 1.0 / NULLIF(a.gross_amount, 0), 4)   AS discount_rate,
    ROUND(a.avg_delivery_days, 2)                                  AS avg_delivery_days,
    RANK() OVER (PARTITION BY a.dim_type ORDER BY a.revenue DESC)    AS revenue_rank_in_dim,
    RANK() OVER (PARTITION BY a.dim_type ORDER BY a.gross_profit * 1.0 / NULLIF(a.revenue, 0) DESC) AS margin_rank_in_dim,
    CASE
        WHEN a.gross_profit * 1.0 / NULLIF(a.revenue, 0) >= 0.16 THEN '高毛利-重点经营'
        WHEN a.gross_profit * 1.0 / NULLIF(a.revenue, 0) >= 0.13 THEN '中毛利-稳定经营'
        ELSE '低毛利-需优化定价与折扣'
    END                                                            AS perf_level
FROM dim_agg a
ORDER BY a.dim_type, a.revenue DESC;
