#!/usr/bin/env python
# coding: utf-8

# In[2]:


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
    detaslotのプロジェクトルートとして返す。
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
        "detaslotのプロジェクトルートを"
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


db_path = Path(
    site_config.DB_PATH
)


print(f"[INFO] 対象店舗: {args.site}")
print(f"[INFO] 使用DB: {db_path}")
print(f"[INFO] 対象テーブル: {TABLE_NAME}")


# =========================================================
# 対象カラム
# =========================================================

SOURCE_COLUMNS = [
    "実行日",
    "台番号",
    "最終ゲーム",
]

DESTINATION_COLUMN = "前日最終ゲーム数"


# =========================================================
# SQLite共通
# =========================================================

def quote_identifier(
    identifier: str,
) -> str:
    """
    SQLiteのテーブル名・カラム名を
    []で安全に囲む。
    """
    return (
        "["
        + str(identifier).replace(
            "]",
            "]]",
        )
        + "]"
    )


def get_table_columns(
    connection: sqlite3.Connection,
    table_name: str,
) -> set[str]:
    """
    SQLiteテーブルに存在するカラム名を取得する。
    """
    cursor = connection.execute(
        f"PRAGMA table_info("
        f"{quote_identifier(table_name)}"
        f")"
    )

    return {
        str(row[1])
        for row in cursor.fetchall()
    }


def require_columns(
    existing_columns: set[str],
    required_columns: list[str],
) -> None:
    """
    必須カラムがDBに存在するか確認する。
    """
    missing_columns = [
        column
        for column in required_columns
        if column not in existing_columns
    ]

    if missing_columns:
        raise RuntimeError(
            f"{TABLE_NAME} に必要列がありません: "
            f"{missing_columns}"
        )


def normalize_machine_number(
    value: Any,
) -> str:
    """
    台番号を照合用形式へ統一する。

    例:
        32     -> "32"
        "0032" -> "32"
        32.0   -> "32"
        空欄   -> ""
    """
    if value is None:
        return ""

    try:
        if pd.isna(value):
            return ""
    except (
        TypeError,
        ValueError,
    ):
        pass

    text = str(value).strip()

    if not text:
        return ""

    try:
        number = float(text)

        if number.is_integer():
            return str(int(number))
    except ValueError:
        pass

    if text.isdigit():
        return str(int(text))

    return text


def clean_game_value(
    value: Any,
) -> int | None:
    """
    最終ゲーム数を整数へ変換する。

    空欄・NaN・変換不能値はNone。
    """
    if value is None:
        return None

    try:
        if pd.isna(value):
            return None
    except (
        TypeError,
        ValueError,
    ):
        pass

    text = str(value).strip()

    if not text:
        return None

    text = (
        text
        .replace(",", "")
        .replace("Ｇ", "")
        .replace("G", "")
        .strip()
    )

    try:
        return int(
            float(text)
        )
    except (
        TypeError,
        ValueError,
    ):
        return None


# =========================================================
# メイン処理
# =========================================================

def main() -> None:
    start_time = time.time()

    require_file(
        db_path,
        "店舗別SQLiteデータベース",
    )

    # -----------------------------------------------------
    # DBカラム確認
    # -----------------------------------------------------

    with sqlite3.connect(
        db_path
    ) as connection:
        table_columns = get_table_columns(
            connection,
            TABLE_NAME,
        )

    require_columns(
        table_columns,
        [
            *SOURCE_COLUMNS,
            DESTINATION_COLUMN,
        ],
    )

    print(
        f"[DB] 必須カラム確認完了: "
        f"{len(SOURCE_COLUMNS) + 1}列"
    )

    # -----------------------------------------------------
    # 必要データ取得
    # -----------------------------------------------------

    select_columns = ", ".join(
        quote_identifier(column)
        for column in SOURCE_COLUMNS
    )

    select_sql = f"""
        SELECT
            ROWID AS _rowid,
            {select_columns},
            {quote_identifier(DESTINATION_COLUMN)}
                AS current_value
        FROM {quote_identifier(TABLE_NAME)}
        WHERE
            {quote_identifier("実行日")} IS NOT NULL
            AND TRIM(
                CAST(
                    {quote_identifier("実行日")}
                    AS TEXT
                )
            ) <> ''
        ORDER BY
            datetime(
                {quote_identifier("実行日")}
            ) DESC,
            ROWID DESC
    """

    with sqlite3.connect(
        db_path
    ) as connection:
        dataframe = pd.read_sql_query(
            select_sql,
            connection,
        )

    if dataframe.empty:
        print(
            "[INFO] 対象データがありません。"
        )
        return

    print(
        f"[DB] 全データ件数: "
        f"{len(dataframe)}件"
    )

    # -----------------------------------------------------
    # 型整備
    # -----------------------------------------------------

    dataframe["実行日"] = pd.to_datetime(
        dataframe["実行日"],
        errors="coerce",
    )

    dataframe = dataframe.dropna(
        subset=[
            "実行日",
            "台番号",
        ],
    ).copy()

    dataframe[
        "照合用台番号"
    ] = dataframe[
        "台番号"
    ].map(
        normalize_machine_number
    )

    dataframe = dataframe[
        dataframe["照合用台番号"] != ""
    ].copy()

    if dataframe.empty:
        print(
            "[INFO] 有効な実行日・台番号を"
            "持つデータがありません。"
        )
        return

    dataframe[
        "最終ゲーム_数値"
    ] = dataframe[
        "最終ゲーム"
    ].map(
        clean_game_value
    )

    # -----------------------------------------------------
    # 最新日・前日
    # -----------------------------------------------------

    latest_date = (
        dataframe["実行日"]
        .dt.date
        .max()
    )

    previous_date = (
        pd.Timestamp(latest_date)
        - pd.Timedelta(days=1)
    ).date()

    print(
        f"[DB] 最新日: "
        f"{latest_date}"
    )
    print(
        f"[DB] 前日: "
        f"{previous_date}"
    )

    latest_date_dataframe = dataframe[
        dataframe["実行日"].dt.date
        == latest_date
    ].copy()

    previous_date_dataframe = dataframe[
        dataframe["実行日"].dt.date
        == previous_date
    ].copy()

    print(
        f"[DB] 最新日レコード: "
        f"{len(latest_date_dataframe)}件"
    )
    print(
        f"[DB] 前日レコード: "
        f"{len(previous_date_dataframe)}件"
    )

    if latest_date_dataframe.empty:
        print(
            "[ERROR] 最新日データがありません。"
        )
        return

    if previous_date_dataframe.empty:
        print(
            "[WARN] 前日データがありません。"
            "更新をスキップします。"
        )
        return

    # -----------------------------------------------------
    # 最新日の各台の最新1レコードを選択
    # -----------------------------------------------------

    latest_rows = (
        latest_date_dataframe
        .sort_values(
            [
                "照合用台番号",
                "実行日",
                "_rowid",
            ],
            ascending=[
                True,
                False,
                False,
            ],
        )
        .drop_duplicates(
            subset=[
                "照合用台番号"
            ],
            keep="first",
        )
        .copy()
    )

    print(
        f"[DB] 最新日の対象台数: "
        f"{len(latest_rows)}台"
    )

    # -----------------------------------------------------
    # 前日の各台の最新1レコードを選択
    # -----------------------------------------------------

    previous_latest_rows = (
        previous_date_dataframe
        .sort_values(
            [
                "照合用台番号",
                "実行日",
                "_rowid",
            ],
            ascending=[
                True,
                False,
                False,
            ],
        )
        .drop_duplicates(
            subset=[
                "照合用台番号"
            ],
            keep="first",
        )
        .copy()
    )

    previous_game_map: dict[
        str,
        int | None,
    ] = dict(
        zip(
            previous_latest_rows[
                "照合用台番号"
            ],
            previous_latest_rows[
                "最終ゲーム_数値"
            ],
        )
    )

    print(
        f"[DB] 前日最終ゲームマッピング: "
        f"{len(previous_game_map)}台"
    )

    # -----------------------------------------------------
    # 更新データ作成
    # -----------------------------------------------------

    update_parameters: list[
        tuple[
            int | None,
            int,
        ]
    ] = []

    missing_previous_count = 0
    unchanged_count = 0

    for _, row in latest_rows.iterrows():
        machine_number = str(
            row["照合用台番号"]
        ).strip()

        previous_game_raw = previous_game_map.get(
            machine_number
        )
        
        previous_game = clean_game_value(
            previous_game_raw
        )

        if previous_game is None:
            missing_previous_count += 1

            print(
                f"[SKIP] 台番号="
                f"{row['台番号']} "
                f"の前日最終ゲームがありません。"
            )
            continue

        current_value = clean_game_value(
            row["current_value"]
        )

        if current_value == previous_game:
            unchanged_count += 1

            print(
                f"[NO CHANGE] 台番号="
                f"{row['台番号']}, "
                f"前日最終={previous_game}"
            )
            continue

        update_parameters.append((
            int(previous_game),
            int(row["_rowid"]),
        ))

        print(
            f"[UPDATE準備] 台番号="
            f"{row['台番号']}, "
            f"ROWID={row['_rowid']}, "
            f"旧値={current_value!r}, "
            f"新値={previous_game}"
        )

    print(
        f"[DB] 更新対象: "
        f"{len(update_parameters)}件"
    )
    print(
        f"[DB] 変更なし: "
        f"{unchanged_count}件"
    )
    print(
        f"[DB] 前日データなし: "
        f"{missing_previous_count}台"
    )

    # -----------------------------------------------------
    # ROWID単位で更新
    # -----------------------------------------------------

    update_sql = f"""
        UPDATE {quote_identifier(TABLE_NAME)}
        SET
            {quote_identifier(DESTINATION_COLUMN)}
            = ?
        WHERE
            ROWID = ?
    """

    updated_count = 0

    if update_parameters:
        with sqlite3.connect(
            db_path
        ) as connection:
            cursor = connection.cursor()

            cursor.executemany(
                update_sql,
                update_parameters,
            )

            connection.commit()

            updated_count = len(
                update_parameters
            )

    # -----------------------------------------------------
    # 完了
    # -----------------------------------------------------

    print(
        "✅ 最新日 前日最終ゲーム数列 "
        f"更新完了: {updated_count}件"
    )
    print(
        f"[DB] 更新対象日: "
        f"{latest_date}"
    )
    print(
        f"[DB] 参照日: "
        f"{previous_date}"
    )
    print(
        f"[INFO] 所要時間: "
        f"{time.time() - start_time:.1f}秒"
    )


# =========================================================
# 実行
# =========================================================

if __name__ == "__main__":
    main()


# In[ ]:




