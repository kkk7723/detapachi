#!/usr/bin/env python
# coding: utf-8

# In[1]:


from __future__ import annotations

import argparse
import importlib
import sqlite3
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
# 共通設定
# =========================================================
start_time = time.time()


# 宵越し対象カラム（確変は不要に）
columns_for_db = ["実行日", "台番号", "大当り回数", "最終スタート"]

# データ読み込み
with sqlite3.connect(db_path) as conn:
    df = pd.read_sql_query(f'''
        SELECT {", ".join([f"[{col}]" for col in columns_for_db])}
        FROM result_table
        ORDER BY ROWID DESC
    ''', conn)

# 日付変換と最新日抽出
df["実行日"] = pd.to_datetime(df["実行日"], errors='coerce')
df = df.dropna(subset=["実行日"])
max_date = df["実行日"].dt.date.max()
df_today = df[df["実行日"].dt.date == max_date].copy()

# 宵越し累計計算関数（大当り回数 >= 1 が初めて出る行まで）
def calc_start_sum(sub_df: pd.DataFrame) -> float:
    sub_df = sub_df.copy()
    sub_df["大当り回数"] = pd.to_numeric(sub_df["大当り回数"], errors='coerce').fillna(0)
    sub_df["最終スタート"] = pd.to_numeric(sub_df["最終スタート"], errors='coerce').fillna(0)

    # ORDER BY ROWID DESC の想定：最新→過去の順
    cutoff_idx = sub_df[(sub_df["大当り回数"] >= 1)].index.min()
    cutoff_df = sub_df if pd.isna(cutoff_idx) else sub_df.loc[:cutoff_idx]
    return float(cutoff_df["最終スタート"].sum())

# 台番号ごとに集計
start_sums = []
for tainum, group in df.groupby("台番号"):
    start_sum = calc_start_sum(group)
    start_sums.append({"台番号": tainum, "宵越し累計ゲーム数": start_sum})

start_sums_df = pd.DataFrame(start_sums)

# 最新日データにマージ（台番号キー）
df_today = pd.merge(df_today[["実行日", "台番号"]], start_sums_df, on="台番号", how="left")

# DB更新（最新日だけを更新）
with sqlite3.connect(db_path) as conn:
    cur = conn.cursor()

    for _, row in df_today.iterrows():
        cur.execute(
            f'''
            UPDATE [{TABLE_NAME}]
            SET [宵越し累計ゲーム数] = ?
            WHERE [台番号] = ?
              AND date([実行日]) = ?
            ''',
            (
                row["宵越し累計ゲーム数"],
                row["台番号"],
                row["実行日"].strftime(
                    "%Y-%m-%d"
                ),
            ),
        )

    conn.commit()

print(
    f"✅ 宵越し累計ゲーム数更新完了: "
    f"{len(df_today)} 件"
    "（条件: 大当り回数>=1の初出行まで）"
)

print(
    f"[INFO] 所要時間: "
    f"{time.time() - start_time:.1f}秒"
)


# In[ ]:




