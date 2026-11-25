-- ============================================================
-- 题目：线索 → 商机 → 成单漏斗的逐级转化率分析，定位流失环节
-- 口径：漏斗层级 线索 → 需求确认 → 方案演示 → 商务谈判 → 成单（输单视同为「推进到商务谈判后失败」，
--       计入该层级分母）；阶段及以后的数量 = 层级序号 ≥ 当前层级的线索数（用窗口累计求和）；
--       逐级转化率 = 该阶段及以后数量 ÷ 上一阶段及以后数量；
--       成单率 = stage='成单' 数量 ÷ 线索总数；赢率 = 成单数 ÷（成单数 + 输单数）；
--       线索总数按 created_date_id 落在业务窗口 2024-01-01 ~ 2025-12-31。
-- 考察点：CASE WHEN 定义阶段层级序号；窗口函数 SUM() OVER (ORDER BY 层级 DESC) 计算「某阶段及以后」的累计量；
--          LAG() 取上一层级基数；条件聚合算成单率/赢率；UNION ALL 合并漏斗与输单原因分析。
-- 预期结果：
--   共 5 行；列：stage_rank, stage_name, level_lead_cnt, reach_lead_cnt, reach_pct, step_conversion_rate, win_rate_over_all_leads, win_rate_of_closed, avg_win_probability, avg_cycle_days, expected_amount, actual_amount
--     1 | 线索 | 237 | 1062 | 1 | NULL | 0 | NULL | 0.1 | 41.95 | 105,922,422.6 | 0
--     2 | 需求确认 | 226 | 825 | 0.7768 | 0.7768 | 0 | NULL | 0.2893 | 43.14 | 112,882,885.26 | 0
--     3 | 方案演示 | 171 | 599 | 0.564 | 0.7261 | 0 | NULL | 0.4921 | 42.38 | 84,819,841.86 | 0
--     4 | 商务谈判(含输单) | 244 | 428 | 0.403 | 0.7145 | 0 | 0 | 0.4037 | 43.99 | 112,625,194.55 | 0
--     5 | 成单 | 184 | 184 | 0.1733 | 0.4299 | 0.1733 | 1 | 1 | 42.03 | 89,326,375.09 | 89,377,326.72
-- ============================================================
WITH
-- 阶段层级映射（输单与商务谈判同级：均处于谈判阶段）
stage_map(stage, stage_rank) AS (
    SELECT '线索',     1
    UNION ALL SELECT '需求确认', 2
    UNION ALL SELECT '方案演示', 3
    UNION ALL SELECT '商务谈判', 4
    UNION ALL SELECT '输单',     4
    UNION ALL SELECT '成单',     5
),
-- 窗口内线索
leads AS (
    SELECT
        l.lead_id,
        l.stage,
        m.stage_rank,
        l.expected_amount,
        l.actual_amount,
        l.win_probability,
        l.cycle_days,
        l.source_channel,
        l.ai_assisted,
        l.loss_reason,
        d.full_date AS created_date
    FROM fact_lead_opportunity l
    JOIN stage_map m ON m.stage = l.stage
    JOIN dim_date d ON d.date_id = l.created_date_id
    WHERE d.full_date BETWEEN '2024-01-01' AND '2025-12-31'
),
-- 各层级线索数
level_cnt AS (
    SELECT
        stage_rank,
        COUNT(*)                                                     AS level_lead_cnt,
        SUM(CASE WHEN stage = '成单' THEN 1 ELSE 0 END)              AS won_cnt,
        SUM(CASE WHEN stage = '输单' THEN 1 ELSE 0 END)              AS lost_cnt,
        SUM(expected_amount)                                        AS expected_amount,
        SUM(actual_amount)                                          AS actual_amount,
        AVG(win_probability)                                        AS avg_win_probability,
        AVG(cycle_days)                                             AS avg_cycle_days
    FROM leads
    GROUP BY stage_rank
),
-- 累计：该层级及以后的线索数（窗口函数倒序累计）
cumulative AS (
    SELECT
        lc.*,
        SUM(lc.level_lead_cnt) OVER (ORDER BY lc.stage_rank DESC)  AS reach_lead_cnt,
        SUM(lc.won_cnt)         OVER (ORDER BY lc.stage_rank DESC) AS reach_won_cnt,
        SUM(lc.lost_cnt)        OVER (ORDER BY lc.stage_rank DESC) AS reach_lost_cnt
    FROM level_cnt lc
)
SELECT
    c.stage_rank,
    CASE c.stage_rank
        WHEN 1 THEN '线索'
        WHEN 2 THEN '需求确认'
        WHEN 3 THEN '方案演示'
        WHEN 4 THEN '商务谈判(含输单)'
        WHEN 5 THEN '成单'
    END                                                             AS stage_name,
    c.level_lead_cnt,
    c.reach_lead_cnt,
    ROUND(c.reach_lead_cnt * 1.0 / SUM(c.level_lead_cnt) OVER (), 4) AS reach_pct,
    -- 逐级转化率 = 本级及以后 ÷ 上一级及以后
    ROUND(c.reach_lead_cnt * 1.0
          / NULLIF(LAG(c.reach_lead_cnt) OVER (ORDER BY c.stage_rank), 0), 4) AS step_conversion_rate,
    ROUND(c.won_cnt * 1.0 / SUM(c.level_lead_cnt) OVER (), 4)         AS win_rate_over_all_leads,
    ROUND(c.won_cnt * 1.0
          / NULLIF(c.won_cnt + c.lost_cnt, 0), 4)                    AS win_rate_of_closed,
    ROUND(c.avg_win_probability, 4)                                 AS avg_win_probability,
    ROUND(c.avg_cycle_days, 2)                                      AS avg_cycle_days,
    ROUND(c.expected_amount, 2)                                     AS expected_amount,
    ROUND(c.actual_amount, 2)                                       AS actual_amount
FROM cumulative c
ORDER BY c.stage_rank;
