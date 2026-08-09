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


print(f"[INFO] 対象店舗: {args.site}")
print(f"[INFO] 使用DB: {db_path}")
print(
    f"[INFO] 店舗シート: "
    f"{spreadsheet_name} / {worksheet_name}"
)


# =========================================================
# スプレッドシート範囲設定
# =========================================================

HEADER_ROW = 3
DATA_START_ROW = 4
DATA_END_ROW = 500

# 設定値の範囲
START_COL = "K"
END_COL = "AH"

# 台番号列
DAI_COL_RANGE = (
    f"B{DATA_START_ROW}:B{DATA_END_ROW}"
)


# =========================================================
# 共通関数
# =========================================================

def column_to_index(column: str) -> int:
    """
    スプレッドシート列名を1始まりの列番号へ変換する。

    例:
        A  -> 1
        B  -> 2
        Z  -> 26
        AA -> 27
    """
    index = 0

    for character in column.strip().upper():
        if not (
            "A" <= character <= "Z"
        ):
            raise ValueError(
                f"不正な列名です: {column}"
            )

        index = (
            index * 26
            + ord(character)
            - ord("A")
            + 1
        )

    return index


def pad_row(
    row: list[Any] | tuple[Any, ...] | None,
    column_count: int,
) -> list[str]:
    """
    gspread.get()で省略された行末セルを
    空文字で補い、指定列数に揃える。
    """
    source = row or []

    values = [
        (
            ""
            if value is None
            else str(value).strip()
        )
        for value in source
    ]

    if len(values) < column_count:
        values.extend(
            [""] * (
                column_count
                - len(values)
            )
        )
    elif len(values) > column_count:
        values = values[:column_count]

    return values


def normalize_machine_number(
    value: Any,
) -> str:
    """
    台番号を照合用形式へ統一する。

    例:
        32     -> "32"
        0032   -> "32"
        32.0   -> "32"
        空欄   -> ""
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


def quote_identifier(
    identifier: str,
) -> str:
    """
    SQLiteのテーブル名・カラム名を[]で囲む。
    """
    return (
        "["
        + str(identifier).replace(
            "]",
            "]]",
        )
        + "]"
    )


def make_unique_headers(
    raw_headers: list[str],
) -> list[str]:
    """
    重複する見出しへ #2、#3 を付ける。

    空見出しは空文字のまま保持する。
    """
    headers: list[str] = []
    seen: dict[str, int] = {}

    for header in raw_headers:
        normalized_header = (
            str(header).strip()
            if header is not None
            else ""
        )

        if not normalized_header:
            headers.append("")
            continue

        seen[normalized_header] = (
            seen.get(
                normalized_header,
                0,
            )
            + 1
        )

        count = seen[normalized_header]

        if count == 1:
            headers.append(
                normalized_header
            )
        else:
            headers.append(
                f"{normalized_header}#{count}"
            )

    return headers


def get_table_columns(
    connection: sqlite3.Connection,
    table_name: str,
) -> set[str]:
    """
    SQLiteテーブルに実在するカラム名を取得する。
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
# メイン処理
# =========================================================

def main() -> None:
    start_time = time.time()

    # -----------------------------------------------------
    # 必須ファイル確認
    # -----------------------------------------------------

    require_file(
        GOOGLE_CREDENTIALS_FILE,
        "GoogleサービスアカウントJSON",
    )

    require_file(
        db_path,
        "店舗別SQLiteデータベース",
    )

    # -----------------------------------------------------
    # Google Sheets接続
    # -----------------------------------------------------

    worksheet = open_worksheet(
        credentials_file=GOOGLE_CREDENTIALS_FILE,
        scopes=GOOGLE_SCOPES,
        spreadsheet_name=spreadsheet_name,
        worksheet_name=worksheet_name,
    )



    # -----------------------------------------------------
    # 期待列数
    # -----------------------------------------------------

    expected_column_count = (
        column_to_index(END_COL)
        - column_to_index(START_COL)
        + 1
    )

    print(
        f"[SHEET] 設定範囲: "
        f"{START_COL}{HEADER_ROW}:"
        f"{END_COL}{DATA_END_ROW}"
    )
    print(
        f"[SHEET] 期待列数: "
        f"{expected_column_count}列"
    )

    # O～CBは66列。
    # 古いコメントにある23列ではない。
    # 列名から毎回自動計算する。

    # -----------------------------------------------------
    # 見出し・設定値取得
    # -----------------------------------------------------

    settings_range = (
        f"{START_COL}{HEADER_ROW}:"
        f"{END_COL}{DATA_END_ROW}"
    )

    try:
        block = worksheet.get(
            settings_range
        )
    except Exception as exc:
        raise RuntimeError(
            "[SHEET] 設定値取得失敗: "
            f"{exc}"
        ) from exc

    if not block:
        raise ValueError(
            "[ERROR] 指定範囲にデータがありません: "
            f"{settings_range}"
        )

    raw_headers = pad_row(
        block[0],
        expected_column_count,
    )

    headers = make_unique_headers(
        raw_headers
    )

    # データ行数は4～500行で固定
    expected_data_row_count = (
        DATA_END_ROW
        - DATA_START_ROW
        + 1
    )

    raw_data_rows = block[1:]

    data_rows: list[list[str]] = []

    for row_index in range(
        expected_data_row_count
    ):
        source_row = (
            raw_data_rows[row_index]
            if row_index
            < len(raw_data_rows)
            else []
        )

        data_rows.append(
            pad_row(
                source_row,
                expected_column_count,
            )
        )

    print(
        f"[SHEET] 設定値取得完了: "
        f"{len(data_rows)}行 × "
        f"{expected_column_count}列"
    )

    # -----------------------------------------------------
    # 台番号取得
    # -----------------------------------------------------

    try:
        raw_machine_numbers = worksheet.get(
            DAI_COL_RANGE
        )
    except Exception as exc:
        raise RuntimeError(
            "[SHEET] 台番号取得失敗: "
            f"{exc}"
        ) from exc

    machine_numbers: list[str] = []

    for row_index in range(
        expected_data_row_count
    ):
        raw_value: Any = ""

        if row_index < len(
            raw_machine_numbers
        ):
            source_row = raw_machine_numbers[
                row_index
            ]

            if (
                isinstance(
                    source_row,
                    (list, tuple),
                )
                and source_row
            ):
                raw_value = source_row[0]

        machine_numbers.append(
            normalize_machine_number(
                raw_value
            )
        )

    print(
        f"[SHEET] 台番号取得完了: "
        f"{len(machine_numbers)}行"
    )

    # -----------------------------------------------------
    # DataFrame作成
    # -----------------------------------------------------

    dataframe = pd.DataFrame(
        data_rows,
        columns=headers,
    )

    dataframe.insert(
        0,
        "台番号",
        machine_numbers,
    )

    before_drop_count = len(dataframe)

    dataframe = dataframe[
        dataframe["台番号"] != ""
    ].copy()

    removed_count = (
        before_drop_count
        - len(dataframe)
    )

    print(
        f"[DATA] DataFrame作成完了: "
        f"shape={dataframe.shape}"
    )
    print(
        f"[DATA] 空台番号除外: "
        f"{removed_count}行"
    )

    # -----------------------------------------------------
    # DBの最新実行日データ取得
    # -----------------------------------------------------

    sql = f"""
        SELECT
            {quote_identifier("実行日")},
            {quote_identifier("台番号")}
        FROM {quote_identifier(TABLE_NAME)}
        WHERE
            {quote_identifier("台番号")} IS NOT NULL
            AND TRIM(
                {quote_identifier("台番号")}
            ) <> ''
        ORDER BY ROWID DESC
    """

    with sqlite3.connect(db_path) as connection:
        db_dataframe = pd.read_sql_query(
            sql,
            connection,
        )

    if db_dataframe.empty:
        raise ValueError(
            "[ERROR] DBに台番号データがありません。"
        )

    db_dataframe["実行日"] = pd.to_datetime(
        db_dataframe["実行日"],
        errors="coerce",
    )

    db_dataframe = db_dataframe.dropna(
        subset=["実行日"],
    ).copy()

    if db_dataframe.empty:
        raise ValueError(
            "[ERROR] DB側に有効な実行日データがありません。"
        )

    latest_date = (
        db_dataframe["実行日"]
        .dt.date
        .max()
    )

    latest_dataframe = (
        db_dataframe[
            db_dataframe["実行日"].dt.date
            == latest_date
        ]
        .sort_values(
            "実行日",
            ascending=False,
        )
        .copy()
    )

    latest_dataframe[
        "照合用台番号"
    ] = latest_dataframe[
        "台番号"
    ].map(
        normalize_machine_number
    )

    latest_dataframe = (
        latest_dataframe[
            latest_dataframe["照合用台番号"]
            != ""
        ]
        .drop_duplicates(
            subset=["照合用台番号"],
            keep="first",
        )
        .copy()
    )

    print(
        f"[DB] 最新実行日: "
        f"{latest_date}"
    )
    print(
        f"[DB] 最新日の台数: "
        f"{len(latest_dataframe)}台"
    )

    # -----------------------------------------------------
    # DBに存在するカラムだけを更新対象にする
    # -----------------------------------------------------

    with sqlite3.connect(db_path) as connection:
        table_columns = get_table_columns(
            connection,
            TABLE_NAME,
        )

    # 空見出し・台番号・DBに存在しない見出しを除外
    valid_columns = [
        column
        for column in dataframe.columns
        if (
            column
            and column != "台番号"
            and column in table_columns
        )
    ]

    missing_db_columns = [
        column
        for column in dataframe.columns
        if (
            column
            and column != "台番号"
            and column not in table_columns
        )
    ]

    print(
        f"[DB] 更新対象カラム数: "
        f"{len(valid_columns)}列"
    )

    if missing_db_columns:
        print(
            f"[WARN] DBに存在しないため除外: "
            f"{len(missing_db_columns)}列"
        )

        for column in missing_db_columns:
            print(
                f"  - {column}"
            )

    if not valid_columns:
        raise ValueError(
            "[ERROR] DBへ更新できるカラムがありません。"
        )

    # -----------------------------------------------------
    # スプレッドシート側を台番号で検索できるようにする
    # -----------------------------------------------------

    dataframe = dataframe.copy()

    dataframe[
        "照合用台番号"
    ] = dataframe[
        "台番号"
    ].map(
        normalize_machine_number
    )

    spreadsheet_row_map: dict[
        str,
        pd.Series,
    ] = {}

    duplicate_machine_numbers: list[str] = []

    for _, row in dataframe.iterrows():
        machine_number = str(
            row["照合用台番号"]
        ).strip()

        if not machine_number:
            continue

        if machine_number in spreadsheet_row_map:
            duplicate_machine_numbers.append(
                machine_number
            )
            continue

        spreadsheet_row_map[
            machine_number
        ] = row

    if duplicate_machine_numbers:
        print(
            "[WARN] スプレッドシートに"
            "重複台番号があります。"
            "最初の行を使用します:"
        )

        print(
            "  "
            + ", ".join(
                sorted(
                    set(
                        duplicate_machine_numbers
                    )
                )
            )
        )

    print(
        f"[DATA] 台番号マッピング作成完了: "
        f"{len(spreadsheet_row_map)}台"
    )

    # -----------------------------------------------------
    # DB更新
    # -----------------------------------------------------

    set_clause = ", ".join(
        f"{quote_identifier(column)} = ?"
        for column in valid_columns
    )

    update_sql = f"""
        UPDATE {quote_identifier(TABLE_NAME)}
        SET
            {set_clause}
        WHERE
            {quote_identifier("台番号")} = ?
            AND date(
                {quote_identifier("実行日")}
            ) = ?
    """

    updated_machine_count = 0
    updated_record_count = 0
    skipped_machine_numbers: list[str] = []

    with sqlite3.connect(db_path) as connection:
        cursor = connection.cursor()

        for _, db_row in latest_dataframe.iterrows():
            db_machine_number_raw = str(
                db_row["台番号"]
            ).strip()

            normalized_machine_number = str(
                db_row["照合用台番号"]
            ).strip()

            spreadsheet_row = (
                spreadsheet_row_map.get(
                    normalized_machine_number
                )
            )

            if spreadsheet_row is None:
                skipped_machine_numbers.append(
                    db_machine_number_raw
                )

                print(
                    f"[SKIP] 台番号 "
                    f"{db_machine_number_raw} "
                    f"がスプレッドシートにありません。"
                )
                continue

            execution_date = (
                db_row["実行日"]
                .strftime("%Y-%m-%d")
            )

            parameters = [
                spreadsheet_row[column]
                for column in valid_columns
            ]

            # WHEREにはDBに保存されている元の台番号を使う。
            parameters.extend([
                db_machine_number_raw,
                execution_date,
            ])

            cursor.execute(
                update_sql,
                parameters,
            )

            affected_rows = cursor.rowcount

            if affected_rows > 0:
                updated_machine_count += 1
                updated_record_count += affected_rows

                print(
                    f"[UPDATE] 台番号="
                    f"{db_machine_number_raw}, "
                    f"更新レコード={affected_rows}"
                )
            else:
                print(
                    f"[WARN] UPDATE対象なし: "
                    f"台番号={db_machine_number_raw}, "
                    f"実行日={execution_date}"
                )

        connection.commit()

    # -----------------------------------------------------
    # 完了ログ
    # -----------------------------------------------------

    print(
        f"[DB] 設定値更新完了: "
        f"{updated_machine_count}台"
    )

    print(
        f"[DB] 更新レコード数: "
        f"{updated_record_count}件"
    )

    print(
        f"[DB] スプレッドシート不在: "
        f"{len(skipped_machine_numbers)}台"
    )

    elapsed_time = time.time() - start_time

    print(
        f"[INFO] 実行時間: "
        f"{elapsed_time:.1f}秒"
    )


# =========================================================
# 実行
# =========================================================

if __name__ == "__main__":
    main()