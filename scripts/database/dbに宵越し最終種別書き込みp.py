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

# 必須列
NEEDED = ["実行日", "台番号", "大当り回数", "ステータス1回前"]

with sqlite3.connect(db_path) as conn:
    # 列チェック
    pragma = pd.read_sql_query("PRAGMA table_info(result_table);", conn)
    table_cols = set(pragma["name"].tolist())
    missing = [c for c in NEEDED if c not in table_cols]
    if missing:
        raise RuntimeError(f"result_table に必要列がありません: {missing}")

    # 取得（rowidも持っておく）
    df = pd.read_sql_query(
        f'''
        SELECT ROWID AS rowid, {", ".join([f"[{c}]" for c in NEEDED])}
          FROM result_table
        ''',
        conn
    )

# 型整備
df["実行日"] = pd.to_datetime(df["実行日"], errors="coerce")
df = df.dropna(subset=["実行日"])
df["大当り回数"] = pd.to_numeric(df["大当り回数"], errors="coerce").fillna(0).astype(int)

# 当日（テーブル内の最新“日付”）
max_date = df["実行日"].dt.date.max()
df_today = df[df["実行日"].dt.date == max_date].copy()

# 当日の各台の「最新行のrowid」（更新対象はこの1件のみ）
latest_rowid_by_tai = (
    df_today.sort_values(["台番号", "実行日", "rowid"], ascending=[True, False, False])
            .groupby("台番号", as_index=False)
            .agg(latest_rowid=("rowid", "max"))
)

def pick_prev_status_first_hit(group: pd.DataFrame):
    """
    グループ（1台分）を 最新→過去 になるように並べ、
    大当り回数>=1 が「最初に」出た行の `ステータス1回前` を返す。
    """
    # 厳密に最新→過去へ：実行日降順、同一時刻ならrowid降順
    g = group.sort_values(["実行日", "rowid"], ascending=[False, False]).reset_index(drop=True)
    hit_idx = g.index[g["大当り回数"] >= 1]
    if len(hit_idx) == 0:
        return None
    i = int(hit_idx[0])
    val = g.at[i, "ステータス1回前"]
    return (str(val).strip() if pd.notna(val) and str(val).strip() != "" else None)

# 台番号ごとに算出
calc_rows = []
for tainum, group in df.groupby("台番号", sort=False):
    prev_status = pick_prev_status_first_hit(group)
    calc_rows.append({"台番号": tainum, "宵越し最終ステータス": prev_status})

res_df = pd.DataFrame(calc_rows)

# 当日の最新行にだけマージ
update_df = latest_rowid_by_tai.merge(res_df, on="台番号", how="left")

# DB更新（当日・各台の最新行のみを更新）
updated = 0
with sqlite3.connect(db_path) as conn:
    cur = conn.cursor()
    for _, r in update_df.iterrows():
        cur.execute(
            '''
            UPDATE result_table
               SET [宵越し最終ステータス] = ?
             WHERE ROWID = ?
               AND date([実行日]) = ?
            ''',
            (r["宵越し最終ステータス"], int(r["latest_rowid"]), str(max_date))
        )
        updated += cur.rowcount
    conn.commit()

print(f"✅ 宵越し最終ステータス 更新完了: {updated} 行（当日各台の最新行のみ）")
print(f"[INFO] 所要時間: {time.time() - start_time:.2f} 秒")
