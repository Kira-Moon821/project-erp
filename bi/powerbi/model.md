# Power BI 数据模型说明（ERP 经营分析实验室）

> 口径来源：`docs/数据字典与业务口径.md`（唯一口径来源）。
> 字段名来源：`bi/data/*.csv` 实际列名，由 `bi/verify_baselines.py` 校验输出。
> 数值基线：`python bi/verify_baselines.py`（下文出现的期望值均来自该脚本，可随时重跑复核）。

---

## 1. 建模总览

本项目的数据源是**已展平的 CSV 事实表**（`fact_*_flat.csv`）。每个事实表都把常用的维度属性（客户分层、行业、区域、销售团队等）直接冗余进了行里，同时仓库里还有独立的维度表（`dim_*.csv`）。

因此存在两条可行的建模路线，本模型采用**主路线 A（标准星型模型）**，同时给出**备选路线 B（单表 + DAX）**：

| | 路线 A（推荐 · 本模型采用） | 备选路线 B（单表 + DAX 计算） |
|---|---|---|
| 做法 | 事实表保留主键与度量列，维度属性通过**关系**从维度表取 | 事实表已展平，直接当宽表用，维度表只作校验参考 |
| 优点 | 维度可复用、模型小、度量值语义清晰、BI 惯用 | 导入即用、无需建模、透视灵活 |
| 代价 | 需要先在 Power Query 裁掉冗余列 | 维度表形同虚设，维度变更需重新导出 CSV |
| 适用 | 长期维护、多人协作、企业落地 | 个人快速分析、一次性探索 |

> **重要前提**：`verify_baselines.py` 第 2 节已验证「事实表展平属性 vs 维度表」**不一致数为 0**。
> 这意味着两条路线在数值上完全等价，路线 A 不会改变任何口径，只是把取数路径规范化。

---

## 2. 星型模型结构

```
                          ┌──────────────────┐
                          │     dim_date     │  日期维表（标记为日期表）
                          │  date_id (PK)    │  2024-01-01 ~ 2026-03-31
                          │  full_date       │  ← 唯一可标记为「日期表」的列
                          └────────┬─────────┘
                                   │ 1 : *  (single direction, dim → fact)
        ┌──────────────┬───────────┼───────────┬──────────────┐
        │              │           │           │              │
┌───────▼────────┐ ┌───▼────────┐ ┌▼─────────┐ ┌▼───────────┐ ┌▼─────────────┐
│fact_sales_order│ │fact_sales_ │ │fact_in-  │ │fact_lead_  │ │fact_customer_│
│      _flat     │ │order_item_ │ │ventory_  │ │opportunity_│ │ticket_flat   │
│  order_id (PK) │ │ flat       │ │snapshot_ │ │ flat       │ │ ticket_id(PK)│
│  customer_id ──┼─┐  order_id │ │ flat     │ │ lead_id(PK)│ │ customer_id ─┼─┐
│  employee_id ──┼─┼──▶(FK)    │ │ snapshot_│ │ customer_id┼─┤ customer_id  │ │
│  order_date ───┼─┼─┐ product_ │ │  id (PK) │ │ owner_emp_ │ │ ai_handled   │ │
│  net_amount    │ │ │ id (FK)  │ │ product_ │ │  employee_ │ │ first_resp_  │ │
│  ...           │ │ │ ...      │ │  id (FK) │ │  id (FK)   │ │ ...          │ │
└───────┬────────┘ │ └──────────┘ └────┬─────┘ └──────┬─────┘ └─────────────┘ │
        │          │                    │              │                        │
        │          │              ┌─────▼──────┐       │                        │
        │          │              │dim_product │       │                        │
        │          │              │ product_id │       │                        │
        │          │              │   (PK)     │       │                        │
        │          │              └────────────┘       │                        │
        │          │                                   │                        │
        │          │   ┌──────────────┐                │                        │
        │          │   │ dim_customer │◄───────────────┼────────────────────────┘
        │          │   │ customer_id  │                │
        │          │   │   (PK)       │◄───────────────┘
        │          │   └──────────────┘
        │          │
        │          │   ┌────────────────┐
        │          └──▶│ dim_employee   │◀─── fact_lead_opportunity.owner_employee_id
        │              │ employee_id(PK)│◀─── fact_ai_usage.employee_id
        │              └────────────────┘
        │
        │   ┌──────────────────────┐        ┌────────────────────┐
        └──▶│ fact_marketing_spend │        │   fact_ai_usage    │
            │        _flat         │        │       _flat        │
            │   spend_id (PK)      │        │   usage_id (PK)    │
            │   channel, cost_...  │        │   scenario, ...    │
            └──────────────────────┘        └────────────────────┘
                    （独立事实表，不参与主星型）
```

---

## 3. 表清单与主外键

### 3.1 事实表（7 张）

| 表（Power BI 中的名称） | 主键 | 行数 | 说明 |
|---|---|---|---|
| `fact_sales_order` | `order_id` | 5,727 | 订单级事实表。营收/毛利/客单价主来源 |
| `fact_sales_order_item` | `order_item_id` | 15,201 | 订单明细。商品级结构分析（ABC/帕累托）来源 |
| `fact_inventory_snapshot` | `snapshot_id` | 3,840 | 月末库存快照（24 月 × 80 SKU × 2 仓） |
| `fact_lead_opportunity` | `lead_id` | 1,062 | 线索→商机漏斗 + `ai_assisted` 标记 |
| `fact_customer_ticket` | `ticket_id` | 765 | 客服工单 + `ai_handled` 标记 |
| `fact_marketing_spend` | `spend_id` | 144 | 营销投放（独立周期事实，24 个月 × 6 渠道） |
| `fact_ai_usage` | `usage_id` | 1,224 | 内部 AI 助手使用记录 |

### 3.2 维度表（4 张）

| 表 | 主键 | 行数 | 说明 |
|---|---|---|---|
| `dim_date` | `date_id` | 821 | 日期维表。**注意**：覆盖 2024-01-01 ~ 2026-03-31，尾部 90 天是给交付日期用的 |
| `dim_customer` | `customer_id` | 60 | A(10)/B(20)/C(30) 分层 |
| `dim_employee` | `employee_id` | 18 | 销售团队与角色 |
| `dim_product` | `product_id` | 80 | SKU / 品类 / 品牌 / 单位成本 / 标价 |

> **关键提醒**：`dim_date` 尾部多出的 90 天（2026-01 ~ 2026-03）**不属于业务窗口**。
> 业务窗口 = `2024-01-01 ~ 2025-12-31`。任何营收/库存分析都应先按此窗口过滤，否则尾部日期会让「同比」「周转天数」出现分母污染。
> 实现方式见 §6.3 的 `业务窗口日期` 度量与 `build_guide.md` 的建模步骤。

---

## 4. 关系列表

