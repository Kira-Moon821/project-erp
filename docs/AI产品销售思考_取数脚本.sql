-- =============================================================================
-- AI 产品销售思考 · 取数脚本
-- 项目：ERP 经营分析实验室（工业自动化零部件 B2B 经销商）
-- 数据库：data/erp.db（SQLite，口径来源 docs/数据字典与业务口径.md）
-- 业务窗口：2024-01-01 ~ 2025-12-31（24 个月）
--
-- 执行方式：
--   sqlite3 data/erp.db < docs/AI产品销售思考_取数脚本.sql
--   或 python -c "import sqlite3;c=sqlite3.connect('data/erp.db');c.executescript(open('docs/AI产品销售思考_取数脚本.sql',encoding='utf-8').read())"
--
-- 口径纪律（来自数据字典 §3、§5）：
--   1. 营收 = net_amount 求和，仅 status='已完成'；已退款不计入；已取消不计入订单数。
--   2. 库存/采购指标不受订单状态影响。
--   3. 月末库存快照以 2025-12-31 为业务窗口末点。
--      注意：fact_inventory_snapshot 另含 2026-01-31 一期，其 on_hand 与 2025-12-31 完全相同
--      （仅 in_transit_qty 变化），属维度尾部日期，不作为业务分析末点，见 Q10/Q13。
-- =============================================================================


-- =============================================================================
-- 第一组：AI 辅助商机（销售思考的量化底座）
-- =============================================================================

-- Q1  AI 辅助 vs 未辅助商机的成单率 / 平均赢率 / 平均周期（全量 1062 条）
SELECT ai_assisted,
       COUNT(*)                                                        AS 商机数,
       SUM(CASE WHEN stage='成单' THEN 1 ELSE 0 END)                    AS 成单数,
       ROUND(100.0*SUM(CASE WHEN stage='成单' THEN 1 ELSE 0 END)/COUNT(*), 2) AS 成单率_pct,
       ROUND(AVG(win_probability), 4)                                  AS 平均赢率,
       ROUND(AVG(cycle_days), 1)                                       AS 平均周期_天,
       ROUND(AVG(expected_amount), 1)                                  AS 平均预期额,
       ROUND(AVG(CASE WHEN stage='成单' THEN actual_amount END), 1)     AS 成单均额
FROM fact_lead_opportunity
GROUP BY ai_assisted;
-- 结果：AI 组 354 条 / 成单率 21.75% / 赢率 0.5155 / 周期 36.5 天
--       人工组 708 条 / 成单率 15.11% / 赢率 0.3859 / 周期 45.9 天

-- Q1b 分年度拆分（检验优势是否稳定，而非某一年偶然）
SELECT d.year, l.ai_assisted, COUNT(*) AS 商机数,
       ROUND(100.0*SUM(CASE WHEN l.stage='成单' THEN 1 ELSE 0 END)/COUNT(*), 2) AS 成单率_pct,
       ROUND(AVG(l.win_probability), 4) AS 平均赢率,
       ROUND(AVG(l.cycle_days), 1)      AS 平均周期_天
FROM fact_lead_opportunity l JOIN dim_date d ON d.date_id = l.created_date_id
GROUP BY d.year, l.ai_assisted ORDER BY d.year, l.ai_assisted;
-- 结果：2024 AI 18.49% vs 人工 17.45%（差 1.04pp）；2025 AI 24.04% vs 人工 13.18%（差 10.86pp）

-- Q2  漏斗各级数量与 AI 渗透率
SELECT stage, COUNT(*) AS 数量,
       SUM(ai_assisted) AS AI辅助数,
       ROUND(100.0*SUM(ai_assisted)/COUNT(*), 1) AS AI渗透率_pct
FROM fact_lead_opportunity GROUP BY stage;
-- 结果：线索 237(29.5%)、需求确认 226(32.7%)、方案演示 171(35.1%)、
--       商务谈判 133(33.8%)、成单 184(41.8%)、输单 111(25.2%)

-- Q3  漏斗各级数量与逐级转化率
-- 重要口径说明：fact_lead_opportunity 每行是一条线索的【当前阶段】快照，不是阶段流水。
-- 因此「某阶段及以后」= 当前阶段序号 ≥ 该阶段序号的全部线索（含已推进到更后阶段与已输单的）。
WITH s AS (
  SELECT CASE stage
           WHEN '线索' THEN 1 WHEN '需求确认' THEN 2 WHEN '方案演示' THEN 3
           WHEN '商务谈判' THEN 4 WHEN '成单' THEN 5 WHEN '输单' THEN 5 END AS lvl,
         COUNT(*) AS n,
         SUM(CASE WHEN stage='成单' THEN 1 ELSE 0 END) AS won
  FROM fact_lead_opportunity GROUP BY stage),
-- 累计留存：lvl ≥ k 的线索数（窗口函数后向累加）
lvl AS (SELECT lvl, SUM(n) OVER (ORDER BY lvl DESC) AS n_at_or_after FROM s),
tot AS (SELECT SUM(n) all_leads, SUM(won) all_won FROM s),
f AS (SELECT
  (SELECT all_leads FROM tot) AS l1,
  (SELECT n_at_or_after FROM lvl WHERE lvl=2) AS l2,
  (SELECT n_at_or_after FROM lvl WHERE lvl=3) AS l3,
  (SELECT n_at_or_after FROM lvl WHERE lvl=4) AS l4,
  (SELECT n_at_or_after FROM lvl WHERE lvl=5) AS l5,
  (SELECT all_won FROM tot) AS won)
SELECT '1_线索' AS 阶段, l1 AS 该阶段及以后_线索数,
       ROUND(100.0*l1/l1, 2)   AS 线索到需求确认_pct,
       ROUND(100.0*l3/l1, 2)   AS 线索到方案演示_pct,
       ROUND(100.0*l4/l1, 2)   AS 线索到商务谈判_pct,
       ROUND(100.0*l5/l1, 2)   AS 线索到已决策_pct,
       ROUND(100.0*won/l1, 2)  AS 线索到成单_pct
FROM f
UNION ALL
SELECT '2_需求确认', l2, ROUND(100.0*l3/l2, 2), ROUND(100.0*l4/l2, 2),
       ROUND(100.0*l5/l2, 2), ROUND(100.0*won/l2, 2), ROUND(100.0*won/l2, 2)
FROM f
UNION ALL
SELECT '3_方案演示', l3, ROUND(100.0*l4/l3, 2), ROUND(100.0*l5/l3, 2),
       ROUND(100.0*won/l3, 2), ROUND(100.0*won/l3, 2), ROUND(100.0*won/l3, 2)
FROM f
UNION ALL
SELECT '4_商务谈判', l4, ROUND(100.0*l5/l4, 2), ROUND(100.0*won/l4, 2),
       ROUND(100.0*won/l4, 2), ROUND(100.0*won/l4, 2), ROUND(100.0*won/l4, 2)
FROM f
UNION ALL
SELECT '5_已决策', l5, ROUND(100.0*won/l5, 2), ROUND(100.0*won/l5, 2),
       ROUND(100.0*won/l5, 2), ROUND(100.0*won/l5, 2), ROUND(100.0*won/l5, 2)
FROM f;
-- 结果：线索 1,062 → 需求确认 825（77.68%）→ 方案演示 599（72.61%）→ 商务谈判 428（71.45%）
--       → 已决策 295（68.93%）→ 成单 184（62.37%）
--       即：整体线索到成单率 17.33%，已决策口径胜率 62.37%
--       损耗最大的两跳是「线索→需求确认」丢 237 条、「方案演示→商务谈判」丢 171 条

-- Q4  渠道维度漏斗与 AI 混合度
SELECT source_channel, COUNT(*) AS 线索数,
       SUM(CASE WHEN stage IN ('成单','输单') THEN 1 ELSE 0 END) AS 已决策,
       SUM(CASE WHEN stage='成单' THEN 1 ELSE 0 END)            AS 成单,
       ROUND(100.0*SUM(CASE WHEN stage='成单' THEN 1 ELSE 0 END)/COUNT(*), 2)          AS 成单率_pct,
       ROUND(100.0*SUM(CASE WHEN stage='成单' THEN 1 ELSE 0 END)
             /NULLIF(SUM(CASE WHEN stage IN ('成单','输单') THEN 1 ELSE 0 END),0), 2)   AS 已决策胜率_pct,
       ROUND(AVG(ai_assisted), 3) AS AI混合度
FROM fact_lead_opportunity GROUP BY source_channel ORDER BY 线索数 DESC;
-- 结果：官网 289 / 展会 208 / 转介绍 232；AI 混合度最高的是电话外呼 0.495

-- Q5  输单原因分布（客户跟进类痛点的直接证据）
SELECT loss_reason, COUNT(*) AS 输单数,
       ROUND(100.0*COUNT(*)/SUM(COUNT(*)) OVER (), 1) AS 占比_pct
FROM fact_lead_opportunity WHERE stage='输单' GROUP BY loss_reason ORDER BY 输单数 DESC;
-- 结果：竞品更优 26、技术方案不匹配 23、需求延期 19、预算不足 16、
--       响应不及时 16、决策链未打通 11 —— 跟进类合计 27 条 = 24.3%

-- Q6  AI 商机分层检验（控制混杂后的稳健性）
SELECT source_channel,
       SUM(CASE WHEN ai_assisted=1 THEN 1 ELSE 0 END) AS AI样本,
       SUM(CASE WHEN ai_assisted=0 THEN 1 ELSE 0 END) AS 人工样本,
       ROUND(100.0*SUM(CASE WHEN ai_assisted=1 AND stage='成单' THEN 1 ELSE 0 END)
             /NULLIF(SUM(CASE WHEN ai_assisted=1 THEN 1 ELSE 0 END),0), 2) AS AI成单率_pct,
       ROUND(100.0*SUM(CASE WHEN ai_assisted=0 AND stage='成单' THEN 1 ELSE 0 END)
             /NULLIF(SUM(CASE WHEN ai_assisted=0 THEN 1 ELSE 0 END),0), 2) AS 人工成单率_pct,
       ROUND(AVG(CASE WHEN ai_assisted=1 THEN cycle_days END), 1) AS AI周期,
       ROUND(AVG(CASE WHEN ai_assisted=0 THEN cycle_days END), 1) AS 人工周期
FROM fact_lead_opportunity GROUP BY source_channel ORDER BY AI样本 DESC;
-- 结果：6 个渠道中 5 个 AI 组胜率更高；唯一例外是内容营销（AI 16.0% vs 人工 17.54%）
--       → 说明 AI 优势不是渠道结构造成的，但也不是全渠道通吃的定理

-- Q7  按商机金额带分层（检验优势是否只来自"AI 更容易被用在商机"这一选择偏差）
SELECT CASE WHEN expected_amount < 300000 THEN '1_小于30万'
            WHEN expected_amount < 500000 THEN '2_30至50万'
            ELSE '3_50万以上' END AS 金额带,
       SUM(CASE WHEN ai_assisted=1 THEN 1 ELSE 0 END) AS AI样本,
       SUM(CASE WHEN ai_assisted=0 THEN 1 ELSE 0 END) AS 人工样本,
       ROUND(100.0*SUM(CASE WHEN ai_assisted=1 AND stage='成单' THEN 1 ELSE 0 END)
             /NULLIF(SUM(CASE WHEN ai_assisted=1 THEN 1 ELSE 0 END),0), 2) AS AI成单率_pct,
       ROUND(100.0*SUM(CASE WHEN ai_assisted=0 AND stage='成单' THEN 1 ELSE 0 END)
             /NULLIF(SUM(CASE WHEN ai_assisted=0 THEN 1 ELSE 0 END),0), 2) AS 人工成单率_pct
FROM fact_lead_opportunity GROUP BY 金额带 ORDER BY 金额带;
-- 结果：<30万 16.67% vs 16.35%（几乎无差）；30-50万 22.58% vs 16.96%；
--       >50万 24.46% vs 13.37%
--       → 关键结论：AI 优势集中在大额商机，小额商机几乎无效。
--         销售上必须说"AI 帮的是大单"，不能笼统说"AI 提升成单率"。

-- Q8  Mantel-Haenszel 分层合并（按渠道×年份分层后合并赢率，剔除混杂）
WITH strata AS (
  SELECT l.source_channel, d.year,
         SUM(CASE WHEN l.ai_assisted=1 THEN 1 ELSE 0 END) AS a11,
         SUM(CASE WHEN l.ai_assisted=1 AND l.stage='成单' THEN 1 ELSE 0 END) AS a10,
         SUM(CASE WHEN l.ai_assisted=0 THEN 1 ELSE 0 END) AS a01,
         SUM(CASE WHEN l.ai_assisted=0 AND l.stage='成单' THEN 1 ELSE 0 END) AS a00
  FROM fact_lead_opportunity l JOIN dim_date d ON d.date_id=l.created_date_id
  GROUP BY l.source_channel, d.year)
SELECT ROUND(100.0*SUM(a10)*1.0/NULLIF(SUM(a11),0), 2) AS 分层合并_AI胜率_pct,
       ROUND(100.0*SUM(a00)*1.0/NULLIF(SUM(a01),0), 2) AS 分层合并_人工胜率_pct,
       SUM(a11) AS AI样本, SUM(a01) AS 人工样本
FROM strata;
-- 结果：21.75% vs 15.11%（与未分层一致，说明渠道×年份混杂影响很小）

-- Q9  成单率差异的 z 检验（两比例检验，判断差异是否可能来自抽样波动）
WITH s AS (
  SELECT ai_assisted, COUNT(*) AS n,
         SUM(CASE WHEN stage='成单' THEN 1 ELSE 0 END) AS w
  FROM fact_lead_opportunity GROUP BY ai_assisted),
p AS (SELECT ai_assisted, 1.0*w/n AS p, n FROM s)
SELECT ROUND(MAX(p1.p)-MIN(p0.p), 4) AS 成单率差,
       ROUND((p1.p-p0.p)/SQRT(p1.p*(1-p1.p)/p1.n + p0.p*(1-p0.p)/p0.n), 3) AS z值
FROM p p1, p p0 WHERE p1.ai_assisted=1 AND p0.ai_assisted=0;
-- 结果：差 6.64pp，z=2.58（|z|>1.96，p<0.05，统计显著；但 z=2.58 偏小，
--       仍属于"显著但不强"，对外表述应为"观察到相关"，不能写成因果结论）


-- =============================================================================
-- 第二组：AI 工单处理（客服响应效率）
-- =============================================================================

-- Q10 AI 处理 vs 人工工单全指标对比
SELECT ai_handled, COUNT(*) AS 工单数,
       ROUND(AVG(first_response_minutes), 1) AS 平均首响_分钟,
       ROUND(AVG(resolution_hours), 2)        AS 平均解决时长_小时,
       ROUND(AVG(satisfaction), 3)            AS 平均满意度,
       SUM(converted_to_opportunity)         AS 转商机数,
       ROUND(100.0*SUM(converted_to_opportunity)/COUNT(*), 2) AS 转商机率_pct
FROM fact_customer_ticket GROUP BY ai_handled;
-- 结果：AI 243 单 / 首响 18.1 分钟 / 解决 6.98h / 满意度 4.531 / 转商机 16.05%
--       人工 522 单 / 首响 45.6 分钟 / 解决 14.36h / 满意度 3.875 / 转商机 10.54%

-- Q11 分工单类型（AI 效果是否跨话题稳定）
SELECT topic_type, ai_handled, COUNT(*) AS 工单数,
       ROUND(AVG(first_response_minutes), 1) AS 首响_分钟,
       ROUND(AVG(satisfaction), 2)            AS 满意度,
       ROUND(100.0*SUM(converted_to_opportunity)/COUNT(*), 2) AS 转商机率_pct
FROM fact_customer_ticket GROUP BY topic_type, ai_handled ORDER BY topic_type, ai_handled;
-- 结果：5 类话题（数据导出/报表需求/系统故障/功能咨询/售后支持）AI 首响全部更低，
--       满意度全部更高；其中报表需求类 AI 首响 18.2 vs 人工 44.7 分钟

-- Q12 工单月度趋势（AI 覆盖率波动 → 采纳风险证据）
SELECT d.year_month, COUNT(*) AS 工单数,
       SUM(t.ai_handled) AS AI处理数,
       ROUND(100.0*SUM(t.ai_handled)/COUNT(*), 1) AS AI覆盖率_pct,
       ROUND(AVG(t.first_response_minutes), 1)   AS 整体首响_分钟,
       ROUND(AVG(t.satisfaction), 2)             AS 整体满意度
FROM fact_customer_ticket t JOIN dim_date d ON d.date_id=t.created_date_id
GROUP BY d.year_month ORDER BY d.year_month;
-- 结果：AI 覆盖率月度区间 11.1% ~ 50.0%，波动极大（2024-08 仅 11.1%，2025-10 仅 13.2%）

-- Q13 客户覆盖度（AI 是否只服务大客户）
SELECT COUNT(DISTINCT customer_id) AS 有工单客户数 FROM fact_customer_ticket;
-- 结果：60 个客户全部有工单记录（覆盖率 100%）


-- =============================================================================
-- 第三组：营销投放效率与口径分裂
-- =============================================================================

-- Q14 营销各渠道 CAC / ROAS（全量 24 个月）
SELECT channel,
       ROUND(SUM(cost_amount), 0)       AS 总成本,
       SUM(leads_count)                 AS 线索数,
       ROUND(SUM(cost_amount)/NULLIF(SUM(leads_count),0), 1) AS CAC_元每线索,
       ROUND(SUM(revenue_attributed), 0) AS 归因收入,
       ROUND(SUM(revenue_attributed)/NULLIF(SUM(cost_amount),0), 2) AS ROAS
FROM fact_marketing_spend GROUP BY channel ORDER BY 总成本 DESC;
-- 结果：行业展会 CAC 533.9 / ROAS 4.95；搜索广告 587.5 / 3.49；合作伙伴分成 545.1 / 4.22；
--       外呼中心 586.3 / 1.93；内容营销 598.2 / 2.53；转介绍激励 679.1 / 5.94

-- Q15 营销口径线索 vs CRM 口径线索（数据孤岛的最硬证据）
SELECT (SELECT SUM(leads_count) FROM fact_marketing_spend)      AS 营销口径线索数,
       (SELECT COUNT(*) FROM fact_lead_opportunity)             AS CRM口径线索数,
       ROUND(1.0*(SELECT SUM(leads_count) FROM fact_marketing_spend)
             /(SELECT COUNT(*) FROM fact_lead_opportunity), 2) AS 口径差异倍数;
-- 结果：10,894 vs 1,062 = 10.26 倍
--       → 客户问"我今年投了多少、花了多少钱、带来多少单"时，
--         用哪个口径算出的 CAC 可以差 10 倍以上，这是"数据孤岛与口径不一"的量化证据

-- Q16 同一渠道两种 CAC 口径的对比（渠道名映射：行业展会→展会 等）
-- 说明：营销 channel 与 CRM source_channel 是两套命名，此处手工映射后比较
WITH mkt AS (SELECT channel, SUM(cost_amount) cost, SUM(leads_count) leads
             FROM fact_marketing_spend GROUP BY channel),
crm AS (SELECT source_channel, COUNT(*) leads, SUM(CASE WHEN stage='成单' THEN 1 ELSE 0 END) won
        FROM fact_lead_opportunity GROUP BY source_channel)
SELECT '行业展会→展会' AS 映射, ROUND(m.cost,0) AS 成本, m.leads AS 营销线索, c.leads AS CRM线索, c.won AS 成单,
       ROUND(m.cost/m.leads, 0)  AS CAC_营销口径,
       ROUND(m.cost/c.leads, 0)  AS CAC_CRM口径,
       ROUND(m.cost/c.won, 0)    AS 单成单成本
FROM mkt m JOIN crm c ON m.channel='行业展会' AND c.source_channel='展会'
UNION ALL SELECT '转介绍激励→转介绍', ROUND(m.cost,0), m.leads, c.leads, c.won,
       ROUND(m.cost/m.leads,0), ROUND(m.cost/c.leads,0), ROUND(m.cost/c.won,0)
FROM mkt m JOIN crm c ON m.channel='转介绍激励' AND c.source_channel='转介绍'
UNION ALL SELECT '搜索广告→广告投放', ROUND(m.cost,0), m.leads, c.leads, c.won,
       ROUND(m.cost/m.leads,0), ROUND(m.cost/c.leads,0), ROUND(m.cost/c.won,0)
FROM mkt m JOIN crm c ON m.channel='搜索广告' AND c.source_channel='广告投放'
UNION ALL SELECT '外呼中心→电话外呼', ROUND(m.cost,0), m.leads, c.leads, c.won,
       ROUND(m.cost/m.leads,0), ROUND(m.cost/c.leads,0), ROUND(m.cost/c.won,0)
FROM mkt m JOIN crm c ON m.channel='外呼中心' AND c.source_channel='电话外呼'
UNION ALL SELECT '内容营销→内容营销', ROUND(m.cost,0), m.leads, c.leads, c.won,
       ROUND(m.cost/m.leads,0), ROUND(m.cost/c.leads,0), ROUND(m.cost/c.won,0)
FROM mkt m JOIN crm c ON m.channel='内容营销' AND c.source_channel='内容营销'
UNION ALL SELECT '合作伙伴分成→转介绍', ROUND(m.cost,0), m.leads, c.leads, c.won,
       ROUND(m.cost/m.leads,0), ROUND(m.cost/c.leads,0), ROUND(m.cost/c.won,0)
FROM mkt m JOIN crm c ON m.channel='合作伙伴分成' AND c.source_channel='转介绍';
-- 结果（节选）：行业展会 CAC 营销口径 534 元 / CRM 口径 14,360 元 / 单成单成本 74,672 元
--       转介绍激励 CAC 营销口径 679 元 / CRM 口径 644 元 / 单成单成本 4,150 元
--       → 同一渠道两种口径差 27 倍。单成单成本从 4,150 元到 74,672 元不等，
--         足以让财务和销售对"该砍哪个渠道"得出完全相反的结论。

-- Q17 2025 年分渠道（用于营销止损测算）
SELECT m.channel, ROUND(SUM(m.cost_amount),0) AS 成本,
       SUM(m.leads_count) AS 线索,
       ROUND(SUM(m.revenue_attributed)/SUM(m.cost_amount), 2) AS ROAS
FROM fact_marketing_spend m JOIN dim_date d ON d.date_id=m.date_id
WHERE d.year=2025 GROUP BY m.channel ORDER BY 成本 DESC;
-- 结果：外呼中心 ROAS 2.06、内容营销 ROAS 2.50，合计投入 574,454 元（2025）


-- =============================================================================
-- 第四组：内部 AI 助手使用（采纳率与节省工时）
-- =============================================================================

-- Q18 各场景采纳率与节省工时
SELECT scenario, COUNT(*) AS 记录数,
       SUM(query_count)    AS 查询次数,
       SUM(accepted_count) AS 采纳次数,
       ROUND(100.0*SUM(accepted_count)/SUM(query_count), 2) AS 采纳率_pct,
       ROUND(SUM(minutes_saved)/60.0, 1)                  AS 节省工时_小时,
       COUNT(DISTINCT employee_id)                        AS 使用人数
FROM fact_ai_usage GROUP BY scenario;
-- 结果：自然语言取数 70.68% / 403.4h；经营日报生成 70.21% / 393.9h；客户洞察摘要 70.25% / 376.4h
--       三个场景采纳率几乎一致（70.2%~70.7%），说明采纳瓶颈不是场景设计，是通用信任度

-- Q19 总体采纳率与累计节省工时
SELECT COUNT(*) AS 记录数, SUM(query_count) AS 查询, SUM(accepted_count) AS 采纳,
       ROUND(100.0*SUM(accepted_count)/SUM(query_count), 2) AS 总体采纳率_pct,
       ROUND(SUM(minutes_saved), 0) AS 累计节省分钟,
       ROUND(SUM(minutes_saved)/60.0, 1) AS 累计节省小时,
       COUNT(DISTINCT employee_id) AS 使用人数, COUNT(DISTINCT date_id) AS 有记录月份数
FROM fact_ai_usage;
-- 结果：12,969 次查询 / 9,128 次采纳 / 采纳率 70.38% / 70,419 分钟 = 1,173.7 小时 / 17 人 / 24 个月

-- Q20 单次效率（模块一价值换算的单位价值）
SELECT ROUND(SUM(minutes_saved)*1.0/SUM(accepted_count), 2) AS 每次采纳节省分钟,
       ROUND(SUM(minutes_saved)*1.0/SUM(query_count), 2)    AS 每次查询节省分钟,
       ROUND(AVG(minutes_saved), 2)                         AS 每条记录平均节省分钟
FROM fact_ai_usage;
-- 结果：每次被采纳的查询节省 7.71 分钟（未采纳的不计收益）

-- Q21 采纳率年度与月度趋势（采纳率风险证据）
SELECT d.year, SUM(u.query_count) AS 查询, SUM(u.accepted_count) AS 采纳,
       ROUND(100.0*SUM(u.accepted_count)/SUM(u.query_count), 2) AS 采纳率_pct,
       ROUND(SUM(u.minutes_saved)/60.0, 1) AS 节省工时
FROM fact_ai_usage u JOIN dim_date d ON d.date_id=u.date_id GROUP BY d.year;
-- 结果：2024 采纳率 70.57% / 589.8h；2025 采纳率 70.20% / 583.8h —— 使用量与采纳率双双停滞

-- Q22 各团队采纳率（识别采纳洼地）
SELECT e.team, COUNT(DISTINCT e.employee_id) AS 人数,
       SUM(u.query_count) AS 查询,
       ROUND(100.0*SUM(u.accepted_count)/SUM(u.query_count), 2) AS 采纳率_pct,
       ROUND(SUM(u.minutes_saved)/60.0, 1) AS 节省工时
FROM fact_ai_usage u JOIN dim_employee e ON e.employee_id=u.employee_id
GROUP BY e.team ORDER BY 节省工时 DESC;
-- 结果：线上运营组 70.47%（13人/897.7h）、大客户组 68.70%（最低）、华南销售组 71.28%（最高）
--       团队间差异仅 2.6pp → 采纳率是产品级问题，不是团队能力差异

-- Q23 未使用 AI 的员工（推广缺口）
SELECT e.employee_id, e.employee_name, e.team, e.role
FROM dim_employee e LEFT JOIN fact_ai_usage u ON u.employee_id=e.employee_id
GROUP BY e.employee_id HAVING COUNT(u.usage_id)=0;
-- 结果：1 人（谢文博，线上运营组销售总监）24 个月零使用
--       总监级岗位不用 → 一线对"老板都算不上"的信号敏感，推广阻力真实存在


-- =============================================================================
-- 第五组：库存与补货
-- =============================================================================

-- Q24 业务窗口末月末库存快照
SELECT COUNT(*) AS 快照行数,
       COUNT(DISTINCT product_id) AS SKU数,
       SUM(CASE WHEN on_hand_qty < safety_stock THEN 1 ELSE 0 END) AS 低于安全库存行数,
       SUM(CASE WHEN on_hand_qty = 0 THEN 1 ELSE 0 END)             AS 零库存行数,
       SUM(CASE WHEN in_transit_qty > 0 THEN 1 ELSE 0 END)         AS 有在途行数,
       ROUND(SUM(inventory_value), 0) AS 库存金额
FROM fact_inventory_snapshot
WHERE date_id=(SELECT date_id FROM dim_date WHERE full_date='2025-12-31');
-- 结果：160 行（80 SKU × 2 仓）/ 8 行低于安全库存 / 7 行零库存 / 库存金额 19,067,978 元

-- Q25 末月缺货明细：区分「真缺货」与「停产 SKU 残留安全库存」
SELECT p.sku, p.category, p.status AS 商品状态, s.warehouse,
       s.on_hand_qty AS 现存, s.safety_stock AS 安全库存,
       s.in_transit_qty AS 在途, ROUND(s.inventory_value,0) AS 库存金额
FROM fact_inventory_snapshot s JOIN dim_product p ON p.product_id=s.product_id
WHERE s.date_id=(SELECT date_id FROM dim_date WHERE full_date='2025-12-31')
  AND s.on_hand_qty < s.safety_stock
ORDER BY p.status, p.sku;
-- 结果：8 行缺货中 6 行来自 3 个已停产 SKU（SKU-0052/0071/0078，安全库存仍为 5，库存已为 0）
--       仅 2 行是真缺货：SKU-0041（变频器/华东仓，0 < 26）、SKU-0043（变频器/华东仓，3 < 21）
--       → 这是全项目最锋利的判断：直接上"预测补货"模型，先要修主数据。

-- Q26 在售 SKU 缺货的月度分布（缺货是否持续）
SELECT d.full_date, COUNT(*) AS 在售SKU缺货行数
FROM fact_inventory_snapshot s JOIN dim_product p ON p.product_id=s.product_id
JOIN dim_date d ON d.date_id=s.date_id
WHERE p.status='在售' AND s.on_hand_qty<s.safety_stock AND d.full_date LIKE '2025-%'
GROUP BY d.full_date ORDER BY d.full_date;
-- 结果：2025 年 6 个月出现（1/4/6/8/10/12 月），共 12 行 —— 分布在不同 SKU，非固定某一个

-- Q27 真缺货 SKU 的月末库存轨迹（与需求激增对照）
SELECT d.year_month, p.sku, s.warehouse, s.on_hand_qty AS 现存,
       s.safety_stock AS 安全库存, s.in_transit_qty AS 在途
