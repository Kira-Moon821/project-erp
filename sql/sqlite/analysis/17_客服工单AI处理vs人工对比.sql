-- ============================================================
-- 题目：客服工单 AI 处理 vs 人工处理的响应效率、满意度与转商机率对照
-- 口径：AI 提效三指标（口径文档）：首次响应 first_response_minutes、满意度 satisfaction、
--       转商机率 converted_to_opportunity；解决时长 resolution_hours 为辅助观察指标；
--       转商机率 = SUM(converted_to_opportunity) ÷ 工单数；
--       工单按 created_date_id 落在业务窗口 2024-01-01 ~ 2025-12-31。
-- 考察点：条件聚合 CASE WHEN 算转商机数；窗口函数 MAX(CASE WHEN ...) OVER (PARTITION BY 维度)
--          取 AI 组/对照组指标做差值（组间对比）、RANK() 排响应速度；
--          多维度 UNION ALL（整体 / 工单类型 / 受理渠道）纵向合并。
-- 预期结果：
--   共 26 行；列：dim_type, dim_value, handle_mode, ticket_cnt, avg_first_response_minutes, avg_resolution_hours, avg_satisfaction, satisfied_rate, converted_cnt, converted_rate, first_response_minutes_saved, first_response_improve_pct, resolution_hours_saved, satisfaction_lift, converted_rate_lift_pct, response_speed_rank, ai_value_conclusion
--     受理渠道 | 在线 | AI处理 | 48 | 16.83 | 6.94 | 4.479 | 1 | 11 | 0.2292 | 29.92 | 64 | 8.01 | 0.523 | 13.27 | 1 | AI 提效验证：更快、更满意、转商机更高
--     受理渠道 | 在线 | 人工处理 | 114 | 46.75 | 14.95 | 3.956 | 0.8596 | 11 | 0.0965 | 29.92 | 64 | 8.01 | 0.523 | 13.27 | 8 | 人工处理（基线）
--     受理渠道 | 工单系统 | AI处理 | 102 | 19.4 | 6.71 | 4.549 | 1 | 15 | 0.1471 | 26.02 | 57.29 | 7.89 | 0.707 | 2.75 | 4 | AI 提效验证：更快、更满意、转商机更高
--     受理渠道 | 工单系统 | 人工处理 | 209 | 45.43 | 14.6 | 3.842 | 0.799 | 25 | 0.1196 | 26.02 | 57.29 | 7.89 | 0.707 | 2.75 | 6 | 人工处理（基线）
--     受理渠道 | 电话 | AI处理 | 70 | 17.04 | 7.27 | 4.571 | 0.9714 | 11 | 0.1571 | 27.86 | 62.05 | 6.6 | 0.729 | 5.71 | 2 | AI 提效验证：更快、更满意、转商机更高
--     受理渠道 | 电话 | 人工处理 | 140 | 44.91 | 13.87 | 3.843 | 0.7929 | 14 | 0.1 | 27.86 | 62.05 | 6.6 | 0.729 | 5.71 | 5 | 人工处理（基线）
--     受理渠道 | 邮件 | AI处理 | 23 | 18.65 | 7.34 | 4.435 | 1 | 2 | 0.087 | 26.92 | 59.07 | 6.16 | 0.52 | 0.23 | 3 | AI 提效验证：更快、更满意、转商机更高
--     受理渠道 | 邮件 | 人工处理 | 59 | 45.58 | 13.5 | 3.915 | 0.8475 | 5 | 0.0847 | 26.92 | 59.07 | 6.16 | 0.52 | 0.23 | 7 | 人工处理（基线）
--     ...（其余 18 行略）
-- ============================================================
WITH
-- 窗口内工单
tickets AS (
    SELECT
        t.ticket_id,
        t.topic_type,
        t.channel,
        t.ai_handled,
        t.first_response_minutes,
        t.resolution_hours,
        t.satisfaction,
        t.converted_to_opportunity,
        c.tier
    FROM fact_customer_ticket t
    JOIN dim_date d ON d.date_id = t.created_date_id
    JOIN dim_customer c ON c.customer_id = t.customer_id
    WHERE d.full_date BETWEEN '2024-01-01' AND '2025-12-31'
),
-- 多维度纵向合并
unioned AS (
    SELECT '整体' AS dim_type, 'ALL' AS dim_value, * FROM tickets
    UNION ALL
    SELECT '工单类型', topic_type, * FROM tickets
    UNION ALL
    SELECT '受理渠道', channel, * FROM tickets
    UNION ALL
    SELECT '客户分层', tier, * FROM tickets
),
-- 维度汇总
dim_agg AS (
    SELECT
        u.dim_type,
        u.dim_value,
        u.ai_handled,
        COUNT(*)                                                     AS ticket_cnt,
        AVG(u.first_response_minutes)                               AS avg_first_response_minutes,
        AVG(u.resolution_hours)                                     AS avg_resolution_hours,
        AVG(u.satisfaction)                                         AS avg_satisfaction,
        SUM(CASE WHEN u.satisfaction >= 4 THEN 1 ELSE 0 END)         AS satisfied_cnt,
        SUM(u.converted_to_opportunity)                             AS converted_cnt
    FROM unioned u
    GROUP BY u.dim_type, u.dim_value, u.ai_handled
),
-- 计算指标
metrics AS (
    SELECT
        a.*,
        ROUND(a.converted_cnt * 1.0 / NULLIF(a.ticket_cnt, 0), 4)    AS converted_rate,
        ROUND(a.satisfied_cnt * 1.0 / NULLIF(a.ticket_cnt, 0), 4)     AS satisfied_rate
    FROM dim_agg a
),
-- 取同维度 AI / 人工组指标做差值
compared AS (
    SELECT
        m.*,
        MAX(CASE WHEN m.ai_handled = 1 THEN m.avg_first_response_minutes END) OVER (PARTITION BY m.dim_type, m.dim_value) AS ai_frt,
        MAX(CASE WHEN m.ai_handled = 0 THEN m.avg_first_response_minutes END) OVER (PARTITION BY m.dim_type, m.dim_value) AS ctrl_frt,
        MAX(CASE WHEN m.ai_handled = 1 THEN m.avg_resolution_hours END) OVER (PARTITION BY m.dim_type, m.dim_value)      AS ai_hours,
        MAX(CASE WHEN m.ai_handled = 0 THEN m.avg_resolution_hours END) OVER (PARTITION BY m.dim_type, m.dim_value)      AS ctrl_hours,
        MAX(CASE WHEN m.ai_handled = 1 THEN m.avg_satisfaction END) OVER (PARTITION BY m.dim_type, m.dim_value)           AS ai_sat,
        MAX(CASE WHEN m.ai_handled = 0 THEN m.avg_satisfaction END) OVER (PARTITION BY m.dim_type, m.dim_value)           AS ctrl_sat,
        MAX(CASE WHEN m.ai_handled = 1 THEN m.converted_rate END) OVER (PARTITION BY m.dim_type, m.dim_value)             AS ai_conv,
        MAX(CASE WHEN m.ai_handled = 0 THEN m.converted_rate END) OVER (PARTITION BY m.dim_type, m.dim_value)             AS ctrl_conv
    FROM metrics m
)
SELECT
    c.dim_type,
    c.dim_value,
    CASE c.ai_handled WHEN 1 THEN 'AI处理' ELSE '人工处理' END      AS handle_mode,
    c.ticket_cnt,
    ROUND(c.avg_first_response_minutes, 2)                         AS avg_first_response_minutes,
    ROUND(c.avg_resolution_hours, 2)                               AS avg_resolution_hours,
    ROUND(c.avg_satisfaction, 3)                                   AS avg_satisfaction,
    ROUND(c.satisfied_rate, 4)                                     AS satisfied_rate,
    c.converted_cnt,
    ROUND(c.converted_rate, 4)                                    AS converted_rate,
    -- AI 相对人工的改善幅度
    ROUND(c.ctrl_frt - c.ai_frt, 2)                                AS first_response_minutes_saved,
    ROUND((c.ctrl_frt - c.ai_frt) * 100.0 / NULLIF(c.ctrl_frt, 0), 2) AS first_response_improve_pct,
    ROUND(c.ctrl_hours - c.ai_hours, 2)                            AS resolution_hours_saved,
    ROUND(c.ai_sat - c.ctrl_sat, 3)                                AS satisfaction_lift,
    ROUND((c.ai_conv - c.ctrl_conv) * 100, 2)                      AS converted_rate_lift_pct,
    RANK() OVER (PARTITION BY c.dim_type ORDER BY c.avg_first_response_minutes ASC) AS response_speed_rank,
    CASE
        WHEN c.ai_handled = 1 AND c.avg_first_response_minutes < c.ctrl_frt
             AND c.avg_satisfaction > c.ctrl_sat
             AND c.converted_rate > c.ctrl_conv
            THEN 'AI 提效验证：更快、更满意、转商机更高'
        WHEN c.ai_handled = 0 THEN '人工处理（基线）'
        ELSE '差异不明显'
    END                                                            AS ai_value_conclusion
FROM compared c
ORDER BY c.dim_type, c.dim_value, c.ai_handled DESC;
