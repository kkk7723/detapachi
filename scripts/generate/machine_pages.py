#!/usr/bin/env python
# coding: utf-8

# In[1]:


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
    # scripts/generate/*.py から実行
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
    COMMON_VISIBLE_COLUMNS,
    DEFAULT_SITE,
    TABLE_NAME,
    TEMPLATES_DIR,
    require_file,
)


# =========================================================
# 店舗選択
# =========================================================

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "店舗別SQLiteデータベースから"
            "台番号ごとの履歴HTMLを生成します。"
        )
    )

    parser.add_argument(
        "--site",
        default=DEFAULT_SITE,
        help="configフォルダ内の店舗設定名",
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


site_name = str(
    args.site
).strip()


if not site_name:
    raise ValueError(
        "店舗設定名が空です。"
    )


config_file = (
    PROJECT_ROOT
    / "config"
    / f"{site_name}.py"
)


if not config_file.is_file():
    raise FileNotFoundError(
        f"店舗設定が見つかりません: "
        f"{config_file}"
    )


try:
    site_config = importlib.import_module(
        f"config.{site_name}"
    )

except ModuleNotFoundError as exc:
    raise SystemExit(
        f"[ERROR] 店舗設定が見つかりません: "
        f"config/{site_name}.py"
    ) from exc


# =========================================================
# 店舗必須設定確認
# =========================================================

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
            f"config/{site_name}.py に "
            f"{setting_name} が設定されていません。"
        )


# =========================================================
# 店舗別設定
# =========================================================

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

shop_name = str(
    getattr(
        site_config,
        "SHOP_NAME",
        getattr(
            site_config,
            "GSHEET_NAME",
            site_name,
        ),
    )
).strip()


# config/common.py の共通表示カラムを使用
configured_visible_columns = list(
    COMMON_VISIBLE_COLUMNS
)


print(
    f"[INFO] 対象店舗: "
    f"{site_name}"
)

print(
    f"[INFO] 店舗名: "
    f"{shop_name}"
)

print(
    f"[INFO] 使用DB: "
    f"{db_path}"
)

print(
    f"[INFO] テンプレートルート: "
    f"{TEMPLATES_DIR}"
)

print(
    f"[INFO] 台番号ページ出力先: "
    f"{machines_output_dir}"
)

print(
    f"[INFO] 共通表示カラム設定数: "
    f"{len(configured_visible_columns)}列"
)


# =========================================================
# ページ設定
# =========================================================

TEMPLATE_NAME = (
    "machines/machine.html"
)


# HTML内で画像として表示するカラム
IMAGE_COLUMNS = [
    "台画像URL",
    "img_url_a",
    "img_url_b",
    "img_url_c",
    "img_url_d",
]


# HTML表へ表示しない大型データ
EXCLUDED_COLUMNS = {
    "svgデータ",
}


# COMMON_VISIBLE_COLUMNSに含まれていなくても、
# 台番号ページでは優先的に表示するカラム
PRIORITY_COLUMNS = [
    "実行日",
    "取得更新日",
    "台番号",
    "機種名",
]


# =========================================================
# SQLite共通
# =========================================================

def quote_identifier(
    identifier: str,
) -> str:
    """
    SQLiteの識別子を[]で安全に囲む。
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
    SQLiteテーブルのカラム名を
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
    台番号ページ生成用のインデックスを作成する。

    既に存在する場合は何もしない。
    """
    index_name = (
        f"idx_{TABLE_NAME}_machine_execution"
    )

    sql = f"""
        CREATE INDEX IF NOT EXISTS
        {quote_identifier(index_name)}
        ON {quote_identifier(TABLE_NAME)} (
            {quote_identifier("台番号")},
            {quote_identifier("実行日")}
        )
    """

    connection.execute(
        sql
    )

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
    台番号をファイル名用に整形する。

    例:
        32     -> "32"
        "0032" -> "32"
        32.0   -> "32"

    数字以外を含む値はそのまま返す。
    """
    if value is None:
        return ""

    text = str(
        value
    ).strip()

    if not text:
        return ""

    try:
        numeric_value = float(
            text
        )

        if numeric_value.is_integer():
            return str(
                int(
                    numeric_value
                )
            )

    except (
        TypeError,
        ValueError,
    ):
        pass

    return text


def safe_machine_sort_key(
    value: Any,
) -> tuple[int, int | str]:
    """
    台番号を並べ替えるためのキーを返す。

    数値台番号を先に数値順で並べ、
    文字を含む台番号を後ろに並べる。
    """
    normalized = normalize_machine_number(
        value
    )

    try:
        return (
            0,
            int(
                normalized
            ),
        )

    except ValueError:
        return (
            1,
            normalized,
        )


def format_cell_value(
    value: Any,
) -> Any:
    """
    テンプレートへ渡すセル値を整形する。
    """
    if value is None:
        return ""

    if isinstance(
        value,
        float,
    ):
        if value.is_integer():
            return int(
                value
            )

    return value


def prepare_row(
    row: sqlite3.Row,
    visible_columns: list[str],
) -> dict[str, Any]:
    """
    sqlite3.Rowをテンプレート用dictへ変換する。
    """
    return {
        column: format_cell_value(
            row[column]
        )
        for column in visible_columns
    }


# =========================================================
# Jinja2
# =========================================================

def create_template_environment() -> Environment:
    """
    共通テンプレートフォルダを使用して
    Jinja2環境を作成する。
    """
    environment = Environment(
        loader=FileSystemLoader(
            str(
                TEMPLATES_DIR
            )
        ),
        autoescape=select_autoescape(
            [
                "html",
                "xml",
            ]
        ),
        trim_blocks=True,
        lstrip_blocks=True,
    )

    environment.globals[
        "SHOP_NAME"
    ] = shop_name

    environment.globals[
        "SITE_KEY"
    ] = site_name

    environment.globals[
        "RUN_DATETIME"
    ] = datetime.now().strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    return environment


# =========================================================
# 表示カラム作成
# =========================================================

def build_visible_columns(
    database_columns: list[str],
) -> list[str]:
    """
    config/common.py のCOMMON_VISIBLE_COLUMNSから、
    DBに存在する表示対象カラムだけを作成する。

    画像カラムおよび重要カラムは、
    COMMON_VISIBLE_COLUMNSに含まれていなくても
    DBに存在すれば自動的に追加する。
    """
    visible_columns = [
        column
        for column in configured_visible_columns
        if (
            column in database_columns
            and column not in EXCLUDED_COLUMNS
        )
    ]

    # -----------------------------------------------------
    # 画像カラムを自動追加
    # -----------------------------------------------------

    for column in reversed(
        IMAGE_COLUMNS
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

    # -----------------------------------------------------
    # 重要カラムを先頭に追加
    # -----------------------------------------------------

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
# 全台履歴を一括取得
# =========================================================

def load_all_machine_histories(
    connection: sqlite3.Connection,
    visible_columns: list[str],
) -> list[sqlite3.Row]:
    """
    全台について、実行日ごとの最新1レコードだけを
    SQL 1回で一括取得する。

    同じ台番号・同じ日付に複数レコードがある場合は、

    1. 実行日時が最も新しい
    2. 同時刻ならROWIDが最も大きい

    レコードを採用する。
    """
    ranked_source_columns = ", ".join(
        (
            f"source."
            f"{quote_identifier(column)}"
        )
        for column in visible_columns
    )

    final_select_columns = ", ".join(
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
                {ranked_source_columns},

                ROW_NUMBER() OVER (
                    PARTITION BY
                        CAST(
                            source.{quote_identifier("台番号")}
                            AS TEXT
                        ),
                        date(
                            source.{quote_identifier("実行日")}
                        )

                    ORDER BY
                        datetime(
                            source.{quote_identifier("実行日")}
                        ) DESC,
                        source.ROWID DESC
                ) AS row_rank

            FROM {quote_identifier(TABLE_NAME)}
                AS source

            WHERE
                source.{quote_identifier("台番号")}
                    IS NOT NULL

                AND TRIM(
                    CAST(
                        source.{quote_identifier("台番号")}
                        AS TEXT
                    )
                ) <> ''

                AND source.{quote_identifier("実行日")}
                    IS NOT NULL

                AND TRIM(
                    CAST(
                        source.{quote_identifier("実行日")}
                        AS TEXT
                    )
                ) <> ''
        )

        SELECT
            ranked._rowid,
            {final_select_columns}

        FROM ranked

        WHERE
            ranked.row_rank = 1

        ORDER BY
            CASE
                WHEN TRIM(
                    CAST(
                        ranked.{quote_identifier("台番号")}
                        AS TEXT
                    )
                ) GLOB '[0-9]*'
                THEN 0
                ELSE 1
            END ASC,

            CAST(
                ranked.{quote_identifier("台番号")}
                AS INTEGER
            ) ASC,

            CAST(
                ranked.{quote_identifier("台番号")}
                AS TEXT
            ) ASC,

            datetime(
                ranked.{quote_identifier("実行日")}
            ) DESC,

            ranked._rowid DESC
    """

    print(
        "[DB] 全台の日付別最新履歴を"
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
# 台番号別グループ化
# =========================================================

def group_histories_by_machine(
    rows: list[sqlite3.Row],
) -> dict[str, list[sqlite3.Row]]:
    """
    一括取得した履歴を台番号ごとに分ける。
    """
    histories: dict[
        str,
        list[sqlite3.Row],
    ] = {}

    for row in rows:
        machine_number = (
            normalize_machine_number(
                row["台番号"]
            )
        )

        if not machine_number:
            continue

        histories.setdefault(
            machine_number,
            [],
        ).append(
            row
        )

    return histories


# =========================================================
# HTML生成
# =========================================================

def generate_machine_pages(
    *,
    template,
    histories_by_machine: dict[
        str,
        list[sqlite3.Row],
    ],
    visible_columns: list[str],
) -> tuple[int, int]:
    """
    台番号ごとのHTMLを生成する。
    """
    machine_numbers = sorted(
        histories_by_machine.keys(),
        key=safe_machine_sort_key,
    )

    print(
        f"[GENERATE] 対象台数: "
        f"{len(machine_numbers)}台"
    )

    generated_count = 0
    skipped_count = 0

    for machine_number in machine_numbers:
        history_rows = (
            histories_by_machine.get(
                machine_number,
                [],
            )
        )

        if not history_rows:
            skipped_count += 1

            print(
                f"[SKIP] 台番号="
                f"{machine_number}: "
                f"履歴なし"
            )

            continue

        template_rows = [
            prepare_row(
                row,
                visible_columns,
            )
            for row in history_rows
        ]

        rendered_html = template.render(
            machine_number=machine_number,
            rows=template_rows,
            columns=visible_columns,
            image_columns=IMAGE_COLUMNS,
        )

        output_path = (
            machines_output_dir
            / f"{machine_number}.html"
        )

        output_path.write_text(
            rendered_html,
            encoding="utf-8",
        )

        generated_count += 1

        print(
            f"[GENERATE] 台番号="
            f"{machine_number}, "
            f"日数={len(template_rows)}件 "
            f"→ {output_path}"
        )

    return (
        generated_count,
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
        Path(
            TEMPLATES_DIR
        )
        / TEMPLATE_NAME
    )

    require_file(
        template_path,
        "台番号ページテンプレート",
    )

    machines_output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    # -----------------------------------------------------
    # テンプレート読込
    # -----------------------------------------------------

    environment = create_template_environment()

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

        database_columns = get_table_columns(
            connection,
            TABLE_NAME,
        )

        if not database_columns:
            raise RuntimeError(
                f"{TABLE_NAME} が存在しないか、"
                "カラムがありません。"
            )

        required_database_columns = (
            "台番号",
            "実行日",
        )

        for required_column in (
            required_database_columns
        ):
            if required_column not in database_columns:
                raise RuntimeError(
                    f"{TABLE_NAME} に"
                    f"{required_column}カラムが"
                    "ありません。"
                )

        visible_columns = build_visible_columns(
            database_columns
        )

        if not visible_columns:
            raise RuntimeError(
                "台番号ページへ表示できる"
                "DBカラムがありません。"
            )

        print(
            f"[DB] DBカラム数: "
            f"{len(database_columns)}列"
        )

        print(
            f"[DB] 表示カラム数: "
            f"{len(visible_columns)}列"
        )

        for column in visible_columns:
            image_label = (
                " [IMAGE]"
                if column in IMAGE_COLUMNS
                else ""
            )

            print(
                f"  - {column}"
                f"{image_label}"
            )

        # 検索用インデックス
        create_database_index(
            connection
        )

        # 全台の履歴を1回で取得
        all_history_rows = (
            load_all_machine_histories(
                connection,
                visible_columns,
            )
        )

    if not all_history_rows:
        print(
            "[INFO] 生成対象の履歴が"
            "ありません。"
        )
        return

    # -----------------------------------------------------
    # 台番号別に分割
    # -----------------------------------------------------

    histories_by_machine = (
        group_histories_by_machine(
            all_history_rows
        )
    )

    print(
        f"[DB] 台番号別グループ数: "
        f"{len(histories_by_machine)}台"
    )

    # -----------------------------------------------------
    # HTML生成
    # -----------------------------------------------------

    (
        generated_count,
        skipped_count,
    ) = generate_machine_pages(
        template=template,
        histories_by_machine=(
            histories_by_machine
        ),
        visible_columns=visible_columns,
    )

    # -----------------------------------------------------
    # 完了
    # -----------------------------------------------------

    elapsed_time = (
        time.time()
        - start_time
    )

    print()

    print(
        f"✅ 台番号ページ生成完了: "
        f"{generated_count}ページ"
    )

    print(
        f"[INFO] スキップ: "
        f"{skipped_count}台"
    )

    print(
        f"[INFO] DB取得履歴数: "
        f"{len(all_history_rows)}件"
    )

    print(
        f"[INFO] 出力先: "
        f"{machines_output_dir}"
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




