import argparse
import importlib
import json
import math
import subprocess
import os
import re
import sys
import time
import psutil
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from seleniumbase import Driver


# ==================================================
# プロジェクトルート設定
# ==================================================

if "__file__" in globals():
    # scripts/scraping/scraping.py から実行
    PROJECT_ROOT = Path(__file__).resolve().parents[2]
else:
    # scripts/scraping/*.ipynb から実行
    PROJECT_ROOT = Path.cwd().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

print(f"PROJECT_ROOT: {PROJECT_ROOT}")
print(f"config存在: {(PROJECT_ROOT / 'config').exists()}")
print(f"utils存在: {(PROJECT_ROOT / 'utils').exists()}")


# ==================================================
# 共通モジュール
# ==================================================

from config.common import (
    DEFAULT_SITE,
    BATCH_SIZE,
    GOOGLE_CREDENTIALS_FILE,
    GOOGLE_SCOPES,
    HISTORY_COLUMNS,
    HR01_GATEWAY,
    HR01_INTERFACE,
    SQUID_PROXY,
    TABLE_NAME,
    TAPO_IP,
    TAPO_PASSWORD,
    TAPO_USERNAME,
    require_file,
)

from utils.db_utils import (
    ensure_update_unique_schema,
    get_starting_sku_seq,
    insert_scraping_row,
    open_database,
)

from utils.sheet_utils import (
    get_target_flag,
    get_target_site,
    load_scraping_targets,
    open_worksheet,
)

from utils.network_utils import (
    get_global_ip,
    get_squid_ip,
    reboot_hr01_sync,
    reset_hr01_route,
    resolve_proxy,
    verify_hr01_global_ip,
)

from utils.today_mode_utils import (
    DB_TODAY_SCHEMA,
    collect_today_data,
)

from utils.screenshot_utils import (
    save_machine_elements_as_webp,
)

from utils.scraping_value_utils import (
    normalize_dai_number,
    normalize_update_date_text,
    to_int_or_none,
)

from utils.browser_utils import (
    get_chrome_process_info,
    kill_browser_process_tree,
    open_browser,
    wait_browser_ready,
)

from utils.search_utils import (
    SearchResultTimeoutError,
    ensure_on_target_or_raise,
    wait_for_update_date,
    wait_machine_number_input_ready,
    wait_search_menu_ready,
)

from utils.selenium_utils import (
    dismiss_overlays,
    safe_click,
    safe_set_value,
    switch_to_frame_containing,
)
from utils.cookie_utils import load_cookies
from utils.history_utils import click_more

from utils.browser_diagnostics_utils import (
    log_browser_diagnostics,
    log_request_headers,
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


site_config = importlib.import_module(
    f"config.{args.site}"
)

print(f"対象店舗: {args.site}")

# ==================================================
# 店舗選択
# ==================================================

TODAY_MODE = site_config.TODAY_MODE
PROXY_MODE = site_config.PROXY_MODE
PROXY_LIST = site_config.PROXY_LIST
PROXY_ROTATE_EVERY = site_config.PROXY_ROTATE_EVERY

db_path = site_config.DB_PATH
cookie_files = site_config.COOKIE_FILES
output_root = site_config.SITE_OUTPUT_DIR

table_name = TABLE_NAME
start_time = time.time()
now = datetime.now()
today = (now - timedelta(days=1)).strftime("%Y%m%d")
sku_date = now.strftime("%Y%m%d")

# WebP画像出力先:
# detaslot/output/<site>/img/<YYYYMMDD>/webp/
image_root = output_root / "img" / today
webp_dir = image_root / "webp"
webp_dir.mkdir(
    parents=True,
    exist_ok=True,
)


# 1台ごとにスクショ保存する複数要素
SCREENSHOT_TARGETS = [
    {
        "name": "machine_number",
        "by": By.CSS_SELECTOR,
        "value": "h2.nc-text-align-left",
        "timeout": 10,
    },
    {
        "name": "history",
        "by": By.XPATH,
        "value": "//tbody[@id='tblHISTb']",
        "timeout": 10,
    },
    {
        "name": "today",
        "by": By.CSS_SELECTOR,
        "value": "#tblDAbv2",
        "timeout": 10,
    },
    {
        "name": "machine_name",
        "by": By.ID,
        "value": "divKI-name",
        "timeout": 10,
    },
]

# googlesupure
require_file(
    GOOGLE_CREDENTIALS_FILE,
    "GoogleサービスアカウントJSON",
)

worksheet_slot = open_worksheet(
    credentials_file=GOOGLE_CREDENTIALS_FILE,
    scopes=GOOGLE_SCOPES,
    spreadsheet_name=site_config.GSHEET_NAME,
    worksheet_name=site_config.SHEET_NAME,
)

target_site = get_target_site(worksheet_slot)
target_flag = get_target_flag(now)

scraping_targets = load_scraping_targets(
    worksheet_slot,
    target_flag,
)

filtered_dai_numbers = [
    target.machine_number
    for target in scraping_targets
]

filtered_urls = [
    target.url
    for target in scraping_targets
]



conn = open_database(db_path)
ensure_update_unique_schema(conn, table_name)

# ==================================================
# ログ共通
# ==================================================

def print_step(message: str) -> None:
    """処理段階を統一形式で表示する。"""
    print(f"[STEP] {message}")


# 履歴カラム名:
# common.py の HISTORY_COLUMNS をもとに判定する。
HISTORY_COLUMN_NAMES = tuple(
    HISTORY_COLUMNS.values()
)

HIST_RE = re.compile(
    rf"^("
    rf"{'|'.join(re.escape(name) for name in HISTORY_COLUMN_NAMES)}"
    rf")(\d+)回前$"
)

# ======== バッチ開始時のナビ（既存の安定化） ========
MAX_NAV_RETRY = site_config.MAX_NAV_RETRY


def open_and_navigate_with_retry(
    proxy_url: str | None,
    target_url: str,
    cookie_file,
):
    last_err = None

    pu = urlparse(target_url)
    home = f"{pu.scheme}://{pu.hostname}/"

    for attempt in range(
        1,
        MAX_NAV_RETRY + 1,
    ):
        drv = None

        try:
            # ==========================================
            # 使用Proxy確認
            # ==========================================
            print(
                f"[NET] Chrome使用Proxy: "
                f"{proxy_url or '(none)'}"
            )

            # ==========================================
            # Chrome起動
            # ==========================================
            drv = open_browser(
                proxy_url=proxy_url
            )

            # ページロードが固まった場合は30秒で解除
            drv.set_page_load_timeout(30)

            wait_browser_ready(drv)

            # ==========================================
            # Chrome起動後のHR01経由確認
            # ==========================================
            print(
                "[NET] Chrome起動後の"
                "HR01経由確認開始"
            )

            hr01_ip, squid_ip = verify_hr01_global_ip(
                hr01_interface=HR01_INTERFACE,
                squid_proxy=SQUID_PROXY,
                timeout=20,
                require_match=True,
            )

            print(
                "[NET] Chrome/Squidは"
                "HR01経由です: "
                f"{squid_ip}"
            )

            # =====================
            # ホームアクセス
            # =====================
            drv.get(home)

            WebDriverWait(
                drv,
                15,
            ).until(
                lambda d: d.execute_script(
                    "return document.readyState"
                ) in (
                    "interactive",
                    "complete",
                )
            )

            # =====================
            # Cookie投入
            # =====================
            if os.path.exists(cookie_file):
                load_cookies(
                    drv,
                    cookie_file,
                )
                drv.refresh()

                WebDriverWait(
                    drv,
                    15,
                ).until(
                    lambda d: d.execute_script(
                        "return document.readyState"
                    ) in (
                        "interactive",
                        "complete",
                    )
                )

            # =====================
            # 本命URL
            # =====================
            try:
                drv.get(target_url)

            except TimeoutException:
                print(
                    "[NAV] ページロード30秒超過"
                )

                try:
                    drv.execute_script(
                        "window.stop();"
                    )
                except Exception:
                    pass

            # ==========================================
            # 本命URLのHTML読み込み完了待ち
            # ==========================================
            WebDriverWait(
                drv,
                30,
            ).until(
                lambda d: d.execute_script(
                    "return document.readyState"
                ) in (
                    "interactive",
                    "complete",
                )
            )

            # ==========================================
            # ブラウザ診断
            # ==========================================
            log_browser_diagnostics(
                drv
            )
            
            # ==========================================
            # 実Request Headers診断
            # ==========================================
            log_request_headers(
                drv,
                "pscube.jp",
            )




            # ==========================================
            # 台番号検索メニューをまず10秒待つ
            # ==========================================
            try:
                print(
                    "[NAV] 台番号検索メニュー待機"
                    "（最大10秒）"
                )

                wait_search_menu_ready(
                    drv,
                    timeout=10,
                )

            except TimeoutException:
                # ======================================
                # 10秒以内に描画されなければ
                # 「スロットデータ」リンクをクリック
                # ======================================
                print(
                    "[NAV] 台番号検索メニューが"
                    "8秒以内に描画されませんでした"
                )

                try:
                    print(
                        f"[NAV] リンククリック前URL: "
                        f"{drv.current_url}"
                    )
                except Exception:
                    pass

                print(
                    "[NAV] 「スロットデータ」"
                    "リンクをクリックします"
                )

                # ======================================
                # スロットデータリンクを取得
                #
                # <a href="cgi-bin/nc-v03-001.php?cd_ps=2">
                # ======================================
                slot_link = WebDriverWait(
                    drv,
                    10,
                ).until(
                    EC.element_to_be_clickable(
                        (
                            By.CSS_SELECTOR,
                            (
                                'a[href="cgi-bin/'
                                'nc-v03-001.php?cd_ps=2"]'
                            ),
                        )
                    )
                )

                # ======================================
                # スロットデータリンクをクリック
                # ======================================
                try:
                    slot_link.click()

                except Exception:
                    drv.execute_script(
                        "arguments[0].click();",
                        slot_link,
                    )

                # ======================================
                # クリック後のページ読み込み待ち
                # ======================================
                WebDriverWait(
                    drv,
                    30,
                ).until(
                    lambda d: d.execute_script(
                        "return document.readyState"
                    ) in (
                        "interactive",
                        "complete",
                    )
                )

                try:
                    print(
                        f"[NAV] リンククリック後URL: "
                        f"{drv.current_url}"
                    )
                except Exception:
                    pass

                # ======================================
                # クリック後に台番号検索メニューを待つ
                # ======================================
                print(
                    "[NAV] リンククリック後、"
                    "台番号検索メニュー待機"
                    "（最大30秒）"
                )

                wait_search_menu_ready(
                    drv,
                    timeout=30,
                )

            # ==========================================
            # ナビゲーション成功
            # ==========================================
            print(
                f"[NAV] 成功（試行 "
                f"{attempt}/{MAX_NAV_RETRY}）"
            )

            return drv

        except Exception as e:
            last_err = e

            print(
                f"[NAV] 失敗（試行 "
                f"{attempt}/{MAX_NAV_RETRY}）: "
                f"{type(e).__name__}: {e}"
            )

            try:
                if drv:
                    drv.execute_script(
                        "window.stop();"
                    )
            except Exception:
                pass

            try:
                if drv:
                    drv.quit()
            except Exception:
                pass

            time.sleep(2)

    raise RuntimeError(
        f"ナビゲーションに失敗: {last_err}"
    )
    

# ========= メインループ =========
batch_size = BATCH_SIZE
sku_seq = get_starting_sku_seq(
    conn,
    table_name,
    sku_date,
)

total = len(filtered_dai_numbers)

# ==================================================
# Cookie切替状態
#
# Cookieはbatch単位では切り替えない。
# スクリプト開始時はCOOKIE_FILESの先頭を使用し、
# HR01再起動が正常完了するたびに
# 1つ次のCookieへ切り替える。
# 最後まで到達したら先頭へ戻る。
# ==================================================

if not cookie_files:
    raise RuntimeError(
        "COOKIE_FILESが空です。"
        " 店舗configに1個以上のCookieファイルを設定してください。"
    )

cookie_index = 0
current_cookie_file = cookie_files[
    cookie_index
]

print(
    f"[COOKIE] 初期Cookie: "
    f"{current_cookie_file}"
)

for batch_start in range(
    0,
    total,
    batch_size,
):
    batch_end = min(
        batch_start + batch_size,
        total,
    )

    # batchが変わってもCookieは変更しない。
    # 現在のCookieをそのまま次のブラウザでも使用する。
    print(
        f"[COOKIE] 現在のCookie: "
        f"{current_cookie_file}"
    )

    proxy_url = resolve_proxy(
        batch_index=batch_start,
        mode=PROXY_MODE,
        proxy_list=PROXY_LIST,
        rotate_every=PROXY_ROTATE_EVERY,
    )

    # ==================================================
    # HR01ルート設定
    # ==================================================
    
    print(
        "[NET] HR01ルート設定"
    )
    
    reset_hr01_route(
        hr01_interface=HR01_INTERFACE,
        hr01_gateway=HR01_GATEWAY,
    )


    # ==================================================
    # バッチ開始時のブラウザ起動
    # ==================================================

    try:
        browser = open_and_navigate_with_retry(
            proxy_url,
            target_site,
            current_cookie_file,
        )

    except Exception as e:
        print(
            f"[FATAL] バッチ "
            f"{batch_start}-{batch_end} "
            f"のナビゲーションに失敗: "
            f"{type(e).__name__}: {e}"
        )

        time.sleep(3)
        continue

    # ==================================================
    # 台番号ごとの処理
    # ==================================================

    for index in range(
        batch_start,
        batch_end,
    ):
        dai_number = filtered_dai_numbers[index]
        url = filtered_urls[index]

        # --------------------------------------------------
        # 1行分の初期データ
        # --------------------------------------------------

        data_entry = {
            "台番号": dai_number,
            "pscubeURL": url,
            "取得更新日": None,
            "機種名": None,
            "svgデータ": None,
            "SKU": f"{sku_date}{sku_seq:04d}",
            "実行日": datetime.now().strftime(
                "%Y-%m-%d %H:%M:%S"
            ),
        }

        sku_seq += 1

        # 本日欄カラムをNoneで初期化
        for col in DB_TODAY_SCHEMA.keys():
            data_entry[col] = None

        try:
            print()
            print(
                f"========== 台番号 {dai_number} "
                f"({index + 1}/{total}) =========="
            )

            tried_restart = False

            # ==============================================
            # 同じ台番号を最大2回処理
            # 1回目失敗後のみブラウザ・HR01を再起動
            # ==============================================

            while True:
                try:
                    # --------------------------------------
                    # ページ状態確認
                    # --------------------------------------

                    print_step(
                        "ページ状態確認"
                    )

                    ensure_on_target_or_raise(
                        browser,
                        target_site,
                        timeout=12,
                    )

                    # --------------------------------------
                    # オーバーレイ除去
                    # --------------------------------------

                    print_step(
                        "オーバーレイ除去"
                    )

                    dismiss_overlays(
                        browser
                    )

                    # --------------------------------------
                    # 台番号検索メニュー
                    # --------------------------------------

                    print_step(
                        "「台番号で探す」をクリック"
                    )

                    safe_click(
                        browser,
                        (
                            By.XPATH,
                            (
                                "//div["
                                "contains(@class,'search-item') "
                                "and contains(.,'台番号で探す')"
                                "]"
                            ),
                        ),
                        timeout=12,
                    )

                    # --------------------------------------
                    # 台番号入力欄
                    # --------------------------------------

                    print_step(
                        "台番号入力欄待機"
                    )

                    wait_machine_number_input_ready(
                        browser,
                        timeout=15,
                    )

                    print_step(
                        f"台番号入力: {dai_number}"
                    )

                    safe_set_value(
                        browser,
                        (
                            By.NAME,
                            "cd_dai",
                        ),
                        dai_number,
                        timeout=12,
                    )

                    # 追加
                    time.sleep(3)

                    # --------------------------------------
                    # 検索ボタン取得
                    # --------------------------------------

                    print_step(
                        "検索ボタン取得"
                    )

                    search_button_locator = (
                        By.CSS_SELECTOR,
                        (
                            ".nc-da-search-btn"
                            ".nc-da-search-btn-submit"
                        ),
                    )

                    WebDriverWait(
                        browser,
                        5,
                    ).until(
                        EC.presence_of_element_located(
                            search_button_locator
                        )
                    )

                    buttons = browser.find_elements(
                        *search_button_locator
                    )

                    target_button = next(
                        (
                            button
                            for button in buttons
                            if (
                                button.is_displayed()
                                and button.is_enabled()
                            )
                        ),
                        buttons[0] if buttons else None,
                    )

                    if target_button is None:
                        raise RuntimeError(
                            "検索ボタンが見つかりませんでした。"
                        )
                    # --------------------------------------
                    # 検索実行
                    # --------------------------------------
                    
                    print_step(
                        "検索ボタンクリック"
                    )
                    
                    expected_number = normalize_dai_number(
                        dai_number
                    )
                    
                    expected_param = (
                        f"cd_dai={int(expected_number):04d}"
                    )
                    
                    browser.execute_script(
                        (
                            "arguments[0].scrollIntoView("
                            "{block:'center'}"
                            ");"
                        ),
                        target_button,
                    )
                    
                    # ======================================
                    # 検索ボタンは1回だけクリックする
                    #
                    # 通常クリックそのものが例外になった場合のみ
                    # JSクリックをフォールバックとして使用する。
                    #
                    # 「クリックしたがURL遷移しない」場合には
                    # 再クリックしない。
                    # ======================================
                    
                    try:
                        target_button.click()
                    
                        print(
                            "[SEARCH] 通常クリック実行"
                        )
                    
                    except Exception:
                        browser.execute_script(
                            "arguments[0].click();",
                            target_button,
                        )
                    
                        print(
                            "[SEARCH] JSクリック実行"
                        )
                    
                    # ======================================
                    # URL遷移を最大15秒待つ
                    #
                    # ここでは検索ボタンを再クリックしない。
                    # サイト側のレスポンスが遅い場合も
                    # 最大15秒そのまま待つ。
                    # ======================================
                    
                    print(
                        "[SEARCH] "
                        "目的台番号のURL遷移待機"
                        "（最大15秒）"
                    )
                    
                    click_success = False
                    click_deadline = time.time() + 15
                    
                    last_url = ""
                    
                    while time.time() < click_deadline:
                        try:
                            current_url = browser.current_url
                    
                            last_url = current_url
                    
                            if expected_param in current_url:
                                click_success = True
                    
                                print(
                                    "[SEARCH] "
                                    "検索クリック成功確認: "
                                    f"{expected_param}"
                                )
                    
                                print(
                                    "[SEARCH] 遷移後URL: "
                                    f"{current_url}"
                                )
                    
                                break
                    
                        except WebDriverException:
                            raise
                    
                        except Exception:
                            pass
                    
                        time.sleep(0.5)
                    
                    # ======================================
                    # 15秒経過しても目的URLでなければ失敗
                    #
                    # 重要:
                    # ここでは再クリックしない。
                    #
                    # RuntimeErrorを上へ投げ、
                    # 既存のブラウザ終了・HR01再起動処理へ
                    # 任せる。
                    # ======================================
                    
                    if not click_success:
                        print(
                            "[SEARCH ERROR] "
                            "15秒以内に目的台番号のURLへ"
                            "遷移しませんでした"
                        )
                    
                        print(
                            "[SEARCH ERROR] "
                            f"expected={expected_param!r}, "
                            f"current_url={last_url!r}"
                        )
                    
                        raise RuntimeError(
                            "検索ボタンを1回クリックしましたが、"
                            "15秒以内に目的台番号のURLへ"
                            "遷移しませんでした。"
                            f" expected={expected_param!r}"
                            f" current_url={last_url!r}"
                        )
                    
                    # --------------------------------------
                    # 検索結果待機
                    # --------------------------------------
                    
                    print_step(
                        "取得更新日・表示台番号待機"
                        "（最大60秒）"
                    )
                    
                    update_date, displayed_text = (
                        wait_for_update_date(
                            browser,
                            dai_number=dai_number,
                            timeout=60,
                        )
                    )


                    # --------------------------------------
                    # もっと見る前の固定待機
                    # --------------------------------------
                    
                    print(
                        "[WAIT] もっと見るクリック前に5秒待機"
                    )
                    
                    time.sleep(5)
                    
                    # --------------------------------------
                    # もっと見る
                    # --------------------------------------

                    print_step(
                        "「もっと見る」展開"
                    )

                    more_click_count = click_more(
                        browser,
                        max_clicks=5,
                        wait_after_click=5,
                        change_timeout=10,
                    )

                    print(
                        f"[MORE] 最終クリック回数="
                        f"{more_click_count}"
                    )

                    # --------------------------------------
                    # 更新日時
                    # --------------------------------------

                    print_step(
                        "更新日時正規化・変換"
                    )

                    normalized_update_date = (
                        normalize_update_date_text(
                            update_date
                        )
                    )

                    if not normalized_update_date:
                        raise ValueError(
                            "取得更新日の正規化結果が空です。"
                            f" raw={update_date!r}"
                        )

                    update_date_obj = datetime.strptime(
                        normalized_update_date,
                        "%Y/%m/%d %H:%M",
                    )

                    data_entry["取得更新日"] = (
                        update_date_obj.strftime(
                            "%Y-%m-%d %H:%M:%S"
                        )
                    )

                    print(
                        f"取得更新日: "
                        f"{data_entry['取得更新日']}"
                    )

                    # --------------------------------------
                    # 表示台番号
                    # --------------------------------------

                    print_step(
                        "検索結果の台番号取得"
                    )

                    try:
                        h2_element = browser.find_element(
                            By.CSS_SELECTOR,
                            "h2.nc-text-align-left",
                        )

                        machine_number_text = (
                            h2_element.text
                            .replace(
                                "台番号 ",
                                "",
                            )
                            .strip()
                        )

                        if machine_number_text:
                            data_entry["台番号"] = (
                                machine_number_text
                            )

                    except Exception as e:
                        print(
                            "[WARN] 台番号取得失敗。"
                            "検索値を保持します: "
                            f"{type(e).__name__}: {e}"
                        )

                    # --------------------------------------
                    # 機種名
                    # --------------------------------------

                    print_step(
                        "機種名取得"
                    )

                    try:
                        title_element = (
                            browser.find_element(
                                By.ID,
                                "divKI-name",
                            )
                        )

                        data_entry["機種名"] = (
                            title_element.text.strip()
                        )

                    except Exception as e:
                        print(
                            "[WARN] 機種名取得失敗: "
                            f"{type(e).__name__}: {e}"
                        )

                    # --------------------------------------
                    # 本日データ
                    # --------------------------------------

                    print_step(
                        "本日データ取得"
                    )

                    try:
                        print(
                            "=== 本日欄処理開始 "
                            f"(MODE={TODAY_MODE}) ==="
                        )

                        today_data = collect_today_data(
                            browser,
                            mode=TODAY_MODE,
                        )

                        data_entry.update(
                            today_data
                        )

                        if today_data:
                            print(
                                "[TODAY] 取得内容"
                            )

                            for key, value in (
                                today_data.items()
                            ):
                                print(
                                    f"[TODAY] "
                                    f"{key}={value}"
                                )

                        else:
                            print(
                                "[TODAY] "
                                "保存対象データなし"
                            )

                        print(
                            f"[TODAY] 保存件数="
                            f"{len(today_data)}"
                        )

                        print(
                            "=== 本日欄処理終了 ==="
                        )
                        print()

                    except Exception as e:
                        print(
                            "本日テーブル取得エラー: "
                            f"{type(e).__name__}: {e}"
                        )

                    # --------------------------------------
                    # 履歴取得
                    # --------------------------------------

                    print_step(
                        "履歴取得"
                    )

                    try:
                        history_table = (
                            browser.find_element(
                                By.ID,
                                "tblHIST",
                            )
                        )

                        history_rows = (
                            history_table.find_elements(
                                By.TAG_NAME,
                                "tr",
                            )
                        )

                        if len(history_rows) <= 1:
                            print(
                                "履歴データなし"
                            )

                        else:
                            header_cells = (
                                history_rows[0]
                                .find_elements(
                                    By.TAG_NAME,
                                    "th",
                                )
                                or history_rows[0]
                                .find_elements(
                                    By.TAG_NAME,
                                    "td",
                                )
                            )

                            header_texts = [
                                (
                                    cell.text
                                    or ""
                                ).strip()
                                for cell in header_cells
                            ]

                            wanted_columns = list(
                                HISTORY_COLUMNS.values()
                            )

                            column_indexes = {
                                name: next(
                                    (
                                        column_index
                                        for (
                                            column_index,
                                            text,
                                        )
                                        in enumerate(
                                            header_texts
                                        )
                                        if name in text
                                    ),
                                    None,
                                )
                                for name
                                in wanted_columns
                            }

                            body_rows = (
                                history_rows[1:]
                            )

                            max_history_count = min(
                                100,
                                len(body_rows),
                            )

                            for history_number in range(
                                1,
                                max_history_count + 1,
                            ):
                                row_element = (
                                    body_rows[
                                        history_number - 1
                                    ]
                                )

                                cells = (
                                    row_element.find_elements(
                                        By.TAG_NAME,
                                        "td",
                                    )
                                )

                                def get_cell_text(
                                    cell_index,
                                ):
                                    if (
                                        cell_index
                                        is not None
                                        and cell_index
                                        < len(cells)
                                    ):
                                        return (
                                            cells[
                                                cell_index
                                            ].text
                                            or ""
                                        ).strip()

                                    return ""

                                history_time = (
                                    get_cell_text(
                                        column_indexes[
                                            HISTORY_COLUMNS[
                                                "time"
                                            ]
                                        ]
                                    )
                                    or None
                                )

                                history_game = (
                                    to_int_or_none(
                                        get_cell_text(
                                            column_indexes[
                                                HISTORY_COLUMNS[
                                                    "game"
                                                ]
                                            ]
                                        )
                                    )
                                )

                                history_status = (
                                    get_cell_text(
                                        column_indexes[
                                            HISTORY_COLUMNS[
                                                "status"
                                            ]
                                        ]
                                    )
                                    or None
                                )

                                if (
                                    column_indexes[
                                        HISTORY_COLUMNS[
                                            "output"
                                        ]
                                    ]
                                    is not None
                                ):
                                    history_output = (
                                        to_int_or_none(
                                            get_cell_text(
                                                column_indexes[
                                                    HISTORY_COLUMNS[
                                                        "output"
                                                    ]
                                                ]
                                            )
                                        )
                                    )

                                else:
                                    history_output = None

                                data_entry[
                                    f"{HISTORY_COLUMNS['time']}"
                                    f"{history_number}"
                                    f"回前"
                                ] = history_time

                                data_entry[
                                    f"{HISTORY_COLUMNS['game']}"
                                    f"{history_number}"
                                    f"回前"
                                ] = history_game

                                data_entry[
                                    f"{HISTORY_COLUMNS['status']}"
                                    f"{history_number}"
                                    f"回前"
                                ] = history_status

                                data_entry[
                                    f"{HISTORY_COLUMNS['output']}"
                                    f"{history_number}"
                                    f"回前"
                                ] = history_output

                                print(
                                    f"[HISTORY] "
                                    f"{history_number}回前 | "
                                    f"{HISTORY_COLUMNS['time']}="
                                    f"{history_time} | "
                                    f"{HISTORY_COLUMNS['game']}="
                                    f"{history_game} | "
                                    f"{HISTORY_COLUMNS['status']}="
                                    f"{history_status} | "
                                    f"{HISTORY_COLUMNS['output']}="
                                    f"{history_output}"
                                )

                            print(
                                "履歴行数(上→下): "
                                f"{len(body_rows)} "
                                f"→ 保存: "
                                f"{max_history_count}行 "
                                "（最上段=1回前）"
                            )

                    except Exception as e:
                        print(
                            "履歴取得エラー: "
                            f"{type(e).__name__}: {e}"
                        )

                    # --------------------------------------
                    # SVG取得
                    # --------------------------------------

                    print_step(
                        "SVG取得"
                    )

                    try:
                        svg_elements = (
                            browser.find_elements(
                                By.CSS_SELECTOR,
                                'svg[version="1.1"]',
                            )
                        )

                        if len(svg_elements) >= 2:
                            data_entry["svgデータ"] = (
                                browser.execute_script(
                                    (
                                        "return "
                                        "arguments[0].outerHTML;"
                                    ),
                                    svg_elements[1],
                                )
                            )

                            print(
                                "svgデータ取得 OK"
                            )

                        else:
                            print(
                                "svgデータ 要素不足"
                            )

                    except Exception as e:
                        print(
                            "svgデータ取得エラー: "
                            f"{type(e).__name__}: {e}"
                        )

                    # --------------------------------------
                    # WebP保存
                    # --------------------------------------

                    print_step(
                        "WebP保存"
                    )

                    screenshot_results = (
                        save_machine_elements_as_webp(
                            browser,
                            dai_number=dai_number,
                            target_date=today,
                            output_dir=webp_dir,
                            targets=SCREENSHOT_TARGETS,
                            quality=80,
                        )
                    )

                    saved_screenshots = [
                        name
                        for (
                            name,
                            saved_path,
                        )
                        in screenshot_results.items()
                        if saved_path is not None
                    ]

                    print(
                        f"[SHOT] 保存完了: "
                        f"{saved_screenshots}"
                    )

                    print_step(
                        "台データ取得完了"
                    )

                    # 台番号処理成功
                    break

                # ==========================================
                # 台番号処理中のエラー
                # ==========================================

                except Exception as row_error:
                    print(
                        f"[ROW ERROR] "
                        f"台番号={dai_number}, "
                        f"例外型="
                        f"{type(row_error).__name__}, "
                        f"内容={row_error!r}"
                    )

                    # 再起動後にも失敗した場合
                    if tried_restart:
                        print(
                            f"[SKIP] 台番号 "
                            f"{dai_number} は"
                            "再起動後も失敗したため、"
                            "DB保存して次の台番号へ"
                            "進みます"
                        )

                        break

                    tried_restart = True

                    print(
                        f"[RESTART] 台番号 "
                        f"{dai_number} "
                        "ブラウザ終了・HR01再起動"
                    )
                    
                    # ======================================
                    # ブラウザ終了・HR01再起動
                    # ======================================
                    
                    try:
                        print("[INFO] ブラウザプロセス終了開始")
                    
                        kill_browser_process_tree(
                            browser
                        )
                    
                        print("[INFO] ブラウザプロセス終了完了")
                    
                        time.sleep(3)
                    
                        # ----------------------------------
                        # HR01再起動前のIP確認
                        # ----------------------------------
                    
                        print(
                            "[INFO] HR01再起動前の"
                            "グローバルIP確認開始"
                        )
                    
                        before_hr01_ip = None
                        before_squid_ip = None
                    
                        try:
                            before_hr01_ip = get_global_ip(
                                HR01_INTERFACE,
                                timeout=20,
                            )
                    
                            print(
                                "[INFO] 再起動前HR01グローバルIP: "
                                f"{before_hr01_ip}"
                            )
                    
                        except Exception as ip_error:
                            print(
                                "[WARN] 再起動前HR01グローバルIP"
                                "取得失敗: "
                                f"{type(ip_error).__name__}: "
                                f"{ip_error}"
                            )
                    
                        try:
                            before_squid_ip = get_squid_ip(
                                SQUID_PROXY,
                                timeout=20,
                            )
                    
                            print(
                                "[INFO] 再起動前Squid経由IP: "
                                f"{before_squid_ip}"
                            )
                    
                        except Exception as ip_error:
                            print(
                                "[WARN] 再起動前Squid経由IP"
                                "取得失敗: "
                                f"{type(ip_error).__name__}: "
                                f"{ip_error}"
                            )
                    
                        # ----------------------------------
                        # HR01再起動
                        # ----------------------------------
                    
                        print(
                            "[INFO] HR01再起動開始"
                        )
                    
                        reboot_hr01_sync(
                            tapo_username=TAPO_USERNAME,
                            tapo_password=TAPO_PASSWORD,
                            tapo_ip=TAPO_IP,
                            hr01_interface=HR01_INTERFACE,
                            hr01_gateway=HR01_GATEWAY,
                            squid_proxy=SQUID_PROXY,
                        )
                    
                        print(
                            "[INFO] HR01再起動完了"
                        )

                        # Cookieも次へ切り替え
                        cookie_index = (
                            cookie_index + 1
                        ) % len(cookie_files)
                        
                        current_cookie_file = cookie_files[
                            cookie_index
                        ]
                        
                        print(
                            f"[COOKIE] HR01再起動後Cookie切替: "
                            f"{current_cookie_file}"
                        )
                        
                        

                        # ----------------------------------
                        # HR01再起動後のIP確認
                        # ----------------------------------
                    
                        print(
                            "[INFO] 対象URLアクセス前の"
                            "グローバルIP確認開始"
                        )
                    
                        after_hr01_ip = None
                        after_squid_ip = None
                    
                        try:
                            after_hr01_ip = get_global_ip(
                                HR01_INTERFACE,
                                timeout=20,
                            )
                    
                            print(
                                "[INFO] 再起動後HR01グローバルIP: "
                                f"{after_hr01_ip}"
                            )
                    
                        except Exception as ip_error:
                            print(
                                "[WARN] 再起動後HR01グローバルIP"
                                "取得失敗: "
                                f"{type(ip_error).__name__}: "
                                f"{ip_error}"
                            )
                    
                        try:
                            after_squid_ip = get_squid_ip(
                                SQUID_PROXY,
                                timeout=20,
                            )
                    
                            print(
                                "[INFO] 再起動後Squid経由IP: "
                                f"{after_squid_ip}"
                            )
                    
                        except Exception as ip_error:
                            print(
                                "[WARN] 再起動後Squid経由IP"
                                "取得失敗: "
                                f"{type(ip_error).__name__}: "
                                f"{ip_error}"
                            )
                    
                        # ----------------------------------
                        # IP変更判定
                        # ----------------------------------
                    
                        if (
                            before_hr01_ip
                            and after_hr01_ip
                        ):
                            if before_hr01_ip != after_hr01_ip:
                                print(
                                    "[IP CHANGE] HR01グローバルIP変更確認OK: "
                                    f"{before_hr01_ip} "
                                    f"-> {after_hr01_ip}"
                                )
                            else:
                                print(
                                    "[IP CHANGE WARN] "
                                    "HR01グローバルIPは変更されていません: "
                                    f"{after_hr01_ip}"
                                )
                    
                        else:
                            print(
                                "[IP CHANGE WARN] "
                                "再起動前後のHR01 IPを両方取得できないため、"
                                "IP変更を判定できません"
                            )
                    
                        # ----------------------------------
                        # 再起動後の経路確認
                        # ----------------------------------
                    
                        if (
                            after_hr01_ip
                            and after_squid_ip
                        ):
                            if after_hr01_ip == after_squid_ip:
                                print(
                                    "[PROXY] 再起動後のSquidは"
                                    "HR01経由です"
                                )
                            else:
                                print(
                                    "[PROXY WARN] 再起動後のIPが不一致です"
                                )
                                print(
                                    f"[PROXY WARN] HR01: "
                                    f"{after_hr01_ip}"
                                )
                                print(
                                    f"[PROXY WARN] Squid: "
                                    f"{after_squid_ip}"
                                )
                    
                        # ----------------------------------
                        # ブラウザ再起動
                        # ----------------------------------
                    
                        print(
                            "[INFO] ブラウザ再起動開始"
                        )
                    
                        browser = open_and_navigate_with_retry(
                            proxy_url,
                            target_site,
                            current_cookie_file,
                        )
                    
                        print(
                            "[INFO] ブラウザ再起動完了"
                        )
                    
                        print(
                            f"[RETRY] 台番号 "
                            f"{dai_number} を再実行"
                        )
                    
                        continue
                    
                    except Exception as restart_error:
                        print(
                            "[RESTART ERROR] "
                            f"{type(restart_error).__name__}: "
                            f"{restart_error}"
                        )
                    
                        break

        # ==================================================
        # 台番号ごとに必ずDB保存
        # ==================================================
        
        finally:
            print_step(
                "DB保存"
            )
        
            try:
                insert_scraping_row(
                    conn,
                    table_name,
                    data_entry,
                    DB_TODAY_SCHEMA,
                    HIST_RE,
                )
        
            except Exception as db_error:
                print(
                    "[DB保存失敗] "
                    f"SKU="
                    f"{data_entry.get('SKU')} "
                    f"err={db_error!r}"
                )
        
            # ==============================================
            # 次の台番号検索まで待機
            #
            # DB保存まで完全に終了してから
            # 次の台の検索通信まで間隔を空ける。
            # ==============================================
        
            print(
                "[WAIT] 次の台まで8秒待機"
            )
            
            time.sleep(8)

    # ==================================================
    # バッチ終了
    # ==================================================

    print(
        f"[BATCH] 完了: "
        f"{batch_start}-{batch_end}"
    )

    print_step(
        "ブラウザ終了"
    )

    print(
        "[QUIT] バッチ終了時の"
        "browser.quit() 開始"
    )

    try:
        browser.quit()

        print(
            "[QUIT] バッチ終了時の"
            "browser.quit() 完了"
        )

    except Exception as browser_error:
        print(
            "[QUIT] バッチ終了時の"
            "browser.quit() エラー: "
            f"{type(browser_error).__name__}: "
            f"{browser_error}"
        )

    time.sleep(20)


conn.close()
print("✅ 毎ループUPSERT＋行ごと最小再起動リトライで完了")

print(f"[IMAGE] WebP保存先: {webp_dir}")
print(f"[INFO] 完了: {time.time() - start_time:.2f}秒")