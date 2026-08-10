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
cookie_file = site_config.COOKIE_FILE
output_root = site_config.SITE_OUTPUT_DIR

table_name = TABLE_NAME
start_time = time.time()
now = datetime.now()
today = (now - timedelta(days=1)).strftime("%Y%m%d")
sku_date = now.strftime("%Y%m%d")

# WebP画像出力先:
# detapachi/output/<site>/img/<YYYYMMDD>/webp/
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


# ========= 数値パーサ =========

def to_int_or_none(s: str):
    """
    文字列から整数を抽出。
    - '▲230' や 全角マイナス '－230' / '−230' も負数として解釈
    - 桁以外は無視（カンマ、空白、単位など）
    - '1/281' や '１／２８１' / '1/281.4' 形式は '1/' を削除して分母だけを数値化
    - 小数点は無視して整数化（切り捨て）
    """
    if s is None:
        return None
    s = str(s).strip()
    # 全角数字・全角スラッシュ→半角
    trans_map = str.maketrans("０１２３４５６７８９／．", "0123456789/.")
    s_norm = s.translate(trans_map)
    # 先頭が "1/" の場合は削除
    if s_norm.startswith("1/"):
        s = s_norm[2:].lstrip()
    else:
        s = s_norm
    # マイナス記号・負数表現の検出
    negative = False
    if s.startswith(("▲", "-", "－", "−")):
        negative = True
    # 数字または小数点を抽出
    m = re.search(r"(\d+(?:\.\d+)?)", s)
    if not m:
        return None
    # 小数点があれば切り捨て
    try:
        val = math.floor(float(m.group(1)))
    except ValueError:
        return None
    return -val if negative else val

# 履歴カラム名:
# 時刻1回前、ゲーム1回前、ステータス1回前、出玉pt1回前 ... を判定
HIST_RE = re.compile(
    r"^(時刻|ゲーム|ステータス|出玉pt)(\d+)回前$"
)



# ==================================================
# Selenium共通処理
# ==================================================

def dismiss_overlays(driver):
    """クッキー同意などのオーバーレイを可能な範囲で閉じる。"""
    texts = [
        "同意",
        "同意する",
        "OK",
        "閉じる",
        "許可",
        "Accept",
        "I agree",
        "Close",
    ]

    try:
        candidates = driver.find_elements(
            By.XPATH,
            "//button|//a|//div",
        )

        for element in candidates[:80]:
            try:
                label = (element.text or "").strip()

                if (
                    any(text in label for text in texts)
                    and element.is_displayed()
                    and element.is_enabled()
                ):
                    driver.execute_script(
                        "arguments[0].scrollIntoView({block:'center'});",
                        element,
                    )

                    try:
                        element.click()
                    except Exception:
                        driver.execute_script(
                            "arguments[0].click();",
                            element,
                        )

                    time.sleep(0.1)

            except Exception:
                pass

    except Exception:
        pass


def switch_to_frame_containing(
    driver,
    by,
    value,
    timeout=5,
):
    """
    指定ロケータの要素を含むiframeを探索して切り替える。
    見つからなければトップへ戻してFalseを返す。
    """
    driver.switch_to.default_content()
    deadline = time.time() + timeout

    while time.time() < deadline:
        try:
            if driver.find_elements(by, value):
                return True
        except Exception:
            pass

        frames = driver.find_elements(
            By.TAG_NAME,
            "iframe",
        )

        for frame in frames:
            try:
                driver.switch_to.default_content()
                driver.switch_to.frame(frame)

                if driver.find_elements(by, value):
                    return True

            except Exception:
                continue

        time.sleep(0.2)

    driver.switch_to.default_content()
    return False


def safe_click(
    driver,
    locator,
    timeout=10,
):
    """
    presence確認後、
    通常クリック→JavaScriptクリックの順で試す。
    """
    element = WebDriverWait(
        driver,
        timeout,
    ).until(
        EC.presence_of_element_located(locator)
    )

    try:
        WebDriverWait(
            driver,
            timeout,
        ).until(
            EC.element_to_be_clickable(locator)
        )
    except Exception:
        pass

    try:
        driver.execute_script(
            "arguments[0].scrollIntoView({block:'center'});",
            element,
        )
        element.click()
        return
    except Exception:
        pass

    driver.execute_script(
        "arguments[0].click();",
        element,
    )


def safe_set_value(
    driver,
    locator,
    value,
    timeout=10,
):
    """
    input要素へ値を設定し、
    input/changeイベントを発火する。
    """
    switch_to_frame_containing(
        driver,
        *locator,
        timeout=timeout,
    )

    element = WebDriverWait(
        driver,
        timeout,
    ).until(
        EC.presence_of_element_located(locator)
    )

    try:
        WebDriverWait(
            driver,
            timeout,
        ).until(
            EC.visibility_of_element_located(locator)
        )
    except Exception:
        pass

    driver.execute_script(
        """
        const element = arguments[0];
        const value = arguments[1];

        element.focus();

        const setter =
            Object.getOwnPropertyDescriptor(
                HTMLInputElement.prototype,
                'value'
            ).set;

        setter.call(element, '');
        setter.call(element, value);

        element.dispatchEvent(
            new Event('input', {bubbles: true})
        );

        element.dispatchEvent(
            new Event('change', {bubbles: true})
        );
        """,
        element,
        value,
    )

# ==============================================
# なんのプロセスか確認も
# ==============================================
def open_browser(proxy_url=None):
    """
    SeleniumBase Driverを起動する。

    起動前後のChrome系プロセスを比較し、
    今回増えたPIDと、このブラウザ専用の
    user-data-dirを内部では保存する。

    ログは必要最低限だけ表示する。
    """
    prefix = "[MAIN]"

    # Seleniumのローカル接続には
    # プロキシを適用しない
    proxy_environment_names = (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "http_proxy",
        "https_proxy",
        "ALL_PROXY",
        "all_proxy",
    )

    for environment_name in proxy_environment_names:
        os.environ.pop(
            environment_name,
            None,
        )

    no_proxy = "127.0.0.1,localhost,::1"

    os.environ["NO_PROXY"] = os.environ.get(
        "NO_PROXY",
        no_proxy,
    )

    os.environ["no_proxy"] = os.environ.get(
        "no_proxy",
        no_proxy,
    )

    use_proxy = (
        proxy_url
        if (
            proxy_url
            and str(proxy_url).lower() != "none"
        )
        else None
    )

    # ==============================================
    # Chrome起動前のプロセスを記録
    # ==============================================

    before_processes = get_chrome_process_info()

    print(
        f"{prefix} Chrome起動前の"
        f"Chrome系プロセス数="
        f"{len(before_processes)}"
    )

    print(
        f"{prefix} Driver起動開始"
    )

    # ==============================================
    # Driver起動
    # ==============================================

    driver = Driver(
        uc=True,
        headless=False,
        proxy=use_proxy,
        page_load_strategy="normal",
    )

    print(
        f"{prefix} Driver生成完了"
    )

    # Chrome関連プロセスが出そろうまで少し待つ
    time.sleep(2)

    # ==============================================
    # Chrome起動後のプロセスを確認
    # ==============================================

    after_processes = get_chrome_process_info()

    new_process_ids = sorted(
        set(after_processes)
        - set(before_processes)
    )

    print(
        f"{prefix} Chrome起動後の"
        f"Chrome系プロセス数="
        f"{len(after_processes)} "
        f"（増加={len(new_process_ids)}）"
    )

    # ==============================================
    # SeleniumBaseが自動作成した
    # user-data-dirを取得
    # ==============================================

    profile_dir = None

    for process_id in new_process_ids:
        process_info = after_processes.get(
            process_id
        )

        if not process_info:
            continue

        command_text = (
            process_info.get("cmdline")
            or ""
        )

        match = re.search(
            r"--user-data-dir=(?:\"([^\"]+)\"|'([^']+)'|([^\s]+))",
            command_text,
        )

        if match:
            profile_dir = next(
                (
                    value
                    for value in match.groups()
                    if value
                ),
                None,
            )

            if profile_dir:
                break

    # ==============================================
    # 後の強制終了処理で使う情報を保存
    # ==============================================

    driver._detapachi_process_pids = (
        new_process_ids
    )

    driver._detapachi_profile_dir = (
        profile_dir
    )

    print(
        f"{prefix} user-data-dir="
        f"{profile_dir}"
    )

    if not profile_dir:
        print(
            f"{prefix} [WARN] "
            "user-data-dirを取得できませんでした"
        )

    # ==============================================
    # ブラウザサイズ
    # ==============================================

    driver.set_window_size(
        200,
        1920,
    )

    print(
        f"{prefix} Chrome launched "
        f"session_id={driver.session_id}"
    )

    # ==============================================
    # uc_driverのPID取得
    # ==============================================

    service = getattr(
        driver,
        "service",
        None,
    )

    service_process = getattr(
        service,
        "process",
        None,
    )

    service_pid = getattr(
        service_process,
        "pid",
        None,
    )

    driver._detapachi_driver_pid = (
        service_pid
    )

    print(
        f"{prefix} driver PID="
        f"{service_pid}"
    )

    # ==============================================
    # Proxy表示
    # ==============================================

    if use_proxy:
        print(
            f"{prefix} proxy="
            f"{use_proxy}"
        )

    else:
        print(
            f"{prefix} proxy=(none)"
        )

    return driver

# ==============================================
# もっとみるクリック関連
# ==============================================
def click_more(
    driver,
    *,
    max_clicks: int = 15,
    wait_after_click: float = 0.8,
    change_timeout: int = 5,
) -> int:
    """
    「もっと見る」を安全に展開する。

    終了条件:
    - ボタンが存在しない
    - ボタンが非表示
    - ボタンが無効
    - クリック後に履歴行数が増えない
    - ボタンが同じ状態のまま変化しない
    - max_clicksへ到達
    - ブラウザセッションが切れた

    Returns
    -------
    int
        成功したクリック回数
    """

    more_locator = (
        By.ID,
        "tblHISTm",
    )

    history_row_locator = (
        By.CSS_SELECTOR,
        "#tblHIST tr",
    )

    click_count = 0

    print(
        f"[MORE] 展開開始 "
        f"(最大{max_clicks}回)"
    )

    for attempt in range(
        1,
        max_clicks + 1,
    ):
        try:
            # ブラウザセッション生存確認
            driver.execute_script(
                "return document.readyState"
            )

            # 現在の履歴行数
            before_rows = len(
                driver.find_elements(
                    *history_row_locator
                )
            )

            buttons = driver.find_elements(
                *more_locator
            )

            visible_buttons = []

            for button in buttons:
                try:
                    if (
                        button.is_displayed()
                        and button.is_enabled()
                    ):
                        visible_buttons.append(
                            button
                        )
                except Exception:
                    continue

            if not visible_buttons:
                print(
                    "[MORE] ボタンなし・非表示のため終了"
                )
                break

            button = visible_buttons[0]

            print(
                f"[MORE] クリック "
                f"{attempt}/{max_clicks} "
                f"(クリック前履歴行数={before_rows})"
            )

            try:
                driver.execute_script(
                    """
                    arguments[0].scrollIntoView({
                        block: 'center',
                        inline: 'nearest'
                    });
                    """,
                    button,
                )
            except Exception:
                pass
                
            time.sleep(5)  # ← これだけ追加スクロール
            
            try:
                button.click()
            except Exception:
                driver.execute_script(
                    "arguments[0].click();",
                    button,
                )

            click_count += 1

            # クリック後、履歴行数の増加または
            # ボタン消失を短時間だけ待つ
            deadline = (
                time.time()
                + change_timeout
            )

            changed = False
            after_rows = before_rows

            while time.time() < deadline:
                try:
                    after_rows = len(
                        driver.find_elements(
                            *history_row_locator
                        )
                    )

                    current_buttons = (
                        driver.find_elements(
                            *more_locator
                        )
                    )

                    current_visible = False

                    for current_button in current_buttons:
                        try:
                            if current_button.is_displayed():
                                current_visible = True
                                break
                        except Exception:
                            continue

                    if after_rows > before_rows:
                        changed = True
                        break

                    if not current_visible:
                        changed = True
                        break

                except WebDriverException:
                    raise

                except Exception:
                    pass

                time.sleep(0.2)

            print(
                f"[MORE] クリック後履歴行数="
                f"{after_rows}"
            )

            if not changed:
                print(
                    "[MORE] 履歴件数が増えないため終了"
                )
                break

            time.sleep(
                wait_after_click
            )

        except TimeoutException:
            print(
                "[MORE] ボタン待機タイムアウトのため終了"
            )
            break

        except WebDriverException as exc:
            print(
                "[MORE] WebDriverエラー: "
                f"{type(exc).__name__}: {exc}"
            )
            raise

        except Exception as exc:
            print(
                "[MORE] 展開エラー: "
                f"{type(exc).__name__}: {exc}"
            )
            break

    else:
        print(
            f"[MORE] 最大クリック数 "
            f"{max_clicks}回へ到達"
        )

    print(
        f"[MORE] 展開終了 "
        f"(成功クリック={click_count}回)"
    )

    return click_count

def load_cookies(browser):
    try:
        with open(cookie_file, "r") as file:
            cookies = json.load(file)
            for cookie in cookies:
                if "sameSite" in cookie:
                    cookie.pop("sameSite")
                browser.add_cookie(cookie)
        print("Cookies loaded.")
    except FileNotFoundError:
        print("No cookies found.")

def wait_browser_ready(driver, timeout=10):
    """Chrome起動直後の準備完了待ち（about:blank → readyState 確認 → no-op JS）"""
    driver.get("about:blank")
    WebDriverWait(driver, timeout).until(
        lambda d: d.execute_script("return document.readyState") in ("interactive", "complete")
    )
    driver.execute_script("return 1")  # no-op：Executorが生きてるか確認


def wait_search_menu_ready(
    driver,
    timeout=30,
):
    """
    「台番号で探す」の検索メニューが
    表示・操作可能になるまで待つ。

    台番号入力欄 cd_dai は、
    検索メニューをクリックした後に表示されるため、
    ここでは待たない。

    タイムアウト時は、
    URL・タイトル・readyState・
    search-item数・iframe数などをログ出力する。
    """
    locator = (
        By.XPATH,
        (
            "//div[contains(@class,'search-item') "
            "and contains(.,'台番号で探す')]"
        ),
    )

    deadline = time.time() + timeout
    last_error = None

    last_top_count = 0
    last_iframe_count = 0
    last_search_item_count = 0

    while time.time() < deadline:
        try:
            # ==========================================
            # まずトップ階層を確認
            # ==========================================
            driver.switch_to.default_content()

            elements = driver.find_elements(
                *locator
            )

            last_top_count = len(elements)

            for element in elements:
                try:
                    if (
                        element.is_displayed()
                        and element.is_enabled()
                    ):
                        print(
                            "[NAV] 台番号検索メニュー"
                            "描画完了"
                        )

                        driver.switch_to.default_content()

                        return element

                except Exception as exc:
                    last_error = exc
                    continue

            # ==========================================
            # iframe数確認
            # ==========================================
            frames = driver.find_elements(
                By.TAG_NAME,
                "iframe",
            )

            last_iframe_count = len(frames)

            # ==========================================
            # iframe内を探索
            # ==========================================
            for frame_index, frame in enumerate(
                frames
            ):
                try:
                    driver.switch_to.default_content()
                    driver.switch_to.frame(frame)

                    elements = driver.find_elements(
                        *locator
                    )

                    for element in elements:
                        try:
                            if (
                                element.is_displayed()
                                and element.is_enabled()
                            ):
                                print(
                                    "[NAV] 台番号検索メニュー"
                                    "描画完了"
                                    "（iframe内 "
                                    f"index={frame_index}）"
                                )

                                return element

                        except Exception as exc:
                            last_error = exc
                            continue

                except Exception as exc:
                    last_error = exc
                    continue

            driver.switch_to.default_content()

            # ==========================================
            # search-item自体が存在するか確認
            # ==========================================
            try:
                last_search_item_count = len(
                    driver.find_elements(
                        By.CSS_SELECTOR,
                        ".search-item",
                    )
                )

            except Exception as exc:
                last_error = exc

        except Exception as exc:
            last_error = exc

        time.sleep(0.5)

    # ==============================================
    # タイムアウト時の詳細ログ
    # ==============================================
    try:
        driver.switch_to.default_content()
    except Exception:
        pass

    try:
        current_url = driver.current_url
    except Exception as exc:
        current_url = (
            f"(取得失敗: "
            f"{type(exc).__name__}: {exc})"
        )

    try:
        title = driver.title
    except Exception as exc:
        title = (
            f"(取得失敗: "
            f"{type(exc).__name__}: {exc})"
        )

    try:
        ready_state = driver.execute_script(
            "return document.readyState"
        )
    except Exception as exc:
        ready_state = (
            f"(取得失敗: "
            f"{type(exc).__name__}: {exc})"
        )

    try:
        page_source_length = len(
            driver.page_source
        )
    except Exception:
        page_source_length = -1

    try:
        body_text = driver.find_element(
            By.TAG_NAME,
            "body",
        ).text
    except Exception:
        body_text = ""

    body_preview = (
        body_text
        .replace("\n", " ")
        .strip()
    )

    if len(body_preview) > 500:
        body_preview = (
            body_preview[:500]
            + "..."
        )

    print()
    print(
        "========== [NAV DEBUG] =========="
    )

    print(
        f"[NAV DEBUG] timeout={timeout}秒"
    )

    print(
        f"[NAV DEBUG] current_url="
        f"{current_url}"
    )

    print(
        f"[NAV DEBUG] title="
        f"{title!r}"
    )

    print(
        f"[NAV DEBUG] readyState="
        f"{ready_state}"
    )

    print(
        f"[NAV DEBUG] 対象XPath要素数="
        f"{last_top_count}"
    )

    print(
        f"[NAV DEBUG] search-item数="
        f"{last_search_item_count}"
    )

    print(
        f"[NAV DEBUG] iframe数="
        f"{last_iframe_count}"
    )

    print(
        f"[NAV DEBUG] page_source長="
        f"{page_source_length}"
    )

    print(
        f"[NAV DEBUG] body先頭="
        f"{body_preview!r}"
    )

    print(
        f"[NAV DEBUG] last_error="
        f"{last_error!r}"
    )

    print(
        "================================="
    )
    print()

    raise TimeoutException(
        "台番号検索メニューが"
        f"{timeout}秒以内に描画されませんでした。"
        f" current_url={current_url!r}"
        f" readyState={ready_state!r}"
        f" target_count={last_top_count}"
        f" search_item_count="
        f"{last_search_item_count}"
        f" iframe_count={last_iframe_count}"
        f" last_error={last_error!r}"
    )


def wait_machine_number_input_ready(
    driver,
    timeout=15,
):
    """
    「台番号で探す」をクリックした後、
    台番号入力欄 cd_dai が
    表示・操作可能になるまで待つ。
    """
    locator = (
        By.NAME,
        "cd_dai",
    )

    deadline = time.time() + timeout
    last_error = None

    while time.time() < deadline:
        try:
            # 現在のframeをまず確認する。
            elements = driver.find_elements(*locator)

            for element in elements:
                if (
                    element.is_displayed()
                    and element.is_enabled()
                ):
                    print(
                        "[SEARCH] 台番号入力欄描画完了"
                    )
                    return element

            # 見つからなければトップとiframeを探索する。
            driver.switch_to.default_content()

            elements = driver.find_elements(*locator)

            for element in elements:
                if (
                    element.is_displayed()
                    and element.is_enabled()
                ):
                    print(
                        "[SEARCH] 台番号入力欄描画完了"
                    )
                    return element

            frames = driver.find_elements(
                By.TAG_NAME,
                "iframe",
            )

            for frame in frames:
                try:
                    driver.switch_to.default_content()
                    driver.switch_to.frame(frame)

                    elements = driver.find_elements(
                        *locator
                    )

                    for element in elements:
                        if (
                            element.is_displayed()
                            and element.is_enabled()
                        ):
                            print(
                                "[SEARCH] 台番号入力欄描画完了"
                                "（iframe内）"
                            )
                            return element

                except Exception as exc:
                    last_error = exc
                    continue

            driver.switch_to.default_content()

        except Exception as exc:
            last_error = exc

        time.sleep(0.3)

    driver.switch_to.default_content()

    raise TimeoutException(
        "台番号入力欄が"
        f"{timeout}秒以内に描画されませんでした。"
        f" last_error={last_error!r}"
    )

# ================
#　ブラウザkidoukakuni
# ================

def get_chrome_process_info() -> dict[int, dict]:
    """
    現在動作しているChrome系プロセスを
    PIDをキーにして取得する。
    """
    processes: dict[int, dict] = {}

    for process in psutil.process_iter(
        [
            "pid",
            "ppid",
            "name",
            "cmdline",
            "create_time",
        ]
    ):
        try:
            name = (
                process.info.get("name")
                or ""
            ).lower()

            cmdline = process.info.get(
                "cmdline"
            ) or []

            command_text = " ".join(
                str(value)
                for value in cmdline
            )

            lower_command = command_text.lower()

            if not any(
                keyword in name
                or keyword in lower_command
                for keyword in (
                    "chrome",
                    "chromium",
                    "chromedriver",
                    "uc_driver",
                )
            ):
                continue

            processes[process.pid] = {
                "pid": process.pid,
                "ppid": process.info.get("ppid"),
                "name": process.info.get("name"),
                "cmdline": command_text,
                "create_time": process.info.get(
                    "create_time"
                ),
            }

        except (
            psutil.NoSuchProcess,
            psutil.AccessDenied,
            psutil.ZombieProcess,
        ):
            continue

    return processes

# ================
#　pyブラウザプロセス終了
# ================
def kill_browser_process_tree(
    driver,
) -> None:
    """
    このDriverが使用している専用profile_dirのChromeと、
    対応するuc_driverだけを終了する。

    手動Chromeや他スクリプトのChromeには影響しない。
    """
    print("[KILL] このブラウザのプロセス終了開始")

    profile_dir = getattr(
        driver,
        "_detapachi_profile_dir",
        None,
    )

    service = getattr(
        driver,
        "service",
        None,
    )

    service_process = getattr(
        service,
        "process",
        None,
    )

    driver_pid = getattr(
        service_process,
        "pid",
        None,
    )

    print(
        f"[KILL] 対象profile_dir="
        f"{profile_dir}"
    )

    print(
        f"[KILL] uc_driver PID="
        f"{driver_pid}"
    )

    target_processes = []

    if profile_dir:
        for process in psutil.process_iter(
            [
                "pid",
                "name",
                "cmdline",
            ]
        ):
            try:
                command_text = " ".join(
                    process.info.get("cmdline")
                    or []
                )

                if profile_dir in command_text:
                    target_processes.append(
                        process
                    )

                    print(
                        "[KILL] 対象検出: "
                        f"PID={process.pid}, "
                        f"name={process.info.get('name')}"
                    )

            except (
                psutil.NoSuchProcess,
                psutil.AccessDenied,
                psutil.ZombieProcess,
            ):
                continue

    print(
        f"[KILL] profile一致プロセス数="
        f"{len(target_processes)}"
    )

    # Chrome本体・子プロセスを終了
    for process in reversed(
        target_processes
    ):
        try:
            process.kill()

            print(
                f"[KILL] 終了要求: "
                f"PID={process.pid}"
            )

        except (
            psutil.NoSuchProcess,
            psutil.AccessDenied,
        ):
            pass

    if target_processes:
        gone, alive = psutil.wait_procs(
            target_processes,
            timeout=5,
        )

        print(
            f"[KILL] 終了済み={len(gone)}, "
            f"残存={len(alive)}"
        )

        for process in alive:
            try:
                process.kill()
            except (
                psutil.NoSuchProcess,
                psutil.AccessDenied,
            ):
                pass

    # 最後にuc_driverを終了
    if driver_pid:
        try:
            driver_process = psutil.Process(
                driver_pid
            )

            driver_process.kill()

            print(
                f"[KILL] uc_driver終了: "
                f"PID={driver_pid}"
            )

        except psutil.NoSuchProcess:
            print(
                "[KILL] uc_driverは"
                "すでに終了済み"
            )

        except psutil.AccessDenied as error:
            print(
                "[KILL] uc_driver終了権限エラー: "
                f"{error}"
            )

    print(
        "[KILL] このブラウザの"
        "プロセス終了完了"
    )
    
# ======== バッチ開始時のナビ（既存の安定化） ========
MAX_NAV_RETRY = site_config.MAX_NAV_RETRY


def open_and_navigate_with_retry(
    proxy_url: str | None,
    target_url: str,
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
                load_cookies(drv)
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
            # 台番号検索メニューをまず8秒待つ
            # ==========================================
            try:
                print(
                    "[NAV] 台番号検索メニュー待機"
                    "（最大8秒）"
                )

                wait_search_menu_ready(
                    drv,
                    timeout=8,
                )

            except TimeoutException:
                # ======================================
                # 8秒以内に描画されなければ
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
    
# ======== ★ 行ごとの“最小”再起動用（1回だけ） ========
def ensure_on_target_or_raise(
    driver,
    target_url,
    timeout=12,
):
    """
    ページが生存しており、
    台番号検索フォームを操作できるか確認する。
    """
    ready = driver.execute_script(
        "return document.readyState"
    )

    if ready not in (
        "interactive",
        "complete",
    ):
        raise TimeoutException(
            f"readyState={ready}"
        )

    current_host = urlparse(
        driver.current_url
    ).hostname

    target_host = urlparse(
        target_url
    ).hostname

    allowed_hosts = {
        target_host,
        f"www.{target_host}"
        if target_host
        and not target_host.startswith("www.")
        else target_host,
    }

    if current_host not in allowed_hosts:
        raise WebDriverException(
            f"unexpected host: "
            f"{driver.current_url}"
        )

    wait_search_menu_ready(
        driver,
        timeout=timeout,
    )
    
class SearchResultTimeoutError(TimeoutException):
    """検索後、取得更新日要素を時間内に取得できなかった。"""


def normalize_dai_number(value) -> str:
    """台番号表記を比較用の数字文字列へ統一する。"""
    match = re.search(r"\d+", str(value or ""))
    if not match:
        return ""
    return str(int(match.group()))


def normalize_update_date_text(text: str) -> str:
    """取得更新日の表示文字列を YYYY/MM/DD HH:MM 形式へ正規化する。"""
    value = str(text or "")
    value = value.replace("\xa0", " ")
    value = value.replace("\u3000", " ")
    value = re.sub(r"\s+", " ", value)
    value = re.sub(r"\s*更新\s*$", "", value)
    return value.strip()


def wait_for_update_date(
    driver,
    *,
    dai_number,
    timeout=60,
) -> tuple[str, str]:
    """
    検索後、次の条件が両方成立するまで最大timeout秒待つ。

    1. 取得更新日 #upYMDhms が空ではない
    2. 表示台番号が検索台番号と一致する

    Cloudflare確認画面が表示された場合は、
    トップページおよびiframeを確認してログを出す。

    Cloudflareが自動通過した場合はそのまま続行する。
    一定時間残り続けた場合は例外を出す。

    Returns
    -------
    tuple[str, str]
        取得更新日の生文字列、画面上の台番号表示
    """

    expected_number = normalize_dai_number(
        dai_number
    )

    deadline = time.time() + timeout

    last_update_text = ""
    last_display_text = ""
    last_display_number = ""

    # Cloudflareを最初に検出した時刻
    cloudflare_started_at = None

    # 同じiframe検出ログを何度も出さないため
    cloudflare_logged = False

    while time.time() < deadline:
        try:
            # ==========================================
            # ブラウザクラッシュ・セッション切断確認
            # ==========================================
            driver.execute_script(
                "return document.readyState"
            )

            # ==========================================
            # Cloudflare確認
            # ==========================================
            cloudflare_detected = False

            # ------------------------------------------
            # トップページ確認
            # ------------------------------------------
            try:
                driver.switch_to.default_content()

                title = (
                    driver.title
                    or ""
                ).lower()

                body_text = (
                    driver.find_element(
                        By.TAG_NAME,
                        "body",
                    ).text
                    or ""
                ).lower()

                if (
                    "just a moment" in title
                    or "verify you are human" in body_text
                    or "cloudflare" in body_text
                ):
                    cloudflare_detected = True

            except Exception:
                pass

            # ------------------------------------------
            # iframe確認
            # ------------------------------------------
            try:
                driver.switch_to.default_content()

                frames = driver.find_elements(
                    By.TAG_NAME,
                    "iframe",
                )

                for frame_index, frame in enumerate(
                    frames
                ):
                    try:
                        frame_src = (
                            frame.get_attribute(
                                "src"
                            )
                            or ""
                        ).lower()

                        frame_title = (
                            frame.get_attribute(
                                "title"
                            )
                            or ""
                        ).lower()

                        if (
                            "cloudflare" in frame_src
                            or "challenge" in frame_src
                            or "turnstile" in frame_src
                            or "cloudflare" in frame_title
                            or "challenge" in frame_title
                            or "turnstile" in frame_title
                        ):
                            cloudflare_detected = True

                            if not cloudflare_logged:
                                print(
                                    "[CLOUDFLARE] "
                                    "Cloudflare iframeを検出: "
                                    f"index={frame_index}, "
                                    f"src={frame_src!r}, "
                                    f"title={frame_title!r}"
                                )

                                cloudflare_logged = True

                            break

                    except Exception:
                        continue

            except Exception:
                pass

            finally:
                try:
                    driver.switch_to.default_content()
                except Exception:
                    pass

            # ==========================================
            # Cloudflare表示中
            # ==========================================
            if cloudflare_detected:
                if cloudflare_started_at is None:
                    cloudflare_started_at = (
                        time.time()
                    )

                    print(
                        "[CLOUDFLARE] "
                        "Cloudflare確認画面を検出しました。"
                        "自動通過を最大15秒待ちます"
                    )

                elapsed = (
                    time.time()
                    - cloudflare_started_at
                )

                if elapsed >= 15:
                    raise RuntimeError(
                        "Cloudflare確認画面が"
                        "15秒以内に自動通過しませんでした"
                    )

                time.sleep(0.5)
                continue

            # ==========================================
            # Cloudflareから通常ページへ戻った
            # ==========================================
            if cloudflare_started_at is not None:
                print(
                    "[CLOUDFLARE] "
                    "Cloudflare自動通過を確認しました"
                )

                cloudflare_started_at = None
                cloudflare_logged = False

            # ==========================================
            # 必ずトップ階層へ戻す
            # ==========================================
            driver.switch_to.default_content()

            # ------------------------------
            # 取得更新日
            # ------------------------------
            update_elements = (
                driver.find_elements(
                    By.ID,
                    "upYMDhms",
                )
            )

            if update_elements:
                try:
                    last_update_text = (
                        update_elements[0]
                        .get_attribute(
                            "textContent"
                        )
                        or ""
                    ).strip()

                except Exception:
                    last_update_text = ""

            else:
                last_update_text = ""

            # ------------------------------
            # 表示台番号
            # ------------------------------
            number_elements = (
                driver.find_elements(
                    By.CSS_SELECTOR,
                    "h2.nc-text-align-left",
                )
            )

            if number_elements:
                try:
                    last_display_text = (
                        number_elements[0]
                        .get_attribute(
                            "textContent"
                        )
                        or ""
                    ).strip()

                    last_display_number = (
                        normalize_dai_number(
                            last_display_text
                        )
                    )

                except Exception:
                    last_display_text = ""
                    last_display_number = ""

            else:
                last_display_text = ""
                last_display_number = ""

            # ==========================================
            # 更新日あり + 台番号一致
            # ==========================================
            if (
                last_update_text
                and last_display_number
                == expected_number
            ):
                print(
                    "[SEARCH] 検索結果を確認: "
                    f"台番号={expected_number}, "
                    f"更新日時={last_update_text!r}, "
                    f"台番号表示="
                    f"{last_display_text!r}"
                )

                return (
                    last_update_text,
                    last_display_text,
                )

            # ==========================================
            # 前の検索結果が残っている
            # ==========================================
            if (
                last_display_number
                and last_display_number
                != expected_number
            ):
                print(
                    "[SEARCH] 前の検索結果を表示中: "
                    f"検索={expected_number}, "
                    f"表示={last_display_number}"
                )

        # ==============================================
        # Chromeクラッシュ等
        # ==============================================
        except WebDriverException:
            raise

        # ==============================================
        # Cloudflareタイムアウト等
        # ==============================================
        except RuntimeError:
            raise

        # ==============================================
        # DOM切替途中など
        # ==============================================
        except Exception:
            pass

        time.sleep(0.5)

    # ==============================================
    # 通常タイムアウト
    # ==============================================
    raise SearchResultTimeoutError(
        f"検索後{timeout}秒以内に対象台番号の"
        "取得更新日を確認できませんでした。"
        f" expected={expected_number!r}"
        f" displayed={last_display_number!r}"
        f" display_text={last_display_text!r}"
        f" update_text={last_update_text!r}"
    )

# ========= メインループ =========
batch_size = BATCH_SIZE
sku_seq = get_starting_sku_seq(
    conn,
    table_name,
    sku_date,
)

total = len(filtered_dai_numbers)

for batch_start in range(
    0,
    total,
    batch_size,
):
    batch_end = min(
        batch_start + batch_size,
        total,
    )

    proxy_url = resolve_proxy(
        batch_index=batch_start,
        mode=PROXY_MODE,
        proxy_list=PROXY_LIST,
        rotate_every=PROXY_ROTATE_EVERY,
    )

    print(
        f"[INFO] Proxy for batch "
        f"{batch_start}-{batch_end}: "
        f"{proxy_url or '(none)'}"
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
                        "[WAIT] もっと見るクリック前に8秒待機"
                    )
                    
                    time.sleep(8)
                    
                    # --------------------------------------
                    # もっと見る
                    # --------------------------------------

                    print_step(
                        "「もっと見る」展開"
                    )

                    more_click_count = click_more(
                        browser,
                        max_clicks=5,
                        wait_after_click=10,
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

                            # ここはパチとカラム違う
                            wanted_columns = [
                                "時刻",
                                "スタート",
                                "ステータス",
                                "出玉pt",
                            ]

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
                                            "時刻"
                                        ]
                                    )
                                    or None
                                )

                                history_game = (
                                    to_int_or_none(
                                        get_cell_text(
                                            column_indexes[
                                                "スタート"
                                            ]
                                        )
                                    )
                                )

                                history_status = (
                                    get_cell_text(
                                        column_indexes[
                                            "ステータス"
                                        ]
                                    )
                                    or None
                                )

                                if (
                                    column_indexes[
                                        "出玉pt"
                                    ]
                                    is not None
                                ):
                                    history_output = (
                                        to_int_or_none(
                                            get_cell_text(
                                                column_indexes[
                                                    "出玉pt"
                                                ]
                                            )
                                        )
                                    )

                                else:
                                    history_output = None

                                data_entry[
                                    f"時刻"
                                    f"{history_number}"
                                    f"回前"
                                ] = history_time

                                data_entry[
                                    f"スタート"
                                    f"{history_number}"
                                    f"回前"
                                ] = history_game

                                data_entry[
                                    f"ステータス"
                                    f"{history_number}"
                                    f"回前"
                                ] = history_status

                                data_entry[
                                    f"出玉pt"
                                    f"{history_number}"
                                    f"回前"
                                ] = history_output

                                print(
                                    f"[HISTORY] "
                                    f"{history_number}回前 | "
                                    f"時刻={history_time} | "
                                    f"スタート={history_game} | "
                                    f"ステータス="
                                    f"{history_status} | "
                                    f"出玉pt="
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
                "[WAIT] 次の台まで15秒待機"
            )
            
            time.sleep(15)

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

    time.sleep(5)


conn.close()
print("✅ 毎ループUPSERT＋行ごと最小再起動リトライで完了")

print(f"[IMAGE] WebP保存先: {webp_dir}")
print(f"[INFO] 完了: {time.time() - start_time:.2f}秒")