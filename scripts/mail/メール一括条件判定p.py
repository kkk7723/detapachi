from __future__ import annotations

import argparse
import html
import importlib
import re
import smtplib
import sqlite3
import sys
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd


# =========================================================
# プロジェクトルート設定
# =========================================================

def find_project_root(
    start_path: Path,
) -> Path:
    """
    config/ と utils/ が存在するディレクトリを
    detapachiのプロジェクトルートとして返す。
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
        "detapachiのプロジェクトルートを"
        "特定できませんでした。"
        f" 開始位置: {start_path}"
    )


if "__file__" in globals():
    # scripts/mail/*.py から実行
    PROJECT_ROOT = find_project_root(
        Path(__file__)
    )
else:
    # Notebookから実行
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
    MAIL_APP_PASSWORD,
    MAIL_RECEIVER_EMAILS,
    MAIL_SENDER_EMAIL,
    SMTP_PORT,
    SMTP_SERVER,
    TABLE_NAME,
    require_file,
)


# =========================================================
# 店舗選択
# =========================================================

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
        f"店舗設定が見つかりません: "
        f"{config_file}"
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
    "LOG_FILE_SUFFIX",
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

spreadsheet_name = str(
    site_config.GSHEET_NAME
)

worksheet_name = str(
    site_config.SHEET_NAME
)

shop_name = str(
    getattr(
        site_config,
        "SHOP_NAME",
        spreadsheet_name,
    )
)

public_base_url = str(
    getattr(
        site_config,
        "SITE_PUBLIC_BASE_URL",
        (
            "https://sedoinfinity.xsrv.jp/"
            f"{args.site}"
        ),
    )
).rstrip("/")

log_file_suffix = str(
    site_config.LOG_FILE_SUFFIX
)

log_root_dir = Path(
    getattr(
        site_config,
        "LOG_ROOT_DIR",
        "/home/ubuntu/logs/detapachi",
    )
)

power_off_text = str(
    getattr(
        site_config,
        "POWER_OFF_TEXT",
        "電源OFF",
    )
)

power_on_text = str(
    getattr(
        site_config,
        "POWER_ON_TEXT",
        "電源ON",
    )
)


print(f"[INFO] 対象店舗: {args.site}")
print(f"[INFO] 店舗名: {shop_name}")
print(f"[INFO] 使用DB: {db_path}")
print(f"[INFO] 対象テーブル: {TABLE_NAME}")

print(
    f"[INFO] 公開URL基準: "
    f"{public_base_url}"
)

print(
    f"[INFO] ログファイル末尾: "
    f"{log_file_suffix}"
)

print(
    f"[INFO] ログルート: "
    f"{log_root_dir}"
)

print(
    f"[INFO] メール送信元: "
    f"{MAIL_SENDER_EMAIL}"
)

print(
    f"[INFO] メール送信先: "
    f"{', '.join(MAIL_RECEIVER_EMAILS)}"
)


# =========================================================
# 判定対象カラム
# =========================================================

BORDER_COLUMNS = [
    (
        f"等価削りあり{rotation}"
        "回転プラマイボーダー残りゲーム数"
    )
    for rotation in range(
        13,
        21,
    )
]


THRESHOLD_COLUMNS = [
    "出玉数初当り確率最終回転率",
    "出玉数noボナ回転率",
    "svg差枚noボナ回転率",
    "svg差枚最終回転率",
]


# =========================================================
# メール表示カラム
# =========================================================

DISPLAY_COLUMNS = [
    "台番号",
    "サイト",
    "pscubeURL",
    "ptoolURL",
    "ぱち解析URL",
    "期待値URL",
    "機種名",
    "大当り回数",
    "最終スタート",
    "宵越し累計ゲーム数",
]


# =========================================================
# DBから取得する基本カラム
# =========================================================

BASE_NEEDED_COLUMNS = [
    "実行日",
    "台番号",

    # メール表示用
    "pscubeURL",
    "ptoolURL",
    "ぱち解析URL",
    "期待値URL",
    "機種名",
    "大当り回数",
    "最終スタート",
    "宵越し累計ゲーム数",

    # 初当り・継続判定用
    "宵越し最終ステータス",
    "機種別回転設定値",
    "単発後天井残りゲーム数",
    "確変後天井残りゲーム数",

    # ボーダー判定用
    *BORDER_COLUMNS,

    # 回転率判定用
    *THRESHOLD_COLUMNS,
]


# =========================================================
# メールCSS
# =========================================================

TABLE_CSS = """
<style>
body {
    font-family:
        Arial,
        "Noto Sans JP",
        sans-serif;
    color: #222;
}

.styled-table {
    border-collapse: collapse;
    width: 100%;
    margin-top: 8px;
}

.styled-table th,
.styled-table td {
    border: 1px solid #ccc;
    padding: 5px;
    text-align: left;
    white-space: nowrap;
}

.styled-table th {
    background-color: #f2f2f2;
}

.section {
    margin: 14px 0 24px;
}

.section h2 {
    margin: 0 0 8px;
}

hr {
    border: none;
    border-top: 1px solid #ddd;
    margin: 16px 0;
}

.small {
    color: #666;
    font-size: 12px;
}
</style>
"""


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
    SQLiteテーブルのカラム名を取得する。
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
# 値変換
# =========================================================

def normalize_machine_number(
    value: Any,
) -> str:
    """
    台番号をURL用の文字列に変換する。

    例:
        32   -> "32"
        0032 -> "32"
        32.0 -> "32"
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

    if text.isdigit():
        return str(
            int(text)
        )

    return text


def is_valid_url(
    value: Any,
) -> bool:
    """
    HTTPまたはHTTPSのURLか確認する。
    """
    if not isinstance(
        value,
        str,
    ):
        return False

    text = value.strip()

    return (
        text.startswith("http://")
        or text.startswith("https://")
    )


def make_anchor(
    url: str,
    label: str = "リンク",
) -> str:
    """
    HTMLリンクを作成する。
    """
    escaped_url = html.escape(
        url,
        quote=True,
    )

    escaped_label = html.escape(
        label,
    )

    return (
        f'<a href="{escaped_url}" '
        f'target="_blank" '
        f'rel="noopener noreferrer">'
        f"{escaped_label}</a>"
    )


def convert_url_columns_to_anchor(
    dataframe: pd.DataFrame,
) -> pd.DataFrame:
    """
    URLカラムをHTMLリンクへ変換する。
    """
    output = dataframe.copy()

    url_columns = [
        column
        for column in output.columns
        if (
            "URL" in str(column)
            or str(column).startswith(
                "img_url_"
            )
        )
    ]

    for column in url_columns:
        output[column] = output[
            column
        ].apply(
            lambda value: (
                make_anchor(
                    value.strip()
                )
                if is_valid_url(value)
                else value
            )
        )

    return output


