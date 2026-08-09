#!/usr/bin/env python
# coding: utf-8

# In[2]:


from __future__ import annotations

import argparse
import importlib
import sqlite3
import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta
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
    # scripts/generate/date_pages.py
    PROJECT_ROOT = find_project_root(
        Path(__file__)
    )
else:
    # scripts/generate/*.ipynb
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
    COMMON_VISIBLE_COLUMNS,
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

dates_output_dir = (
    site_output_dir
    / "dates"
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

configured_visible_columns = list(
    COMMON_VISIBLE_COLUMNS
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
    f"[INFO] 日付別ページ出力先: "
    f"{dates_output_dir}"
)


# =========================================================
# ページ設定
# =========================================================

TEMPLATE_NAME = "dates/day.html"

EXECUTION_DATE_COLUMN = "実行日"
MACHINE_NUMBER_COLUMN = "台番号"

IMAGE_COLUMNS = [
    "台画像URL",
    "img_url_a",
    "img_url_b",
    "img_url_c",
    "img_url_d",
]

EXCLUDED_COLUMNS = {
    "svgデータ",
}

PRIORITY_COLUMNS = [
    "実行日",
    "取得更新日",
    "台番号",
    "機種名",
    "BIG",
    "REG",
    "ATART",
    "最終ゲーム",
    "宵越し累計ゲーム数",
    "svg差枚",
]


# =========================================================
# SQLite共通
# =========================================================

def quote_identifier(
    identifier: str,
) -> str:
    """
    SQLite識別子を[]で囲む。
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
    SQLiteテーブルのカラム名を定義順で取得する。
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
    日付別ページ生成用インデックスを作成する。
    """
    index_name = (
        f"idx_{TABLE_NAME}_execution_machine"
    )

    sql = f"""
        CREATE INDEX IF NOT EXISTS
        {quote_identifier(index_name)}
        ON {quote_identifier(TABLE_NAME)} (
            {quote_identifier(EXECUTION_DATE_COLUMN)},
            {quote_identifier(MACHINE_NUMBER_COLUMN)}
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

    32、0032、32.0はすべて32にする。
    """
    if value is None:
        return ""

    text = str(value).strip()

    if not text:
        return ""

    try:
        number = float(text)

        if number.is_integer():
            return str(int(number))
    except ValueError:
        pass

    return text


def safe_machine_sort_key(
    value: Any,
) -> tuple[int, int | str]:
    """
    台番号のソートキー。
    """
    normalized = normalize_machine_number(
        value
    )

    try:
        return 0, int(normalized)
    except ValueError:
        return 1, normalized


def format_cell_value(
    value: Any,
) -> Any:
    """
    テンプレート表示用に値を整形する。
    """
    if value is None:
        return ""

    if isinstance(value, float):
        if value.is_integer():
            return int(value)

    return value


def execution_date_to_display_date(
    execution_date: str,
) -> str:
    """
    DB実行日の1日前を、ページ上の日付として返す。

    例:
        2026-08-02 -> 2026-08-01
    """
    try:
        parsed = datetime.strptime(
            execution_date,
            "%Y-%m-%d",
        )

        return (
            parsed - timedelta(days=1)
        ).strftime("%Y-%m-%d")

    except (TypeError, ValueError):
        return execution_date


def prepare_row(
    row: sqlite3.Row,
    visible_columns: list[str],
) -> dict[str, Any]:
    """
    SQLite Rowをテンプレート用dictへ変換する。
    """
    result = {
        column: format_cell_value(
            row[column]
        )
        for column in visible_columns
    }

    result[
        "台番号ファイル名"
    ] = normalize_machine_number(
        row[MACHINE_NUMBER_COLUMN]
    )

    return result


# =========================================================
# 表示カラム
# =========================================================

def build_visible_columns(
    database_columns: list[str],
) -> list[str]:
    """
    config/common.pyのCOMMON_VISIBLE_COLUMNSから、
    DBに実在する表示カラムを作成する。
    """
    visible_columns = [
        column
        for column in configured_visible_columns
        if (
            column in database_columns
            and column not in EXCLUDED_COLUMNS
        )
    ]

    for column in reversed(
        PRIORITY_COLUMNS
    ):
        if (
            column in database_columns
            and column not in visible_columns
            and column not in EXCLUDED_COLUMNS
        ):
            visible_columns.insert(
                0,
                column,
            )

    return visible_columns


# =========================================================
# Jinja2
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
# 全日付データを一括取得
# =========================================================

def load_all_date_rows(
    connection: sqlite3.Connection,
    visible_columns: list[str],
) -> list[sqlite3.Row]:
    """
    各実行日・各台番号について、
    最新1レコードだけをSQL 1回で取得する。

    同日・同じ台番号に複数レコードがある場合は、
    実行日時が最新の行を採用する。
    同時刻の場合はROWID最大の行を採用する。
    """
    source_columns = ", ".join(
        (
            f"source."
            f"{quote_identifier(column)}"
        )
        for column in visible_columns
    )

    ranked_columns = ", ".join(
        (
            f"ranked."
            f"{quote_identifier(column)}"
        )
        for column in visible_columns
    )

    sql = f"""
        WITH ranked AS (
            SELECT
                source.ROWID AS _rowid,
                {source_columns},

                date(
                    source.
                    {quote_identifier(EXECUTION_DATE_COLUMN)}
                ) AS execution_date_only,

                ROW_NUMBER() OVER (
                    PARTITION BY
                        date(
                            source.
                            {quote_identifier(EXECUTION_DATE_COLUMN)}
                        ),
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
                {quote_identifier(EXECUTION_DATE_COLUMN)}
                IS NOT NULL

                AND TRIM(
                    CAST(
                        source.
                        {quote_identifier(EXECUTION_DATE_COLUMN)}
                        AS TEXT
                    )
                ) <> ''

                AND source.
                {quote_identifier(MACHINE_NUMBER_COLUMN)}
                IS NOT NULL

                AND TRIM(
                    CAST(
                        source.
                        {quote_identifier(MACHINE_NUMBER_COLUMN)}
                        AS TEXT
                    )
                ) <> ''
        )

        SELECT
            ranked._rowid,
            ranked.execution_date_only,
            {ranked_columns}

        FROM ranked

        WHERE
            ranked.row_rank = 1

        ORDER BY
            ranked.execution_date_only DESC,

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
        "[DB] 全日付・全台の最新履歴を"
        "一括取得開始"
    )

    rows = connection.execute(
        sql
    ).fetchall()

    print(
        f"[DB] 一括取得完了: "
        f"{len(rows)}件"
    )

    return rows


# =========================================================
# 実行日別にグループ化
# =========================================================

def group_rows_by_execution_date(
    rows: list[sqlite3.Row],
) -> dict[str, list[sqlite3.Row]]:
    """
    DB行を実行日ごとに分ける。
    """
    grouped: dict[
        str,
        list[sqlite3.Row],
    ] = defaultdict(list)

    for row in rows:
        execution_date = str(
            row["execution_date_only"]
            or ""
        ).strip()

        if not execution_date:
            continue

        grouped[execution_date].append(
            row
        )

    return dict(grouped)


# =========================================================
# 日付別HTML生成
# =========================================================

def generate_date_pages(
    *,
    template,
    grouped_rows: dict[
        str,
        list[sqlite3.Row],
    ],
    visible_columns: list[str],
) -> tuple[int, int]:
    """
    実行日ごとに日付別ページを生成する。
    """
    execution_dates = sorted(
        grouped_rows.keys(),
        reverse=True,
    )

    generated_count = 0
    generated_row_count = 0

    for execution_date in execution_dates:
        rows = grouped_rows.get(
            execution_date,
            [],
        )

        if not rows:
            continue

        rows = sorted(
            rows,
            key=lambda row: (
                safe_machine_sort_key(
                    row[MACHINE_NUMBER_COLUMN]
                )
            ),
        )

        template_rows = [
            prepare_row(
                row,
                visible_columns,
            )
            for row in rows
        ]

        display_date = (
            execution_date_to_display_date(
                execution_date
            )
        )

        rendered_html = template.render(
            display_date=display_date,
            execution_date=execution_date,
            rows=template_rows,
            columns=visible_columns,
            image_columns=IMAGE_COLUMNS,
        )

        output_path = (
            dates_output_dir
            / f"day_{display_date}.html"
        )

        output_path.write_text(
            rendered_html,
            encoding="utf-8",
        )

        generated_count += 1
        generated_row_count += len(
            template_rows
        )

        print(
            f"[GENERATE] 表示日="
            f"{display_date}, "
            f"DB実行日={execution_date}, "
            f"台数={len(template_rows)} "
            f"→ {output_path}"
        )

    return (
        generated_count,
        generated_row_count,
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

    template_path = (
        Path(TEMPLATES_DIR)
        / TEMPLATE_NAME
    )

    require_file(
        template_path,
        "日付別ページテンプレート",
    )

    dates_output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    environment = (
        create_template_environment()
    )

    template = environment.get_template(
        TEMPLATE_NAME
    )

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
            EXECUTION_DATE_COLUMN,
            MACHINE_NUMBER_COLUMN,
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

        visible_columns = (
            build_visible_columns(
                database_columns
            )
        )

        if not visible_columns:
            raise RuntimeError(
                "日付別ページへ表示できる"
                "カラムがありません。"
            )

        print(
            f"[DB] 表示カラム数: "
            f"{len(visible_columns)}列"
        )

        for column in visible_columns:
            print(
                f"  - {column}"
            )

        create_database_index(
            connection
        )

        all_rows = load_all_date_rows(
            connection,
            visible_columns,
        )

    if not all_rows:
        print(
            "[INFO] 日付別ページの"
            "生成対象データがありません。"
        )
        return

    grouped_rows = (
        group_rows_by_execution_date(
            all_rows
        )
    )

    print(
        f"[DB] 対象実行日数: "
        f"{len(grouped_rows)}日"
    )

    (
        generated_count,
        generated_row_count,
    ) = generate_date_pages(
        template=template,
        grouped_rows=grouped_rows,
        visible_columns=visible_columns,
    )

    elapsed_time = (
        time.time() - start_time
    )

    print()
    print(
        f"✅ 日付別ページ生成完了: "
        f"{generated_count}ページ"
    )
    print(
        f"[INFO] 総表示レコード数: "
        f"{generated_row_count}件"
    )
    print(
        f"[INFO] 出力先: "
        f"{dates_output_dir}"
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




