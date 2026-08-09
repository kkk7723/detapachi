#!/usr/bin/env python
# coding: utf-8

# In[2]:


from __future__ import annotations

import argparse
import importlib
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from jinja2 import (
    Environment,
    FileSystemLoader,
    select_autoescape,
)


# =========================================================
# プロジェクトルート設定
# =========================================================

def find_project_root(
    start_path: Path,
) -> Path:
    """
    config/、utils/、templates/ が存在する
    detaslotのプロジェクトルートを返す。
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
            and (candidate / "templates").is_dir()
        ):
            return candidate

    raise RuntimeError(
        "detaslotのプロジェクトルートを"
        "特定できませんでした。"
        f" 開始位置: {start_path}"
    )


if "__file__" in globals():
    # scripts/generate/machine_index.py から実行
    PROJECT_ROOT = find_project_root(
        Path(__file__)
    )
else:
    # scripts/generate/*.ipynb から実行
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
    f"[INFO] templates存在: "
    f"{(PROJECT_ROOT / 'templates').is_dir()}"
)


# =========================================================
# 共通設定
# =========================================================

from config.common import (
    DEFAULT_SITE,
    TABLE_NAME,
    TEMPLATES_DIR,
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
)

for setting_name in required_site_settings:
    if not hasattr(
        site_config,
        setting_name,
    ):
        raise AttributeError(
            f"config/{args.site}.py に "
            f"{setting_name} が設定されていません。"
        )


db_path = Path(
    site_config.DB_PATH
)

site_output_dir = Path(
    site_config.SITE_OUTPUT_DIR
)

machines_output_dir = (
    site_output_dir
    / "machines"
)

output_path = (
    machines_output_dir
    / "index.html"
)

shop_name = str(
    getattr(
        site_config,
        "SHOP_NAME",
        getattr(
            site_config,
            "GSHEET_NAME",
            args.site,
        ),
    )
)


print(f"[INFO] 対象店舗: {args.site}")
print(f"[INFO] 店舗名: {shop_name}")
print(f"[INFO] 使用DB: {db_path}")
print(f"[INFO] 対象テーブル: {TABLE_NAME}")
print(
    f"[INFO] テンプレートルート: "
    f"{TEMPLATES_DIR}"
)
print(
    f"[INFO] 一覧ページ出力先: "
    f"{output_path}"
)


# =========================================================
# ページ設定
# =========================================================

TEMPLATE_NAME = (
    "machines/machine_index.html"
)

MACHINE_NUMBER_COLUMN = "台番号"
MACHINE_NAME_COLUMN = "機種名"
EXECUTION_DATE_COLUMN = "実行日"
UPDATE_DATE_COLUMN = "取得更新日"

# 一覧ページで画像表示したい場合に使用
IMAGE_COLUMN_CANDIDATES = [
    "img_url_d",
    "img_url_c",
    "img_url_b",
    "img_url_a",
    "台画像URL",
]


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
) -> list[str]:
    """
    SQLiteテーブルに存在するカラム名を
    定義順で取得する。
    """
    cursor = connection.execute(
        f"PRAGMA table_info("
        f"{quote_identifier(table_name)}"
        f")"
    )

    return [
        str(row[1])
        for row in cursor.fetchall()
    ]


def create_database_index(
    connection: sqlite3.Connection,
) -> None:
    """
    台番号と実行日の検索用インデックスを作成する。
    """
    index_name = (
        f"idx_{TABLE_NAME}_machine_execution"
    )

    sql = f"""
        CREATE INDEX IF NOT EXISTS
        {quote_identifier(index_name)}
        ON {quote_identifier(TABLE_NAME)} (
            {quote_identifier(MACHINE_NUMBER_COLUMN)},
            {quote_identifier(EXECUTION_DATE_COLUMN)}
        )
    """

    connection.execute(sql)
    connection.commit()

    print(
        f"[DB] インデックス確認完了: "
        f"{index_name}"
    )


# =========================================================
# 値整形
# =========================================================

def normalize_machine_number(
    value: Any,
) -> str:
    """
    台番号を表示・ファイル名用に整形する。

    例:
        32     -> "32"
        "0032" -> "32"
        32.0   -> "32"
    """
    if value is None:
        return ""

    text = str(value).strip()

    if not text:
        return ""

    try:
        numeric_value = float(text)

        if numeric_value.is_integer():
            return str(
                int(numeric_value)
            )
    except ValueError:
        pass

    return text


def safe_machine_sort_key(
    value: Any,
) -> tuple[int, int | str]:
    """
    台番号を数値順に並べるためのキーを返す。

    数字以外を含む台番号は後ろへ並べる。
    """
    normalized = normalize_machine_number(
        value
    )

    try:
        return (
            0,
            int(normalized),
        )
    except ValueError:
        return (
            1,
            normalized,
        )


def clean_text(
    value: Any,
) -> str:
    """
    Noneを空文字へ変換し、文字列をstripする。
    """
    if value is None:
        return ""

    return str(value).strip()


def select_image_column(
    database_columns: list[str],
) -> str | None:
    """
    一覧ページに使用する画像URLカラムを選ぶ。

    IMAGE_COLUMN_CANDIDATESの先頭から、
    DBに存在する最初のカラムを採用する。
    """
    for column in IMAGE_COLUMN_CANDIDATES:
        if column in database_columns:
            return column

    return None


# =========================================================
# Jinja2設定
# =========================================================

def create_template_environment() -> Environment:
    """
    Jinja2環境を作成する。
    """
    environment = Environment(
        loader=FileSystemLoader(
            str(TEMPLATES_DIR)
        ),
        autoescape=select_autoescape([
            "html",
            "xml",
        ]),
        trim_blocks=True,
        lstrip_blocks=True,
    )

    environment.globals[
        "SHOP_NAME"
    ] = shop_name

    environment.globals[
        "SITE_KEY"
    ] = args.site

    environment.globals[
        "RUN_DATETIME"
    ] = datetime.now().strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    return environment


# =========================================================
# 各台の最新1レコード取得
# =========================================================

def load_latest_machine_rows(
    connection: sqlite3.Connection,
    database_columns: list[str],
) -> list[sqlite3.Row]:
    """
    全台について最新1レコードだけをSQL 1回で取得する。

    優先順:
    1. 実行日時が新しい
    2. 同時刻ならROWIDが大きい
    """
    optional_columns: list[str] = []

    for column in [
        MACHINE_NAME_COLUMN,
        UPDATE_DATE_COLUMN,
    ]:
        if column in database_columns:
            optional_columns.append(
                column
            )

    image_column = select_image_column(
        database_columns
    )

    if (
        image_column
        and image_column
        not in optional_columns
    ):
        optional_columns.append(
            image_column
        )

    ranked_select_parts = [
        (
            f"source."
            f"{quote_identifier(MACHINE_NUMBER_COLUMN)}"
        ),
        (
            f"source."
            f"{quote_identifier(EXECUTION_DATE_COLUMN)}"
        ),
    ]

    for column in optional_columns:
        ranked_select_parts.append(
            f"source.{quote_identifier(column)}"
        )

    ranked_select_clause = ",\n                ".join(
        ranked_select_parts
    )

    final_select_parts = [
        (
            f"ranked."
            f"{quote_identifier(MACHINE_NUMBER_COLUMN)}"
        ),
        (
            f"ranked."
            f"{quote_identifier(EXECUTION_DATE_COLUMN)}"
        ),
    ]

    for column in optional_columns:
        final_select_parts.append(
            f"ranked.{quote_identifier(column)}"
        )

    final_select_clause = ",\n            ".join(
        final_select_parts
    )

    sql = f"""
        WITH ranked AS (
            SELECT
                source.ROWID AS _rowid,
                {ranked_select_clause},

                ROW_NUMBER() OVER (
                    PARTITION BY
                        CAST(
                            source.
                            {quote_identifier(MACHINE_NUMBER_COLUMN)}
                            AS TEXT
                        )

                    ORDER BY
                        datetime(
                            source.
                            {quote_identifier(EXECUTION_DATE_COLUMN)}
                        ) DESC,
                        source.ROWID DESC
                ) AS row_rank

            FROM {quote_identifier(TABLE_NAME)}
                AS source

            WHERE
                source.
                {quote_identifier(MACHINE_NUMBER_COLUMN)}
                IS NOT NULL

                AND TRIM(
                    CAST(
                        source.
                        {quote_identifier(MACHINE_NUMBER_COLUMN)}
                        AS TEXT
                    )
                ) <> ''

                AND source.
                {quote_identifier(EXECUTION_DATE_COLUMN)}
                IS NOT NULL

                AND TRIM(
                    CAST(
                        source.
                        {quote_identifier(EXECUTION_DATE_COLUMN)}
                        AS TEXT
                    )
                ) <> ''
        )

        SELECT
            ranked._rowid,
            {final_select_clause}

        FROM ranked

        WHERE
            ranked.row_rank = 1

        ORDER BY
            CASE
                WHEN TRIM(
                    CAST(
                        ranked.
                        {quote_identifier(MACHINE_NUMBER_COLUMN)}
                        AS TEXT
                    )
                ) GLOB '[0-9]*'
                THEN 0
                ELSE 1
            END ASC,

            CAST(
                ranked.
                {quote_identifier(MACHINE_NUMBER_COLUMN)}
                AS INTEGER
            ) ASC,

            CAST(
                ranked.
                {quote_identifier(MACHINE_NUMBER_COLUMN)}
                AS TEXT
            ) ASC
    """

    print(
        "[DB] 各台の最新レコードを"
        "一括取得開始"
    )

    rows = connection.execute(
        sql
    ).fetchall()

    print(
        f"[DB] 一括取得完了: "
        f"{len(rows)}台"
    )

    return rows


# =========================================================
# テンプレート用データ作成
# =========================================================

def build_machine_list(
    rows: list[sqlite3.Row],
    database_columns: list[str],
) -> list[dict[str, Any]]:
    """
    sqlite3.Rowからテンプレート用の一覧データを作成する。
    """
    image_column = select_image_column(
        database_columns
    )

    machines: list[
        dict[str, Any]
    ] = []

    for row in rows:
        machine_number = (
            normalize_machine_number(
                row[MACHINE_NUMBER_COLUMN]
            )
        )

        if not machine_number:
            continue

        machine_name = ""

        if MACHINE_NAME_COLUMN in row.keys():
            machine_name = clean_text(
                row[MACHINE_NAME_COLUMN]
            )

        execution_datetime = clean_text(
            row[EXECUTION_DATE_COLUMN]
        )

        update_datetime = ""

        if UPDATE_DATE_COLUMN in row.keys():
            update_datetime = clean_text(
                row[UPDATE_DATE_COLUMN]
            )

        image_url = ""

        if (
            image_column
            and image_column in row.keys()
        ):
            image_url = clean_text(
                row[image_column]
            )

        machines.append({
            "machine_number": machine_number,
            "machine_name": machine_name,
            "execution_datetime": (
                execution_datetime
            ),
            "update_datetime": (
                update_datetime
            ),
            "image_url": image_url,
            "detail_url": (
                f"{machine_number}.html"
            ),
        })

    machines.sort(
        key=lambda machine: (
            safe_machine_sort_key(
                machine["machine_number"]
            )
        )
    )

    return machines


# =========================================================
# メイン処理
# =========================================================

def main() -> None:
    start_time = time.time()

    # -----------------------------------------------------
    # 必須ファイル確認
    # -----------------------------------------------------

    require_file(
        db_path,
        "店舗別SQLiteデータベース",
    )

    template_path = (
        Path(TEMPLATES_DIR)
        / TEMPLATE_NAME
    )

    require_file(
        template_path,
        "台番号一覧テンプレート",
    )

    machines_output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    # -----------------------------------------------------
    # テンプレート読込
    # -----------------------------------------------------

    environment = (
        create_template_environment()
    )

    template = environment.get_template(
        TEMPLATE_NAME
    )

    # -----------------------------------------------------
    # DBから各台の最新データ取得
    # -----------------------------------------------------

    with sqlite3.connect(
        db_path
    ) as connection:
        connection.row_factory = (
            sqlite3.Row
        )

        database_columns = (
            get_table_columns(
                connection,
                TABLE_NAME,
            )
        )

        if not database_columns:
            raise RuntimeError(
                f"{TABLE_NAME} が存在しないか、"
                "カラムがありません。"
            )

        required_columns = [
            MACHINE_NUMBER_COLUMN,
            EXECUTION_DATE_COLUMN,
        ]

        missing_columns = [
            column
            for column in required_columns
            if column not in database_columns
        ]

        if missing_columns:
            raise RuntimeError(
                f"{TABLE_NAME} に必要列がありません: "
                f"{missing_columns}"
            )

        create_database_index(
            connection
        )

        latest_rows = load_latest_machine_rows(
            connection,
            database_columns,
        )

    if not latest_rows:
        print(
            "[INFO] 台番号一覧の対象データが"
            "ありません。"
        )
        return

    # -----------------------------------------------------
    # テンプレート用データ作成
    # -----------------------------------------------------

    machines = build_machine_list(
        latest_rows,
        database_columns,
    )

    if not machines:
        print(
            "[INFO] 有効な台番号がありません。"
        )
        return

    print(
        f"[GENERATE] 一覧対象台数: "
        f"{len(machines)}台"
    )

    for machine in machines:
        print(
            f"[MACHINE] "
            f"{machine['machine_number']}番台 "
            f"{machine['machine_name']}"
        )

    # -----------------------------------------------------
    # HTML生成
    # -----------------------------------------------------

    rendered_html = template.render(
        machines=machines,
        machine_count=len(machines),
    )

    output_path.write_text(
        rendered_html,
        encoding="utf-8",
    )

    elapsed_time = (
        time.time() - start_time
    )

    # -----------------------------------------------------
    # 完了
    # -----------------------------------------------------

    print()
    print(
        "✅ 台番号一覧ページ生成完了"
    )
    print(
        f"[INFO] 対象台数: "
        f"{len(machines)}台"
    )
    print(
        f"[INFO] 出力先: "
        f"{output_path}"
    )
    print(
        f"[INFO] 所要時間: "
        f"{elapsed_time:.2f}秒"
    )


# =========================================================
# 実行
# =========================================================

if __name__ == "__main__":
    main()


# In[ ]:




