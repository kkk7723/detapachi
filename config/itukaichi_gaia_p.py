

from __future__ import annotations

from config.common import (
    CREDENTIALS_DIR,
    DB_DIR,
    OUTPUT_DIR,
    STATIC_DIR,
    EXPORT_DIR,
    TEMPLATES_DIR,
    UPLOAD_DIR,
)


# =========================================================
# 店舗基本設定
# =========================================================

# 新しいフォルダ構成で使用する店舗識別子
SITE_KEY = "itukaichi_gaia_p"

# 旧プロジェクト名との互換用
PROJECT_DIR = "itukaichi_gaia_p"

# HTMLやサイト内で表示する店舗名
SHOP_NAME = "ガイア五日市店p"

# ログにでてくるファイル名
LOG_FILE_SUFFIX = "itukaichi_gaia_p.log"

# =========================================================
# 公開URL設定
# =========================================================

# output/gigaslot/ が公開されるURL
SITE_PUBLIC_BASE_URL = (
    "https://sedoinfinity.xsrv.jp/itukaichi_gaia_p"
)

# スクリーンショット名 → DBカラム名
SCREENSHOT_DB_COLUMNS = {
    "history": "img_url_a",
    "today": "img_url_b",
    "machine_name": "img_url_c",
    "machine_number": "img_url_d",
}


# =========================================================
# Google Spreadsheet設定
# =========================================================

# Googleスプレッドシートのブック名
GSHEET_NAME = "五日市ガイア"

# ブック内のワークシート名（タブ名）
SHEET_NAME = "pachi"


# =========================================================
# スクレイピング設定
# =========================================================

# サイトごとの「本日データ」取得方式
#
# 1:
#   柳井ガイア、岩国テキサスなど
#
# 2:
#   <tbody id^="tblDAb"> のtrから取得
#   td[0] = ラベル
#   td[1] = 値
#
# 3:
#   ul.nc-border-a > li の
#   .title / .value ペアを順番に取得
TODAY_MODE = 1

# 1台当たりの最大処理時間（秒）
ROW_TIMEOUT = 40

# ページ遷移の最大再試行回数
MAX_NAV_RETRY = 3


# =========================================================
# プロキシ設定
# =========================================================

# 使用可能な設定:
#
# "none"
#   プロキシを使用しない
#
# "list"
#   PROXY_LISTを順番に使用する
#
# "127.0.0.1:3128"
#   PROXY_MODEへ直接プロキシを指定することも可能
PROXY_MODE = "list"

PROXY_LIST: list[str] = [
    "127.0.0.1:3128",
]

# 何件ごとにプロキシを切り替えるか
PROXY_ROTATE_EVERY = 10


# =========================================================
# 店舗別パス
# =========================================================

# SQLiteデータベース
DB_PATH = DB_DIR / SITE_KEY / "data.db"

# Selenium用Cookie
COOKIE_FILES = [
    CREDENTIALS_DIR / SITE_KEY / "cookies1.json",
    CREDENTIALS_DIR / SITE_KEY / "cookies2.json",
    CREDENTIALS_DIR / SITE_KEY / "cookies3.json",
]

# HTML・画像などの店舗別出力先
SITE_OUTPUT_DIR = OUTPUT_DIR / SITE_KEY

# 店舗別アップロードファイル保存先
SITE_UPLOAD_DIR = UPLOAD_DIR / SITE_KEY

# テンプレートは全店舗共通
SITE_TEMPLATE_DIR = TEMPLATES_DIR

# CSS・JSなどの静的ファイルも全店舗共通
SITE_STATIC_DIR = STATIC_DIR

# csv保存先
SITE_EXPORT_DIR = EXPORT_DIR / SITE_KEY
