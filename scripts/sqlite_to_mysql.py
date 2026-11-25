# -*- coding: utf-8 -*-
"""
SQLite 方言 → MySQL 8 方言 自动转换器。

把 sql/sqlite/analysis/*.sql 改写成 sql/mysql/analysis/*.sql，
保证两套脚本**逻辑完全等价**（同样的题目、同样的口径、同样的输出列），
只是语法适配各自数据库。

转换规则表
--------------------------------------------------------------------------------
SQLite                              MySQL 8
--------------------------------------------------------------------------------
strftime('%Y-%m',                   DATE_FORMAT(...,'%Y-%m')
    date(ym || '-01', '+1 month'))
date(date(ym || '-01',
    '+1 month'), '-1 day')         DATE_SUB(DATE_ADD(STR_TO_DATE(...),INTERVAL 1 MONTH),INTERVAL 1 DAY)
julianday(a) - julianday(b)        DATEDIFF(a, b)
strftime('%d', d)                   DAYOFMONTH(d)
group_concat(x, ', ')               GROUP_CONCAT(x SEPARATOR ', ')
CAST(... AS INTEGER)                CAST(... AS SIGNED)
||  (字符串拼接)                     CONCAT(a, b)
WITH RECURSIVE                      WITH RECURSIVE        （MySQL 8 原生支持）
ROWS BETWEEN n PRECEDING           同名语法               （MySQL 8 原生支持）
LAG / LEAD / RANK / ROW_NUMBER      同名语法               （MySQL 8 原生支持）
ROUND(x, n) / COALESCE / CASE       同名语法               （完全通用）
LIMIT n                             同名语法               （完全通用）
--------------------------------------------------------------------------------
MySQL 8 默认开启 ONLY_FULL_GROUP_BY，能额外暴露 SQLite 下不报错的
「非聚合列出现在 GROUP BY 之外」问题 —— 这是本转换器刻意保留的严格性。

用法：
    python scripts/sqlite_to_mysql.py            # 生成 sql/mysql/analysis/*.sql
    python scripts/sqlite_to_mysql.py --check    # 只校验幂等（生成后重跑应无差异）
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "sql" / "sqlite" / "analysis"
DST = ROOT / "sql" / "mysql" / "analysis"

# --------------------------------------------------------------------------
# 规则：按顺序应用，每条是 (正则, 替换模板)
# --------------------------------------------------------------------------
RULES: list[tuple[re.Pattern, str]] = [
    # 1) strftime('%Y-%m', date(ym || '-01', '+1 month'))
    #    注意末尾必须把 strftime 的闭合括号一并吃掉，否则会多出一个右括号
    (re.compile(r"strftime\(\s*'%Y-%m'\s*,\s*date\(\s*(\w+)\s*\|\|\s*'-01'\s*,\s*'\+1 month'\s*\)\s*\)", re.I),
     r"DATE_FORMAT(DATE_ADD(STR_TO_DATE(CONCAT(\1, '-01'), '%Y-%m-%d'), INTERVAL 1 MONTH), '%Y-%m')"),

    # 2) date(date(ym || '-01', '+1 month'), '-1 day')
    (re.compile(r"date\(\s*date\(\s*(\w+)\s*\|\|\s*'-01'\s*,\s*'\+1 month'\s*\)\s*,\s*'-1 day'\s*\)", re.I),
     r"DATE_SUB(DATE_ADD(STR_TO_DATE(CONCAT(\1, '-01'), '%Y-%m-%d'), INTERVAL 1 MONTH), INTERVAL 1 DAY)"),

    # 3) date(ym || '-01', '+1 month') —— 单独出现时
    (re.compile(r"date\(\s*(\w+)\s*\|\|\s*'-01'\s*,\s*'\+1 month'\s*\)", re.I),
     r"DATE_ADD(STR_TO_DATE(CONCAT(\1, '-01'), '%Y-%m-%d'), INTERVAL 1 MONTH)"),

    # 4) CAST(julianday(a) - julianday(b) AS INTEGER)
    (re.compile(r"CAST\(\s*julianday\(\s*([^()]+?)\s*\)\s*-\s*julianday\(\s*([^()]+?)\s*\)\s*AS\s+INTEGER\s*\)", re.I),
     r"CAST(DATEDIFF(\1, \2) AS SIGNED)"),

    # 5) CAST(strftime('%d', expr) AS INTEGER)
    (re.compile(r"CAST\(\s*strftime\(\s*'%d'\s*,\s*([^()]+?)\s*\)\s*AS\s+INTEGER\s*\)", re.I),
     r"CAST(DAYOFMONTH(\1) AS SIGNED)"),

    # 6) CAST(x AS INTEGER)
    (re.compile(r"\bAS\s+INTEGER\b", re.I), "AS SIGNED"),

    # 7) group_concat(x, ', ')  →  GROUP_CONCAT(x SEPARATOR ', ')
    #    分隔符字面量是 "', '"（引号 + 逗号 + 空格 + 引号），不能按 ", ', '" 的直觉写正则
    (re.compile(r"group_concat\(([^()]*),\s*'(,\s*)'\s*\)", re.I | re.S),
     r"GROUP_CONCAT(\1 SEPARATOR ', ')"),
    (re.compile(r"\bgroup_concat\s*\(", re.I), "GROUP_CONCAT("),

    # 8) SQLite 的 MAX(a, b) 是标量两参数版；MySQL 的 MAX 只接受一个参数 → 用 GREATEST
    (re.compile(r"\bMAX\(([^()]*),\s*0\s*\)", re.I), r"GREATEST(\1, 0)"),
    (re.compile(r"\bMIN\(([^()]*),\s*0\s*\)", re.I), r"LEAST(\1, 0)"),

    # 9) AVG(整数列) 在 MySQL 下返回 DECIMAL(...,4)（scale=4），
    #    SQLite 下 AVG 返回完整精度的 REAL，两库末位会差。
    #    统一用 DOUBLE 语义消除该差异（对整数/浮点列均无损）
    (re.compile(r"\bAVG\(\s*(\w+(?:\.\w+)*)\s*\)", re.I), r"AVG(CAST(\1 AS DOUBLE))"),

    # 10) SELECT '标签', 某列, * FROM t  →  SELECT '标签', 某列, t.* FROM t
    #    MySQL 不允许 * 与其他表达式混排（除非用表限定 t.*）
    (re.compile(r",\s*\*(\s+FROM\s+)(\w+)", re.I), r", \2.*\1\2"),

    # 11) 剩余的 || 字符串拼接 → CONCAT
    (re.compile(r"(\w+)\s*\|\|\s*('[^']*')"), r"CONCAT(\1, \2)"),
    (re.compile(r"('[^']*')\s*\|\|\s*(\w+)"), r"CONCAT(\1, \2)"),
]

# --------------------------------------------------------------------------
# 特例补丁：SQLite 允许 SELECT g.* 后再用同名列覆盖，MySQL 会报 1060 重名。
# 这里把 16 号脚本的 metrics CTE 改写成「显式列 + 计算列」，语义与 SQLite 完全等价。
# --------------------------------------------------------------------------
SPECIAL_PATCHES: dict[str, list[tuple[str, str]]] = {
    "16_AI辅助vs未辅助商机对比.sql": [
        (
            """    SELECT
        g.*,
        ROUND(g.won_cnt * 1.0 / NULLIF(g.lead_cnt, 0), 4)      AS win_rate,
        ROUND(g.avg_win_probability, 4)                        AS avg_win_probability,
        ROUND(g.avg_cycle_days, 2)                             AS avg_cycle_days,
        ROUND(g.expected_amount, 2)                            AS expected_amount,
        ROUND(g.actual_amount, 2)                              AS actual_amount,
        ROUND(g.actual_amount * 1.0 / NULLIF(g.expected_amount, 0), 4) AS amount_realization_rate
    FROM grouped g""",
            """    -- MySQL 8 不允许 SELECT g.* 之后再定义同名列（Duplicate column name），
    -- 故此处显式列出 grouped 的全部列。
    -- 注意：SQLite 中 SELECT g.* 后面再写同名列时，下游引用取的是 g.* 里的原始列
    -- （SQLite 自动把重名列命名为 xxx:1，m.xxx 解析到第一个），
    -- 所以这里刻意不加 ROUND，与 SQLite 版逐值一致
    SELECT
        g.dim_type,
        g.dim_value,
        g.ai_assisted,
        g.lead_cnt,
        g.won_cnt,
        g.lost_cnt,
        g.avg_win_probability,
        g.avg_cycle_days,
        g.expected_amount,
        g.actual_amount,
        ROUND(g.won_cnt * 1.0 / NULLIF(g.lead_cnt, 0), 4)      AS win_rate,
        ROUND(g.actual_amount * 1.0 / NULLIF(g.expected_amount, 0), 4) AS amount_realization_rate
    FROM grouped g""",
        ),
    ],
}


# 头部注释里的方言说明替换
HEADER_REPLACEMENTS = [
    ("SQLite 方言", "MySQL 8 方言"),
    ("SQLite 专用", "MySQL 8 专用"),
    ("sqlite", "MySQL"),
    ("SQLite", "MySQL 8"),
]


def convert(text: str, filename: str = "") -> str:
    # 先套用方言规则
    for pat, rep in RULES:
        text = pat.sub(rep, text)
    # 再套用特例补丁
    for old, new in SPECIAL_PATCHES.get(filename, []):
        if old not in text:
            print(f"⚠️  特例补丁未命中：{filename}（请检查源脚本是否已改动）")
        text = text.replace(old, new)
    # 只替换注释行里的方言名称，避免动到 SQL 主体
    out = []
    for line in text.splitlines():
        if line.lstrip().startswith("--"):
            for a, b in HEADER_REPLACEMENTS:
                line = line.replace(a, b)
        out.append(line)
    text = "\n".join(out)

    # MySQL 要求行注释 "--" 之后必须紧跟空白字符（SQLite 不要求）
    # 同时去掉注释里的反引号（MySQL 中反引号是标识符引用符）
    text = re.sub(r"(?m)(^|\s)--(?=\S)", r"\1-- ", text)
    text = re.sub(r"(?m)^(\s*--[^\n]*?)`([^`\n]*)`", r"\1\2", text)
    return text + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description="SQLite → MySQL 8 方言转换")
    ap.add_argument("--check", action="store_true", help="只比对，不写入")
    args = ap.parse_args()

    DST.mkdir(parents=True, exist_ok=True)
    files = sorted(SRC.glob("*.sql"))
    if not files:
        print("没有找到 SQLite 脚本")
        return 1

    changed = []
    for src in files:
        converted = convert(src.read_text(encoding="utf-8"), src.name)
        dst = DST / src.name
        if args.check:
            if not dst.exists() or dst.read_text(encoding="utf-8") != converted:
                changed.append(src.name)
        else:
            dst.write_text(converted, encoding="utf-8")

    if args.check:
        if changed:
            print(f"❌ 以下 MySQL 脚本与转换结果不一致，请重跑本脚本：\n   " + "\n   ".join(changed))
            return 1
        print(f"✅ {len(files)} 个 MySQL 脚本与 SQLite 源保持同步")
        return 0

    # 残留方言检查（注意：GROUP_CONCAT 是合法 MySQL 语法，不能误报）
    residual = []
    for dst in sorted(DST.glob("*.sql")):
        t = dst.read_text(encoding="utf-8")
        if re.search(r"\bjulianday\s*\(", t, re.I):
            residual.append(f"{dst.name}: 仍有 julianday(")
        if re.search(r"\bstrftime\s*\(", t, re.I):
            residual.append(f"{dst.name}: 仍有 strftime(")
        if re.search(r"(?<!GROUP_)\bgroup_concat\s*\(", t):
            residual.append(f"{dst.name}: 仍有 group_concat(")
        if re.search(r"\w+\s*\|\|\s*'", t):
            residual.append(f"{dst.name}: 仍有 || 拼接")
        if re.search(r"\bAS\s+INTEGER\b", t, re.I):
            residual.append(f"{dst.name}: 仍有 AS INTEGER")
        if re.search(r",\s*\*\s+FROM", t, re.I):
            residual.append(f"{dst.name}: 仍有未加表限定的 SELECT *, ")
    if residual:
        print("⚠️  残留未转换的 SQLite 语法：")
        for r in residual:
            print("   -", r)
        return 1

    print(f"✅ 已生成 {len(files)} 个 MySQL 8 脚本 → {DST.relative_to(ROOT)}")
    print("   转换规则：strftime / julianday / group_concat / || / date() / CAST AS INTEGER")
    return 0


if __name__ == "__main__":
    sys.exit(main())
