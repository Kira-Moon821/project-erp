-- ============================================================
-- 题目：客户流失预警——近 90 天无成交但历史贡献高的客户清单
-- 口径：参照日 as_of = 2025-12-31；「近 90 天」= 2025-10-02 ~ 2025-12-31 窗口内无「已完成」订单；
--       历史贡献高 = 历史营收位于全部客户前 25%（PERCENT_RANK < 0.25）；
--       历史营收 M = 2024-01-01 ~ 2025-12-31 已完成订单 net_amount 求和。
-- 考察点：LEFT JOIN 判定「窗口内无成交」；窗口函数 PERCENT_RANK() 做贡献分位、
--          ROW_NUMBER() 做排名、COUNT(*) OVER () 提供分母；CASE WHEN 分级输出预警等级。
-- 预期结果：
--   共 52 行；列：customer_id, customer_name, tier, industry, region, channel, acquisition_source, customer_status, last_order_date, days_since_last_order, hist_order_cnt, hist_revenue, hist_profit, revenue_share_pct, revenue_rank, revenue_pct_rank, recent90d_order_cnt, recent90d_revenue, churn_risk_level, suggested_action
--     4 | 合肥医疗器械有限公司 | A | 电子代工 | 华东 | 直销 | 展会 | 合作中 | 2025-12-30 | 1 | 247 | 3,732,266.22 | 988,033.39 | 0.0531 | 1 | 0 | 35 | 507,527.63 | 关注-成交显著下滑 | 核查竞品与价格，安排销售主动触达
--     10 | 上海物流科技有限公司 | A | 电子代工 | 华北 | 经销 | 展会 | 合作中 | 2025-12-30 | 1 | 241 | 3,714,743.93 | 981,793.9 | 0.0528 | 2 | 0.0169 | 41 | 617,017.45 | 关注-成交显著下滑 | 核查竞品与价格，安排销售主动触达
--     7 | 青岛化工装备有限公司 | A | 新能源 | 西南 | 电商 | 展会 | 已流失 | 2025-12-31 | 0 | 217 | 3,476,688.85 | 920,314.43 | 0.0494 | 3 | 0.0339 | 43 | 848,445.76 | 关注-成交显著下滑 | 核查竞品与价格，安排销售主动触达
--     1 | 杭州新能源材料有限公司 | A | 食品饮料 | 华东 | 电商 | 电话外呼 | 合作中 | 2025-12-31 | 0 | 251 | 3,407,007.88 | 893,722.5 | 0.0484 | 4 | 0.0508 | 51 | 616,313.9 | 关注-成交显著下滑 | 核查竞品与价格，安排销售主动触达
--     5 | 苏州精密制造有限公司 | A | 电子代工 | 西南 | 经销 | 展会 | 合作中 | 2025-12-23 | 8 | 230 | 3,311,397.29 | 898,732.82 | 0.0471 | 5 | 0.0678 | 40 | 608,739.25 | 关注-成交显著下滑 | 核查竞品与价格，安排销售主动触达
--     6 | 重庆化工装备有限公司 | A | 新能源 | 西南 | 直销 | 广告投放 | 合作中 | 2025-12-25 | 6 | 218 | 3,293,972.47 | 882,517.68 | 0.0468 | 6 | 0.0847 | 41 | 569,406 | 关注-成交显著下滑 | 核查竞品与价格，安排销售主动触达
--     3 | 广州化工装备有限公司 | A | 食品饮料 | 华北 | 经销 | 展会 | 合作中 | 2025-12-28 | 3 | 245 | 3,262,021.36 | 852,880.84 | 0.0464 | 7 | 0.1017 | 37 | 270,366.83 | 关注-成交显著下滑 | 核查竞品与价格，安排销售主动触达
--     9 | 西安化工装备有限公司 | A | 汽车零部件 | 华东 | 经销 | 转介绍 | 合作中 | 2025-12-30 | 1 | 223 | 3,176,310.38 | 872,125.81 | 0.0452 | 8 | 0.1186 | 42 | 499,893.95 | 关注-成交显著下滑 | 核查竞品与价格，安排销售主动触达
--     ...（其余 44 行略）
-- ============================================================
WITH
-- 客户全量历史成交汇总（仅已完成订单）
cust_hist AS (
    SELECT
        o.customer_id,
        COUNT(*)            AS hist_order_cnt,
        SUM(o.net_amount)   AS hist_revenue,
        SUM(o.gross_profit) AS hist_profit,
        MAX(d.full_date)    AS last_order_date
    FROM fact_sales_order o
    JOIN dim_date d ON d.date_id = o.order_date_id
    WHERE o.status = '已完成'
      AND d.full_date BETWEEN '2024-01-01' AND '2025-12-31'
    GROUP BY o.customer_id
),
-- 窗口内（近 90 天）成交汇总；无成交的客户不会出现在这里
cust_recent AS (
    SELECT
        o.customer_id,
        COUNT(*)            AS recent_order_cnt,
        SUM(o.net_amount)   AS recent_revenue,
        MAX(d.full_date)    AS recent_last_order
    FROM fact_sales_order o
    JOIN dim_date d ON d.date_id = o.order_date_id
    WHERE o.status = '已完成'
      AND d.full_date BETWEEN '2025-10-02' AND '2025-12-31'
    GROUP BY o.customer_id
),
-- 贡献分位与排名（先 LEFT JOIN 近 90 天成交，无成交则为空）
ranked AS (
    SELECT
        h.*,
        COALESCE(rc.recent_order_cnt, 0)   AS recent90d_order_cnt,
        COALESCE(rc.recent_revenue, 0)     AS recent90d_revenue,
        rc.recent_last_order,
        ROW_NUMBER() OVER (ORDER BY h.hist_revenue DESC)            AS revenue_rank,
        PERCENT_RANK() OVER (ORDER BY h.hist_revenue DESC)          AS revenue_pct_rank,
        COUNT(*) OVER ()                                            AS total_customer_cnt,
        SUM(h.hist_revenue) OVER ()                                 AS total_revenue
    FROM cust_hist h
    LEFT JOIN cust_recent rc ON rc.customer_id = h.customer_id
)
SELECT
    c.customer_id,
    c.customer_name,
    c.tier,
    c.industry,
    c.region,
    c.channel,
    c.acquisition_source,
    c.status                                                AS customer_status,
    r.last_order_date,
    CAST(DATEDIFF('2025-12-31', r.last_order_date) AS SIGNED) AS days_since_last_order,
    r.hist_order_cnt,
    ROUND(r.hist_revenue, 2)                                AS hist_revenue,
    ROUND(r.hist_profit, 2)                                 AS hist_profit,
    ROUND(r.hist_revenue * 1.0 / r.total_revenue, 4)        AS revenue_share_pct,
    r.revenue_rank,
    r.revenue_pct_rank,
    r.recent90d_order_cnt,
    ROUND(r.recent90d_revenue, 2)                      AS recent90d_revenue,
    -- 预警分级：高贡献且近 90 天无成交 = 高危
    CASE
        WHEN r.recent90d_order_cnt = 0 AND r.revenue_pct_rank < 0.10 THEN '高危-核心客户已沉默'
        WHEN r.recent90d_order_cnt = 0 AND r.revenue_pct_rank < 0.25 THEN '高危-重要客户已沉默'
        WHEN r.recent90d_order_cnt = 0                                  THEN '关注-低贡献已沉默'
        WHEN r.recent90d_revenue < r.hist_revenue * 0.25                THEN '关注-成交显著下滑'
        ELSE '健康'
    END                                                     AS churn_risk_level,
    -- 建议动作
    CASE
        WHEN r.recent90d_order_cnt = 0 AND r.revenue_pct_rank < 0.25
            THEN '72 小时内客户经理回访 + 订单流失原因复盘'
        WHEN r.recent90d_order_cnt = 0
            THEN '纳入沉睡客户培育池，自动推送选品与促销'
        WHEN r.recent90d_revenue < r.hist_revenue * 0.25
            THEN '核查竞品与价格，安排销售主动触达'
        ELSE '常规维护'
    END                                                     AS suggested_action
FROM ranked r
JOIN dim_customer c ON c.customer_id = r.customer_id
WHERE r.recent90d_order_cnt = 0
   OR r.recent90d_revenue < r.hist_revenue * 0.25
ORDER BY r.hist_revenue DESC;
