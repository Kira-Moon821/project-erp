-- ============================================================
-- 题目：营销渠道 CAC / ROAS / 线索成本分析，识别高效获客渠道
-- 口径：CAC = 渠道成本 ÷ 线索数；ROAS = 归因收入 ÷ 成本；线索成本 = 渠道成本 ÷ 线索数（口径文档定义）；
--       单线索归因收入 = 归因收入 ÷ 线索数；渠道 ROI 排名按 ROAS 降序；
--       投放记录按 date_id 落在业务窗口 2024-01-01 ~ 2025-12-31；线索数 = SUM(leads_count)。
-- 考察点：条件聚合 + NULLIF 防除零；窗口函数 RANK() OVER (ORDER BY ROAS DESC) 排名、
--          SUM() OVER () 计算成本/线索的市场份额、LAG() 做 ROAS 环比（按月）；
--          CTE 分渠道汇总与分月汇总后 UNION ALL 合并。
-- 预期结果：
--   共 150 行；列：scope, scope_value, scope_month, spend_record_cnt, campaign_cnt, total_cost, total_leads, total_revenue_attributed, cac, cost_per_lead, roas, revenue_per_lead, cost_share_pct, lead_share_pct, roas_rank, cac_rank, efficiency_level
--     月度渠道 | 内容营销 | 2024-01 | NULL | NULL | 12,675.1 | 25 | 26,444.12 | 507 | 507 | 2.09 | 1,057.76 | NULL | NULL | 5 | NULL | 中-优化转化
--     月度渠道 | 内容营销 | 2024-02 | NULL | NULL | 10,289.49 | 11 | 30,404.05 | 935.41 | 935.41 | 2.95 | 2,764 | NULL | NULL | 5 | NULL | 良-维持投放
--     月度渠道 | 内容营销 | 2024-03 | NULL | NULL | 14,199.52 | 20 | 39,942.17 | 709.98 | 709.98 | 2.81 | 1,997.11 | NULL | NULL | 5 | NULL | 良-维持投放
--     月度渠道 | 内容营销 | 2024-04 | NULL | NULL | 18,936.7 | 21 | 59,162.16 | 901.75 | 901.75 | 3.12 | 2,817.25 | NULL | NULL | 5 | NULL | 良-维持投放
--     月度渠道 | 内容营销 | 2024-05 | NULL | NULL | 17,210.5 | 21 | 52,045.7 | 819.55 | 819.55 | 3.02 | 2,478.37 | NULL | NULL | 5 | NULL | 良-维持投放
--     月度渠道 | 内容营销 | 2024-06 | NULL | NULL | 18,518.04 | 23 | 51,087.76 | 805.13 | 805.13 | 2.76 | 2,221.21 | NULL | NULL | 5 | NULL | 良-维持投放
--     月度渠道 | 内容营销 | 2024-07 | NULL | NULL | 18,333.29 | 27 | 37,176.38 | 679.01 | 679.01 | 2.03 | 1,376.9 | NULL | NULL | 6 | NULL | 中-优化转化
--     月度渠道 | 内容营销 | 2024-08 | NULL | NULL | 19,597.63 | 52 | 58,520.83 | 376.88 | 376.88 | 2.99 | 1,125.4 | NULL | NULL | 5 | NULL | 良-维持投放
--     ...（其余 142 行略）
-- ============================================================
WITH
-- 窗口内投放明细
spend_base AS (
    SELECT
        s.spend_id,
        s.channel,
        s.campaign_name,
        s.cost_amount,
        s.leads_count,
        s.revenue_attributed,
        d.year_month AS ym,
        d.full_date
    FROM fact_marketing_spend s
    JOIN dim_date d ON d.date_id = s.date_id
    WHERE d.full_date BETWEEN '2024-01-01' AND '2025-12-31'
),
-- 渠道级汇总
channel_agg AS (
    SELECT
        channel,
        COUNT(*)                                    AS spend_record_cnt,
        COUNT(DISTINCT campaign_name)               AS campaign_cnt,
        SUM(cost_amount)                            AS total_cost,
        SUM(leads_count)                            AS total_leads,
        SUM(revenue_attributed)                     AS total_revenue_attributed
    FROM spend_base
    GROUP BY channel
),
-- 月度汇总（用于观察 ROAS 趋势）
month_agg AS (
    SELECT
        ym,
        channel,
        SUM(cost_amount)        AS monthly_cost,
        SUM(leads_count)        AS monthly_leads,
        SUM(revenue_attributed) AS monthly_revenue
    FROM spend_base
    GROUP BY ym, channel
)
SELECT
    '渠道汇总'                                   AS scope,
    c.channel                                    AS scope_value,
    NULL                                         AS scope_month,
    c.spend_record_cnt,
    c.campaign_cnt,
    ROUND(c.total_cost, 2)                       AS total_cost,
    c.total_leads,
    ROUND(c.total_revenue_attributed, 2)         AS total_revenue_attributed,
    -- CAC = 成本 ÷ 线索数；线索成本同口径（口径文档）
    ROUND(c.total_cost * 1.0 / NULLIF(c.total_leads, 0), 2)    AS cac,
    ROUND(c.total_cost * 1.0 / NULLIF(c.total_leads, 0), 2)    AS cost_per_lead,
    -- ROAS = 归因收入 ÷ 成本
    ROUND(c.total_revenue_attributed * 1.0 / NULLIF(c.total_cost, 0), 2) AS roas,
    ROUND(c.total_revenue_attributed * 1.0 / NULLIF(c.total_leads, 0), 2) AS revenue_per_lead,
    ROUND(c.total_cost * 1.0 / SUM(c.total_cost) OVER (), 4)    AS cost_share_pct,
    ROUND(c.total_leads * 1.0 / SUM(c.total_leads) OVER (), 4)  AS lead_share_pct,
    RANK() OVER (ORDER BY c.total_revenue_attributed * 1.0 / NULLIF(c.total_cost, 0) DESC) AS roas_rank,
    RANK() OVER (ORDER BY c.total_cost * 1.0 / NULLIF(c.total_leads, 0) ASC)             AS cac_rank,
    -- 效率分级
    CASE
        WHEN c.total_revenue_attributed * 1.0 / NULLIF(c.total_cost, 0) >= 5.0 THEN '优-高回报加投'
        WHEN c.total_revenue_attributed * 1.0 / NULLIF(c.total_cost, 0) >= 2.5 THEN '良-维持投放'
        WHEN c.total_revenue_attributed * 1.0 / NULLIF(c.total_cost, 0) >= 1.0 THEN '中-优化转化'
        ELSE '差-缩减或更换'
    END                                           AS efficiency_level
FROM channel_agg c
UNION ALL
SELECT
    '月度渠道',
    m.channel,
    m.ym,
    NULL,
    NULL,
    ROUND(m.monthly_cost, 2),
    m.monthly_leads,
    ROUND(m.monthly_revenue, 2),
    ROUND(m.monthly_cost * 1.0 / NULLIF(m.monthly_leads, 0), 2),
    ROUND(m.monthly_cost * 1.0 / NULLIF(m.monthly_leads, 0), 2),
    ROUND(m.monthly_revenue * 1.0 / NULLIF(m.monthly_cost, 0), 2),
    ROUND(m.monthly_revenue * 1.0 / NULLIF(m.monthly_leads, 0), 2),
    NULL,
    NULL,
    RANK() OVER (PARTITION BY m.ym ORDER BY m.monthly_revenue * 1.0 / NULLIF(m.monthly_cost, 0) DESC) AS roas_rank,
    NULL,
    CASE
        WHEN m.monthly_revenue * 1.0 / NULLIF(m.monthly_cost, 0) >= 5.0 THEN '优-高回报加投'
        WHEN m.monthly_revenue * 1.0 / NULLIF(m.monthly_cost, 0) >= 2.5 THEN '良-维持投放'
        WHEN m.monthly_revenue * 1.0 / NULLIF(m.monthly_cost, 0) >= 1.0 THEN '中-优化转化'
        ELSE '差-缩减或更换'
    END
FROM month_agg m
-- 加 scope_month 作为第三排序键：同一渠道有 24 个月的数据行，
-- 若只按 scope/scope_value 排序，并列行的先后在不同数据库里不确定
ORDER BY scope, scope_value, scope_month;
