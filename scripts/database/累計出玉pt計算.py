#!/usr/bin/env python
# coding: utf-8

# In[2]:


from __future__ import annotations
import argparse
import importlib
import sqlite3
import numpy as np
import sys
import time
from pathlib import Path
from typing import Any
import pandas as pd

# =========================================================
# プロジェクトルート設定
# =========================================================

def find_project_root(
    start_path: Path,
) -> Path:
    """
    config/ と utils/ が存在するディレクトリを
    detapachiのプロジェクトルートとして返す。
    """
    current = start_path.resolve()

    if current.is_file():
        current = current.parent

    for candidate in [
        current,
        *current.parents,
    ]:
        if (
            (candidate / "config").is_dir()
            and (candidate / "utils").is_dir()
        ):
            return candidate

    raise RuntimeError(
        "detapachiのプロジェクトルートを"
        "特定できませんでした。"
        f" 開始位置: {start_path}"
    )


if "__file__" in globals():
    # scripts/database/*.py から実行
    PROJECT_ROOT = find_project_root(
        Path(__file__)
    )
else:
    # scripts/database/*.ipynb から実行
    PROJECT_ROOT = find_project_root(
        Path.cwd()
    )


if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(
        0,
        str(PROJECT_ROOT),
    )


print(
    f"[INFO] PROJECT_ROOT: "
    f"{PROJECT_ROOT}"
)
print(
    f"[INFO] config存在: "
    f"{(PROJECT_ROOT / 'config').is_dir()}"
)
print(
    f"[INFO] utils存在: "
    f"{(PROJECT_ROOT / 'utils').is_dir()}"
)


# =========================================================
# 共通設定
# =========================================================

from config.common import (
    DEFAULT_SITE,
    TABLE_NAME,
    require_file,
)

start_time = time.time()

# ==================================================
# 店舗選択
# ==================================================

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--site",
        default=DEFAULT_SITE,
        help="config名",
    )

    return parser.parse_args()


if "__file__" in globals():
    # .py実行時
    # --site指定があればそれを使用し、
    # 指定がなければDEFAULT_SITEを使用
    args = parse_args()
else:
    # Notebook実行時
    args = argparse.Namespace(
        site=DEFAULT_SITE,
    )


config_file = (
    PROJECT_ROOT
    / "config"
    / f"{args.site}.py"
)

if not config_file.is_file():
    raise FileNotFoundError(
        f"店舗設定が見つかりません: {config_file}"
    )



try:
    site_config = importlib.import_module(
        f"config.{args.site}"
    )
except ModuleNotFoundError as exc:
    raise SystemExit(
        f"[ERROR] 店舗設定が見つかりません: "
        f"config/{args.site}.py"
    ) from exc


if not hasattr(site_config, "DB_PATH"):
    raise AttributeError(
        f"config/{args.site}.py に "
        "DB_PATH が設定されていません。"
    )


db_path = Path(site_config.DB_PATH)

print(f"[INFO] 対象店舗: {args.site}")
print(f"[INFO] 使用DB: {db_path}")
print(f"[INFO] 対象テーブル: {TABLE_NAME}")

# =========================================================
# カラム定義
# =========================================================

# === 必須基本列 ===
BASE_NEEDED = ["実行日", "台番号", "大当り回数"]  # 大当り回数は未使用でも残置OK（既存コード互換）

with sqlite3.connect(db_path) as conn:
    # テーブル列一覧
    pragma = pd.read_sql_query("PRAGMA table_info(result_table);", conn)
    table_cols = set(pragma["name"].tolist())

    # 基本列チェック
    missing = [c for c in BASE_NEEDED if c not in table_cols]
    if missing:
        raise RuntimeError(f"result_table に必要列がありません: {missing}")

    # 出玉pt1〜100回前（存在する列だけ）
    pt_cols = [f"出玉pt{i}回前" for i in range(1, 101) if f"出玉pt{i}回前" in table_cols]
    if not pt_cols:
        raise RuntimeError("評価対象の『出玉ptX回前』列が1つも見つかりません。")

    # 書き込み先
    target_col = "累計出玉pt"
    if target_col not in table_cols:
        raise RuntimeError(f"書き込み先カラム '{target_col}' が result_table に存在しません。")

    # 本日データの取得（まず日付判定のため基本列だけ読む）
    df_basic = pd.read_sql_query(
        f'''
        SELECT ROWID AS rowid, {", ".join([f"[{c}]" for c in BASE_NEEDED])}
          FROM result_table
        ''',
        conn
    )

# 型整備
df_basic["実行日"] = pd.to_datetime(df_basic["実行日"], errors="coerce")
df_basic = df_basic.dropna(subset=["実行日"])

# 当日（テーブル内の最新“日付”）
max_date = df_basic["実行日"].dt.date.max()
df_today_basic = df_basic[df_basic["実行日"].dt.date == max_date].copy()

# 当日の各台の最新行rowid
latest_rowid_by_tai = (
    df_today_basic.sort_values(["台番号", "実行日", "rowid"], ascending=[True, False, False])
                  .groupby("台番号", as_index=False)
                  .agg(latest_rowid=("rowid", "max"))
)

# --- 更新に必要な列だけで当日分を再取得（出玉pt列＋書き込み先含む） ---
select_cols = ["ROWID AS rowid"] + BASE_NEEDED + pt_cols + [target_col]
select_cols_sql = ", ".join([c if c.startswith("ROWID") else f"[{c}]" for c in select_cols])

with sqlite3.connect(db_path) as conn:
    df_today = pd.read_sql_query(
        f'''
        SELECT {select_cols_sql}
          FROM result_table
         WHERE date([実行日]) = ?
        ''',
        conn,
        params=(str(max_date),)
    )

# 当日の各台「最新行」のみ
df_latest = df_today[df_today["rowid"].isin(latest_rowid_by_tai["latest_rowid"])].copy()

# 出玉pt列を数値化して合計
df_latest[pt_cols] = df_latest[pt_cols].apply(pd.to_numeric, errors="coerce").fillna(0)
df_latest[target_col] = df_latest[pt_cols].sum(axis=1).astype(int)

# DB更新（当日・各台の最新行のみ）
updated = 0
with sqlite3.connect(db_path) as conn:
    cur = conn.cursor()
    for _, r in df_latest.iterrows():
        cur.execute(
            f'''
            UPDATE result_table
               SET [{target_col}] = ?
             WHERE ROWID = ?
               AND date([実行日]) = ?
            ''',
            (int(r[target_col]), int(r["rowid"]), str(max_date))
        )
        updated += cur.rowcount
    conn.commit()

print(f"✅ 累計出玉pt 更新完了: {updated} 行（当日各台の最新行のみ）")
print(f"[INFO] 所要時間: {time.time() - start_time:.2f} 秒")


# In[ ]:





# In[ ]:




