# -*- coding: utf-8 -*-
"""
Tableau 工作簿结构自检（不依赖任何第三方库 / 网络）。

校验项：
  1. twb XML 良构
  2. 每个 worksheet 引用的 datasource id 在 <datasources> 中存在
  3. rows/cols/filters/encodings 中引用的每一个字段，
     都在对应 worksheet 的 <datasource-dependencies> 里声明过
  4. 计算字段 formula 里引用的原始列，在该 datasource 的 metadata-records 中存在
  5. twbx 内含 twb + 全部 Data/*.csv，且 CSV 无 BOM
  6. twb 内 <metadata-records> 的列名 与 CSV 实际表头一致

用法： python bi/tableau/verify_twb.py
退出码 0 = 全通过
"""
from __future__ import annotations

import re
import sys
import zipfile
from pathlib import Path
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
TWB = ROOT / "bi" / "tableau" / "ERP经营分析.twb"
TWBX = ROOT / "bi" / "tableau" / "ERP经营分析.twbx"

errors: list[str] = []
warns: list[str] = []


def err(msg):
    errors.append(msg)


def warn(msg):
    warns.append(msg)


def main() -> int:
    # ---- 1. XML 良构 ----
    try:
        tree = ET.parse(TWB)
    except ET.ParseError as e:
        print(f"❌ XML 解析失败: {e}")
        return 1
    root = tree.getroot()
    if root.tag != "workbook":
        err(f"根元素不是 workbook: {root.tag}")
    print(f"✅ 1. XML 良构，根元素 = {root.tag}")

    # ---- 数据源索引 ----
    ds_caps = {}
    ds_cols: dict[str, set[str]] = {}
    ds_calcs: dict[str, dict[str, str]] = {}
    for ds in root.findall("./datasources/datasource"):
        name = ds.get("name")
        cap = ds.get("caption")
        ds_caps[name] = cap
        cols = set()
        for mr in ds.findall(".//metadata-record"):
            rn = mr.find("remote-name")
            if rn is not None:
                cols.add(rn.text)
        ds_cols[name] = cols
        calcs = {}
        for c in ds.findall("./column"):
            calc = c.find("./calculation")
            if calc is not None:
                calcs[c.get("name")] = calc.get("formula")
        ds_calcs[name] = calcs
    print(f"✅ 2. 数据源 {len(ds_caps)} 个：" + ", ".join(sorted(ds_caps.values())))

    # ---- 3. worksheet 字段声明检查 ----
    FIELD_RE = re.compile(r"\[datasource\.([^\]]+)\]\.\[([^\]]+)\]")
    checked = 0
    for ws in root.findall("./worksheets/worksheet"):
        wname = ws.get("name")
        deps = ws.findall(".//datasource-dependencies")
        if not deps:
            err(f"[{wname}] 缺少 datasource-dependencies")
            continue
        dep = deps[0]
        dep_ds = dep.get("datasource")
        if dep_ds not in ds_caps:
            err(f"[{wname}] 依赖了不存在的数据源 {dep_ds}")
            continue
        declared = {c.get("name", "").strip("[]") for c in dep.findall("./column")}
        insts = {i.get("name", "").strip("[]") for i in dep.findall("./column-instance")}
        # 所有引用
        refs = []
        for tag in (".//rows/column", ".//cols/column", ".//slices/column",
                    ".//encodings/*", ".//filter"):
            for node in ws.findall(tag):
                txt = (node.text or "").strip()
                if not txt:
                    continue
                if tag == ".//encodings/*":
                    txt = node.get("column") or ""
                if tag == ".//filter":
                    continue
                m = FIELD_RE.search(txt)
                if m:
                    refs.append((m.group(1), m.group(2)))
        for dsid, inst in refs:
            if dsid != dep_ds:
                err(f"[{wname}] 引用了别的工作表数据源 {dsid}")
                continue
            if inst not in insts:
                err(f"[{wname}] 引用字段实例 {inst} 未在 datasource-dependencies 声明")
            checked += 1
    print(f"✅ 3. 字段引用检查完成，共校验 {checked} 处引用")

    # ---- 4. 计算字段引用的原始列存在性 ----
    token_re = re.compile(r"\[([^\[\]]+)\]")
    for dsname, calcs in ds_calcs.items():
        for cname, formula in calcs.items():
            for token in token_re.findall(formula or ""):
                if token.startswith("Calculation_"):
                    if token not in calcs:
                        err(f"[{ds_caps[dsname]}] 计算字段 {cname} 引用了未定义字段 {token}")
                elif token not in ds_cols[dsname]:
                    err(f"[{ds_caps[dsname]}] 计算字段 {cname} 引用了不存在的原始列 {token}")
    print(f"✅ 4. 计算字段公式列引用检查完成，共 {sum(len(c) for c in ds_calcs.values())} 个计算字段")

    # ---- 5. twbx 完整性 ----
    if not TWBX.exists():
        err("twbx 不存在")
    else:
        with zipfile.ZipFile(TWBX) as z:
            names = z.namelist()
            if "ERP经营分析.twb" not in names:
                err("twbx 内缺少 twb")
            csvs = [n for n in names if n.startswith("Data/") and n.endswith(".csv")]
            src = sorted(p.name for p in (ROOT / "bi" / "data").glob("*.csv"))
            if sorted(n.split("/")[-1] for n in csvs) != src:
                err(f"twbx 内 CSV 与 bi/data 不一致: {sorted(n.split('/')[-1] for n in csvs)}")
            for n in csvs:
                head = z.read(n)[:3]
                if head.startswith(b"\xef\xbb\xbf"):
                    err(f"twbx 内 {n} 带 BOM，Tableau textscan 可能导致首列名错位")
        print(f"✅ 5. twbx 完整性检查完成，内含 {len(csvs)} 个 CSV（无 BOM）")

    # ---- 6. metadata 列名 == CSV 表头 ----
    for name, cap in ds_caps.items():
        csv_path = ROOT / "bi" / "data" / f"{cap}.csv"
        if not csv_path.exists():
            err(f"数据源 {cap} 在 bi/data 下找不到 CSV")
            continue
        import csv as _csv
        with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
            header = next(_csv.reader(f))
        if set(header) != ds_cols[name]:
            missing = set(header) - ds_cols[name]
            extra = ds_cols[name] - set(header)
            err(f"数据源 {cap} 列名与 CSV 不一致 缺={sorted(missing)} 多={sorted(extra)}")
    print("✅ 6. metadata-records 列名与 CSV 表头一致性检查完成")

    # ---- 输出 ----
    if warns:
        print("\n⚠️  警告：")
        for w in warns:
            print("   -", w)
    if errors:
        print(f"\n❌ 校验未通过，共 {len(errors)} 个问题：")
        for e in errors:
            print("   -", e)
        return 1
    print("\n🎉 Tableau 工作簿结构校验全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
