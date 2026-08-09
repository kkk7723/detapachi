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

def find_project_root(start_path: Path) -> Path:
    """
    config/、utils/、scripts/ が存在する場所を
    プロジェクトルートとして返す。
    """
    current = start_path.resolve()

    if current.is_file():
        current = current.parent

    for candidate in [current, *current.parents]:
        if (
            (candidate / "config").is_dir()
            and (candidate / "utils").is_dir()
            and (candidate / "scripts").is_dir()
        ):
            return candidate

    raise RuntimeError(
        "detaslotのプロジェクトルートを"
        f"特定できませんでした: {start_path}"
    )


if "__file__" in globals():
    # .py実行時
    PROJECT_ROOT = find_project_root(
        Path(__file__)
    )
else:
    # Notebook実行時
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


# SITE_PUBLIC_BASE_URLがあれば優先
public_base_url = str(
    getattr(
        site_config,
        "SITE_PUBLIC_BASE_URL",
        f"https://sedoinfinity.xsrv.jp/{args.site}",
    )
).rstrip("/")


machine_base_url = (
    f"{public_base_url}/machines"
)


print(f"[INFO] 対象店舗: {args.site}")
print(f"[INFO] 使用DB: {db_path}")
print(f"[INFO] 対象テーブル: {TABLE_NAME}")
print(
    f"[INFO] 台番号URL基準: "
    f"{machine_base_url}"
)


# =========================================================
# SQLite共通
# =========================================================

def quote_identifier(
    identifier: str,
) -> str:
    """
    SQLiteの識別子を[]で囲む。
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
    テーブルに存在するカラム名を取得する。
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


# =========================================================
# 台番号整形
# =========================================================

def normalize_machine_number(
    value: Any,
) -> str:
    """
    URLファイル名用に台番号を整形する。

    例:
        32     -> "32"
        "0032" -> "32"
        32.0   -> "32"
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
            return str(
                int(number)
            )
    except ValueError:
        pass

    return text


def make_machine_url(
    machine_number: Any,
) -> str | None:
    """
    台番号詳細ページのURLを作成する。

    現在のページ構成:
        /machines/32.html
    """
    normalized = normalize_machine_number(
        machine_number
    )

    if not normalized:
        return None

    return (
        f"{machine_base_url}/"
        f"{normalized}.html"
    )


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
    # カラム確認
    # -----------------------------------------------------

    with sqlite3.connect(
        db_path
    ) as connection:
        table_columns = get_table_columns(
            connection,
            TABLE_NAME,
        )

    required_columns = [
        "実行日",
        "SKU",
        "台番号",
        "台番号URL",
    ]

    missing_columns = [
        column
        for column in required_columns
        if column not in table_columns
    ]

    if missing_columns:
        raise RuntimeError(
            f"{TABLE_NAME} に必要列がありません: "
            f"{missing_columns}"
        )

    print(
        "[DB] 必須カラム確認完了"
    )

    # -----------------------------------------------------
    # DB内の最新日取得
    # -----------------------------------------------------

    latest_date_sql = f"""
        SELECT
            MAX(
                date(
                    {quote_identifier("実行日")}
                )
            )
        FROM {quote_identifier(TABLE_NAME)}
        WHERE
            {quote_identifier("実行日")}
            IS NOT NULL
            AND TRIM(
                CAST(
                    {quote_identifier("実行日")}
                    AS TEXT
                )
            ) <> ''
    """

    with sqlite3.connect(
        db_path
    ) as connection:
        latest_date_row = connection.execute(
            latest_date_sql
        ).fetchone()

    latest_date = (
        latest_date_row[0]
        if latest_date_row
        else None
    )

    if not latest_date:
        print(
            "[INFO] 有効な実行日データがありません。"
        )
        return

    print(
        f"[DB] 最新日: "
        f"{latest_date}"
    )

    # -----------------------------------------------------
    # 最新日のレコード取得
    # -----------------------------------------------------

    select_sql = f"""
        SELECT
            ROWID AS _rowid,
            {quote_identifier("実行日")},
            {quote_identifier("SKU")},
            {quote_identifier("台番号")},
            {quote_identifier("台番号URL")}
                AS current_url
        FROM {quote_identifier(TABLE_NAME)}
        WHERE
            date(
                {quote_identifier("実行日")}
            ) = ?
        ORDER BY ROWID ASC
    """

    with sqlite3.connect(
        db_path
    ) as connection:
        dataframe = pd.read_sql_query(
            select_sql,
            connection,
            params=[
                latest_date,
            ],
        )

    if dataframe.empty:
        print(
            "[INFO] 最新日の対象データが"
            "ありません。"
        )
        return

    print(
        f"[DB] 対象レコード: "
        f"{len(dataframe)}件"
    )

    # -----------------------------------------------------
    # URL生成
    # -----------------------------------------------------

    dataframe[
        "new_url"
    ] = dataframe[
        "台番号"
    ].map(
        make_machine_url
    )

    generated_count = int(
        dataframe["new_url"]
        .notna()
        .sum()
    )

    print(
        f"[URL] 生成成功: "
        f"{generated_count}件"
    )

    # -----------------------------------------------------
    # 更新対象抽出
    # -----------------------------------------------------

    update_parameters: list[
        tuple[
            str | None,
            int,
        ]
    ] = []

    unchanged_count = 0
    invalid_count = 0

    for _, row in dataframe.iterrows():
        new_url = row["new_url"]

        current_url = (
            ""
            if pd.isna(row["current_url"])
            else str(
                row["current_url"]
            ).strip()
        )

        if not new_url:
            invalid_count += 1

            print(
                f"[SKIP] 台番号不正: "
                f"{row['台番号']!r}"
            )
            continue

        if current_url == new_url:
            unchanged_count += 1
            continue

        update_parameters.append((
            new_url,
            int(row["_rowid"]),
        ))

        print(
            f"[UPDATE準備] "
            f"台番号={row['台番号']}, "
            f"SKU={row['SKU']}, "
            f"URL={new_url}"
        )

    print(
        f"[DB] 変更なし: "
        f"{unchanged_count}件"
    )
    print(
        f"[DB] 台番号不正: "
        f"{invalid_count}件"
    )
    print(
        f"[DB] 更新対象: "
        f"{len(update_parameters)}件"
    )

    # -----------------------------------------------------
    # ROWID単位で更新
    # -----------------------------------------------------

    update_sql = f"""
        UPDATE {quote_identifier(TABLE_NAME)}
        SET
            {quote_identifier("台番号URL")}
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

    print(
        f"✅ 台番号URL更新完了: "
        f"{updated_count}件"
    )
    print(
        f"[DB] 対象日: "
        f"{latest_date}"
    )
    print(
        f"[INFO] 所要時間: "
        f"{time.time() - start_time:.2f}秒"
    )


# =========================================================
# 実行
# =========================================================

if __name__ == "__main__":
    main()


# In[ ]:




