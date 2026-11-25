# BI 资产总览

> 目的：把**同一份 CSV**（`bi/data/*.csv`）用两个主流 BI 工具各做一遍，
> 并让两边的数字与 SQL、Excel 三方对得上。
> 口径唯一来源：`docs/数据字典与业务口径.md`

---

## 1. 目录结构

```
bi/
├── data/                     # ★ 11 个 CSV（utf-8-sig，Excel 双击不乱码）
│   ├── dim_date.csv                dim_customer.csv
│   ├── dim_employee.csv            dim_product.csv
│   ├── fact_sales_order_flat.csv        （订单头，31 列）
│   ├── fact_sales_order_item_flat.csv   （订单行，24 列）
│   ├── fact_inventory_snapshot_flat.csv （库存快照，17 列）
│   ├── fact_lead_opportunity_flat.csv  （商机漏斗，22 列）
│   ├── fact_customer_ticket_flat.csv   （客服工单，16 列）
│   ├── fact_marketing_spend_flat.csv   （营销投放，11 列）
│   └── fact_ai_usage_flat.csv          （AI 使用，13 列）
│
├── powerbi/                  # ★ Power BI
│   ├── ERP经营分析.pbip         ← 双击这个打开（PBIP 项目）
│   ├── ERP经营分析.SemanticModel/definition/model.tmdl   （11 表 / 30 度量 / 15 关系）
│   ├── ERP经营分析.Report/definition/report.json          （2 页 / 9 视觉对象）
│   ├── powerquery/erp_model.pq  （19 个 M 查询，星型建模路线 A/B 两套）
│   ├── dax/dax_measures.dax      （52 个 DAX 度量值，按 9 个主题分组）
│   ├── model.md                 （数据模型说明书：关系、度量、时间智能）
│   ├── build_guide.md           （搭建指南：PBIP 打开 / 手工复现两条路）
│   ├── build_pbip.py            （生成 PBIP 的脚本）
│   └── verify_pbip.py           （PBIP 结构自检）
│
├── tableau/                  # ★ Tableau
│   ├── ERP经营分析.twbx         ← 双击这个打开（Tableau Public 2026.3 实测可用）
│   ├── ERP经营分析.twb           （明文工作簿，便于 review 与 diff）
│   ├── calcs.md                 （32 个计算字段清单，自动从 twb 提取）
│   ├── build_twb.py             （生成工作簿的脚本）
│   ├── verify_twb.py            （工作簿结构自检）
│   └── gen_calcs_doc.py         （从 twb 自动生成 calcs.md）
│
└── verify_baselines.py        # BI 侧关键指标的基线数值核对
```

---

## 2. 两份工程文件的对比

| | Power BI（PBIP） | Tableau（twbx） |
|---|---|---|
| **主文件** | `ERP经营分析.pbip` | `ERP经营分析.twbx` |
| **模型载体** | TMDL（`model.tmdl`，纯文本） | 数据源 + 计算字段（XML） |
| **数据连接** | CSV → Power Query M → 分区 | CSV → textscan 直连 |
| **模型形态** | 星型（11 表 / 15 关系） | 展平事实表 + 维度表并存（单表分析路线） |
| **指标载体** | 30 个 DAX 度量值（TMDL 内） | 32 个 Tableau 计算字段 |
| **报表** | 2 个页面 / 9 个视觉对象（PBIR） | 10 个工作表 / 3 个仪表板 |
| **时间智能** | `DATEADD(dim_date[full_date], -1, YEAR)` | `LOOKUP(..., -12)` |
| **可 review 性** | 高（全是文本） | 中（XML） |
| **打开方式** | Power BI Desktop → 打开 `.pbip` | Tableau Public → 打开 `.twbx` |

> 为什么 Tableau 侧走「展平事实表」路线？
> 因为 CSV 本身已经把维度属性冗余进了事实行（`customer_tier`、`sales_team`、`category`…），
> 直接用能让工作簿在任何 Tableau 版本里都稳定打开、不依赖关系配置。
> 需要星型关系时，`powerquery/erp_model.pq` 提供了完整的 Tableau 版 M 脚本可自行改造。

---

## 3. 口径对照表（**面试必背**）

| 指标 | SQL | Excel | Power BI DAX | Tableau 计算字段 |
|---|---|---|---|---|
| 营收 | `SUM(CASE WHEN order_status='已完成' AND is_return=0 THEN net_amount END)` | `SUMIFS(净额, 订单状态,"已完成")` | `CALCULATE(SUM(fact_sales_order[net_amount]), fact_sales_order[order_status]="已完成", fact_sales_order[is_return]=0)` | `SUM(IF [order_status]="已完成" AND [is_return]=0 THEN [net_amount] END)` |
| 毛利率 | `SUM(gross_profit)/SUM(net_amount)` | `=IFERROR((B3-C3)/B3,0)` | `DIVIDE([毛利],[营收])` | `SUM(...gross_profit END) / SUM(...net_amount END)` |
| 订单数 | `COUNT(DISTINCT order_id)` | `COUNTIFS(...)` | `CALCULATE(DISTINCTCOUNT(...))` | `COUNTD(IF ... THEN [order_id] END)` |
| 客单价 | 营收 ÷ 订单数 | 公式列 | `DIVIDE([营收],[完成订单数])` | 营收 ÷ 订单数 |
| 帕累托累计占比 | `SUM(...) OVER (ORDER BY ... ROWS UNBOUNDED PRECEDING)` | 辅助列 + 累加 | `RUNNING_SUM` | `RUNNING_SUM(SUM([revenue_amount])) / TOTAL(SUM([revenue_amount]))` |
| 同比 | `LAG(...) OVER (ORDER BY ym)` | 公式列 | `DATEADD(dim_date[full_date], -1, YEAR)` | `LOOKUP(SUM(...), -12)` |
| 缺货率 | `COUNT(DISTINCT CASE WHEN stock_gap>0 THEN product_id END) / COUNT(DISTINCT product_id)` | 透视表 + 计数 | `DIVIDE([缺货 SKU 数], ...)` | 同 DAX |
| AI 采纳率 | `SUM(accepted_count)/SUM(query_count)` | 公式列 | `DIVIDE(SUM(...), SUM(...))` | 同 DAX |

**四条贯穿全局的约定**（写进每个工具的文档里）：

1. 营收类指标**一律只算已完成且非退货**
2. 金额**先聚合再算比率**，绝不对行级比率列求和或求平均
3. 计数**一律 COUNTD**（一单多行时 COUNT 会重复计）
4. 除法**一律用 DIVIDE / NULLIF** 防除零

---

## 4. 校验脚本

```bash
python bi/verify_baselines.py      # 关键指标的基线数值核对
python bi/tableau/verify_twb.py    # Tableau 工作簿结构（XML / 字段引用 / CSV 一致性）
python bi/powerbi/verify_pbip.py   # PBIP 结构（JSON / TMDL / 度量引用 / 关系引用 / CSV 一致性）
python bi/tableau/gen_calcs_doc.py # 重新生成 calcs.md
```

校验内容举例：

- Tableau：每个工作表引用的字段实例是否都在 `datasource-dependencies` 里声明过
- Tableau：每个计算字段公式里引用的原始列是否真的存在于对应数据源
- Tableau：twbx 内的 CSV 是否为无 BOM 副本（否则首列名会错位）
- PBIP：TMDL 里声明的列与 M 脚本 `TransformColumnTypes` 的类型是否一一对应
- PBIP：每个 DAX 度量值引用的 `表[列]` 是否存在
- PBIP：每条关系的 `fromColumn` / `toColumn` 是否存在
- 两侧：`metadata-records` / `model.tmdl` 的列名与 CSV 实际表头是否完全一致

---

## 5. 复现与再生成

```bash
python scripts/export_bi_csv.py       # 从数据库导出 bi/data/*.csv 与 excel/data/*.csv
python bi/powerbi/build_pbip.py       # 重新生成 PBIP 项目
python bi/tableau/build_twb.py        # 重新生成 Tableau 工作簿
```

CSV 是**派生产物**：改了数据库 → 重跑导出 → 重跑上面的两个 build 脚本 → 跑校验。
这样 BI 工程文件永远与数据库一致，不会出现「文档改了但图没变」。