FROM fact_inventory_snapshot s JOIN dim_product p ON p.product_id=s.product_id
JOIN dim_date d ON d.date_id=s.date_id
WHERE p.sku IN ('SKU-0041','SKU-0043') AND d.full_date>='2025-07-01'
ORDER BY p.sku, s.warehouse, d.year_month;
-- 结果：SKU-0041/华东仓 11月 96 → 12月 0（在途仅 4）；SKU-0043/华东仓 11月 73 → 12月 3（在途 42）
--       → 两个 SKU 都是"一个月内被打空"，不是长期缺货

-- Q28 真缺货 SKU 的月销量（证明是需求激增而非预测错误）
SELECT d.year_month, p.sku, ROUND(SUM(i.qty),0) AS 销量, ROUND(SUM(i.revenue_amount),0) AS 销售额
FROM fact_sales_order_item i JOIN dim_product p ON p.product_id=i.product_id
JOIN fact_sales_order o ON o.order_id=i.order_id JOIN dim_date d ON d.date_id=o.order_date_id
WHERE o.status='已完成' AND p.sku IN ('SKU-0041','SKU-0043') AND d.full_date>='2025-09-01'
GROUP BY d.year_month, p.sku ORDER BY d.year_month, p.sku;
-- 结果：SKU-0041 销量 9月125 / 10月107 / 11月152 / 12月108；SKU-0043 10月123 / 12月143
--       → 安全库存按月均设定，但 SKU 月销量标准差大，固定安全库存必然被打穿

-- Q29 SKU 销量波动性（月峰值 ≥ 2 倍月均的 SKU 数）
WITH m AS (SELECT i.product_id, d.year_month, SUM(i.qty) q
           FROM fact_sales_order_item i JOIN fact_sales_order o ON o.order_id=i.order_id
           JOIN dim_date d ON d.date_id=o.order_date_id
           WHERE o.status='已完成' GROUP BY i.product_id, d.year_month),
s AS (SELECT product_id, AVG(q) avg_m, MAX(q) max_m FROM m GROUP BY product_id)
SELECT COUNT(*) AS 有销售SKU数,
       SUM(CASE WHEN max_m >= 2*avg_m THEN 1 ELSE 0 END) AS 高波动SKU数,
       ROUND(100.0*SUM(CASE WHEN max_m>=2*avg_m THEN 1 ELSE 0 END)/COUNT(*), 1) AS 高波动占比_pct
FROM s;
-- 结果：77 个 SKU 中 68 个高波动，占比 88.3%
--       → 需求预测模块的真正产品形态是"波动感知的动态安全库存"，不是"趋势预测"

-- Q30 库存周转天数（口径：期末库存金额 ÷ 日均销售成本）
WITH dc AS (SELECT SUM(o.cost_amount)/365.0 AS daily_cost
            FROM fact_sales_order o JOIN dim_date d ON d.date_id=o.order_date_id
            WHERE o.status='已完成' AND d.year=2025)
SELECT (SELECT SUM(inventory_value) FROM fact_inventory_snapshot
        WHERE date_id=(SELECT date_id FROM dim_date WHERE full_date='2025-12-31')) AS 期末库存,
       ROUND((SELECT daily_cost FROM dc),0) AS 日均销售成本,
       ROUND((SELECT SUM(inventory_value) FROM fact_inventory_snapshot
              WHERE date_id=(SELECT date_id FROM dim_date WHERE full_date='2025-12-31'))
             /(SELECT daily_cost FROM dc), 1) AS 库存周转天数;
-- 结果：期末库存 19,067,978 元 / 日均销售成本 87,615 元 / 周转天数 217.6 天
--       期末库存相当于年营收的 50.5%

-- Q31 滞销与零动销 SKU
WITH sold90 AS (
  SELECT i.product_id, ABS(SUM(i.qty)) AS sold
  FROM fact_inventory_transaction i JOIN dim_date d ON d.date_id=i.date_id
  WHERE i.txn_type='销售出库' AND d.full_date BETWEEN '2025-10-03' AND '2025-12-31'
  GROUP BY i.product_id),
snap AS (SELECT product_id, SUM(on_hand_qty) q, SUM(inventory_value) v
         FROM fact_inventory_snapshot
         WHERE date_id=(SELECT date_id FROM dim_date WHERE full_date='2025-12-31') GROUP BY product_id),
agg AS (SELECT p.product_id, p.sku, p.status, COALESCE(s.q,0) onhand,
               COALESCE(s.v,0) val, COALESCE(x.sold,0) sold90
        FROM dim_product p LEFT JOIN snap s ON s.product_id=p.product_id
        LEFT JOIN sold90 x ON x.product_id=p.product_id)
SELECT COUNT(*) AS SKU总数,
       SUM(status='在售') AS 在售SKU,
       SUM(sold90>0) AS 近90天有销售,
       SUM(sold90=0 AND onhand>0) AS 滞销SKU,
       SUM(sold90=0 AND onhand=0) AS 零动销且零库存,
       ROUND(SUM(val),0) AS 库存总额
FROM agg;
-- 结果：80 个 SKU / 77 在售 / 77 个近 90 天全部有销售 / 滞销 0 / 零动销且零库存 3
--       3 个零动销的正是 SKU-0052/0071/0078（已停产、库存已清零）
--       → 「滞销 SKU」这个销售话术在本项目数据上不成立，不能用；真实问题是缺货与高波动

-- Q32 库存集中度与帕累托贡献
WITH snap AS (SELECT product_id, SUM(on_hand_qty) q, SUM(inventory_value) v
              FROM fact_inventory_snapshot
              WHERE date_id=(SELECT date_id FROM dim_date WHERE full_date='2025-12-31') GROUP BY product_id),
ranked AS (SELECT product_id, v, ROW_NUMBER() OVER (ORDER BY v DESC) rn FROM snap),
rev AS (SELECT i.product_id, SUM(i.revenue_amount) rev
        FROM fact_sales_order_item i JOIN fact_sales_order o ON o.order_id=i.order_id
        WHERE o.status='已完成' GROUP BY i.product_id),
rr AS (SELECT product_id, rev, SUM(rev) OVER (ORDER BY rev DESC) cum, COUNT(*) OVER () tot FROM rev)
SELECT (SELECT ROUND(SUM(inventory_value),0) FROM fact_inventory_snapshot
        WHERE date_id=(SELECT date_id FROM dim_date WHERE full_date='2025-12-31')) AS 库存总额,
       (SELECT ROUND(SUM(rev),0) FROM rr) AS 两年总销售额,
       (SELECT COUNT(*) FROM rr WHERE cum>=0.8*tot) AS 贡献八成销售额所需SKU数,
       (SELECT COUNT(*) FROM rr) AS 有销售SKU总数,
       (SELECT ROUND(100.0*COUNT(*)/(SELECT COUNT(*) FROM rr),1) FROM rr WHERE cum>=0.8*tot) AS 帕累托SKU占比_pct;
-- 结果：需全部 77 个 SKU 才凑够 80% 销售额，占比 100% → 无帕累托结构，
--       80/20 的经典打法在这家客户上失效，这是 2×2 分层里"数字化程度低"格的典型特征

-- Q33 在途采购与供应商货期
SELECT status, COUNT(*) AS 采购单数, ROUND(SUM(total_amount),0) AS 金额
FROM fact_purchase_order GROUP BY status;
-- 结果：在途 23 单 472,879 元；已入库 3,491 单 67,489,452 元；已取消 0 单
-- 补货提前期：见下
SELECT ROUND(AVG(julianday(d2.full_date)-julianday(d1.full_date)),1) AS 实际平均货期_天,
       s.supplier_name, s.lead_time_days AS 供应商承诺货期, s.rating
FROM fact_purchase_order p JOIN dim_date d1 ON d1.date_id=p.order_date_id
JOIN dim_date d2 ON d2.date_id=p.arrival_date_id JOIN dim_supplier s ON s.supplier_id=p.supplier_id
GROUP BY s.supplier_id ORDER BY 实际平均货期_天;
-- 结果：实际平均货期 17.1~18.2 天，供应商承诺货期 5~30 天（承诺值与实际值差异大）


-- =============================================================================
-- 第六组：营收、分层客户、RFM（客户画像与商业价值）
-- =============================================================================

-- Q34 年度营收与增速
SELECT d.year, COUNT(DISTINCT o.order_id) AS 订单数,
       ROUND(SUM(o.net_amount),0)   AS 营收,
       ROUND(SUM(o.gross_amount),0) AS 吊牌额,
       ROUND(100.0*SUM(o.discount_amount)/SUM(o.gross_amount), 2) AS 折扣率_pct,
       ROUND(SUM(o.gross_profit),0) AS 毛利,
       ROUND(100.0*SUM(o.gross_profit)/SUM(o.net_amount), 2) AS 毛利率_pct,
       ROUND(SUM(o.net_amount)/COUNT(o.order_id),0) AS 客单价,
       COUNT(DISTINCT o.customer_id) AS 成交客户数
FROM fact_sales_order o JOIN dim_date d ON d.date_id=o.order_date_id
WHERE o.status='已完成' GROUP BY d.year ORDER BY d.year;
-- 结果：2024 营收 32,572,691 / 2517 单 / 毛利率 15.19% / 客单价 12,941
--       2025 营收 37,755,382 / 2941 单 / 毛利率 15.30% / 客单价 12,838
--       增速 +15.91%（2024→2025），订单增速 +16.85%，客单价微降 -0.80%
--       → 增长全部来自订单量，不是单价提升；这是「AI 提升大单」命题的起点

-- Q35 月度营收（季节性，供预测模块基线）
SELECT d.year_month, COUNT(o.order_id) AS 订单数, ROUND(SUM(o.net_amount),0) AS 营收
FROM fact_sales_order o JOIN dim_date d ON d.date_id=o.order_date_id
WHERE o.status='已完成' GROUP BY d.year_month ORDER BY d.year_month;
-- 结果：2024-02 最低 1,443,343；2025-12 最高 4,462,449（2 月春节低谷 + 12 月旺季）

-- Q36 季度营收
SELECT d.year_quarter, ROUND(SUM(o.net_amount),0) AS 营收, COUNT(o.order_id) AS 订单数
FROM fact_sales_order o JOIN dim_date d ON d.date_id=o.order_date_id
WHERE o.status='已完成' GROUP BY d.year_quarter ORDER BY d.year_quarter;
-- 结果：2025Q4 11,567,027 最高；2025Q1 6,706,166 最低；Q4 占比约 30%

-- Q37 客户分层画像（分层的价值差异）
SELECT c.tier, COUNT(DISTINCT o.customer_id) AS 客户数, COUNT(o.order_id) AS 订单数,
       ROUND(SUM(o.net_amount),0) AS 营收,
       ROUND(100.0*SUM(o.net_amount)/(SELECT SUM(net_amount) FROM fact_sales_order WHERE status='已完成'),2) AS 营收占比_pct,
       ROUND(SUM(o.net_amount)/COUNT(o.order_id),0) AS 客单价,
       ROUND(100.0*SUM(o.discount_amount)/SUM(o.gross_amount),2) AS 折扣率_pct,
       ROUND(100.0*SUM(o.gross_profit)/SUM(o.net_amount),2) AS 毛利率_pct,
       ROUND(COUNT(o.order_id)*1.0/COUNT(DISTINCT o.customer_id),1) AS 单客订单数,
       ROUND(SUM(o.net_amount)*1.0/COUNT(DISTINCT o.customer_id),0) AS 单客营收
FROM fact_sales_order o JOIN dim_customer c ON c.customer_id=o.customer_id
WHERE o.status='已完成' GROUP BY c.tier ORDER BY c.tier;
-- 结果：A 类 10 家 / 营收占比 47.54% / 客单价 14,569 / 折扣率 12.09% / 毛利率 26.42% / 单客订单 229.5
--       B 类 20 家 / 29.50% / 11,655 / 7.14% / 5.92% / 89.0
--       C 类 30 家 / 22.96% / 11,674 / 3.45% / 4.10% / 46.1
--       → A 类单客订单数是 C 类的 5 倍；C 类折扣率最低但毛利率也最低（3.45% 折扣换不来溢价）

-- Q38 RFM 分层（R=最近成交距 2025-12-31 天数，F=成交次数，M=成交金额，各取四分位）
WITH base AS (
  SELECT o.customer_id AS cid, MAX(d.full_date) AS last_order,
         COUNT(o.order_id) AS f, SUM(o.net_amount) AS m
  FROM fact_sales_order o JOIN dim_date d ON d.date_id=o.order_date_id
  WHERE o.status='已完成' AND d.full_date<='2025-12-31' GROUP BY o.customer_id),
scored AS (
  SELECT cid, f, m, julianday('2025-12-31')-julianday(last_order) AS r,
         NTILE(4) OVER (ORDER BY julianday('2025-12-31')-julianday(last_order) ASC) AS rq,
         NTILE(4) OVER (ORDER BY f DESC) AS fq,
         NTILE(4) OVER (ORDER BY m DESC) AS mq
  FROM base)
SELECT rq AS R档, COUNT(*) AS 客户数,
       ROUND(AVG(f),1) AS 平均成交次数, ROUND(AVG(m),0) AS 平均成交金额, ROUND(AVG(r),0) AS 平均距今天数
FROM scored GROUP BY rq ORDER BY rq;
-- R 汇总（流失风险池）
WITH base AS (
  SELECT o.customer_id AS cid, MAX(d.full_date) AS last_order, COUNT(o.order_id) AS f, SUM(o.net_amount) AS m
  FROM fact_sales_order o JOIN dim_date d ON d.date_id=o.order_date_id
  WHERE o.status='已完成' AND d.full_date<='2025-12-31' GROUP BY o.customer_id),
scored AS (SELECT cid, f, m, julianday('2025-12-31')-julianday(last_order) AS r,
           NTILE(4) OVER (ORDER BY julianday('2025-12-31')-julianday(last_order) ASC) AS rq FROM base)
SELECT 'R1_最活跃' AS 分层, COUNT(*) AS 客户数, ROUND(SUM(m),0) AS 营收 FROM scored WHERE rq=1
UNION ALL SELECT 'R2', COUNT(*), ROUND(SUM(m),0) FROM scored WHERE rq=2
UNION ALL SELECT 'R3', COUNT(*), ROUND(SUM(m),0) FROM scored WHERE rq=3
UNION ALL SELECT 'R4_最久未成交', COUNT(*), ROUND(SUM(m),0) FROM scored WHERE rq=4;
-- 结果：R1 15 家 / 29,263,898 元；R4 15 家 / 10,279,071 元（仍占总营收 14.6%）
--       注意：R4 是"最久未成交"而非"已流失"，因为 60 家客户在 24 个月内全部有成交，
--       本数据集没有真实的流失样本 → 客户洞察模块的"流失预警"在本项目上无法验证

-- Q39 品类结构（预测模块的品类起点）
SELECT p.category, COUNT(*) AS 明细行数, ROUND(SUM(i.revenue_amount),0) AS 销售额,
       ROUND(AVG(i.unit_price),0) AS 平均单价
FROM fact_sales_order_item i JOIN dim_product p ON p.product_id=i.product_id
JOIN fact_sales_order o ON o.order_id=i.order_id WHERE o.status='已完成'
GROUP BY p.category ORDER BY 销售额 DESC;
-- 结果：伺服电机 21,711,824；变频器 15,708,367；工业交换机 9,843,550；精密减速机 7,770,977；
--       PLC控制器 6,029,194；工业传感器 3,480,033；电源模块 3,329,609；气动元件 2,454,518
--       → 前两品类占 48.4%，但缺货的两个 SKU 都属变频器

-- Q40 付款状态（现金流，与跟进模块的商务话术相关）
SELECT payment_status, COUNT(*) AS 订单数, ROUND(SUM(net_amount),0) AS 金额
FROM fact_sales_order GROUP BY payment_status;
-- 结果：已付 4,602 单 59,149,826；未付款 500 单 6,720,822；部分付款 625 单 7,978,821
--       未完全回款 1,125 单 / 14,699,643 元，占 20.5%


-- =============================================================================
-- 第七组：交付与运营基线
-- =============================================================================

-- Q41 交付周期
SELECT ROUND(AVG(delivery_days),1) AS 平均交付天数, MIN(delivery_days) AS 最短, MAX(delivery_days) AS 最长
FROM fact_sales_order WHERE status='已完成';
-- 结果：平均 11.8 天（1~29 天）

-- Q42 订单状态分布
SELECT status, COUNT(*) AS 订单数, ROUND(SUM(net_amount),0) AS 金额
FROM fact_sales_order GROUP BY status;
-- 结果：已完成 5,458 / 已退款 75 / 处理中 98 / 已取消 96

-- Q43 员工结构（席位定价的依据）
SELECT team, role, COUNT(*) AS 人数 FROM dim_employee GROUP BY team, role ORDER BY team, role;
-- 结果：18 人；线上运营组 13 人（销售顾问 3、高级销售顾问 4、售前顾问 2、销售主管 3、销售总监 1、销售运营 1），
--       另 5 个区域/大客户销售组各 1 人（华东/华南/西南/大客户组 + 华东各 1）
-- 席位建议：销售类 16 席（含 1 总监）+ 分析/运营 2 席 = 18 席；或按"活跃使用者 17 人"计（Q19 实测）


-- =============================================================================
-- 第八组：ROI 测算输入汇总（配合 scripts/AI产品销售思考_ROI测算.py）
-- =============================================================================
-- 收益侧四个模块的全部输入与假设见：scripts/AI产品销售思考_ROI测算.py
-- 关键输入速查（均为实测）：
--   年营收 37,755,382.34 元        毛利率 15.30%
--   年线索 595 条                   AI 覆盖 208 条（35.0%）
--   AI 组成单率 24.04%              人工组 13.18%            差 10.86pp
--   成单均额 504,914 元
--   AI 节省 583.8 小时/年            每次采纳节省 7.71 分钟
--   营销年投入 3,124,744 元         低效渠道（外呼+内容）574,454 元
--   两真缺货 SKU 年销售额 1,626,273 元    2025 在售缺货月份数 6
--   期末库存 19,067,978 元          库存周转天数 217.6 天
-- =============================================================================
