#!/usr/bin/env python
# coding: utf-8

# In[2]:


from __future__ import annotations
import argparse
import importlib
import sqlite3
import sys
import numpy as np
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

# 必須列
BASE_NEEDED = ["実行日", "台番号"]
SRC_COLS = ["初当り確率", "初当り回数"]
TARGET_COL = "累計通常ゲーム数初当り確率"

with sqlite3.connect(db_path) as conn:
    pragma = pd.read_sql_query("PRAGMA table_info(result_table);", conn)
    table_cols = set(pragma["name"].tolist())

    missing = [c for c in (BASE_NEEDED + SRC_COLS + [TARGET_COL]) if c not in table_cols]
    if missing:
        raise RuntimeError(f"result_table に必要列がありません: {missing}")

    # 最新日付判定用
    df_basic = pd.read_sql_query(
        '''
        SELECT ROWID AS rowid, [実行日], [台番号]
          FROM result_table
        ''',
        conn
    )

# 日付整備
df_basic["実行日"] = pd.to_datetime(df_basic["実行日"], errors="coerce")
df_basic = df_basic.dropna(subset=["実行日"])

# 最新日付
max_date = df_basic["実行日"].dt.date.max()

# 各台の最新行 rowid
latest_rowid_by_tai = (
    df_basic[df_basic["実行日"].dt.date == max_date]
      .sort_values(["台番号", "実行日", "rowid"], ascending=[True, False, False])
      .groupby("台番号", as_index=False)
      .agg(latest_rowid=("rowid", "max"))
)

# 当日分の必要列取得
select_cols = ["ROWID AS rowid"] + BASE_NEEDED + SRC_COLS + [TARGET_COL]
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

# 最新行のみ
df_latest = df_today[df_today["rowid"].isin(latest_rowid_by_tai["latest_rowid"])].copy()

# 数値化（DBは既に数値前提だが、安全のため）
df_latest["初当り確率"] = pd.to_numeric(df_latest["初当り確率"], errors="coerce")
df_latest["初当り回数"] = pd.to_numeric(df_latest["初当り回数"], errors="coerce")

# 計算： 累計通常ゲーム数初当り確率 = 初当り確率 × 初当り回数
result = np.where(~df_latest["初当り確率"].isna() & ~df_latest["初当り回数"].isna(),
                  df_latest["初当り確率"].values * df_latest["初当り回数"].values,
                  np.nan)

# 必要に応じて丸め（例：整数化するなら .round(0).astype("Int64")）
df_latest[TARGET_COL] = pd.to_numeric(result, errors="coerce")

# DB更新
updated = 0
with sqlite3.connect(db_path) as conn:
    cur = conn.cursor()
    for _, r in df_latest.iterrows():
        val = r[TARGET_COL]
        cur.execute(
            f'''
            UPDATE result_table
               SET [{TARGET_COL}] = ?
             WHERE ROWID = ?
               AND date([実行日]) = ?
            ''',
            (None if pd.isna(val) else float(val), int(r["rowid"]), str(max_date))
        )
        updated += cur.rowcount
    conn.commit()

print(f"✅ {TARGET_COL} 更新完了: {updated} 行（最新日付・各台の最新行のみ）")
print(f"[INFO] 所要時間: {time.time() - start_time:.2f} 秒")


# In[ ]:




