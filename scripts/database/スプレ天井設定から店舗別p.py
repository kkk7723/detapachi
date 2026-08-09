from __future__ import annotations

import argparse
import importlib
import re
import sys
import time
import unicodedata
from pathlib import Path
from typing import Any

import gspread
from google.oauth2.service_account import Credentials


# =========================================================
# プロジェクトルート設定
# =========================================================

def find_project_root(start_path: Path) -> Path:
    """
    config/ と utils/ が存在するディレクトリを
    detapachiのプロジェクトルートとして返す。
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
        "detapachiのプロジェクトルートを特定できません。"
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
# プロジェクト共通設定
# =========================================================

from config.common import (
    DEFAULT_SITE,
    GOOGLE_CREDENTIALS_FILE,
    GOOGLE_SCOPES,
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
    "GSHEET_NAME",
    "SHEET_NAME",
)

for setting_name in required_site_settings:
    if not hasattr(site_config, setting_name):
        raise AttributeError(
            f"config/{args.site}.py に "
            f"{setting_name} が設定されていません。"
        )


print(f"[INFO] 対象店舗: {args.site}")
print(
    f"[INFO] 店舗シート: "
    f"{site_config.GSHEET_NAME} / "
    f"{site_config.SHEET_NAME}"
)


# =========================================================
# 参照元マスター設定
# =========================================================

# 参照元となる共通マスターブックID
TARGET_SHEET_ID = (
    "1rfYzr3be-A8OFBcspv-YAb430Dx6HPO1Wb9ruoI-cXU"
)

# 参照元タブ
TARGET_SHEET_NAME = "pachi"


# =========================================================
# スプレッドシート範囲設定
# =========================================================

# 店舗シート側
RANGE_SEARCH     = "E4:E4000"     # 検索キーワード（SRC）
RANGE_URL_OUT    = "L4:L4000"     # URL出力（SRC）
RANGE_BLOCK_OUT  = "M4:AH4000"    # ブロック出力（SRC, 22列）

# 共通マスター側
RANGE_KEYWORD    = "AL4:BN4000"   # キーワード列群（TARGET, 可変列）
RANGE_URL_SRC    = "B4:B4000"     # URL列（TARGET）
RANGE_BLOCK_SRC  = "P4:AK4000"    # ブロック（TARGET, 22列）

ROW_START = 4
ROW_END = 1000

# 4～500行
N_ROWS = ROW_END - ROW_START + 1

# M～BX、BU～EFは64列
N_BLOCK_COLS = 22                     # M..AH / P..AK は22列


# =========================================================
# 正規化・配列整形
# =========================================================

def normalize_text(value: Any) -> str:
    """
    照合用文字列を正規化する。

    処理:
    - NFKC正規化
    - ゼロ幅空白除去
    - 全角スペースを半角へ統一
    - 連続空白を1文字へ圧縮
    - 前後空白除去
    - 小文字化
    """
    text = (
        ""
        if value is None
        else str(value)
    )

    text = unicodedata.normalize(
        "NFKC",
        text,
    )

    text = text.replace(
        "\u3000",
        " ",
    )

    text = re.sub(
        r"[\u200B-\u200D\uFEFF]",
        "",
        text,
    )

    text = re.sub(
        r"\s+",
        " ",
        text,
    ).strip()

    return text.lower()


def pad_rows_2d(
    rows: list | None,
    row_count: int,
    column_count: int,
) -> list[list[Any]]:
    """
    2次元配列を指定した行数・列数に整形する。

    不足するセルは空文字で埋め、
    余分な列は切り捨てる。
    """
    source_rows = rows or []
    output: list[list[Any]] = []

    for row_index in range(row_count):
        if row_index < len(source_rows):
            source_row = source_rows[row_index]

            if isinstance(
                source_row,
                (list, tuple),
            ):
                row = [
                    ""
                    if value is None
                    else value
                    for value in source_row
                ]
            else:
                row = [
                    ""
                    if source_row is None
                    else source_row
                ]
        else:
            row = []

        if len(row) < column_count:
            row.extend(
                [""] * (
                    column_count - len(row)
                )
            )
        else:
            row = row[:column_count]

        output.append(row)

    return output


def pad_column_2d(
    column_values: list | None,
    row_count: int,
) -> list[list[Any]]:
    """
    Google Sheetsから取得した1列データを
    指定行数×1列に整形する。

    空行が [] で返る場合にも対応する。
    """
    source_values = column_values or []
    output: list[list[Any]] = []

    for row_index in range(row_count):
        value: Any = ""

        if row_index < len(source_values):
            source_row = source_values[
                row_index
            ]

            if isinstance(
                source_row,
                (list, tuple),
            ):
                if source_row:
                    value = (
                        ""
                        if source_row[0] is None
                        else source_row[0]
                    )
            else:
                value = (
                    ""
                    if source_row is None
                    else source_row
                )

        output.append([value])

    return output


# =========================================================
# Google Sheets認証
# =========================================================

def create_gspread_client() -> gspread.Client:
    """
    config/common.py の認証設定を使って
    gspreadクライアントを作成する。
    """
    credentials_path = require_file(
        GOOGLE_CREDENTIALS_FILE,
        "GoogleサービスアカウントJSON",
    )

    credentials = (
        Credentials.from_service_account_file(
            str(credentials_path),
            scopes=list(GOOGLE_SCOPES),
        )
    )

    return gspread.authorize(
        credentials
    )


# =========================================================
# メイン処理
# =========================================================

def main() -> None:
    start_time = time.time()

    # -----------------------------------------------------
    # Google Sheets接続
    # -----------------------------------------------------

    print("[SHEET] Google Sheets認証開始")

    client = create_gspread_client()

    # 店舗別の検索元シート
    worksheet_source = (
        client.open(
            site_config.GSHEET_NAME
        ).worksheet(
            site_config.SHEET_NAME
        )
    )

    print(
        f"[SHEET] 店舗シート取得完了: "
        f"{site_config.GSHEET_NAME} / "
        f"{site_config.SHEET_NAME}"
    )

    # 共通マスター
    workbook_target = client.open_by_key(
        TARGET_SHEET_ID
    )

    worksheet_target = (
        workbook_target.worksheet(
            TARGET_SHEET_NAME
        )
    )

    print(
        f"[SHEET] 参照元マスター取得完了: "
        f"{TARGET_SHEET_NAME}"
    )

    # -----------------------------------------------------
    # 店舗シートから検索語を取得
    # -----------------------------------------------------

    try:
        search_values_raw = (
            worksheet_source.get(
                RANGE_SEARCH
            )
        )
    except Exception as exc:
        raise RuntimeError(
            "[SHEET] 店舗シートの検索語取得失敗: "
            f"{exc}"
        ) from exc

    search_values = pad_column_2d(
        search_values_raw,
        N_ROWS,
    )

    print(
        f"[SHEET] 店舗検索語取得完了: "
        f"{len(search_values)}行"
    )

    # -----------------------------------------------------
    # 共通マスターからデータ取得
    # -----------------------------------------------------

    try:
        keyword_matrix_raw = (
            worksheet_target.get(
                RANGE_KEYWORD
            )
        )

        url_column_raw = (
            worksheet_target.get(
                RANGE_URL_SRC
            )
        )

        block_matrix_raw = (
            worksheet_target.get(
                RANGE_BLOCK_SRC
            )
        )

    except Exception as exc:
        raise RuntimeError(
            "[SHEET] 共通マスターデータ取得失敗: "
            f"{exc}"
        ) from exc

    # 別名列は末尾の空セルが省略されるため、
    # 全行中の最大列数を採用する。
    keyword_column_count = max(
        (
            len(row)
            for row in (
                keyword_matrix_raw or [[]]
            )
            if isinstance(
                row,
                (list, tuple),
            )
        ),
        default=0,
    )

    if keyword_column_count < 1:
        keyword_column_count = 1

    keyword_matrix = pad_rows_2d(
        keyword_matrix_raw,
        N_ROWS,
        keyword_column_count,
    )

    url_column = pad_column_2d(
        url_column_raw,
        N_ROWS,
    )

    block_matrix = pad_rows_2d(
        block_matrix_raw,
        N_ROWS,
        N_BLOCK_COLS,
    )

    print(
        f"[SHEET] 共通マスター取得完了: "
        f"キーワード列={keyword_column_count}, "
        f"行数={N_ROWS}, "
        f"設定列={N_BLOCK_COLS}"
    )

    # -----------------------------------------------------
    # 正規化キーワード → マスター行番号
    # -----------------------------------------------------

    keyword_index: dict[str, int] = {}

    duplicate_count = 0

    for row_index in range(N_ROWS):
        keyword_row = keyword_matrix[
            row_index
        ]

        for column_index in range(
            keyword_column_count
        ):
            raw_keyword = (
                keyword_row[column_index]
                if column_index
                < len(keyword_row)
                else ""
            )

            normalized_keyword = (
                normalize_text(
                    raw_keyword
                )
            )

            if not normalized_keyword:
                continue

            # 同じ別名が複数行にある場合は
            # 最初に出た行を優先する。
            if normalized_keyword in keyword_index:
                duplicate_count += 1
                continue

            keyword_index[
                normalized_keyword
            ] = row_index

    print(
        f"[MATCH] マスター検索キー作成完了: "
        f"{len(keyword_index)}件"
    )

    if duplicate_count:
        print(
            f"[MATCH] 重複キー: "
            f"{duplicate_count}件 "
            f"（先に出た行を採用）"
        )

    # -----------------------------------------------------
    # 書き込みデータ作成
    # -----------------------------------------------------

    url_output: list[list[Any]] = []
    block_output: list[list[Any]] = []

    empty_block = [
        ""
    ] * N_BLOCK_COLS

    matched_count = 0
    empty_count = 0
    unmatched_count = 0

    unmatched_debug: list[
        tuple[int, Any, str]
    ] = []

    for row_index in range(N_ROWS):
        source_row = search_values[
            row_index
        ]

        raw_term = (
            source_row[0]
            if source_row
            else ""
        )

        normalized_term = normalize_text(
            raw_term
        )

        # 店舗シートの検索語が空欄
        if not normalized_term:
            url_output.append([""])
            block_output.append(
                empty_block.copy()
            )

            empty_count += 1
            continue

        matched_row_index = (
            keyword_index.get(
                normalized_term
            )
        )

        # 共通マスターに一致なし
        if matched_row_index is None:
            url_output.append([
                "一致なし"
            ])

            block_output.append(
                empty_block.copy()
            )

            unmatched_count += 1

            if len(unmatched_debug) < 10:
                unmatched_debug.append(
                    (
                        row_index + ROW_START,
                        raw_term,
                        normalized_term,
                    )
                )

            continue

        # URL取得
        url_value: Any = ""

        if (
            matched_row_index
            < len(url_column)
            and url_column[
                matched_row_index
            ]
        ):
            url_value = (
                url_column[
                    matched_row_index
                ][0]
                or ""
            )

        url_output.append([
            url_value
        ])

        # 設定値64列取得
        matched_block = (
            block_matrix[
                matched_row_index
            ]
            if matched_row_index
            < len(block_matrix)
            else empty_block
        )

        normalized_block = [
            ""
            if value is None
            else value
            for value in matched_block
        ]

        block_output.append(
            normalized_block
        )

        matched_count += 1

    # 念のため最終的な配列サイズを固定
    url_output = pad_rows_2d(
        url_output,
        N_ROWS,
        1,
    )

    block_output = pad_rows_2d(
        block_output,
        N_ROWS,
        N_BLOCK_COLS,
    )

    print(
        f"[MATCH] 一致: "
        f"{matched_count}件"
    )
    print(
        f"[MATCH] 不一致: "
        f"{unmatched_count}件"
    )
    print(
        f"[MATCH] 検索語空欄: "
        f"{empty_count}件"
    )

    # -----------------------------------------------------
    # 店舗シートへ一括書き込み
    # -----------------------------------------------------

    try:
        worksheet_source.batch_update([
            {
                "range": RANGE_URL_OUT,
                "values": url_output,
            },
            {
                "range": RANGE_BLOCK_OUT,
                "values": block_output,
            },
        ])
    except Exception as exc:
        raise RuntimeError(
            "[SHEET] 一括書き込み失敗: "
            f"{exc}"
        ) from exc

    print(
        f"[SHEET] URL書き込み完了: "
        f"{RANGE_URL_OUT}"
    )
    print(
        f"[SHEET] 設定値書き込み完了: "
        f"{RANGE_BLOCK_OUT}"
    )

    # -----------------------------------------------------
    # 未一致デバッグ
    # -----------------------------------------------------

    if unmatched_debug:
        print(
            "[DEBUG] 未一致例 "
            "（先頭10件: 行番号 / 原文 / 正規化後）"
        )

        for (
            sheet_row_number,
            raw_value,
            normalized_value,
        ) in unmatched_debug:
            print(
                f"  - 行{sheet_row_number}: "
                f"{raw_value!r} "
                f"=> {normalized_value!r}"
            )

    elapsed_time = (
        time.time() - start_time
    )

    print(
        f"[INFO] 完了: "
        f"{N_ROWS}行処理 / "
        f"{elapsed_time:.2f}秒"
    )


# =========================================================
# 実行
# =========================================================

if __name__ == "__main__":
    main()