| # | 维度表（1 端） | 事实表（* 端） | 基数 | 方向 | 交叉筛选 | 关系说明 |
|---|---|---|---|---|---|---|
| 1 | `dim_date[full_date]` | `fact_sales_order[order_date]` | 1 : * | 单向（维→事） | 否 | 时间智能分析的**唯一**入口，必须单向 |
| 2 | `dim_date[full_date]` | `fact_sales_order_item[order_date]` | 1 : * | 单向 | 否 | 同上 |
| 3 | `dim_date[full_date]` | `fact_inventory_snapshot[snapshot_date]` | 1 : * | 单向 | 否 | 库存按月末快照对齐 |
| 4 | `dim_date[full_date]` | `fact_lead_opportunity[created_date]` | 1 : * | 单向 | 否 | 漏斗按线索创建日归期 |
| 5 | `dim_date[full_date]` | `fact_customer_ticket[created_date]` | 1 : * | 单向 | 否 | 工单按创建日归期 |
| 6 | `dim_date[full_date]` | `fact_marketing_spend[date]` | 1 : * | 单向 | 否 | 投放按投放日归期 |
| 7 | `dim_date[full_date]` | `fact_ai_usage[date]` | 1 : * | 单向 | 否 | AI 使用按月末记录日归期 |
| 8 | `dim_customer[customer_id]` | `fact_sales_order[customer_id]` | 1 : * | 单向 | 否 | 客户维度，60 个客户全覆盖 |
| 9 | `dim_customer[customer_id]` | `fact_lead_opportunity[customer_id]` | 1 : * | 单向 | 否 | 客户维度 |
| 10 | `dim_customer[customer_id]` | `fact_customer_ticket[customer_id]` | 1 : * | 单向 | 否 | 客户维度 |
| 11 | `dim_product[product_id]` | `fact_sales_order_item[product_id]` | 1 : * | 单向 | 否 | 商品维度 |
| 12 | `dim_product[product_id]` | `fact_inventory_snapshot[product_id]` | 1 : * | 单向 | 否 | 商品维度 |
| 13 | `dim_employee[employee_id]` | `fact_sales_order[employee_id]` | 1 : * | 单向 | 否 | 员工维度 |
| 14 | `dim_employee[employee_id]` | `fact_lead_opportunity[owner_employee_id]` | 1 : * | 单向 | 否 | 线索归属销售 |
| 15 | `dim_employee[employee_id]` | `fact_ai_usage[employee_id]` | 1 : * | 单向 | 否 | AI 使用者 |
| 16 | `fact_sales_order[order_id]` | `fact_sales_order_item[order_id]` | 1 : * | 单向 | 否 | **订单↔明细**：事实表挂事实表 |

### 4.1 为什么全部单向、全部不交叉筛选

1. **日期关系必须单向**：双向的日期关系会让「总览页的日期切片器」同时回压到所有事实表，
   在做同比（`SAMEPERIODLASTYEAR`）时会形成筛选上下文的相互干扰，出现难以排查的数字跳变。
2. **不做交叉筛选（Cross filter = Neither）**：订单↔明细的关系（#16）若开启双向，
   明细上的 `order_status` 筛选会反写回订单表，导致 `订单数` 被明细行数污染。
   单向（订单→明细）时，明细表上的度量值天然继承订单级筛选，符合「营收按订单状态口径」的要求。
3. **关系完整性**：所有外键在维度表中 100% 命中（`verify_baselines.py` §2 全部 OK），
   因此可在建模时勾选「假设引用完整性」以启用 DAX 引擎的内部优化（Blink 加速）。

> **注意**：`fact_marketing_spend` 与 `fact_ai_usage` 没有到主星型的维度关系（营销的 `channel`
> 与线索的 `source_channel` 取值体系不同——营销是「搜索广告/行业展会/…」，线索是「官网/展会/…」，
> 二者不可直接 join）。这两个表作为**独立事实**接入报表页。

---

## 5. 度量表与维度表的分工

### 5.1 分工原则

| | 维度表（dim_*） | 事实表（fact_*） | 度量（Power BI 独有） |
|---|---|---|---|
| 存放什么 | **描述性属性**：名称、分类、层级、标签 | **可度量数值** + 事实粒度主键 + 外键 | 业务指标定义（DAX 公式） |
| 基数 | 一行一实体（客户 60、员工 18、商品 80） | 一行一业务事件（订单 5,727） | 不占存储，运行时计算 |
| 能否做 SUM | 否（文本列为主） | 是（金额/数量列） | — |
| 是否被切片器筛选 | 是（天然筛选入口） | 是（行级粒度） | 否，只响应上下文 |

### 5.2 本项目中的具体分工

**维度表承担**（这些属性只存在于维度表，是维度表存在的意义）：

| 维度表 | 提供的事实表里没有的属性 |
|---|---|
| `dim_customer` | `annual_contract_value`（合同额）、`contract_date`、`status`（合作中/已流失）、`customer_manager_id` |
| `dim_product` | `unit_cost`（单位成本）、`list_price`（标价）、`supplier_id`、`launch_date`、`status`（在售/停产） |
| `dim_employee` | `hire_date`、`is_active` |
| `dim_date` | `is_weekend`、`week_of_year`、`day_of_week`、`month_name`、`year_quarter` |

> **动销率**这个指标必须靠 `dim_product[status]="在售"` 才能算准——
> 事实表里没有商品状态字段。明细表只有 77 个有销售的 SKU，而 `dim_product` 里「在售」也是 77 个、「停产」3 个，
> 所以动销率 = 77/77 = **100%**（基线值）。这个 100% 看起来很反常，是数据本身的设计结果：
> 3 个停产 SKU 恰好是 `SKU-0052 / SKU-0071 / SKU-0078`，它们**从未产生过销售且库存恒为 0**。

**事实表承担**（度量直接来自事实列，不再重算）：
`net_amount`、`gross_amount`、`discount_amount`、`cost_amount`、`gross_profit`、`qty`、`revenue_amount`、
`on_hand_qty`、`safety_stock`、`inventory_value`、`win_probability`、`cycle_days`、`first_response_minutes`、
`satisfaction`、`query_count`、`accepted_count`、`minutes_saved`、`cost_amount`(营销)、`leads_count`、`revenue_attributed`。

**度量值（DAX）承担**：所有需要**跨表组合、上下文改写、期间对比**的指标——
同比/环比/YTD/滚动 12 月、ABC 分类、帕累托贡献、RFM 分层、库存周转天数、漏斗逐级转化率、AI 对照组对比。
详见 `dax/dax_measures.dax`。

---

## 6. 日期层级设计

### 6.1 层级结构

以 `dim_date` 为日期维表，层级为：

```
年 (year, 2024)
 └─ 季度 (year_quarter, 2024Q1)
     └─ 月 (year_month, 2024-01)
         └─ 日 (full_date, 2024-01-01)
```

| 层级 | 列名 | 类型 | 排序 | 备注 |
|---|---|---|---|---|
| 年 | `year` | 整数 | 升序 | 2024 / 2025 |
| 季度 | `year_quarter` | 文本 | 按 `year` + `quarter` 排序 | 值形如 `2024Q1`，**文本排序会错** |
| 月 | `year_month` | 文本 | 按 `year_month` 升序 | 值形如 `2024-01`，**文本排序恰好正确** |
| 日 | `full_date` | 日期 | 升序 | 唯一可用于时间智能的列 |

### 6.2 排序陷阱与解法

`year_quarter` 是文本列（`2024Q1`）。文本按字典序排序时 `2024Q1 < 2024Q2 < 2024Q3 < 2024Q4 < 2025Q1`，
**恰好正确**，可以直接用。但一旦有类似 `2024Q10` 的格式就会错位——本项目不会发生，所以**无需处理**，
但仍建议在模型视图里把 `quarter` 列设为「按列排序」以防万一。

> **注意**：`dim_date` 里同时存在 `quarter`（值形如 `2024Q1`）与 `year_quarter`（同值）。
> 事实表里也有 `quarter`（同值 `2024Q1`）与 `year_month`。
> 建关系时**只连 `full_date`**，不要把事实表的 `year`/`quarter`/`year_month` 再连一遍——
> 那会造成同一维度被两条路径筛两次（Power BI 允许，但语义混乱且影响性能）。

### 6.3 业务窗口约束

`dim_date` 覆盖 821 天（2024-01-01 ~ 2026-03-31），而业务窗口是 731 天（2024-01-01 ~ 2025-12-31）。
尾部 90 天在源库中用于承载**交付日期**（`fact_sales_order` 有 `delivery_days`，但交付日期本身不在导出的 CSV 中）。

处理方式（两种，二选一）：

- **方式 1（推荐，报表级）**：在「经营总览」页加一个日期切片器，默认选中 2024-01-01 ~ 2025-12-31，
  并在 `dax_measures.dax` 中提供 `业务窗口日期` 标记列 + `是否业务窗口` 度量做二次保险。
- **方式 2（模型级）**：在 Power Query 的 `dim_date` 步骤中直接过滤掉尾部日期。
  代价是以后要用交付日期做分析时得改回来。

