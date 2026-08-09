#!/usr/bin/env python
# coding: utf-8

# In[1]:


from __future__ import annotations

import argparse
import importlib
import sys
import time
from pathlib import Path
from typing import Any

import pandas as pd


# =========================================================
# プロジェクトルート設定
# =========================================================

def find_project_root(start_path: Path) -> Path:
    """
    config/ と utils/ が存在するディレクトリを
    プロジェクトルートとして返す。
    """
    current = start_path.resolve()

    if current.is_file():
        current = current.parent

    for candidate in [current, *current.parents]:
        if (
            (candidate / "config").is_dir()
            and (candidate / "utils").is_dir()
        ):
            return candidate

    raise RuntimeError(
        "detaslotのプロジェクトルートを特定できませんでした。"
        f" 開始位置: {start_path}"
    )


if "__file__" in globals():
    # scripts/database/*.py から実行する場合
    PROJECT_ROOT = find_project_root(Path(__file__))
else:
    # scripts/database/*.ipynb などNotebookから実行する場合
    PROJECT_ROOT = find_project_root(Path.cwd())


if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


print(f"[INFO] PROJECT_ROOT: {PROJECT_ROOT}")
print(
    f"[INFO] config存在: "
    f"{(PROJECT_ROOT / 'config').is_dir()}"
)
print(
    f"[INFO] utils存在: "
    f"{(PROJECT_ROOT / 'utils').is_dir()}"
)


# =========================================================
# プロジェクト共通モジュール
# =========================================================

from config.common import (
    DEFAULT_SITE,
    GOOGLE_CREDENTIALS_FILE,
    GOOGLE_SCOPES,
    TABLE_NAME,
    require_file,
)

from utils.sheet_utils import open_worksheet


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


site_config = importlib.import_module(
    f"config.{args.site}"
)

print(f"対象店舗: {args.site}")

# =========================================================
# 店舗別設定
# =========================================================

required_site_settings = (
    "DB_PATH",
    "GSHEET_NAME",
    "SHEET_NAME",
)

for setting_name in required_site_settings:
    if not hasattr(site_config, setting_name):
        raise AttributeError(
            f"config/{args.site}.py に "
            f"{setting_name} が設定されていません。"
        )


db_path = Path(site_config.DB_PATH)
spreadsheet_name = site_config.GSHEET_NAME
worksheet_name = site_config.SHEET_NAME

start_time = time.time()


# =========================================================
# 設定値
# =========================================================

# スプレッドシートの台番号列
MACHINE_NUMBER_RANGE = "B4:B500"

# 機種名を書き込む開始セル
MACHINE_NAME_COLUMN = "E"
MACHINE_NAME_START_ROW = 4

# DBから取得するカラム
DB_COLUMNS = [
    "実行日",
    "台番号",
    "機種名",
]


# =========================================================
# 共通関数
# =========================================================

def quote_identifier(identifier: str) -> str:
    """
    SQLiteの識別子を安全に[]で囲む。
    """
    return (
        "["
        + str(identifier).replace("]", "]]")
        + "]"
    )


def normalize_machine_number(
    value: Any,
) -> str:
    """
    台番号を照合用の形式へ統一する。

    例:
        32      -> "32"
        "0032"  -> "32"
        32.0    -> "32"
        "32.0"  -> "32"
        空欄    -> ""

    DB側が0032、シート側が32でも一致する。
    """
    if value is None:
        return ""

    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass

    text = str(value).strip()

    if not text:
        return ""

    # Excelやpandas経由の "32.0" を処理
    try:
        number = float(text)

        if number.is_integer():
            return str(int(number))
    except ValueError:
        pass

    # 数字だけなら先頭ゼロを除去
    if text.isdigit():
        return str(int(text))

    return text


def normalize_machine_name(
    value: Any,
) -> str:
    """
    機種名をスプレッドシート書き込み用文字列へ変換する。
    """
    if value is None:
        return ""

    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass

    return str(value).strip()


# =========================================================
# 必須ファイル・DB確認
# =========================================================

require_file(
    GOOGLE_CREDENTIALS_FILE,
    "GoogleサービスアカウントJSON",
)

require_file(
    db_path,
    "店舗別SQLiteデータベース",
)

print(f"[INFO] 使用DB: {db_path}")
print(
    f"[INFO] スプレッドシート: "
    f"{spreadsheet_name} / {worksheet_name}"
)


# =========================================================
# Google Sheets接続
# =========================================================

worksheet = open_worksheet(
    credentials_file=GOOGLE_CREDENTIALS_FILE,
    scopes=GOOGLE_SCOPES,
    spreadsheet_name=spreadsheet_name,
    worksheet_name=worksheet_name,
)

print(
    "[SHEET] Googleスプレッドシート認証・"
    "ワークシート取得完了"
)


# =========================================================
# DBから必要データ取得
# =========================================================

select_columns = ", ".join(
    quote_identifier(column)
    for column in DB_COLUMNS
)

sql = f"""
    SELECT
        {select_columns}
    FROM {quote_identifier(TABLE_NAME)}
    ORDER BY ROWID DESC
"""

import sqlite3

with sqlite3.connect(db_path) as conn:
    df = pd.read_sql_query(
        sql,
        conn,
    )

print(
    f"[DB] データ取得完了: "
    f"{len(df)}件"
)


# =========================================================
# 最新実行日のデータだけを抽出
# =========================================================

if df.empty:
    raise RuntimeError(
        f"{TABLE_NAME} にデータがありません。"
    )


df["実行日"] = pd.to_datetime(
    df["実行日"],
    errors="coerce",
)

df = df.dropna(
    subset=["実行日"],
).copy()

if df.empty:
    raise RuntimeError(
        "有効な実行日を持つDBデータがありません。"
    )


latest_date = df["実行日"].dt.date.max()

df_latest = (
    df[
        df["実行日"].dt.date
        == latest_date
    ]
    .sort_values(
        "実行日",
        ascending=False,
    )
    .drop_duplicates(
        subset=["台番号"],
        keep="first",
    )
    .copy()
)

print(
    f"[DB] 最新日: {latest_date}"
)
print(
    f"[DB] 最新日の台数: "
    f"{len(df_latest)}件"
)


# =========================================================
# スプレッドシートから台番号を取得
# =========================================================

try:
    machine_number_rows = worksheet.get(
        MACHINE_NUMBER_RANGE
    )
except Exception as exc:
    raise RuntimeError(
        "[SHEET] 台番号取得失敗: "
        f"{exc}"
    ) from exc


sheet_machine_numbers: list[str] = []

for row in machine_number_rows:
    raw_value = (
        row[0]
        if row and len(row) > 0
        else ""
    )

    sheet_machine_numbers.append(
        normalize_machine_number(
            raw_value
        )
    )


print(
    f"[SHEET] 台番号取得完了: "
    f"{len(sheet_machine_numbers)}行"
)


# =========================================================
# DBの台番号 → 機種名マッピング作成
# =========================================================

df_latest["照合用台番号"] = (
    df_latest["台番号"]
    .map(normalize_machine_number)
)

df_latest["機種名"] = (
    df_latest["機種名"]
    .map(normalize_machine_name)
)

# 台番号が空欄のDBデータは除外
df_latest = df_latest[
    df_latest["照合用台番号"] != ""
].copy()


machine_map = dict(
    zip(
        df_latest["照合用台番号"],
        df_latest["機種名"],
    )
)


print(
    f"[DB] 台番号→機種名マッピング作成完了: "
    f"{len(machine_map)}件"
)


# =========================================================
# 書き込み用データ作成
# =========================================================

machine_names: list[list[str]] = []

matched_count = 0
unmatched_numbers: list[str] = []

for machine_number in sheet_machine_numbers:
    if not machine_number:
        machine_names.append([""])
        continue

    machine_name = machine_map.get(
        machine_number,
        "",
    )

    machine_names.append([
        machine_name
    ])

    if machine_name:
        matched_count += 1
    else:
        unmatched_numbers.append(
            machine_number
        )


print(
    f"[MATCH] 一致: "
    f"{matched_count}件"
)
print(
    f"[MATCH] 不一致: "
    f"{len(unmatched_numbers)}件"
)

if unmatched_numbers:
    print(
        "[MATCH] 不一致台番号: "
        + ", ".join(unmatched_numbers)
    )


# =========================================================
# スプレッドシートへ一括書き込み
# =========================================================

if not machine_names:
    print(
        "[WARN] 書き込み対象がないため、"
        "スプレッドシート更新をスキップします。"
    )
else:
    end_row = (
        MACHINE_NAME_START_ROW
        + len(machine_names)
        - 1
    )

    target_range = (
        f"{MACHINE_NAME_COLUMN}"
        f"{MACHINE_NAME_START_ROW}:"
        f"{MACHINE_NAME_COLUMN}"
        f"{end_row}"
    )

    try:
        worksheet.update(
            range_name=target_range,
            values=machine_names,
        )
    except Exception as exc:
        raise RuntimeError(
            "[SHEET] 機種名書き込み失敗: "
            f"{exc}"
        ) from exc

    print(
        f"[SHEET] 機種名書き込み完了: "
        f"{target_range}"
    )
    print(
        f"[SHEET] 書き込み行数: "
        f"{len(machine_names)}件"
    )


# =========================================================
# 完了
# =========================================================

elapsed_time = time.time() - start_time

print(
    f"[INFO] 処理完了: "
    f"{elapsed_time:.2f}秒"
)


# In[ ]:




