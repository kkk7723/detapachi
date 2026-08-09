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

# 使う列（※カラムは既にDBに存在している前提）
cols = [
    "実行日", "台番号", "宵越し累計ゲーム数",
    "単発後天井設定値", "確変後天井設定値"
]

# 読み込み（新しい順）
with sqlite3.connect(db_path) as conn:
    df = pd.read_sql_query(f'''
        SELECT ROWID AS rowid, {", ".join([f"[{c}]" for c in cols])}
        FROM result_table
        ORDER BY ROWID DESC
    ''', conn)

if df.empty:
    print("❌ 対象データがありません")
    sys.exit(0)

# 型整備
df["実行日"] = pd.to_datetime(df["実行日"], errors="coerce")
df = df.dropna(subset=["実行日"]).copy()
for c in ["宵越し累計ゲーム数", "単発後天井設定値", "確変後天井設定値"]:
    df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0)

# 最新日だけ対象
max_date = df["実行日"].dt.date.max()
df_today = df[df["実行日"].dt.date == max_date].copy()
if df_today.empty:
    print("❌ 最新日データがありません")
    sys.exit(0)

# 残りゲーム数を計算（必要なら .clip(lower=0) を付けてもOK）
df_today["単発後天井残りゲーム数"] = df_today["単発後天井設定値"] - df_today["宵越し累計ゲーム数"]
df_today["確変後天井残りゲーム数"] = df_today["確変後天井設定値"] - df_today["宵越し累計ゲーム数"]
# 0未満を0にしたい場合は下記を有効化
# df_today["単発後天井残りゲーム数"] = df_today["単発後天井残りゲーム数"].clip(lower=0)
# df_today["確変後天井残りゲーム数"] = df_today["確変後天井残りゲーム数"].clip(lower=0)

# DB更新（最新日の該当行のみ）
update_sql = '''
UPDATE result_table
SET [単発後天井残りゲーム数] = ?,
    [確変後天井残りゲーム数] = ?
WHERE [台番号] = ?
  AND date([実行日]) = ?
'''
updated = 0
with sqlite3.connect(db_path) as conn:
    cur = conn.cursor()
    for _, r in df_today.iterrows():
        cur.execute(
            update_sql,
            (
                float(r["単発後天井残りゲーム数"]),
                float(r["確変後天井残りゲーム数"]),
                r["台番号"],
                str(max_date),
            )
        )
        updated += cur.rowcount
    conn.commit()

print(f"✅ 残りゲーム数 更新完了: {updated} 行（対象日: {max_date}）")
print(f"[INFO] 所要時間: {time.time() - start_time:.2f} 秒")


# In[ ]:




