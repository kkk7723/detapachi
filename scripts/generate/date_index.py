#!/usr/bin/env python
# coding: utf-8

# In[2]:


from __future__ import annotations

import argparse
import importlib
import sqlite3
import sys
import time
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
    # scripts/generate/date_index.py
    PROJECT_ROOT = find_project_root(
        Path(__file__)
    )
else:
    # Notebook
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

dates_output_dir = (
    site_output_dir
    / "dates"
)

output_path = (
    dates_output_dir
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
    f"[INFO] 日付一覧出力先: "
    f"{output_path}"
)


# =========================================================
# ページ設定
# =========================================================

TEMPLATE_NAME = (
    "dates/date_index.html"
)

EXECUTION_DATE_COLUMN = "実行日"
MACHINE_NUMBER_COLUMN = "台番号"


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
    SQLiteテーブルのカラム名を取得する。
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
    実行日・台番号検索用インデックスを作成する。
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
# 日付処理
# =========================================================

def normalize_date(
    value: Any,
) -> str:
    """
    YYYY-MM-DD形式へ整形する。
    """
    if value is None:
        return ""

    text = str(value).strip()[:10]

    if not text:
        return ""

    try:
        parsed = datetime.strptime(
            text,
            "%Y-%m-%d",
        )

        return parsed.strftime(
            "%Y-%m-%d"
        )

    except ValueError:
        return ""


def execution_date_to_display_date(
    execution_date: str,
) -> str:
    """
    DB実行日の1日前を表示日として返す。

    例:
        2026-08-02
        ↓
        2026-08-01
    """
    normalized = normalize_date(
        execution_date
    )

    if not normalized:
        return ""

    parsed = datetime.strptime(
        normalized,
        "%Y-%m-%d",
    )

    return (
        parsed - timedelta(days=1)
    ).strftime("%Y-%m-%d")


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
# DBから日付一覧取得
# =========================================================

def load_date_summaries(
    connection: sqlite3.Connection,
) -> list[sqlite3.Row]:
    """
    実行日ごとの台数を取得する。

    同じ実行日・同じ台番号に複数レコードがあっても、
    COUNT(DISTINCT 台番号)で1台として数える。
    """
    sql = f"""
        SELECT
            date(
                {quote_identifier(EXECUTION_DATE_COLUMN)}
            ) AS execution_date,

            COUNT(
                DISTINCT CAST(
                    {quote_identifier(MACHINE_NUMBER_COLUMN)}
                    AS TEXT
                )
            ) AS machine_count

        FROM {quote_identifier(TABLE_NAME)}

        WHERE
            {quote_identifier(EXECUTION_DATE_COLUMN)}
            IS NOT NULL

            AND TRIM(
                CAST(
                    {quote_identifier(EXECUTION_DATE_COLUMN)}
                    AS TEXT
                )
            ) <> ''

            AND {quote_identifier(MACHINE_NUMBER_COLUMN)}
            IS NOT NULL

            AND TRIM(
                CAST(
                    {quote_identifier(MACHINE_NUMBER_COLUMN)}
                    AS TEXT
                )
            ) <> ''

        GROUP BY
            date(
                {quote_identifier(EXECUTION_DATE_COLUMN)}
            )

        ORDER BY
            date(
                {quote_identifier(EXECUTION_DATE_COLUMN)}
            ) DESC
    """

    print(
        "[DB] 実行日一覧取得開始"
    )

    rows = connection.execute(
        sql
    ).fetchall()

    print(
        f"[DB] 実行日一覧取得完了: "
        f"{len(rows)}日"
    )

    return rows


# =========================================================
# テンプレート用日付データ
# =========================================================

def build_date_list(
    rows: list[sqlite3.Row],
) -> tuple[
    list[dict[str, Any]],
    int,
]:
    """
    DBの実行日を表示日へ変換し、
    日付別ページが存在するものだけ一覧にする。

    戻り値:
        日付一覧
        ページ不存在によるスキップ件数
    """
    date_items: list[
        dict[str, Any]
    ] = []

    skipped_count = 0
    used_display_dates: set[str] = set()

    for row in rows:
        execution_date = normalize_date(
            row["execution_date"]
        )

        if not execution_date:
            skipped_count += 1
            continue

        display_date = (
            execution_date_to_display_date(
                execution_date
            )
        )

        if not display_date:
            skipped_count += 1
            continue

        # 同じ表示日が重複した場合は先頭だけ採用
        if display_date in used_display_dates:
            print(
                f"[WARN] 表示日重複をスキップ: "
                f"{display_date}"
            )

            skipped_count += 1
            continue

        detail_filename = (
            f"day_{display_date}.html"
        )

        detail_path = (
            dates_output_dir
            / detail_filename
        )

        # 日付別ページが存在しない場合は
        # リンク切れを防ぐため一覧へ載せない
        if not detail_path.is_file():
            print(
                f"[SKIP] 日付別ページなし: "
                f"{detail_path}"
            )

            skipped_count += 1
            continue

        machine_count = int(
            row["machine_count"] or 0
        )

        date_items.append({
            "execution_date": execution_date,
            "display_date": display_date,
            "machine_count": machine_count,
            "detail_url": detail_filename,
        })

        used_display_dates.add(
            display_date
        )

    # 表示日の新しい順
    date_items.sort(
        key=lambda item: (
            item["display_date"]
        ),
        reverse=True,
    )

    return (
        date_items,
        skipped_count,
    )


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
        "日付一覧テンプレート",
    )

    dates_output_dir.mkdir(
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
    # DB処理
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

        create_database_index(
            connection
        )

        date_summary_rows = (
            load_date_summaries(
                connection
            )
        )

    if not date_summary_rows:
        print(
            "[INFO] 日付一覧の対象データが"
            "ありません。"
        )
        return

    # -----------------------------------------------------
    # 一覧データ作成
    # -----------------------------------------------------

    (
        dates,
        skipped_count,
    ) = build_date_list(
        date_summary_rows
    )

    print(
        f"[GENERATE] 掲載日数: "
        f"{len(dates)}日"
    )
    print(
        f"[GENERATE] スキップ日数: "
        f"{skipped_count}日"
    )

    for item in dates:
        print(
            f"[DATE] 表示日="
            f"{item['display_date']}, "
            f"DB実行日="
            f"{item['execution_date']}, "
            f"台数="
            f"{item['machine_count']}"
        )

    # -----------------------------------------------------
    # HTML生成
    # -----------------------------------------------------

    rendered_html = template.render(
        dates=dates,
        date_count=len(dates),
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
        "✅ 日付一覧ページ生成完了"
    )
    print(
        f"[INFO] 掲載日数: "
        f"{len(dates)}日"
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




