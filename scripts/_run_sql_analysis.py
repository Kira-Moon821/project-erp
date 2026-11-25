"""SQL 脚本批量执行与结果回填工具（开发期辅助脚本，不属于交付物）。

用法：
  python scripts/_run_sql_analysis.py            # 只执行并打印
  python scripts/_run_sql_analysis.py --fill     # 执行并把真实结果回填到 .sql 文件的「预期结果」注释
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

import sqlite3

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "erp.db"
DIR = ROOT / "sql" / "sqlite" / "analysis"
MYSQL_DIR = ROOT / "sql" / "mysql" / "analysis"

# MySQL 临时验证实例（scripts/_verify_mysql_instance.md 有说明）
MYSQL_HOST = os.environ.get("ERP_MYSQL_HOST", "127.0.0.1")
MYSQL_PORT = int(os.environ.get("ERP_MYSQL_PORT", "3307"))
MYSQL_USER = os.environ.get("ERP_MYSQL_USER", "root")
MYSQL_PASSWORD = os.environ.get("ERP_MYSQL_PASSWORD", "")
MYSQL_DB = os.environ.get("ERP_MYSQL_DB", "erp_analytics")

HEADER_END = "-- ============================================================"


def _extract_sql(path: Path) -> str:
    """去掉头部注释块，只留可执行 SQL"""
    text = path.read_text(encoding="utf-8")
    idx = text.find(HEADER_END)
    idx2 = text.find(HEADER_END, idx + len(HEADER_END))
    sql = text[idx2 + len(HEADER_END):] if idx2 != -1 else text
    return sql.strip()


def run_one(con, path: Path) -> tuple[bool, list[tuple], str]:
    sql = _extract_sql(path)
    try:
        if isinstance(con, sqlite3.Connection):
            cur = con.execute(sql)
            rows = cur.fetchall()
            cols = [d[0] for d in cur.description] if cur.description else []
            return True, [tuple(cols)] + [tuple(r) for r in rows], sql
        # MySQL：需要 MULTI_STATEMENTS 才能跑含分号的脚本
        import pymysql
        from pymysql.constants import CLIENT
        with pymysql.connect(host=MYSQL_HOST, port=MYSQL_PORT, user=MYSQL_USER,
                             password=MYSQL_PASSWORD, database=MYSQL_DB,
                             charset="utf8mb4",
                             client_flag=CLIENT.MULTI_STATEMENTS) as conn:
            with conn.cursor() as cur:
                cur.execute(sql)
                rows = cur.fetchall() or []
                cols = [d[0] for d in cur.description] if cur.description else []
        return True, [tuple(cols)] + [tuple(r) for r in rows], sql
    except Exception as exc:  # noqa: BLE001
        return False, [], f"{type(exc).__name__}: {exc}"


def summarize(rows: list[tuple], limit: int = 10) -> str:
    if not rows:
        return "（无输出行）"
    head = rows[0]
    body = rows[1:]
    lines = []
    lines.append("共 " + str(len(body)) + " 行；列：" + ", ".join(head))
    for r in body[:limit]:
        cells = []
        for v in r:
            if isinstance(v, float):
                cells.append(f"{v:,.4f}".rstrip("0").rstrip("."))
            elif v is None:
                cells.append("NULL")
            else:
                cells.append(str(v))
        lines.append("  " + " | ".join(cells))
    if len(body) > limit:
        lines.append(f"  ...（其余 {len(body) - limit} 行略）")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fill", action="store_true", help="回填「预期结果」注释")
    ap.add_argument("--mysql", action="store_true", help="在 MySQL 8 上执行（而非 SQLite）")
    args = ap.parse_args()

    if args.mysql:
        con = None
        files = sorted(MYSQL_DIR.glob("[0-9][0-9]_*.sql"))
    else:
        con = sqlite3.connect(DB)
        con.execute("PRAGMA foreign_keys = ON")
        files = sorted(DIR.glob("[0-9][0-9]_*.sql"))
    failures = []
    for f in files:
        ok, rows, err = run_one(con, f)
        status = "PASS" if ok else "FAIL"
        print(f"===== {status}  {f.name}")
        if ok:
            print(summarize(rows))
        else:
            print("  ERROR:", err)
            failures.append((f.name, err))
        print()

    if args.fill:
        for f in files:
            ok, rows, _ = run_one(con, f)
            if not ok:
                continue
            text = f.read_text(encoding="utf-8")
            summary = summarize(rows, limit=8)
            summary = summary.replace("\n", "\n--   ")
            new_text = re.sub(
                r"-- 预期结果：@@RESULT@@",
                "-- 预期结果：\n--   " + summary,
                text,
            )
            f.write_text(new_text, encoding="utf-8")
        print("已回填全部通过脚本的「预期结果」。")

    if failures:
        print(f"\n!!! {len(failures)} 个脚本失败：")
        for name, err in failures:
            print(f"  - {name}: {err}")
        return 1
    print(f"\n全部 {len(files)} 个脚本执行成功。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