本模型采用**方式 1**，并在 `dax_measures.dax` 中显式提供窗口约束度量。

### 6.4 日期表标记

必须执行：`模型视图` → 右键 `dim_date` → **标记为日期表** → 选 `full_date`。

不做这一步的后果（新手最常见的坑）：

- `SAMEPERIODLASTYEAR` / `DATEADD` / `TOTALYTD` 等时间智能函数**直接报红**或返回错误值；
- 同比对比会出现「当前期和去年同期没有对齐」的问题；
- 自动日期/时间功能（Auto Date/Time）会额外生成一张隐藏日期表，导致模型混乱。

---

## 7. 关系视图布局建议

打开 `模型视图` 后，建议按下列方式拖拽排布（从上到下为维表，从下到上为事实表，箭头表示筛选方向）：

```
┌───────────────────────────────────────────────────────────────────────────┐
│  [ dim_date ]          [ dim_customer ]      [ dim_product ]   [ dim_employee ]│
│   full_date                customer_id           product_id        employee_id  │
│   year / quarter           industry / region     category / brand  team / role │
│   year_month / month       tier / channel       unit_cost         is_active    │
│   is_weekend               annual_contract_value list_price                      │
│   week_of_year             status                                              │
│      ▲  (1:*)  单向          ▲  (1:*)  单向        ▲  (1:*)  单向     ▲  (1:*) 单向  │
├─────────────────────────────┴──────────────────────┴──────────────────┴───────────┤
│                                                                                     │
│  [ fact_sales_order ] ◀─────────────── (1:*) ─────────────────── [ fact_sales_order_item ] │
│   order_date ─────────┐   order_id ───────────────────────▶  order_id (FK)          │
│   customer_id ────────┼──────────────────────────────▶  product_id (FK)            │
│   employee_id ────────┼──────────────────────────────▶  customer_id (FK)           │
│   net_amount / ...    │                                   revenue_amount / qty      │
│                                                                                     │
│  [ fact_inventory_snapshot ]   [ fact_lead_opportunity ]  [ fact_customer_ticket ]   │
│   snapshot_date ──┐            created_date ──┐           created_date ──┐          │
│   product_id ─────┼──▶ dim_product            │           customer_id ───┼──▶ dim_customer│
│   inventory_value │            customer_id ───┼──▶ dim_customer         │              │
│                   │            ai_assisted    │           ai_handled    │              │
│                   │            stage          │           ticket_id      │              │
│                   │                           │                           │              │
│  [ fact_marketing_spend ]   [ fact_ai_usage ]   ← 独立事实，放最下方避免视觉拥挤            │
└───────────────────────────────────────────────────────────────────────────┘
```

### 7.1 布局操作步骤

1. `模型视图` → 左侧「数据」窗格勾选显示所有表；
2. 用**多选**（Ctrl + 点选）把 4 张维度表拖到画布**顶部一行**，水平排列；
3. 把 4 张事实表拖到**中部**，`fact_sales_order` 放最左（它是核心表）；
4. `fact_marketing_spend`、`fact_ai_usage` 放**最下方**，与主星型拉开距离；
5. 拖动关系连线让线条不交叉：日期连线统一从 `dim_date` 底部扇出；
6. 勾选关系卡片上的「**卡片视图**」显示基数与方向，确认无误。

### 7.2 隐藏与格式化（让模型干净可读）

在模型视图里对每张表做以下设置：

| 操作 | 位置 | 目的 |
|---|---|---|
| 隐藏冗余维度列 | 选中事实表里已展平的 `customer_tier`/`customer_industry`/`customer_region`/`customer_channel`/`acquisition_source`/`sales_team`/`sales_role`/`category`/`brand`/`sku`/`product_name` → 右键「隐藏」 | 避免与维度表属性**歧义**（同名不同源），报表里只暴露维度表版本 |
| 隐藏外键列 | `customer_id`/`product_id`/`employee_id`/`order_id` → 隐藏 | 防止用户误把 ID 当业务字段拖进报表 |
| 隐藏未用事实列 | `gross_margin`、`discount_rate`（事实表自带的冗余计算列） | 这两列是**行级比率**，直接 SUM 会算错（见坑位说明），统一用 DAX 重算 |
| 设置货币格式 | `net_amount`/`gross_amount`/`cost_amount`/`gross_profit`/`inventory_value`/`annual_contract_value` → 「货币」 | 千分位 + 2 位小数 |
| 设置百分比格式 | DAX 中返回比率的度量 → 「百分比，2 位小数」 | |
| 设置日期表 | `dim_date[full_date]` → 右键「标记为日期表」 | 启用时间智能 |

> **关于 `discount_rate` / `gross_margin` 这两列**：
> 事实表自带它们（订单级比率），但**行级比率不可直接求和**。
> 正确做法是用 DAX 重算：`折扣率 = DIVIDE(SUM(discount_amount), SUM(gross_amount))`，
> `毛利率 = DIVIDE(SUM(gross_profit), SUM(net_amount))`。
> 这两个比率列在模型里应隐藏，只在明细探查时临时启用。

---

## 8. 模型规模与性能预估

| 项 | 数量 |
|---|---|
| 事实表 | 7 张，共 27,963 行 |
| 维度表 | 4 张，共 979 行 |
| 关系 | 16 条，全部单向 |
| DAX 度量值 | 40+（见 `dax/dax_measures.dax`） |

总数据量极小（约 3 MB），Power BI 内存中完全放得下，无需聚合表或增量刷新。
数据量小反而要**重点关注度量值写法**（上下文改写次数），因为像「滚动 12 月」「帕累托累计占比」
这类度量在每次拖动时都会重复计算，笨重的写法会让交互明显卡顿。
`dax/dax_measures.dax` 中对每个复杂度量值都标注了**考察点**，可据此做性能对比。

---

## 9. 两条建模路线的 Power Query 实现差异

完整的 M 脚本见 `powerquery/erp_model.pq`。两条路线的差异集中在**事实表查询的尾部**：

### 路线 A（星型，推荐）——`stg_Sales` 查询

```m
// 事实表只保留：主键 + 外键 + 度量列 + 日期列
// 维度属性（customer_tier / sales_team / category ...）在此处【不保留】，
// 改由模型视图中的关系从 dim_* 表取得
let
    ...
    裁剪维度列 = Table.SelectColumns(源, {"order_id","order_no","order_date","customer_id",
                                          "employee_id","order_channel","order_status",
                                          "payment_status","gross_amount","discount_amount",
                                          "net_amount","cost_amount","gross_profit","delivery_days","is_return"})
in
    裁剪维度列
```

### 路线 B（单表 + DAX）——`stg_Sales_Wide` 查询

```m
// 保留全部展平列，维度表不参与建模
let
    ...
    // 维度表仅用于校验，不 merge；也可选做 merge 补充 dim_product.unit_cost 等缺失属性
in
    源
```

> **路线 B 的补充**：若要用到 `unit_cost`（单位成本）做商品毛利分析，明细事实表里**没有**这个字段，
> 必须从 `dim_product` merge 进来。所以即使走路线 B，`fact_sales_order_item` 仍建议 merge `dim_product`。
> 这正是路线 A 更省事的地方——关系自动处理了这件事。

---

## 10. 与其他文档的关系

| 文档 | 回答的问题 |
|---|---|
| `docs/数据字典与业务口径.md` | 指标**应该**怎么算（唯一口径来源） |
| `model.md`（本文） | 数据**怎么组织**（表、关系、层级） |
| `powerquery/erp_model.pq` | 数据**怎么进来**（M 脚本） |
| `dax/dax_measures.dax` | 指标**在 Power BI 里**怎么算 |
| `build_guide.md` | 在 Power BI Desktop 里**一步步怎么做出来** |
| `../tableau/calcs.md` | 同一批指标**在 Tableau 里**怎么算 |
| `../tableau/口径对照.md` | 两套工具的**实现差异与 8 个坑** |
| `../verify_baselines.py` | **怎么验证**算对了（本文所有期望值的来源） |
