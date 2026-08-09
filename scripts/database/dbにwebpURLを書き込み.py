#!/usr/bin/env python
# coding: utf-8

# In[1]:


from __future__ import annotations

import argparse
import importlib
import sqlite3
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd


# =========================================================
# プロジェクトルート設定
# =========================================================

def find_project_root(start_path: Path) -> Path:
    """
    config/ と utils/ が存在するディレクトリを
    detaslotのプロジェクトルートとして返す。
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
        "detaslotのプロジェクトルートを特定できません。"
        f" 開始位置: {start_path}"
    )


if "__file__" in globals():
    PROJECT_ROOT = find_project_root(
        Path(__file__)
    )
else:
    PROJECT_ROOT = find_project_root(
        Path.cwd()
    )


if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(
        0,
        str(PROJECT_ROOT),
    )


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
# 共通設定
# =========================================================

from config.common import (
    DEFAULT_SITE,
    TABLE_NAME,
    require_directory,
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


required_site_settings = (
    "DB_PATH",
    "SITE_OUTPUT_DIR",
    "SITE_PUBLIC_BASE_URL",
    "SCREENSHOT_DB_COLUMNS",
)

for setting_name in required_site_settings:
    if not hasattr(site_config, setting_name):
        raise AttributeError(
            f"config/{args.site}.py に "
            f"{setting_name} が設定されていません。"
        )


db_path = Path(site_config.DB_PATH)
output_root = Path(
    site_config.SITE_OUTPUT_DIR
)

public_base_url = str(
    site_config.SITE_PUBLIC_BASE_URL
).rstrip("/")

screenshot_db_columns: dict[str, str] = dict(
    site_config.SCREENSHOT_DB_COLUMNS
)


print(f"[INFO] 対象店舗: {args.site}")
print(f"[INFO] 使用DB: {db_path}")
print(
    f"[INFO] 公開URL基準: "
    f"{public_base_url}"
)


# =========================================================
# 日付設定
# =========================================================

start_time = time.time()
now = datetime.now()

# スクリーンショット側と同じ日付
image_date = (
    now - timedelta(days=1)
).strftime("%Y%m%d")

# スクレイピング実行日のDBレコード
execution_date = now.strftime(
    "%Y-%m-%d"
)


# =========================================================
# 画像パス
# =========================================================

webp_dir = (
    output_root
    / "img"
    / image_date
    / "webp"
)

public_webp_base_url = (
    f"{public_base_url}"
    f"/img/{image_date}/webp"
)


print(
    f"[INFO] DBフィルタ日: "
    f"{execution_date}"
)
print(
    f"[INFO] 画像日付: "
    f"{image_date}"
)
print(
    f"[INFO] WebPフォルダ: "
    f"{webp_dir}"
)
print(
    f"[INFO] WebP公開URL: "
    f"{public_webp_base_url}"
)


# =========================================================
# 共通関数
# =========================================================

def quote_identifier(
    identifier: str,
) -> str:
    """
    SQLiteのテーブル名・カラム名を安全に囲む。
    """
    return (
        "["
        + str(identifier).replace(
            "]",
            "]]",
        )
        + "]"
    )


def normalize_machine_number(
    value: Any,
) -> str:
    """
    スクリーンショットのファイル名に使用する
    台番号形式へ変換する。

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
    except (TypeError, ValueError):
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


def build_webp_path_and_url(
    machine_number: Any,
    screenshot_name: str,
) -> tuple[Path | None, str | None]:
    """
    台番号とスクリーンショット種別から、
    ローカルパスと公開URLを生成する。

    例:
        20260801_32_history.webp
    """
    normalized_number = (
        normalize_machine_number(
            machine_number
        )
    )

    if not normalized_number:
        return None, None

    filename = (
        f"{image_date}_"
        f"{normalized_number}_"
        f"{screenshot_name}.webp"
    )

    absolute_path = (
        webp_dir / filename
    )

    public_url = (
        f"{public_webp_base_url}/"
        f"{filename}"
    )

    return absolute_path, public_url


# =========================================================
# メイン処理
# =========================================================

def main() -> None:
    require_file(
        db_path,
        "店舗別SQLiteデータベース",
    )

    require_directory(
        webp_dir,
        "WebP画像フォルダ",
    )

    if not screenshot_db_columns:
        raise ValueError(
            "SCREENSHOT_DB_COLUMNSが空です。"
        )

    print("[CONFIG] スクリーンショット設定")

    for (
        screenshot_name,
        database_column,
    ) in screenshot_db_columns.items():
        print(
            f"  - {screenshot_name} "
            f"→ {database_column}"
        )

    # -----------------------------------------------------
    # DBカラム確認
    # -----------------------------------------------------

    with sqlite3.connect(db_path) as connection:
        table_columns = get_table_columns(
            connection,
            TABLE_NAME,
        )

    valid_screenshot_columns: dict[
        str,
        str,
    ] = {}

    for (
        screenshot_name,
        database_column,
    ) in screenshot_db_columns.items():
        if database_column not in table_columns:
            print(
                f"[WARN] DBカラムがないため除外: "
                f"{screenshot_name} "
                f"→ {database_column}"
            )
            continue

        valid_screenshot_columns[
            screenshot_name
        ] = database_column

    if not valid_screenshot_columns:
        raise ValueError(
            "更新可能な画像URLカラムがありません。"
        )

    # -----------------------------------------------------
    # 当日分DB取得
    # -----------------------------------------------------

    sql = f"""
        SELECT
            {quote_identifier("実行日")},
            {quote_identifier("SKU")},
            {quote_identifier("台番号")}
        FROM {quote_identifier(TABLE_NAME)}
        WHERE
            date(
                {quote_identifier("実行日")}
            ) = ?
        ORDER BY ROWID ASC
    """

    with sqlite3.connect(db_path) as connection:
        dataframe = pd.read_sql_query(
            sql,
            connection,
            params=[execution_date],
        )

    if dataframe.empty:
        print(
            f"[INFO] DB対象データなし: "
            f"{execution_date}"
        )
        return

    dataframe["実行日"] = pd.to_datetime(
        dataframe["実行日"],
        errors="coerce",
    )

    print(
        f"[DB] 対象レコード: "
        f"{len(dataframe)}件"
    )

    # -----------------------------------------------------
    # 画像URL生成
    # -----------------------------------------------------

    found_counts = {
        screenshot_name: 0
        for screenshot_name
        in valid_screenshot_columns
    }

    missing_counts = {
        screenshot_name: 0
        for screenshot_name
        in valid_screenshot_columns
    }

    update_values: list[
        dict[str, Any]
    ] = []

    for _, row in dataframe.iterrows():
        record: dict[str, Any] = {
            "SKU": row["SKU"],
            "台番号": row["台番号"],
        }

        for (
            screenshot_name,
            database_column,
        ) in valid_screenshot_columns.items():
            (
                absolute_path,
                public_url,
            ) = build_webp_path_and_url(
                row["台番号"],
                screenshot_name,
            )

            if (
                absolute_path is not None
                and absolute_path.is_file()
            ):
                record[
                    database_column
                ] = public_url

                found_counts[
                    screenshot_name
                ] += 1
            else:
                # ファイルがない場合はNULLで更新する。
                record[
                    database_column
                ] = None

                missing_counts[
                    screenshot_name
                ] += 1

        update_values.append(record)

    for screenshot_name in valid_screenshot_columns:
        print(
            f"[IMAGE] {screenshot_name}: "
            f"発見={found_counts[screenshot_name]}, "
            f"未発見={missing_counts[screenshot_name]}"
        )

    # -----------------------------------------------------
    # DB更新
    # -----------------------------------------------------

    update_columns = list(
        valid_screenshot_columns.values()
    )

    set_clause = ", ".join(
        f"{quote_identifier(column)} = ?"
        for column in update_columns
    )

    update_sql = f"""
        UPDATE {quote_identifier(TABLE_NAME)}
        SET
            {set_clause}
        WHERE
            {quote_identifier("SKU")} = ?
    """

    updated_count = 0
    no_match_count = 0

    with sqlite3.connect(db_path) as connection:
        cursor = connection.cursor()

        for record in update_values:
            parameters = [
                record.get(column)
                for column in update_columns
            ]

            parameters.append(
                record["SKU"]
            )

            cursor.execute(
                update_sql,
                parameters,
            )

            if cursor.rowcount > 0:
                updated_count += cursor.rowcount
            else:
                no_match_count += 1

        connection.commit()

    # -----------------------------------------------------
    # 完了ログ
    # -----------------------------------------------------

    print(
        f"[DB] 更新完了: "
        f"{updated_count}レコード"
    )

    if no_match_count:
        print(
            f"[WARN] SKU一致なし: "
            f"{no_match_count}件"
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




