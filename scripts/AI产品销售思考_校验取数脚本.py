"""校验 docs/AI产品销售思考_取数脚本.sql 每条语句可执行，并回显关键结果行。"""
import sqlite3
import sys

sql = open('docs/AI产品销售思考_取数脚本.sql', encoding='utf-8').read()
c = sqlite3.connect('data/erp.db')
c.row_factory = sqlite3.Row

# 正确切分：逐行累积，用 sqlite3.complete_statement 判断语句是否完整
stmts, buf = [], ''
for line in sql.split('\n'):
    buf += line + '\n'
    if sqlite3.complete_statement(buf):
        stmts.append(buf)
        buf = ''
if buf.strip():
    stmts.append(buf)

ok = fail = skip = 0
for i, s in enumerate(stmts, 1):
    body = '\n'.join(l for l in s.split('\n') if not l.strip().startswith('--')).strip()
    if not body:
        skip += 1
        continue
    if body.upper().startswith(('SQLITE3', 'IMPORT')) or 'python -c' in body:
        skip += 1
        continue
    try:
        rows = c.execute(body).fetchall()
        ok += 1
        head = [k for k in rows[0].keys()] if rows else []
        print(f"[OK {i:02d}] rows={len(rows)} {head}")
    except Exception as e:
        fail += 1
        print(f"[FAIL {i:02d}] {e}")
        print(body[:400])
        print('-' * 60)

print(f"\n=== 语句数 {len(stmts)} | 成功 {ok} | 失败 {fail} | 跳过 {skip} ===")
sys.exit(1 if fail else 0)
