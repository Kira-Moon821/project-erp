-- ============================================================
-- 题目：客户 RFM 分层，识别重要价值客户与沉睡客户
-- 口径：参照日 as_of = 2025-12-31（业务窗口末日）；R = as_of 距最近一次「已完成」成交的天数；
--       F = 期间已完成成交次数；M = 期间已完成成交金额（net_amount 求和）；
--       分档用四分位（NTILE(4)）：R 越近越好（降序分位后取高分），F/M 越大越好；
--       销售额占比 = 该客户 M ÷ 全体客户 M 之和。
-- 考察点：NTILE(4) 窗口函数做四分位分档；CASE WHEN 多分支映射客户标签；
--          窗口函数 SUM() OVER () 计算全客占比、AVG() OVER (PARTITION BY tier) 做分层基准对比。
-- 预期结果：
--   共 60 行；列：customer_id, customer_name, tier, industry, region, channel, acquisition_source, last_order_date, r_days, f_orders, m_amount, m_profit, r_score, f_score, m_score, rfm_score, rfm_segment, revenue_share_pct, tier_avg_m_amount
--     4 | 合肥医疗器械有限公司 | A | 电子代工 | 华东 | 直销 | 展会 | 2025-12-30 | 1 | 247 | 3,732,266.22 | 988,033.39 | 4 | 4 | 4 | 12 | 重要价值客户 | 0.0531 | 3,343,648.53
--     10 | 上海物流科技有限公司 | A | 电子代工 | 华北 | 经销 | 展会 | 2025-12-30 | 1 | 241 | 3,714,743.93 | 981,793.9 | 4 | 4 | 4 | 12 | 重要价值客户 | 0.0528 | 3,343,648.53
--     7 | 青岛化工装备有限公司 | A | 新能源 | 西南 | 电商 | 展会 | 2025-12-31 | 0 | 217 | 3,476,688.85 | 920,314.43 | 4 | 4 | 4 | 12 | 重要价值客户 | 0.0494 | 3,343,648.53
--     1 | 杭州新能源材料有限公司 | A | 食品饮料 | 华东 | 电商 | 电话外呼 | 2025-12-31 | 0 | 251 | 3,407,007.88 | 893,722.5 | 4 | 4 | 4 | 12 | 重要价值客户 | 0.0484 | 3,343,648.53
--     9 | 西安化工装备有限公司 | A | 汽车零部件 | 华东 | 经销 | 转介绍 | 2025-12-30 | 1 | 223 | 3,176,310.38 | 872,125.81 | 4 | 4 | 4 | 12 | 重要价值客户 | 0.0452 | 3,343,648.53
--     2 | 杭州自动化科技有限公司 | A | 物流仓储 | 西南 | 直销 | 广告投放 | 2025-12-31 | 0 | 212 | 3,123,483.69 | 798,318.52 | 4 | 4 | 4 | 12 | 重要价值客户 | 0.0444 | 3,343,648.53
--     8 | 苏州物流科技有限公司 | A | 医疗器械 | 西南 | 直销 | 官网 | 2025-12-30 | 1 | 211 | 2,938,593.27 | 746,704.29 | 4 | 4 | 4 | 12 | 重要价值客户 | 0.0418 | 3,343,648.53
--     3 | 广州化工装备有限公司 | A | 食品饮料 | 华北 | 经销 | 展会 | 2025-12-28 | 3 | 245 | 3,262,021.36 | 852,880.84 | 3 | 4 | 4 | 11 | 重要价值客户 | 0.0464 | 3,343,648.53
--     ...（其余 52 行略）
-- ============================================================
WITH
-- 客户成交汇总
cust_orders AS (
    SELECT
        o.customer_id,
        COUNT(*)              AS f_orders,
        SUM(o.net_amount)     AS m_amount,
        SUM(o.gross_profit)   AS m_profit,
        MAX(d.full_date)      AS last_order_date
    FROM fact_sales_order o
    JOIN dim_date d ON d.date_id = o.order_date_id
    WHERE o.status = '已完成'
      AND d.full_date BETWEEN '2024-01-01' AND '2025-12-31'
    GROUP BY o.customer_id
),
-- 计算 R 值并做四分位分档
rfm_base AS (
    SELECT
        c.customer_id,
        c.customer_name,
        c.tier,
        c.industry,
        c.region,
        c.channel,
        c.acquisition_source,
        co.f_orders,
        ROUND(co.m_amount, 2) AS m_amount,
        co.m_profit,
        co.last_order_date,
        CAST(julianday('2025-12-31') - julianday(co.last_order_date) AS INTEGER) AS r_days
    FROM cust_orders co
    JOIN dim_customer c ON c.customer_id = co.customer_id
),
rfm_scored AS (
    SELECT
        b.*,
        -- R 降序分位：最近成交的排到第 4 档（分数越高越好）
        -- 分位排序追加 customer_id 作为唯一 tiebreaker：NTILE 在存在并列值时，
        -- 档位边界取决于输入行序，若不指定唯一键，SQLite 与 MySQL 的分位结果会不一致
        NTILE(4) OVER (ORDER BY b.r_days DESC, b.customer_id) AS r_score,
        NTILE(4) OVER (ORDER BY b.f_orders, b.customer_id)    AS f_score,
        NTILE(4) OVER (ORDER BY b.m_amount, b.customer_id)    AS m_score
    FROM rfm_base b
)
SELECT
    s.customer_id,
    s.customer_name,
    s.tier,
    s.industry,
    s.region,
    s.channel,
    s.acquisition_source,
    s.last_order_date,
    s.r_days,
    s.f_orders,
    s.m_amount,
    ROUND(s.m_profit, 2)                                             AS m_profit,
    s.r_score,
    s.f_score,
    s.m_score,
    (s.r_score + s.f_score + s.m_score)                              AS rfm_score,
    CASE
        WHEN s.r_score >= 3 AND s.f_score >= 3 AND s.m_score >= 3 THEN '重要价值客户'
        WHEN s.r_score >= 3 AND s.f_score <= 2 AND s.m_score >= 3 THEN '重要发展客户'
        WHEN s.r_score <= 2 AND s.f_score >= 3 AND s.m_score >= 3 THEN '重要保持客户'
        WHEN s.r_score <= 2 AND s.f_score <= 2 AND s.m_score >= 3 THEN '重要挽留客户'
        WHEN s.r_score >= 3 AND s.f_score >= 3 AND s.m_score <= 2 THEN '一般价值客户'
        WHEN s.r_score >= 3 AND s.f_score <= 2 AND s.m_score <= 2 THEN '一般发展客户'
        WHEN s.r_score <= 2 AND s.f_score >= 3 AND s.m_score <= 2 THEN '一般保持客户'
        ELSE '一般挽留客户'
    END                                                             AS rfm_segment,
    ROUND(s.m_amount * 1.0 / SUM(s.m_amount) OVER (), 4)            AS revenue_share_pct,
    ROUND(AVG(s.m_amount) OVER (PARTITION BY s.tier), 2)             AS tier_avg_m_amount
FROM rfm_scored s
-- 加 customer_id 作为最终 tiebreaker：rfm_score 与 m_amount 都可能并列，
-- 若不指定唯一键，并列行的先后在不同数据库里不确定
ORDER BY rfm_score DESC, s.m_amount DESC, s.customer_id;
