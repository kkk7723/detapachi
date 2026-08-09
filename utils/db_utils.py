from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any, Mapping


def open_database(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=60, isolation_level=None)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA busy_timeout=60000;")
    return conn


def ensure_update_unique_schema(
    conn: sqlite3.Connection,
    table_name: str,
) -> None:
    conn.execute(f'DROP INDEX IF EXISTS "ux_{table_name}_upd"')
    conn.execute(
        f'CREATE UNIQUE INDEX IF NOT EXISTS "ux_{table_name}_upd" ON "{table_name}"("台番号", "取得更新日")'
    )


def get_starting_sku_seq(
    conn: sqlite3.Connection,
    table_name: str,
    date_prefix: str,
) -> int:
    try:
        row = conn.execute(
            f'SELECT MAX(CAST(SUBSTR("SKU", 9, 4) AS INTEGER)) FROM "{table_name}" WHERE "SKU" LIKE ? AND LENGTH("SKU") = 12',
            (f"{date_prefix}%",),
        ).fetchone()
        return int(row[0]) + 1 if row and row[0] is not None else 1
    except sqlite3.Error as exc:
        print(f"[DB] SKU初期シーケンス取得失敗: {exc}。1から開始します")
        return 1


def insert_scraping_row(
    conn: sqlite3.Connection,
    table_name: str,
    row: dict[str, Any],
    today_schema: Mapping[str, str],
    history_pattern: re.Pattern[str],
) -> bool:
    machine_no = str(row.get("台番号") or "").strip()
    executed_at = str(row.get("実行日") or "").strip()
    if not machine_no or not executed_at:
        print("[DB] 台番号または実行日が空のため保存をスキップ")
        return False

    history_columns: list[str] = []
    for key in row:
        match = history_pattern.match(key)
        if match and 1 <= int(match.group(2)) <= 100:
            history_columns.append(key)
    history_columns.sort(key=lambda col: int(history_pattern.match(col).group(2)))

    for column in today_schema:
        row.setdefault(column, None)

    base_columns = [
        "pscubeURL", "取得更新日", "台番号", "機種名",
        "svgデータ", "SKU", "実行日",
        *today_schema.keys(),
    ]
    insert_columns = base_columns + history_columns
    update_date = row.get("取得更新日")

    if update_date not in (None, ""):
        exists = conn.execute(
            f'SELECT 1 FROM "{table_name}" WHERE "台番号"=? AND "取得更新日"=? LIMIT 1',
            (machine_no, update_date),
        ).fetchone()
        if exists:
            print(f"[DB] 既存データをスキップ: 台番号={machine_no}, 取得更新日={update_date}")
            return False

    column_sql = ", ".join(f'"{column}"' for column in insert_columns)
    placeholders = ", ".join("?" for _ in insert_columns)
    values = [row.get(column) for column in insert_columns]
    conn.execute(
        f'INSERT INTO "{table_name}" ({column_sql}) VALUES ({placeholders}) ON CONFLICT("台番号", "取得更新日") DO NOTHING',
        values,
    )
    return True