def clean_number_for_display(
    value: Any,
) -> Any:
    """
    メール表示用に数値を整形する。
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

    try:
        number = float(value)

        if number.is_integer():
            return int(number)

        return number

    except (
        TypeError,
        ValueError,
    ):
        return value


# =========================================================
# メール設定確認
# =========================================================

def validate_mail_settings() -> None:
    """
    メール設定に不足がないか確認する。
    """
    missing_settings: list[str] = []

    if not SMTP_SERVER:
        missing_settings.append(
            "SMTP_SERVER"
        )

    if not SMTP_PORT:
        missing_settings.append(
            "SMTP_PORT"
        )

    if not MAIL_SENDER_EMAIL:
        missing_settings.append(
            "MAIL_SENDER_EMAIL"
        )

    if not MAIL_APP_PASSWORD:
        missing_settings.append(
            "MAIL_APP_PASSWORD"
        )

    if not MAIL_RECEIVER_EMAILS:
        missing_settings.append(
            "MAIL_RECEIVER_EMAILS"
        )

    if missing_settings:
        raise RuntimeError(
            "config/common.py のメール設定が"
            "不足しています: "
            + ", ".join(
                missing_settings
            )
        )


# =========================================================
# メール送信
# =========================================================

def send_email(
    subject: str,
    html_body: str,
) -> None:
    """
    HTMLメールを送信する。
    """
    validate_mail_settings()

    message = MIMEMultipart(
        "alternative"
    )

    message["From"] = formataddr((
        shop_name,
        MAIL_SENDER_EMAIL,
    ))

    message["To"] = ", ".join(
        MAIL_RECEIVER_EMAILS
    )

    message["Subject"] = subject

    message.attach(
        MIMEText(
            html_body,
            "html",
            "utf-8",
        )
    )

    try:
        with smtplib.SMTP(
            SMTP_SERVER,
            SMTP_PORT,
            timeout=30,
        ) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()

            server.login(
                MAIL_SENDER_EMAIL,
                MAIL_APP_PASSWORD,
            )

            server.sendmail(
                MAIL_SENDER_EMAIL,
                MAIL_RECEIVER_EMAILS,
                message.as_string(),
            )

        print(
            f"[MAIL] 送信完了: "
            f"{subject}"
        )

    except Exception as exc:
        raise RuntimeError(
            "[MAIL] メール送信失敗: "
            f"{type(exc).__name__}: "
            f"{exc}"
        ) from exc


# =========================================================
# メール表作成
# =========================================================

def build_mail_table(
    source_dataframe: pd.DataFrame,
    extra_columns: list[str],
) -> str:
    """
    条件一致データからHTMLテーブルを作成する。
    """
    base_columns = [
        column
        for column in DISPLAY_COLUMNS
        if column in source_dataframe.columns
    ]

    valid_extra_columns = [
        column
        for column in extra_columns
        if column in source_dataframe.columns
    ]

    output_columns = list(
        dict.fromkeys(
            base_columns
            + valid_extra_columns
        )
    )

    if not output_columns:
        return (
            "<p>表示可能なカラムが"
            "ありません。</p>"
        )

    mail_dataframe = (
        source_dataframe[
            output_columns
        ]
        .copy()
    )

    if "台番号" in mail_dataframe.columns:
        mail_dataframe[
            "台番号_ソート用"
        ] = pd.to_numeric(
            mail_dataframe["台番号"],
            errors="coerce",
        )

        mail_dataframe = (
            mail_dataframe
            .sort_values(
                [
                    "台番号_ソート用",
                    "台番号",
                ],
                ascending=True,
                na_position="last",
            )
            .drop(
                columns=[
                    "台番号_ソート用"
                ]
            )
        )

    for column in mail_dataframe.columns:
        if (
            "URL" in str(column)
            or str(column).startswith(
                "img_url_"
            )
            or column == "サイト"
        ):
            continue

        mail_dataframe[column] = (
            mail_dataframe[column]
            .map(
                clean_number_for_display
            )
        )

    return mail_dataframe.to_html(
        index=False,
        escape=False,
        border=1,
        classes="styled-table",
    )


# =========================================================
# 最新データ取得
# =========================================================

def load_latest_data() -> tuple[
    pd.DataFrame,
    Any,
]:
    """
    DB内の最新日について、
    各台の最新1レコードを取得する。
    """
    require_file(
        db_path,
        "店舗別SQLiteデータベース",
    )

    needed_columns = list(
        dict.fromkeys(
            BASE_NEEDED_COLUMNS
        )
    )

    with sqlite3.connect(
        db_path
    ) as connection:
        existing_columns = (
            get_table_columns(
                connection,
                TABLE_NAME,
            )
        )

        if "実行日" not in existing_columns:
            raise RuntimeError(
                f"{TABLE_NAME} に"
                "実行日カラムがありません。"
            )

        if "台番号" not in existing_columns:
            raise RuntimeError(
                f"{TABLE_NAME} に"
                "台番号カラムがありません。"
            )

        select_columns = [
            column
            for column in needed_columns
            if column in existing_columns
        ]

        missing_columns = [
            column
            for column in needed_columns
            if column not in existing_columns
        ]

        if missing_columns:
            print(
                "[WARN] DBに存在しないため"
                "取得対象から除外: "
                f"{len(missing_columns)}列"
            )

            for column in missing_columns:
                print(
                    f"  - {column}"
                )

        select_clause = ", ".join(
            quote_identifier(column)
            for column in select_columns
        )

        sql = f"""
            SELECT
                ROWID AS _rowid,
                {select_clause}
            FROM {quote_identifier(TABLE_NAME)}
            ORDER BY
                datetime(
                    {quote_identifier("実行日")}
                ) DESC,
                ROWID DESC
        """

        dataframe = pd.read_sql_query(
            sql,
            connection,
        )

    if dataframe.empty:
        raise RuntimeError(
            "DBに対象データがありません。"
        )

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

    if dataframe.empty:
        raise RuntimeError(
            "有効な実行日・台番号を持つ"
            "データがありません。"
        )

    latest_date = (
        dataframe["実行日"]
        .dt.date
        .max()
    )

    latest_dataframe = dataframe[
        dataframe["実行日"].dt.date
        == latest_date
    ].copy()

    # 同じ台番号では最新1レコードだけ採用
    latest_dataframe = (
        latest_dataframe
        .sort_values(
            [
                "台番号",
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
            subset=["台番号"],
            keep="first",
        )
        .copy()
    )

    print(
        f"[DB] 最新日: "
        f"{latest_date}"
    )

    print(
        f"[DB] 最新日の対象台数: "
        f"{len(latest_dataframe)}台"
    )

    return (
        latest_dataframe,
        latest_date,
    )


# =========================================================
# サイトリンク作成
# =========================================================

def add_site_links(
    dataframe: pd.DataFrame,
) -> pd.DataFrame:
    """
    台番号ごとの公開ページリンクを作成する。
    """
    output = dataframe.copy()

    def create_site_link(
        machine_number: Any,
    ) -> str:
        normalized_number = (
            normalize_machine_number(
                machine_number
            )
        )

        if not normalized_number:
            return ""

        machine_url = (
            f"{public_base_url}/machines/"
            f"{normalized_number}.html"
        )

        return make_anchor(
            machine_url
        )

    output["サイト"] = output[
        "台番号"
    ].map(
        create_site_link
    )

    return output


# =========================================================
# 初当り・継続の残りゲーム数判定
# =========================================================

def check_and_notify(
    dataframe: pd.DataFrame,
    latest_date: Any,
    kind_label: str,
    remain_column: str,
) -> tuple[list[str], int]:
    """
    宵越し最終ステータス別に判定する。

    条件:
        残りゲーム数
        <
        機種別回転設定値に対応する
        ボーダー残りゲーム数
    """
    temporary = dataframe.copy()

    required_columns = [
        "宵越し最終ステータス",
        "機種別回転設定値",
        remain_column,
    ]

    missing_columns = [
        column
        for column in required_columns
        if column not in temporary.columns
    ]

    if missing_columns:
        print(
            f"[WARN] {kind_label}判定に"
            "必要なカラムがありません: "
            f"{missing_columns}"
        )

        return [], 0

    temporary[
        remain_column
    ] = pd.to_numeric(
        temporary[remain_column],
        errors="coerce",
    )

    temporary[
        "機種別回転設定値"
    ] = pd.to_numeric(
        temporary["機種別回転設定値"],
        errors="coerce",
    )

    temporary = temporary[
        temporary["宵越し最終ステータス"]
        .astype(str)
        .str.strip()
        == kind_label
    ].copy()

    if temporary.empty:
        print(
            f"[INFO] {kind_label}: "
            "対象ステータスなし"
        )

        return [], 0

    rotation_to_column = {
        rotation: (
            f"等価削りあり{rotation}"
            "回転プラマイボーダー残りゲーム数"
        )
        for rotation in range(
            13,
            21,
        )
        if (
            f"等価削りあり{rotation}"
            "回転プラマイボーダー残りゲーム数"
        )
        in temporary.columns
    }

    if not rotation_to_column:
        print(
            f"[WARN] {kind_label}: "
            "ボーダーカラムがありません"
        )

        return [], 0

    sections: list[str] = []
    total_hits = 0

    for (
        rotation,
        border_column,
    ) in rotation_to_column.items():
        subset = temporary[
            temporary["機種別回転設定値"]
            == rotation
        ].copy()

        if subset.empty:
            continue

        subset[border_column] = pd.to_numeric(
            subset[border_column],
            errors="coerce",
        )

        hits = subset[
            subset[remain_column].notna()
            & subset[border_column].notna()
            & (
                subset[remain_column]
                < subset[border_column]
            )
        ].copy()

        if hits.empty:
            continue

        table_html = build_mail_table(
            hits,
            [
                "宵越し最終ステータス",
                "機種別回転設定値",
                remain_column,
                border_column,
            ],
        )

        section_html = f"""
        <div class="section">
            <h2>
                {html.escape(kind_label)}
                条件一致
                （機種別回転設定値{rotation}）
                {len(hits)}件
                ({latest_date})
            </h2>

            {table_html}
        </div>
        """

        sections.append(
            section_html
        )

        total_hits += len(hits)

        print(
            f"[HIT] {kind_label} "
            f"回転設定値{rotation}: "
            f"{len(hits)}件"
        )

    if total_hits == 0:
        print(
            f"[INFO] {kind_label}: "
            "条件一致なし"
        )

    return (
        sections,
        total_hits,
    )


# =========================================================
# 回転率設定値超え判定
# =========================================================

def notify_threshold_over(
    dataframe: pd.DataFrame,
    latest_date: Any,
) -> tuple[str, int]:
    """
    次の4カラムのいずれかが
    機種別回転設定値を超えた台を通知する。

    - 出玉数初当り確率最終回転率
    - 出玉数noボナ回転率
    - svg差枚noボナ回転率
    - svg差枚最終回転率
    """
    temporary = dataframe.copy()

    setting_column = (
        "機種別回転設定値"
    )

    existing_target_columns = [
        column
        for column in THRESHOLD_COLUMNS
        if column in temporary.columns
    ]

    if setting_column not in temporary.columns:
        print(
            "[WARN] 機種別回転設定値が"
            "存在しないため、"
            "回転率判定をスキップ"
        )

        return "", 0

    if not existing_target_columns:
        print(
            "[WARN] 回転率判定カラムが"
            "存在しないためスキップ"
        )

        return "", 0

    temporary[
        setting_column
    ] = pd.to_numeric(
        temporary[setting_column],
        errors="coerce",
    )

    for column in existing_target_columns:
        temporary[column] = pd.to_numeric(
            temporary[column],
            errors="coerce",
        )

    # 4種類のうち1つでも
    # 機種別回転設定値を超えたら対象
    condition = temporary[
        existing_target_columns
    ].gt(
        temporary[setting_column],
        axis=0,
    ).any(
        axis=1
    )

    hits = temporary[
        condition
        & temporary[setting_column].notna()
    ].copy()

    if hits.empty:
        print(
            "[INFO] 回転率設定値超えなし"
        )

        return "", 0

    table_html = build_mail_table(
        hits,
        [
            setting_column,
            *existing_target_columns,
        ],
    )

    section_html = f"""
    <div class="section">
        <h2>
            回転率設定値超えアラート
            {len(hits)}台
            ({latest_date})
        </h2>

        {table_html}
    </div>
    """

    print(
        f"[HIT] 回転率設定値超え: "
        f"{len(hits)}台"
    )

    return (
        section_html,
        len(hits),
    )


# =========================================================
# 当日ログ取得・イベント集計
# =========================================================

def get_today_log_path() -> Path | None:
    """
    Asia/Tokyo の本日日付フォルダから、
    対象店舗の最新ログファイルを取得する。

    例:
        /home/ubuntu/logs/detapachi/
        20260810/
        001001_ootake_maruhachi_p.log

    店舗config:
        LOG_FILE_SUFFIX = "ootake_maruhachi_p.log"

    実際の検索:
        *_ootake_maruhachi_p.log
    """
    today_text = (
        pd.Timestamp.now(
            tz=ZoneInfo("Asia/Tokyo")
        )
        .strftime("%Y%m%d")
    )

    log_dir = (
        log_root_dir
        / today_text
    )

    if not log_dir.is_dir():
        print(
            f"[WARN] 当日ログディレクトリが"
            f"見つかりません: {log_dir}"
        )
        return None

    pattern = f"*_{log_file_suffix}"

    log_files = [
        path
        for path in log_dir.glob(pattern)
        if path.is_file()
    ]

    if not log_files:
        print(
            f"[WARN] 対象ログが見つかりません: "
            f"{log_dir / pattern}"
        )
        return None

    latest_log_file = max(
        log_files,
        key=lambda path: path.stat().st_mtime,
    )

    print(
        f"[LOG] 使用ログ: "
        f"{latest_log_file}"
    )

    return latest_log_file


def analyze_log_events(
    log_path: Path | None,
) -> tuple[int, int]:
    """
    当日ログから以下を数える。

    1. 電源OFFイベント回数
       - 電源ON状態から電源OFFを検出した時だけ1回加算
       - OFF状態中に「電源OFF」が複数行あっても重複加算しない
       - 「電源ON」を検出したらOFF状態を解除する

    2. NAV最終試行失敗回数
       - 例:
         [NAV] 失敗（試行 3/3）
         [NAV] 失敗（試行 4/4）
       - 現在試行回数と最大試行回数が同じ行だけ数える
       - 1/3、2/3、3/4など途中試行の失敗は数えない
    """
    if log_path is None:
        return 0, 0

    if not log_path.is_file():
        print(
            f"[WARN] 当日ログが見つかりません: "
            f"{log_path}"
        )
        return 0, 0

    power_off_count = 0
    power_is_off = False
    nav_final_failure_count = 0

    nav_failure_pattern = re.compile(
        r"\[NAV\]\s*失敗"
        r"[（(]\s*試行\s*"
        r"(\d+)\s*/\s*(\d+)\s*[）)]"
    )

    with log_path.open(
        "r",
        encoding="utf-8",
        errors="replace",
    ) as log_file:
        for line in log_file:
            if (
                power_on_text
                and power_on_text in line
            ):
                power_is_off = False

            if (
                power_off_text
                and power_off_text in line
            ):
                if not power_is_off:
                    power_off_count += 1
                    power_is_off = True

            nav_match = nav_failure_pattern.search(
                line
            )

            if nav_match is not None:
                current_attempt = int(
                    nav_match.group(1)
                )
                max_attempt = int(
                    nav_match.group(2)
                )

                if current_attempt == max_attempt:
                    nav_final_failure_count += 1

    print(
        f"[LOG] 電源OFFイベント: "
        f"{power_off_count}回"
    )

    print(
        f"[LOG] NAV最終試行失敗: "
        f"{nav_final_failure_count}回"
    )

    return (
        power_off_count,
        nav_final_failure_count,
    )


# =========================================================
# メイン処理
# =========================================================

def main() -> None:
    start_time = time.time()

    validate_mail_settings()

    log_path = get_today_log_path()

    (
        power_off_count,
        nav_final_failure_count,
    ) = analyze_log_events(
        log_path
    )

    latest_dataframe, latest_date = (
        load_latest_data()
    )

    latest_dataframe = add_site_links(
        latest_dataframe
    )

    latest_dataframe = (
        convert_url_columns_to_anchor(
            latest_dataframe
        )
    )

    all_sections: list[str] = []
    total_hits = 0

    # -----------------------------------------------------
    # 初当り
    # -----------------------------------------------------

    sections, hit_count = (
        check_and_notify(
            latest_dataframe,
            latest_date,
            "初当り",
            "単発後天井残りゲーム数",
        )
    )

    all_sections.extend(
        sections
    )

    total_hits += hit_count

    # -----------------------------------------------------
    # 継続
    # -----------------------------------------------------

    sections, hit_count = (
        check_and_notify(
            latest_dataframe,
            latest_date,
            "継続",
            "確変後天井残りゲーム数",
        )
    )

    all_sections.extend(
        sections
    )

    total_hits += hit_count

    # -----------------------------------------------------
    # 回転率設定値超え
    # -----------------------------------------------------

    section, hit_count = (
        notify_threshold_over(
            latest_dataframe,
            latest_date,
        )
    )

    if section:
        all_sections.append(
            section
        )

    total_hits += hit_count

    print(
        f"[INFO] 合計ヒット: "
        f"{total_hits}"
    )

    # -----------------------------------------------------
    # 条件一致・ログ警告なし
    # -----------------------------------------------------

    has_log_alert = (
        power_off_count > 0
        or nav_final_failure_count > 0
    )

    if (
        not all_sections
        and not has_log_alert
    ):
        print(
            "[INFO] 条件一致・電源OFF・"
            "NAV最終試行失敗ともに"
            "ないためメール送信しません。"
        )

        print(
            f"[INFO] スクリプト完了: "
            f"{time.time() - start_time:.2f}秒"
        )

        return

    # -----------------------------------------------------
    # メール本文作成
    # -----------------------------------------------------

    escaped_shop_name = html.escape(
        shop_name
    )

    escaped_spreadsheet_name = html.escape(
        spreadsheet_name
    )

    escaped_worksheet_name = html.escape(
        worksheet_name
    )

    log_path_html = (
        html.escape(str(log_path))
        if log_path is not None
        else "ログなし"
    )

    header_html = f"""
    <h1>
        {escaped_shop_name}
        集約通知
    </h1>

    <div class="small">
        対象日: {latest_date}<br>
        店舗シート:
        {escaped_spreadsheet_name}
        /
        {escaped_worksheet_name}<br>
        ログ: {log_path_html}<br>
        電源OFFイベント: {power_off_count}回<br>
        NAV最終試行失敗: {nav_final_failure_count}回<br>
        合計ヒット: {total_hits}
    </div>

    <hr>
    """

    full_html = (
        "<html>"
        f"<head>{TABLE_CSS}</head>"
        "<body>"
        f"{header_html}"
        f"{''.join(all_sections)}"
        "</body>"
        "</html>"
    )

    subject = (
        f"{shop_name} 集約通知 "
        f"{latest_date} "
        f"（条件{total_hits}件 / "
        f"電源OFF{power_off_count}回 / "
        f"NAV失敗{nav_final_failure_count}回）"
    )

    send_email(
        subject,
        full_html,
    )

    print(
        f"[INFO] スクリプト完了: "
        f"{time.time() - start_time:.2f}秒"
    )


# =========================================================
# 実行
# =========================================================

if __name__ == "__main__":
    main()