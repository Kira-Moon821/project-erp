// =============================================================================
// ERP 经营分析实验室 — Power Query M 脚本
// =============================================================================
//
// 用法
// ----
// 1) 打开 Power BI Desktop → 首页「获取数据」→「文件夹」→ 选到 bi\data 目录
//    → 选「转换数据」→ 打开「高级编辑器」
// 2) 把【本文件】中**一个** let ... in 代码块整体粘贴进去 → 「完成」
//    （每个代码块 = 一个查询，按 §0 的顺序逐个创建）
// 3) 全部查询建完后，按 `build_guide.md` 的建模步骤在「模型视图」建立关系
//
// ★ 改路径（两种方式，任选其一）
// ------------------------------------------------------------------
//   A. 最简单：直接改下面 `p_DataFolder` 里的路径字符串，改完全部查询一起生效
//   B. 更工程化：在「主页 → 管理参数 → 新建参数」里建一个名为 `DataFolder` 的文本参数，
//      类型选「文本」，值填你的绝对路径；然后把 `p_DataFolder` 改成下面这段：
//
//          p_DataFolder = (DataFolder as text) meta [IsParameterQuery=true, Type="Text", IsParameterQueryRequired=true] in
//              DataFolder
//
//   路径写法提醒：
//     · Windows 用反斜杠 "C:\Users\xxx\erp-analytics-lab\bi\data"，M 里反斜杠要写成 "\\"
//     · 或者干脆用正斜杠 "C:/Users/xxx/erp-analytics-lab/bi/data"，M 与 Power BI 都能正常识别
//     · 结尾不必加 "\"，脚本里会自己拼接
//
// ★ 编码说明
// ------------------------------------------------------------------
//   源 CSV 是 UTF-8 **with BOM**（utf-8-sig），Excel 双击不乱码。
//   M 的 Csv.Document 默认按 UTF-8 读，但 BOM 可能残留到首列名上（列名变成 "﻿order_id"）。
//   因此每个查询都用「去 BOM」步骤统一清理首列名，再做列名清洗。
//
// ★ 两条建模路线
// ------------------------------------------------------------------
//   路线 A（星型模型，推荐）：stg_* 查询用 Table.SelectColumns **裁掉已展平的维度列**
//                            （customer_tier / sales_team / category ...），
//                            维度属性改由模型视图中的关系从 dim_* 表取得。
//   路线 B（单表 + DAX）：用 stg_*_Wide 查询，保留全部展平列，维度表不参与建模。
//                            本文件为两条路线都提供了查询，按需启用即可。
//
// ★ 字段名一致性保证
// ------------------------------------------------------------------
//   本脚本中出现的每一个列名，都取自 bi/data/*.csv 的实际表头，
//   并由 bi/verify_baselines.py 校验输出（该脚本会打印每张表的准确列名）。
//   若源数据重新生成导致列名变化，请先重跑 verify_baselines.py 再改本脚本。
//
// =============================================================================


// =============================================================================
// §0  查询清单（创建顺序）
// -----------------------------------------------------------------------------
//  1. p_DataFolder            参数：数据文件夹路径
//  2. fn_ReadCSV              函数：读取单个 CSV（BOM 处理 + 列名清洗 + 类型转换）
//  3. stg_Date                dim_date       → 日期维表
//  4. stg_Customer            dim_customer
//  5. stg_Employee            dim_employee
//  6. stg_Product             dim_product
//  7. stg_Sales               fact_sales_order_flat      （路线 A：裁剪维度列）
//  8. stg_Sales_Wide          fact_sales_order_flat      （路线 B：保留全部列）
//  9. stg_SalesItem           fact_sales_order_item_flat
// 10. stg_SalesItem_Wide      fact_sales_order_item_flat
// 11. stg_Inventory           fact_inventory_snapshot_flat
// 12. stg_Inventory_Wide      fact_inventory_snapshot_flat
// 13. stg_Lead                fact_lead_opportunity_flat
// 14. stg_Ticket              fact_customer_ticket_flat
// 15. stg_Marketing           fact_marketing_spend_flat
// 16. stg_AIUsage             fact_ai_usage_flat
// 17. dim_Date                由 dim_date 生成的**规范日期表**（含派生列）
// 18. dim_RFM_Base            RFM 计算底表（客户 × 最近成交日/次数/金额）
// 19. dim_RFM                 RFM 分层结果表（供 Tableau 侧对照与 Power BI 侧可选使用）
// =============================================================================


// =============================================================================
// §1  参数与工具函数
// =============================================================================

// -----------------------------------------------------------------------------
// 查询 1：p_DataFolder —— 数据文件夹路径（★ 改这里 ★）
// -----------------------------------------------------------------------------
let
    路径 = "C:/path/to/project-erp/bi/data"
in
    路径


// -----------------------------------------------------------------------------
// 查询 2：fn_ReadCSV —— 通用 CSV 读取函数
// -----------------------------------------------------------------------------
// 参数：文件名字符串、列类型映射表（可选）
// 返回：已去 BOM、已清洗列名、已转换类型的表
//
// 用法（在其他查询里）：
//     调用 = fn_ReadCSV("fact_sales_order_flat.csv")
//     带类型 = fn_ReadCSV("dim_date.csv", {{"full_date", type date}, {"is_weekend", Int64.Type}})
// -----------------------------------------------------------------------------
let
    fn_ReadCSV = (文件短名 as text, 列类型映射 as list) as table =>
        let
            // 拼接完整路径（正斜杠在 Windows 与 M 中通用）
            完整路径 = p_DataFolder & "/" & 文件短名,

            // 读取文件内容并按 UTF-8 解码
            二进制 = File.Contents(完整路径),
            原始文本 = Text.From(二进制, BinaryEncoding.UTF8),

            // ---- 去 BOM ----
            // utf-8-sig 的 BOM 字符是 U+FEFF。若不清理，首列名会变成 "﻿order_id"，
            // 导致后续 Table.SelectColumns 找不到列、或建关系时外键名对不上。
            有BOM = Text.StartsWith(原始文本, Character.FromNumber(65279)),
            去BOM文本 = if 有BOM
                        then Text.Remove(原始文本, 0, 1)
                        else 原始文本,

            // ---- 解析 CSV ----
            // QuoteStyle.Csv 按标准 CSV 规则处理引号；Encoding = 65001 即 UTF-8
            // 不指定 Columns，让 M 按首行自动推断列数
            原始表 = Csv.Document(
                        去BOM文本,
                        [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]
                    ),

            // ---- 列名清洗：去首尾空白 + 去 BOM 残留 ----
            // 只对「需要改名的列」执行 Rename，避免新旧同名时触发异常
            列名 = Table.ColumnNames(原始表),
            新列名 = List.Transform(列名, each Text.Trim(Text.Replace(_, Character.FromNumber(65279), ""))),
            待改名 = List.Select(
                        List.Transform(列名, (旧名, 位置) => {旧名, 新列名{位置}}),
                        each _{0} <> _{1}
                    ),
            清洗表 = if List.Count(待改名) = 0
                     then 原始表
                     else Table.RenameColumns(原始表, 待改名),

            // ---- 类型转换 ----
            // 列类型映射为 null 时不转换（保持推断结果）
            实际映射 = List.Select(列类型映射, each _{1} <> null),
            转换表 = if List.Count(实际映射) = 0
                     then 清洗表
                     else Table.TransformColumnTypes(清洗表, 实际映射),

            // ---- 缓冲 ----
            // 缓冲把结果放进内存，后续步骤不再重复读取磁盘，显著加快刷新
            缓冲表 = Table.Buffer(转换表)
        in
            缓冲表
in
    fn_ReadCSV


// =============================================================================
// §2  维度表查询
// =============================================================================

// -----------------------------------------------------------------------------
// 查询 3：stg_Date —— dim_date
// -----------------------------------------------------------------------------
let
    源 = fn_ReadCSV("dim_date.csv"),

    类型 = Table.TransformColumnTypes(源, {
        {"date_id", Int64.Type},          -- 主键，YYYYMMDD 整数
        {"full_date", type date},         -- ★ 唯一可标记为「日期表」的列
        {"year", Int64.Type},
        {"quarter", type text},           -- 值形如 2024Q1（文本）
        {"year_month", type text},        -- 值形如 2024-01（文本，字典序=时间序）
        {"month", Int64.Type},
        {"month_name", type text},
        {"week_of_year", Int64.Type},
        {"day_of_week", Int64.Type},
        {"is_weekend", Int64.Type}        -- 0/1 标记 → 整数
    }),

    // 业务窗口标记：dim_date 尾部 90 天（2026-01 ~ 2026-03）不属于业务窗口
    加窗口标记 = Table.AddColumn(类型, "是否业务窗口", each
        Date.From([full_date]) >= #date(2024, 1, 1) and Date.From([full_date]) <= #date(2025, 12, 31),
        type logical)
in
    加窗口标记


// -----------------------------------------------------------------------------
// 查询 4：stg_Customer —— dim_customer
// -----------------------------------------------------------------------------
let
    源 = fn_ReadCSV("dim_customer.csv"),

    类型 = Table.TransformColumnTypes(源, {
        {"customer_id", Int64.Type},
        {"customer_name", type text},
        {"industry", type text},              -- 智能制造/汽车零部件/... 共 8 个行业
        {"region", type text},                -- 华东/华南/西南/华北
        {"city", type text},
        {"tier", type text},                  -- A/B/C 分层
        {"channel", type text},               -- 直销/经销/电商/OEM
        {"acquisition_source", type text},    -- 官网/展会/转介绍/广告投放/电话外呼/内容营销
        {"contract_date", type date},
        {"customer_manager_id", Int64.Type},  -- 外键 → dim_employee.employee_id
        {"customer_manager", type text},
        {"annual_contract_value", Currency.Type},
        {"status", type text}                 -- 合作中(58)/已流失(2)
    })
in
    类型


// -----------------------------------------------------------------------------
// 查询 5：stg_Employee —— dim_employee
// -----------------------------------------------------------------------------
let
    源 = fn_ReadCSV("dim_employee.csv"),

    类型 = Table.TransformColumnTypes(源, {
        {"employee_id", Int64.Type},
        {"employee_name", type text},
        {"team", type text},            -- 如 华东销售组 / 大客户组 / 线上运营组
        {"role", type text},            -- 销售顾问/销售主管/销售总监
        {"region", type text},
        {"hire_date", type date},
        {"is_active", Int64.Type}       -- 0/1 标记
    })
in
    类型


// -----------------------------------------------------------------------------
// 查询 6：stg_Product —— dim_product
// -----------------------------------------------------------------------------
let
    源 = fn_ReadCSV("dim_product.csv"),

    类型 = Table.TransformColumnTypes(源, {
        {"product_id", Int64.Type},
        {"sku", type text},
        {"product_name", type text},
        {"category", type text},        -- 品类：工业传感器/变频器/...
        {"brand", type text},
        {"unit", type text},            -- 计价单位：件/台/...
        {"unit_cost", Currency.Type},   -- 单位成本（毛利分析用）
        {"list_price", Currency.Type},  -- 标价
        {"supplier_id", Int64.Type},
        {"launch_date", type date},
        {"status", type text}           -- 在售(77)/停产(3) ← 动销率分母的关键
    })
in
    类型


// =============================================================================
// §3  事实表查询（路线 A：裁剪维度列）
// =============================================================================

// -----------------------------------------------------------------------------
// 查询 7：stg_Sales —— fact_sales_order_flat（路线 A：星型）
// -----------------------------------------------------------------------------
// 保留：主键 + 外键 + 度量列 + 日期列
// 裁掉：customer_name/customer_tier/customer_industry/customer_region/customer_city/
//       customer_channel/acquisition_source/employee_name/sales_team/sales_role/
//       year/quarter/year_month/month/discount_rate/gross_margin
//       —— 这些属性改由 dim_customer / dim_employee / dim_date 通过关系提供，
//          避免同名属性出现「两个来源」的歧义。
// -----------------------------------------------------------------------------
let
    源 = fn_ReadCSV("fact_sales_order_flat.csv"),

    类型 = Table.TransformColumnTypes(源, {
        {"order_id", Int64.Type},
        {"order_no", type text},
        {"order_date", type date},
        {"customer_id", Int64.Type},
        {"employee_id", Int64.Type},
        {"order_channel", type text},      -- 直销/经销/电商/OEM
        {"order_status", type text},       -- 已完成(5458)/已退款(75)/处理中(98)/已取消(96)
        {"payment_status", type text},     -- 已付/部分付款/未付款
        {"gross_amount", Currency.Type},   -- 吊牌额
        {"discount_amount", Currency.Type},-- 折扣额
        {"net_amount", Currency.Type},     -- ★ 营收口径列（仅取已完成）
        {"cost_amount", Currency.Type},
        {"gross_profit", Currency.Type},
        {"delivery_days", Int64.Type},
        {"is_return", Int64.Type}          -- 0/1 标记
    }),

    裁剪维度列 = Table.SelectColumns(类型, {
        "order_id", "order_no", "order_date", "customer_id", "employee_id",
        "order_channel", "order_status", "payment_status",
        "gross_amount", "discount_amount", "net_amount", "cost_amount", "gross_profit",
        "delivery_days", "is_return"
    })
in
    裁剪维度列


// -----------------------------------------------------------------------------
// 查询 8：stg_Sales_Wide —— fact_sales_order_flat（路线 B：单表 + DAX）
// -----------------------------------------------------------------------------
// 保留全部列（含已展平的维度属性），维度表不参与建模。
// 仅在你不打算建星型关系时使用；不要与 stg_Sales 同时启用（列名会冲突）。
// -----------------------------------------------------------------------------
let
    源 = fn_ReadCSV("fact_sales_order_flat.csv"),

    类型 = Table.TransformColumnTypes(源, {
        {"order_id", Int64.Type},
        {"order_no", type text},
        {"order_date", type date},
        {"year", Int64.Type},
        {"quarter", type text},
        {"year_month", type text},
        {"month", Int64.Type},
        {"customer_id", Int64.Type},
        {"customer_name", type text},
        {"customer_tier", type text},
        {"customer_industry", type text},
        {"customer_region", type text},
        {"customer_city", type text},
        {"customer_channel", type text},
        {"acquisition_source", type text},
        {"employee_id", Int64.Type},
        {"employee_name", type text},
        {"sales_team", type text},
        {"sales_role", type text},
        {"order_channel", type text},
        {"order_status", type text},
        {"payment_status", type text},
        {"gross_amount", Currency.Type},
        {"discount_amount", Currency.Type},
        {"net_amount", Currency.Type},
        {"cost_amount", Currency.Type},
        {"gross_profit", Currency.Type},
        {"discount_rate", type number},   -- 行级比率：不可直接 SUM，需 DAX 重算
        {"gross_margin", type number},   -- 行级比率：不可直接 SUM，需 DAX 重算
        {"delivery_days", Int64.Type},
        {"is_return", Int64.Type}
    })
in
    类型


// -----------------------------------------------------------------------------
// 查询 9：stg_SalesItem —— fact_sales_order_item_flat（路线 A：星型）
// -----------------------------------------------------------------------------
// ★ 该表没有 customer_name / employee 等维度名，customer_id 与 product_id 是外键。
// ★ 商品属性（category/brand/sku）来自 dim_product。
// -----------------------------------------------------------------------------
let
    源 = fn_ReadCSV("fact_sales_order_item_flat.csv"),

    类型 = Table.TransformColumnTypes(源, {
        {"order_item_id", Int64.Type},
        {"order_id", Int64.Type},          -- 外键 → fact_sales_order.order_id
        {"order_no", type text},
        {"order_date", type date},
        {"customer_id", Int64.Type},       -- 外键 → dim_customer.customer_id
        {"order_channel", type text},
        {"order_status", type text},       -- 明细行同样带订单状态（743 行为非已完成）
        {"product_id", Int64.Type},        -- 外键 → dim_product.product_id
        {"unit", type text},
        {"qty", Int64.Type},
        {"unit_price", Currency.Type},
        {"discount_rate", type number},    -- 行级比率
        {"revenue_amount", Currency.Type}, -- ★ 商品级营收
        {"cost_amount", Currency.Type},
        {"gross_profit", Currency.Type}
    }),

    裁剪维度列 = Table.SelectColumns(类型, {
        "order_item_id", "order_id", "order_no", "order_date", "customer_id",
        "order_channel", "order_status", "product_id",
        "qty", "unit_price", "revenue_amount", "cost_amount", "gross_profit"
    })
in
    裁剪维度列


// -----------------------------------------------------------------------------
// 查询 10：stg_SalesItem_Wide —— fact_sales_order_item_flat（路线 B：单表 + DAX）
// -----------------------------------------------------------------------------
let
    源 = fn_ReadCSV("fact_sales_order_item_flat.csv"),

    类型 = Table.TransformColumnTypes(源, {
        {"order_item_id", Int64.Type},
        {"order_id", Int64.Type},
        {"order_no", type text},
        {"order_date", type date},
        {"year", Int64.Type},
        {"year_month", type text},
        {"customer_id", Int64.Type},
        {"customer_tier", type text},
        {"customer_industry", type text},
        {"customer_region", type text},
        {"order_channel", type text},
        {"order_status", type text},
        {"product_id", Int64.Type},
        {"sku", type text},
        {"product_name", type text},
        {"category", type text},
        {"brand", type text},
        {"unit", type text},
        {"qty", Int64.Type},
        {"unit_price", Currency.Type},
        {"discount_rate", type number},
        {"revenue_amount", Currency.Type},
        {"cost_amount", Currency.Type},
        {"gross_profit", Currency.Type}
    })
in
    类型


// -----------------------------------------------------------------------------
// 查询 11：stg_Inventory —— fact_inventory_snapshot_flat（路线 A：星型）
// -----------------------------------------------------------------------------
// 粒度：月末 × 商品 × 仓库（24 月 × 80 SKU × 2 仓 = 3,840 行）
// -----------------------------------------------------------------------------
let
    源 = fn_ReadCSV("fact_inventory_snapshot_flat.csv"),

    类型 = Table.TransformColumnTypes(源, {
        {"snapshot_id", Int64.Type},
        {"snapshot_date", type date},     -- 月末日期（2024-01-31 ~ 2025-12-31）
        {"product_id", Int64.Type},      -- 外键 → dim_product.product_id
        {"warehouse", type text},        -- 华东仓/西南仓
        {"on_hand_qty", Int64.Type},     -- 现有库存
        {"safety_stock", Int64.Type},    -- 安全库存（缺货判定：on_hand < safety）
        {"in_transit_qty", Int64.Type},  -- 在途
        {"stock_gap", Int64.Type},       -- = on_hand - safety（已验证 3840 行全部成立）
        {"unit_cost", Currency.Type},
        {"inventory_value", Currency.Type} -- 库存金额（周转天数分子）
    }),

    裁剪维度列 = Table.SelectColumns(类型, {
        "snapshot_id", "snapshot_date", "product_id", "warehouse",
        "on_hand_qty", "safety_stock", "in_transit_qty", "stock_gap",
        "unit_cost", "inventory_value"
    })
in
    裁剪维度列


// -----------------------------------------------------------------------------
// 查询 12：stg_Inventory_Wide —— fact_inventory_snapshot_flat（路线 B：单表 + DAX）
// -----------------------------------------------------------------------------
let
    源 = fn_ReadCSV("fact_inventory_snapshot_flat.csv"),

    类型 = Table.TransformColumnTypes(源, {
        {"snapshot_id", Int64.Type},
        {"snapshot_date", type date},
        {"year_month", type text},
        {"year", Int64.Type},
        {"quarter", type text},
        {"product_id", Int64.Type},
        {"sku", type text},
        {"product_name", type text},
        {"category", type text},
        {"brand", type text},
        {"warehouse", type text},
        {"on_hand_qty", Int64.Type},
        {"safety_stock", Int64.Type},
        {"in_transit_qty", Int64.Type},
        {"stock_gap", Int64.Type},
        {"unit_cost", Currency.Type},
        {"inventory_value", Currency.Type}
    })
in
    类型


// -----------------------------------------------------------------------------
// 查询 13：stg_Lead —— fact_lead_opportunity_flat（路线 A：星型）
// -----------------------------------------------------------------------------
// ★ stage 是「线索当前所处的阶段」，不是历史流转记录。
//   stage 取值：线索(237)/需求确认(226)/方案演示(171)/商务谈判(133)/成单(184)/输单(111)
//   因此「到达某阶段及以后」需按 stage 语义推导，见 dax_measures.dax 的「漏斗到达数」。
// -----------------------------------------------------------------------------
let
    源 = fn_ReadCSV("fact_lead_opportunity_flat.csv"),

    类型 = Table.TransformColumnTypes(源, {
        {"lead_id", Int64.Type},
        {"lead_name", type text},
        {"created_date", type date},
        {"customer_id", Int64.Type},       -- 外键 → dim_customer.customer_id
        {"source_channel", type text},     -- 官网/展会/内容营销/电话外呼/转介绍/广告投放
        {"stage", type text},              -- 线索/需求确认/方案演示/商务谈判/成单/输单
        {"expected_amount", Currency.Type},
        {"actual_amount", Currency.Type},  -- 成单>0，输单=0
        {"win_probability", type number},  -- 0~1
        {"ai_assisted", Int64.Type},       -- ★ 0/1 标记：AI 价值对比的关键分组
        {"cycle_days", Int64.Type},        -- 销售周期
        {"loss_reason", type text},        -- 仅输单线索有值
        {"owner_employee_id", Int64.Type}  -- 外键 → dim_employee.employee_id
    }),

    裁剪维度列 = Table.SelectColumns(类型, {
        "lead_id", "lead_name", "created_date", "customer_id", "source_channel", "stage",
        "expected_amount", "actual_amount", "win_probability", "ai_assisted",
        "cycle_days", "loss_reason", "owner_employee_id"
    })
in
    裁剪维度列


// -----------------------------------------------------------------------------
// 查询 14：stg_Ticket —— fact_customer_ticket_flat（路线 A：星型）
// -----------------------------------------------------------------------------
let
    源 = fn_ReadCSV("fact_customer_ticket_flat.csv"),

    类型 = Table.TransformColumnTypes(源, {
        {"ticket_id", Int64.Type},
        {"created_date", type date},
        {"customer_id", Int64.Type},        -- 外键 → dim_customer.customer_id
        {"topic_type", type text},          -- 报表需求/功能咨询/数据导出/系统故障/售后支持
        {"channel", type text},             -- 电话/邮件/在线...
        {"ai_handled", Int64.Type},         -- ★ 0/1 标记
        {"first_response_minutes", type number},
        {"resolution_hours", type number},
        {"satisfaction", Int64.Type},       -- 1~5
        {"converted_to_opportunity", Int64.Type}  -- ★ 0/1 标记
    }),

    裁剪维度列 = Table.SelectColumns(类型, {
        "ticket_id", "created_date", "customer_id", "topic_type", "channel",
        "ai_handled", "first_response_minutes", "resolution_hours",
        "satisfaction", "converted_to_opportunity"
    })
in
    裁剪维度列


// -----------------------------------------------------------------------------
// 查询 15：stg_Marketing —— fact_marketing_spend_flat（独立事实表）
// -----------------------------------------------------------------------------
// ★ 该表**没有**外键到 dim_*，是独立周期事实（24 个月 × 6 渠道 = 144 行）
//   · channel 取值：搜索广告/行业展会/内容营销/转介绍激励/外呼中心/合作伙伴分成
//   · 注意与线索表 source_channel（官网/展会/转介绍/广告投放/电话外呼/内容营销）**不是同一套体系**，不可 join
//   · cac / roas 两列是行级已算好的比率，做汇总时应重算（见 calcs.md 说明）
// -----------------------------------------------------------------------------
let
    源 = fn_ReadCSV("fact_marketing_spend_flat.csv"),

    类型 = Table.TransformColumnTypes(源, {
        {"spend_id", Int64.Type},
        {"date", type date},                -- 投放日（每月 10 号）
        {"channel", type text},
        {"campaign_name", type text},       -- 如 2024-01 搜索广告投放
        {"cost_amount", Currency.Type},
        {"leads_count", Int64.Type},
        {"revenue_attributed", Currency.Type},
        {"cac", type number},               -- 行级比率：汇总需重算
        {"roas", type number}               -- 行级比率：汇总需重算
    })
in
    类型


// -----------------------------------------------------------------------------
// 查询 16：stg_AIUsage —— fact_ai_usage_flat（独立事实表）
// -----------------------------------------------------------------------------
// ★ date 是**月末**（2024-01-31 ... 2025-12-31），不是月初
//   · acceptance_rate 是行级比率（accepted/query），整体采纳率需按
//     SUM(accepted_count)/SUM(query_count) 重算，不能对 acceptance_rate 求平均
// -----------------------------------------------------------------------------
let
    源 = fn_ReadCSV("fact_ai_usage_flat.csv"),

    类型 = Table.TransformColumnTypes(源, {
        {"usage_id", Int64.Type},
        {"date", type date},
        {"employee_id", Int64.Type},        -- 外键 → dim_employee.employee_id
        {"scenario", type text},            -- 自然语言取数/经营日报生成/客户洞察摘要
        {"query_count", Int64.Type},
        {"accepted_count", Int64.Type},
        {"acceptance_rate", type number},   -- 行级比率
        {"minutes_saved", type number}
    })
in
    类型


// =============================================================================
// §4  日期表生成
// =============================================================================

// -----------------------------------------------------------------------------
// 查询 17：dim_Date —— 规范日期维表
// -----------------------------------------------------------------------------
// 两种来源：
//   (a) 从 dim_date 派生（下方实现）—— 推荐，直接复用源库的日期维表
//   (b) 由事实表派生 —— 备选，见文件末尾 §5 的说明
//
// 本查询在 stg_Date 基础上补充派生列，并保证：
//   · 日期连续无缺失（时间智能的前提）
//   · 提供 年/季/月/周/是否周末 的规范列
//   · 显式标出业务窗口，便于过滤
// -----------------------------------------------------------------------------
let
    源 = stg_Date,

    // 年月序号：用于「按列排序」，避免跨年时月份错序
    加年月序号 = Table.AddColumn(源, "年月序号", each
        Number.FromText(Text.Start([year_month], 4)) * 100 + Number.FromText(Text.End([year_month], 2)),
        Int64.Type),

    // 季度序号：1~4
    加季度序号 = Table.AddColumn(加年月序号, "quarter_no", each
        Number.FromText(Text.End([quarter], 1)), Int64.Type),

    // 是否工作日：周末=0，工作日=1（与 is_weekend 互补，便于按工作日筛选）
    加工作日 = Table.AddColumn(加季度序号, "is_workday", each
        if [is_weekend] = 1 then 0 else 1, Int64.Type),

    // 月份首日：便于按月聚合时对齐到月初
    加月份首日 = Table.AddColumn(加工作日, "month_start", each
        Date.StartOfMonth([full_date]), type date),

    // 季度首日（用「季度首月」推导，兼容性优于 Date.StartOfQuarter）
    加季度首日 = Table.AddColumn(加月份首日, "quarter_start", each
        Date.StartOfMonth(#date(Number.FromText(Text.Start([quarter], 4)),
                                (Number.FromText(Text.End([quarter], 1)) - 1) * 3 + 1,
                                1)), type date),

    // 年首日
    加年首日 = Table.AddColumn(加季度首日, "year_start", each
        #date([year], 1, 1), type date),

    // 按日期升序
    排序 = Table.Sort(加年首日, {{"full_date", Order.Ascending}}),

    // 只保留日期表需要的列
    取列 = Table.SelectColumns(排序, {
        "date_id", "full_date", "year", "quarter", "quarter_no", "year_month", "年月序号",
        "month", "month_name", "week_of_year", "day_of_week", "is_weekend", "is_workday",
        "month_start", "quarter_start", "year_start", "是否业务窗口"
    }),

    // 去掉自定义列名中的中文（保证跨工具一致性，Tableau 侧也用这些名）
    重命名 = Table.RenameColumns(取列, {
        {"年月序号", "year_month_no"},
        {"是否业务窗口", "is_business_window"}
    }),

    缓冲 = Table.Buffer(重命名)
in
    缓冲


// =============================================================================
// §5  RFM 计算（Power Query 路线，可选）
// =============================================================================
//
// 为什么给出 PQ 版本？
//   RFM 的分档（四分位）本质上是一个「先算每个客户的 R/F/M，再对全体客户取分位点」的
//   两步聚合。用 DAX 实现需要在度量里反复迭代（见 dax_measures.dax 的考察点说明），
//   性能较差；用 Power Query 预计算则一次算好、模型里只留结果列，交互最流畅。
//
// 口径（数据字典 §3）：
//   R = 距最近一次成交天数；F = 期间成交次数；M = 期间成交金额；分档用四分位
//   ★ 仅统计 order_status = "已完成" 的订单（与营收口径一致）
//   ★ 参考日 = 业务窗口最后一天 2025-12-31
//
// -----------------------------------------------------------------------------
// 查询 18：dim_RFM_Base —— 客户级 R/F/M 底表
// -----------------------------------------------------------------------------
let
    订单 = stg_Sales,                // 路线 A 用 stg_Sales；路线 B 改用 stg_Sales_Wide（字段都够用）

    仅已完成 = Table.SelectRows(订单, each [order_status] = "已完成"),

    客户分组 = Table.Group(仅已完成, {"customer_id"}, {
        {"最近成交日", each List.Max([order_date]), type date},
        {"成交次数", each Table.RowCount(_), Int64.Type},
        {"成交金额", each List.Sum([net_amount]), type number}
    }),

    加参考日 = Table.AddColumn(客户分组, "参考日", each #date(2025, 12, 31), type date),

    加R值 = Table.AddColumn(加参考日, "R 天数", each
        Duration.Days([参考日] - [最近成交日]), Int64.Type),

    取列 = Table.SelectColumns(加R值, {"customer_id", "最近成交日", "成交次数", "成交金额", "R 天数"}),

    缓冲 = Table.Buffer(取列)
in
    缓冲


// -----------------------------------------------------------------------------
// 查询 19：dim_RFM —— RFM 分层结果表
// -----------------------------------------------------------------------------
// 分档规则（与 dax_measures.dax、tableau/calcs.md 三处保持完全一致）：
//   R 分（越小越好）：R <= P25 → 4；<= P50 → 3；<= P75 → 2；否则 1
//   F 分（越大越好）：F >= P75 → 4；>= P50 → 3；>= P25 → 2；否则 1
//   M 分（越大越好）：M >= P75 → 4；>= P50 → 3；>= P25 → 2；否则 1
//   组合分层：
//     R>=3 & F>=3 & M>=3 → 重要价值客户
//     R>=3 & F>=3 & M<3  → 重要保持客户
//     R>=3 & F<3  & M>=3 → 重要发展客户
//     R>=3 & F<3  & M<3  → 一般保持客户
//     R<3  & F>=3 & M>=3 → 潜力新客
//     R<3  & F>=3 & M<3  → 潜力成长客户
//     R<3  & F<3  & M>=3 → 流失预警客户
//     R<3  & F<3  & M<3  → 沉睡客户
//
// 期望基线（verify_baselines.py 当前输出）：
//   R 四分位 1.0 / 4.0 / 8.25 ；F 46.75 / 69.0 / 94.25 ；M 531,828.62 / 793,050.78 / 1,162,534.20
//   分层：重要价值 21 / 沉睡 18 / 一般保持 10 / 潜力新客 7 / 重要保持 2 / 流失预警 2
// -----------------------------------------------------------------------------
let
    底表 = dim_RFM_Base,

    // ---- 计算四分位点（PERCENTILE.INC，与 Excel / DAX PERCENTILEX.INC 同口径）----
    R升序 = List.Sort(底表[R 天数]),
    F升序 = List.Sort(底表[成交次数]),
    M升序 = List.Sort(底表[成交金额]),

    分位函数 = (列表 as list, p as number) as number =>
        let
            n = List.Count(列表),
            位置 = (n - 1) * p,
            下标 = Number.RoundDown(位置, 0),
            上标 = if 下标 + 1 <= n - 1 then 下标 + 1 else 下标,
            权重 = 位置 - 下标
        in
            列表{下标} + 权重 * (列表{上标} - 列表{下标}),

    R25 = 分位函数(R升序, 0.25), R50 = 分位函数(R升序, 0.50), R75 = 分位函数(R升序, 0.75),
    F25 = 分位函数(F升序, 0.25), F50 = 分位函数(F升序, 0.50), F75 = 分位函数(F升序, 0.75),
    M25 = 分位函数(M升序, 0.25), M50 = 分位函数(M升序, 0.50), M75 = 分位函数(M升序, 0.75),

    // ---- 打分 ----
    加R分 = Table.AddColumn(底表, "R 分", each
        if [R 天数] <= R25 then 4 else if [R 天数] <= R50 then 3 else if [R 天数] <= R75 then 2 else 1,
        Int64.Type),

    加F分 = Table.AddColumn(加R分, "F 分", each
        if [成交次数] >= F75 then 4 else if [成交次数] >= F50 then 3 else if [成交次数] >= F25 then 2 else 1,
        Int64.Type),

    加M分 = Table.AddColumn(加F分, "M 分", each
        if [成交金额] >= M75 then 4 else if [成交金额] >= M50 then 3 else if [成交金额] >= M25 then 2 else 1,
        Int64.Type),

    // ---- 分层 ----
    加分层 = Table.AddColumn(加M分, "RFM 分层", each
        if [R 分] >= 3 and [F 分] >= 3 and [M 分] >= 3 then "重要价值客户"
        else if [R 分] >= 3 and [F 分] >= 3 and [M 分] < 3 then "重要保持客户"
        else if [R 分] >= 3 and [F 分] < 3 and [M 分] >= 3 then "重要发展客户"
        else if [R 分] >= 3 and [F 分] < 3 and [M 分] < 3 then "一般保持客户"
        else if [R 分] < 3 and [F 分] >= 3 and [M 分] >= 3 then "潜力新客"
        else if [R 分] < 3 and [F 分] >= 3 and [M 分] < 3 then "潜力成长客户"
        else if [R 分] < 3 and [F 分] < 3 and [M 分] >= 3 then "流失预警客户"
        else "沉睡客户",
        type text),

    取列 = Table.SelectColumns(加分层, {
        "customer_id", "R 天数", "R 分", "成交次数", "F 分", "成交金额", "M 分", "RFM 分层"
    }),

    排序 = Table.Sort(取列, {{"成交金额", Order.Descending}}),
    缓冲 = Table.Buffer(排序)
in
    缓冲


// =============================================================================
// §6  备选：由事实表派生日期表（方式 b）
// =============================================================================
//
// 若不使用 dim_date，也可由事实表派生一张连续日期表。做法：
//
//   起始日 = MIN(所有事实表日期列)
//   结束日 = MAX(所有事实表日期列)
//   用 List.Dates 生成连续日期序列，再派生 年/季/月/周/是否周末
//
// 示例（以订单表为例）：
//
// let
//     订单 = stg_Sales,
//     起 = List.Min(订单[order_date]),
//     止 = List.Max(订单[order_date]),
//     天数 = Duration.Days(止 - 起) + 1,
//     日期序列 = List.Dates(起, 天数, #duration(1,0,0,0)),
//     日期表 = Table.FromList(日期序列, Splitter.CombineByNames({"full_date"}, false)),
//     加列 = Table.AddColumn(日期表, "year", each Date.Year([full_date]), Int64.Type),
//     加季 = Table.AddColumn(加列, "quarter", each "Q" & Text.From(Date.QuarterOfYear([full_date])), type text),
//     加月 = Table.AddColumn(加季, "year_month", each Date.ToText([full_date], "yyyy-MM"), type text),
//     加周 = Table.AddColumn(加月, "week_of_year", each Date.WeekOfYear([full_date]), Int64.Type),
//     加周末 = Table.AddColumn(加周, "is_weekend", each
//                 if Date.DayOfWeek([full_date]) > 5 then 1 else 0, Int64.Type)
// in
//     加周末
//
// 派生方式与 dim_date 的差异：
//   · dim_date 的 day_of_week 是 1~7（1=周一），Tableau 的 DATEPART('weekday') 也是 1~7（1=周一），
//     两者一致；但 Tableau 的 DATEPART('day','week') 是 0~6（0=周日），**与 dim_date 差 1 天**，
//     这是 tableau/口径对照.md 中列出的坑之一。
//   · dim_date 覆盖 821 天（含尾部 90 天），由事实表派生则只有 731 天（业务窗口内）。
//     两种方式产出的日期表在业务窗口内完全一致。
//
// =============================================================================


// =============================================================================
// §7  常见问题速查
// =============================================================================
//
// Q1. 粘贴后报「列名找不到」？
//     A. 本文件的列名全部来自实际 CSV 表头。若你改了源 CSV 的列名，
//        先跑 `python bi/verify_baselines.py` 看新列名，再同步改本文件的
//        Table.SelectColumns 与 Table.TransformColumnTypes。
//
// Q2. 首列名带一个奇怪的字符？
//     A. BOM 未清干净。fn_ReadCSV 已处理；若仍出现，检查是否走了「直接 CSV」路径
//        而不是经过 fn_ReadCSV。
//
// Q3. 数字变成科学计数法或精度丢失？
//     A. 类型转换没做。金额必须转 Currency.Type（定点小数），不要留 type number。
//        Currency.Type 是 4 位小数定点，能精确表示金额；type number 是双精度浮点，
//        大额求和时可能出现末位误差。
//
// Q4. 日期列变成文本？
//     A. 类型映射里漏了。订单是 order_date，明细是 order_date，库存是 snapshot_date，
//        线索是 created_date，工单是 created_date，营销是 date，AI 使用是 date。
//        注意 fact_ai_usage 和 fact_marketing_spend 的日期列名就叫 "date"。
//
// Q5. 0/1 标记列要不要设 Data Category？
//     A. 在 Power Query 里设不了，要在模型视图里设：
//        ai_assisted / ai_handled / is_return / converted_to_opportunity / is_weekend
//        → 右键「数据类别」→ 选「是/否」或「真/假」。
//        设成「是/否」后，DAX 里可以直接用 Boolean 逻辑判断，且筛选器显示为复选框。
//
// Q6. 要不要在 PQ 里 merge 维度表？
//     A. 路线 A：**不要** merge，用关系代替（模型更干净、维度可复用）。
//        路线 B：一般也不需要；唯一例外是 fact_sales_order_item 需要
//        dim_product.unit_cost 做商品成本分析时，才考虑 merge。
//        若要 merge，用：
//            合并 = Table.NestedJoin(源, {"product_id"}, stg_Product, {"product_id"},
//                                  "新增_商品", JoinKind.LeftOuter),
//            展开 = Table.ExpandTableColumn(合并, "新增_商品", {"unit_cost","list_price","status"},
//                                    {"商品_unit_cost","商品_list_price","商品_status"})
//
// =============================================================================
