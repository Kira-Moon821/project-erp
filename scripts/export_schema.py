"""从 ORM 模型导出两套 DDL，保证「代码 / SQL 脚本 / BI 事实表」口径一致。

产出：
    sql/mysql/schema.sql    —— MySQL 8 方言（ENGINE=InnoDB, utf8mb4）
    sql/sqlite/schema.sql   —— SQLite 方言
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy.dialects import mysql, sqlite            # noqa: E402
from sqlalchemy.schema import CreateIndex, CreateTable    # noqa: E402

from app.db.models import Base                           # noqa: E402

HEADER = """-- ============================================================
-- ERP Analytics Lab · {title}
-- 由 app/db/models.py 自动导出，请勿手工修改后不回写模型
-- 生成命令：python scripts/export_schema.py
-- ============================================================
"""


def render(dialect) -> str:
    lines: list[str] = []
    for table in Base.metadata.sorted_tables:
        lines.append(str(CreateTable(table).compile(dialect=dialect)).strip() + ";")
        for index in sorted(table.indexes, key=lambda i: i.name or ""):
            lines.append(str(CreateIndex(index).compile(dialect=dialect)).strip() + ";")
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    out_mysql = ROOT / "sql" / "mysql" / "schema.sql"
    out_sqlite = ROOT / "sql" / "sqlite" / "schema.sql"
    out_mysql.parent.mkdir(parents=True, exist_ok=True)
    out_sqlite.parent.mkdir(parents=True, exist_ok=True)

    out_mysql.write_text(HEADER.format(title="MySQL 8 建库脚本") + render(mysql.dialect()), encoding="utf-8")
    out_sqlite.write_text(HEADER.format(title="SQLite 建库脚本") + render(sqlite.dialect()), encoding="utf-8")
    print(f"exported: {out_mysql}")
    print(f"exported: {out_sqlite}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
