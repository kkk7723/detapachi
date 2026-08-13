import os
import time
import requests

from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import (
    Select,
    WebDriverWait,
)
from seleniumbase import Driver

from config.common import (
    SQUID_PROXY,
    WEB_SETTING_LOGIN_URL,
    WEB_SETTING_PASSWORD,
)


# ==================================================
# 定数
# ==================================================

PAGE_LOAD_TIMEOUT = 30
ELEMENT_TIMEOUT = 20
PAGE_INITIALIZE_WAIT = 3
NETWORK_SEARCH_TIMEOUT = 60

TARGET_NETWORK_NAME = "NTT DOCOMO"

# ネットワーク設定完了後の待機時間
IP_RECHECK_WAIT = 60


# ==================================================
# Squid経由グローバルIP取得
# ==================================================

def get_squid_global_ip():
    """
    Squidプロキシ経由で現在のグローバルIPを取得する。
    """

    print()
    print("=" * 60)
    print("Squid経由グローバルIP確認")
    print("=" * 60)

    print(
        f"Squid: "
        f"{SQUID_PROXY}"
    )

    proxies = {
        "http": SQUID_PROXY,
        "https": SQUID_PROXY,
    }

    try:

        response = requests.get(
            "https://api.ipify.org",
            proxies=proxies,
            timeout=10,
        )

        response.raise_for_status()

        global_ip = response.text.strip()

        if not global_ip:
            raise RuntimeError(
                "グローバルIPが空です"
            )

        print(
            f"Squid経由グローバルIP: "
            f"{global_ip}"
        )

        return global_ip

    except Exception as e:

        print(
            "Squid経由グローバルIP取得失敗"
        )

        print(
            f"{type(e).__name__}: "
            f"{e}"
        )

        raise


# ==================================================
# ブラウザ起動
# ==================================================

def open_browser():
    """
    SeleniumBase Driver を画面表示モードで起動する。
    """

    print()
    print("=" * 60)
    print("ブラウザ起動")
    print("=" * 60)

    print(
        f"DISPLAY: "
        f"{os.environ.get('DISPLAY')}"
    )

    driver = Driver(
        browser="chrome",
        headed=True,
    )

    driver.set_page_load_timeout(
        PAGE_LOAD_TIMEOUT
    )

    print(
        "ブラウザ起動完了"
    )

    return driver


# ==================================================
# ページ読み込み待ち
# ==================================================

def wait_page_loaded(
    driver,
):
    """
    document.readyState == complete まで待つ。
    """

    WebDriverWait(
        driver,
        PAGE_LOAD_TIMEOUT,
    ).until(
        lambda d: (
            d.execute_script(
                "return document.readyState"
            )
            == "complete"
        )
    )


# ==================================================
# 要素クリック
# ==================================================

def click_element(
    driver,
    element,
):
    """
    通常クリックを試し、
    失敗した場合は JavaScript click を使用する。
    """

    driver.execute_script(
        """
        arguments[0].scrollIntoView({
            block: 'center',
            inline: 'center'
        });
        """,
        element,
    )

    time.sleep(
        0.3
    )

    try:

        element.click()

    except Exception:

        driver.execute_script(
            "arguments[0].click();",
            element,
        )


# ==================================================
# 適用完了ポップアップ
# ==================================================

def accept_apply_alert(
    driver,
):
    """
    適用後に表示される
    「適用しました」のポップアップでOKを押す。
    """

    print(
        "最終確認ポップアップを待機..."
    )

    alert = WebDriverWait(
        driver,
        ELEMENT_TIMEOUT,
    ).until(
        EC.alert_is_present()
    )

    try:

        alert_text = alert.text

        print(
            f"ポップアップ内容: "
            f"{alert_text!r}"
        )

    except Exception:
        pass

    alert.accept()

    print(
        "ポップアップのOKをクリック"
    )


# ==================================================
# web.setting を開く
# ==================================================

def open_web_setting(
    driver,
):
    """
    web.setting を開く。
    """

    print()
    print("=" * 60)
    print("web.setting を開きます")
    print("=" * 60)

    print(
        f"URL: "
        f"{WEB_SETTING_LOGIN_URL}"
    )

    driver.get(
        WEB_SETTING_LOGIN_URL
    )

    wait_page_loaded(
        driver,
    )

    print(
        "web.setting 読み込み完了"
    )

    print(
        f"現在URL: "
        f"{driver.current_url}"
    )

    print(
        f"タイトル: "
        f"{driver.title}"
    )

    # ------------------------------------------
    # ページ固有JavaScript初期化待ち
    # ------------------------------------------

    print(
        "ページ初期化待ち..."
    )

    time.sleep(
        PAGE_INITIALIZE_WAIT
    )

    print(
        "ページ初期化待ち完了"
    )


# ==================================================
# 最初のログインボタン
# ==================================================

def click_first_login_button(
    driver,
):
    """
    最初のログインボタンをクリックする。
    """

    print()
    print(
        "最初のログインボタンを待機..."
    )

    # ------------------------------------------
    # GetNativeAppStatus 準備待ち
    # ------------------------------------------

    WebDriverWait(
        driver,
        ELEMENT_TIMEOUT,
    ).until(
        lambda d: d.execute_script(
            """
            return (
                typeof GetNativeAppStatus
                === 'function'
            );
            """
        )
    )

    print(
        "GetNativeAppStatus 準備完了"
    )

    time.sleep(
        1
    )

    # ------------------------------------------
    # 表示中のログインボタンを探す
    # ------------------------------------------

    buttons = WebDriverWait(
        driver,
        ELEMENT_TIMEOUT,
    ).until(
        EC.presence_of_all_elements_located(
            (
                By.CSS_SELECTOR,
                "button.login-button",
            )
        )
    )

    login_button = None

    for button in buttons:

        if (
            button.is_displayed()
            and button.is_enabled()
        ):
            login_button = button
            break

    if login_button is None:

        raise RuntimeError(
            "表示中のログインボタンが見つかりません"
        )

    print(
        "最初のログインボタンをクリック"
    )

    click_element(
        driver,
        login_button,
    )

    print(
        "パスワード入力欄を待機..."
    )

    WebDriverWait(
        driver,
        ELEMENT_TIMEOUT,
    ).until(
        EC.visibility_of_element_located(
            (
                By.ID,
                "password",
            )
        )
    )

    print(
        "ログイン画面表示完了"
    )


# ==================================================
# パスワード入力
# ==================================================

def input_password(
    driver,
):
    """
    パスワードを入力する。
    """

    print(
        "パスワード入力..."
    )

    password_input = WebDriverWait(
        driver,
        ELEMENT_TIMEOUT,
    ).until(
        EC.visibility_of_element_located(
            (
                By.ID,
                "password",
            )
        )
    )

    password_input.clear()

    password_input.send_keys(
        WEB_SETTING_PASSWORD
    )

    print(
        "パスワード入力完了"
    )


# ==================================================
# ログイン送信
# ==================================================

def submit_login(
    driver,
):
    """
    ログインフォームを送信する。
    """

    print(
        "ログイン送信..."
    )

    submit_button = WebDriverWait(
        driver,
        ELEMENT_TIMEOUT,
    ).until(
        EC.element_to_be_clickable(
            (
                By.ID,
                "submit",
            )
        )
    )

    click_element(
        driver,
        submit_button,
    )

    wait_page_loaded(
        driver,
    )

    time.sleep(
        2
    )

    print(
        "ログイン送信完了"
    )


# ==================================================
# ログイン
# ==================================================

def login_web_setting(
    driver,
):
    """
    web.setting にログインする。
    """

    print()
    print("=" * 60)
    print("web.setting ログイン")
    print("=" * 60)

    click_first_login_button(
        driver,
    )

    input_password(
        driver,
    )

    submit_login(
        driver,
    )

    print()
    print(
        "ログイン処理完了"
    )

    print(
        f"現在URL: "
        f"{driver.current_url}"
    )


# ==================================================
# 設定メニュー
# ==================================================

def click_settings_menu(
    driver,
):
    """
    「設定」をクリックする。
    """

    print()
    print("=" * 60)
    print("設定メニュー")
    print("=" * 60)

    element = WebDriverWait(
        driver,
        ELEMENT_TIMEOUT,
    ).until(
        EC.presence_of_element_located(
            (
                By.XPATH,
                "//span[@data-locale='menu.Settings']"
                "/ancestor::a[1]",
            )
        )
    )

    print(
        "設定をクリック"
    )

    click_element(
        driver,
        element,
    )

    time.sleep(
        1
    )


# ==================================================
# モバイルネットワーク設定
# ==================================================

def click_mobile_network_settings(
    driver,
):
    """
    「モバイルネットワーク設定」をクリックする。
    """

    print(
        "モバイルネットワーク設定を待機..."
    )

    element = WebDriverWait(
        driver,
        ELEMENT_TIMEOUT,
    ).until(
        EC.presence_of_element_located(
            (
                By.XPATH,
                "//span["
                "@data-locale="
                "'menu.MobileNetworkSettings'"
                "]/ancestor::a[1]",
            )
        )
    )

    print(
        "モバイルネットワーク設定をクリック"
    )

    click_element(
        driver,
        element,
    )

    time.sleep(
        1
    )


# ==================================================
# ネットワーク設定
# ==================================================

def click_network_configuration(
    driver,
):
    """
    「ネットワーク設定」をクリックする。
    """

    print(
        "ネットワーク設定を待機..."
    )

    element = WebDriverWait(
        driver,
        ELEMENT_TIMEOUT,
    ).until(
        EC.presence_of_element_located(
            (
                By.XPATH,
                "//span["
                "@data-locale="
                "'menu.NetworkConfiguration'"
                "]/ancestor::a[1]",
            )
        )
    )

    print(
        "ネットワーク設定をクリック"
    )

    click_element(
        driver,
        element,
    )

    time.sleep(
        2
    )


# ==================================================
# 手動ネットワーク検索へ変更
# ==================================================

def select_manual_network_search(
    driver,
):
    """
    network_search を
    自動 -> 手動 に変更する。

    value:
        0 = 自動
        1 = 手動
    """

    print()
    print("=" * 60)
    print("ネットワーク検索方式変更")
    print("=" * 60)

    network_search = WebDriverWait(
        driver,
        ELEMENT_TIMEOUT,
    ).until(
        EC.visibility_of_element_located(
            (
                By.ID,
                "network_search",
            )
        )
    )

    print(
        "ネットワーク検索方式: 手動"
    )

    select = Select(
        network_search
    )

    select.select_by_value(
        "1"
    )

    WebDriverWait(
        driver,
        ELEMENT_TIMEOUT,
    ).until(
        lambda d: Select(
            d.find_element(
                By.ID,
                "network_search",
            )
        ).first_selected_option.get_attribute(
            "value"
        )
        == "1"
    )

    time.sleep(
        2
    )

    print(
        "手動へ変更完了"
    )


# ==================================================
# 手動ネットワーク検索 OK
# ==================================================

def click_manual_network_search_ok(
    driver,
):
    """
    手動ネットワーク検索画面の
    OK ボタンをクリックする。
    """

    print()
    print("=" * 60)
    print("手動ネットワーク検索")
    print("=" * 60)

    print(
        "OKボタンを待機..."
    )

    ok_button = WebDriverWait(
        driver,
        ELEMENT_TIMEOUT,
    ).until(
        EC.element_to_be_clickable(
            (
                By.CSS_SELECTOR,
                "button[onclick='SearchNetwork()']",
            )
        )
    )

    print(
        "OKをクリック"
    )

    click_element(
        driver,
        ok_button,
    )

    print(
        "ネットワーク検索開始"
    )


# ==================================================
# NTT DOCOMO 検索結果待機
# ==================================================

def wait_docomo_network(
    driver,
):
    """
    #search_network_section 内に
    手動ネットワーク検索結果が生成されるまで待つ。

    検索結果から NTT DOCOMO を探して返す。
    """

    print(
        "手動ネットワーク検索結果を待機..."
    )

    # ------------------------------------------
    # 検索結果エリア確認
    # ------------------------------------------

    search_section = WebDriverWait(
        driver,
        ELEMENT_TIMEOUT,
    ).until(
        EC.presence_of_element_located(
            (
                By.ID,
                "search_network_section",
            )
        )
    )

    print(
        "検索結果エリアを確認"
    )

    # ------------------------------------------
    # radio が生成されるまで待機
    # ------------------------------------------

    def network_result_exists(
        driver,
    ):

        radios = search_section.find_elements(
            By.CSS_SELECTOR,
            'input[type="radio"][name="network_new"]',
        )

        return len(radios) > 0

    WebDriverWait(
        driver,
        NETWORK_SEARCH_TIMEOUT,
    ).until(
        network_result_exists
    )

    # ------------------------------------------
    # 検索結果取得
    # ------------------------------------------

    radios = search_section.find_elements(
        By.CSS_SELECTOR,
        'input[type="radio"][name="network_new"]',
    )

    print(
        f"ネットワーク候補数: "
        f"{len(radios)}"
    )

    # ------------------------------------------
    # 候補一覧表示
    # ------------------------------------------

    for index, radio in enumerate(
        radios,
        start=1,
    ):

        try:

            radio_id = radio.get_attribute(
                "id"
            )

            radio_value = radio.get_attribute(
                "value"
            )

            print(
                f"[候補 {index}] "
                f"id={radio_id!r} "
                f"value={radio_value!r} "
                f"displayed={radio.is_displayed()} "
                f"enabled={radio.is_enabled()}"
            )

        except Exception as e:

            print(
                f"[候補 {index}] "
                f"取得失敗: "
                f"{e}"
            )

    # ------------------------------------------
    # NTT DOCOMO を探す
    # ------------------------------------------

    for radio in radios:

        radio_value = radio.get_attribute(
            "value"
        )

        if (
            radio_value
            and
            f"|{TARGET_NETWORK_NAME}|"
            in radio_value
        ):

            print(
                f"{TARGET_NETWORK_NAME}"
                f"ネットワークを確認: "
                f"{radio_value}"
            )

            return radio

    raise RuntimeError(
        f"検索結果に"
        f"{TARGET_NETWORK_NAME}"
        f"が見つかりません"
    )


# ==================================================
# NTT DOCOMO 選択
# ==================================================

def select_docomo_network(
    driver,
):
    """
    手動ネットワーク検索結果から
    NTT DOCOMO を選択する。
    """

    print()
    print("=" * 60)
    print("NTT DOCOMO選択")
    print("=" * 60)

    radio = wait_docomo_network(
        driver,
    )

    print(
        "NTT DOCOMOにチェック..."
    )

    driver.execute_script(
        """
        arguments[0].scrollIntoView({
            block: 'center',
            inline: 'center'
        });
        """,
        radio,
    )

    time.sleep(
        0.5
    )

    try:

        radio.click()

    except Exception as e:

        print(
            f"通常クリック失敗: "
            f"{type(e).__name__}: {e}"
        )

        print(
            "JavaScriptクリックを実行"
        )

        driver.execute_script(
            "arguments[0].click();",
            radio,
        )

    WebDriverWait(
        driver,
        ELEMENT_TIMEOUT,
    ).until(
        lambda d: radio.is_selected()
    )

    print(
        "NTT DOCOMO選択完了"
    )


# ==================================================
# 手動設定を適用
# ==================================================

def apply_manual_network(
    driver,
):
    """
    手動ネットワーク設定を適用し、
    「適用しました」のOKまで押す。
    """

    print()
    print("=" * 60)
    print("手動設定適用")
    print("=" * 60)

    apply_button = WebDriverWait(
        driver,
        ELEMENT_TIMEOUT,
    ).until(
        EC.element_to_be_clickable(
            (
                By.ID,
                "ManualApply",
            )
        )
    )

    print(
        "適用をクリック"
    )

    click_element(
        driver,
        apply_button,
    )

    print(
        "適用クリック完了"
    )

    accept_apply_alert(
        driver,
    )

    print(
        "手動設定適用完了"
    )


# ==================================================
# 自動ネットワーク検索へ変更
# ==================================================

def select_auto_network_search(
    driver,
):
    """
    network_search を
    手動 -> 自動 に変更する。

    value:
        0 = 自動
        1 = 手動
    """

    print()
    print("=" * 60)
    print("ネットワーク検索方式を自動へ変更")
    print("=" * 60)

    network_search = WebDriverWait(
        driver,
        ELEMENT_TIMEOUT,
    ).until(
        EC.visibility_of_element_located(
            (
                By.ID,
                "network_search",
            )
        )
    )

    select = Select(
        network_search
    )

    current_value = (
        select
        .first_selected_option
        .get_attribute(
            "value"
        )
    )

    print(
        f"現在値: "
        f"{current_value}"
    )

    print(
        "ネットワーク検索方式: 自動"
    )

    select.select_by_value(
        "0"
    )

    WebDriverWait(
        driver,
        ELEMENT_TIMEOUT,
    ).until(
        lambda d: Select(
            d.find_element(
                By.ID,
                "network_search",
            )
        ).first_selected_option.get_attribute(
            "value"
        )
        == "0"
    )

    print(
        "自動へ変更完了"
    )

    time.sleep(
        1
    )


# ==================================================
# 表示中の適用ボタン取得
# ==================================================

def get_visible_apply_button(
    driver,
):
    """
    現在表示されている適用ボタンを取得する。
    """

    manual_buttons = driver.find_elements(
        By.ID,
        "ManualApply",
    )

    for button in manual_buttons:

        try:

            if (
                button.is_displayed()
                and button.is_enabled()
            ):
                return button

        except Exception:
            pass

    buttons = driver.find_elements(
        By.XPATH,
        "//button["
        ".//span[@data-locale='common.Apply']"
        "]",
    )

    for button in buttons:

        try:

            if (
                button.is_displayed()
                and button.is_enabled()
            ):
                return button

        except Exception:
            pass

    raise RuntimeError(
        "表示中の適用ボタンが見つかりません"
    )


# ==================================================
# 自動設定を適用
# ==================================================

def apply_auto_network(
    driver,
):
    """
    自動ネットワーク設定を適用し、
    「適用しました」のOKまで押す。
    """

    print()
    print("=" * 60)
    print("自動設定適用")
    print("=" * 60)

    apply_button = WebDriverWait(
        driver,
        ELEMENT_TIMEOUT,
    ).until(
        lambda d: get_visible_apply_button(
            d
        )
    )

    print(
        "自動設定の適用をクリック"
    )

    click_element(
        driver,
        apply_button,
    )

    print(
        "自動設定の適用クリック完了"
    )

    accept_apply_alert(
        driver,
    )

    print(
        "自動設定適用完了"
    )


# ==================================================
# ネットワーク設定処理
# ==================================================

def configure_network(
    driver,
):
    """
    ネットワーク設定を実行する。

    設定
    ↓
    モバイルネットワーク設定
    ↓
    ネットワーク設定
    ↓
    手動
    ↓
    検索
    ↓
    NTT DOCOMO
    ↓
    適用
    ↓
    OK
    ↓
    自動
    ↓
    適用
    ↓
    OK
    """

    print()
    print("=" * 60)
    print("ネットワーク設定開始")
    print("=" * 60)

    click_settings_menu(
        driver,
    )

    click_mobile_network_settings(
        driver,
    )

    click_network_configuration(
        driver,
    )

    # ------------------------------------------
    # 手動
    # ------------------------------------------

    select_manual_network_search(
        driver,
    )

    click_manual_network_search_ok(
        driver,
    )

    select_docomo_network(
        driver,
    )

    apply_manual_network(
        driver,
    )

    # ------------------------------------------
    # 手動適用後の画面安定待ち
    # ------------------------------------------

    print()
    print(
        "手動設定適用後の画面安定待ち..."
    )

    time.sleep(
        2
    )

    # ------------------------------------------
    # 自動へ戻す
    # ------------------------------------------

    select_auto_network_search(
        driver,
    )

    apply_auto_network(
        driver,
    )

    print()
    print("=" * 60)
    print("ネットワーク設定完了")
    print("=" * 60)


# ==================================================
# ブラウザ終了
# ==================================================

def close_browser(
    driver,
):
    """
    ブラウザを終了する。
    """

    if driver is None:
        return

    print()
    print("=" * 60)
    print("ブラウザ終了")
    print("=" * 60)

    try:

        driver.quit()

        print(
            "ブラウザ終了完了"
        )

    except Exception as e:

        print(
            f"ブラウザ終了時エラー: "
            f"{type(e).__name__}: "
            f"{e}"
        )


# ==================================================
# IP変更結果表示
# ==================================================

def print_ip_result(
    before_ip,
    after_ip,
):
    """
    操作前後のSquid経由IPを比較して表示する。
    """

    print()
    print("=" * 60)
    print("グローバルIP変更結果")
    print("=" * 60)

    print(
        f"変更前: "
        f"{before_ip}"
    )

    print(
        f"変更後: "
        f"{after_ip}"
    )

    if before_ip == after_ip:

        print(
            "結果: IPは変更されていません"
        )

    else:

        print(
            "結果: IPが変更されました"
        )


# ==================================================
# HR01 グローバルIP変更
# ==================================================

def change_hr01_global_ip():
    """
    HR01設定画面を操作して
    モバイル回線のグローバルIP変更を行う。

    処理:
        操作前Squid経由IP確認
        ↓
        HR01設定画面ログイン
        ↓
        NTT DOCOMO手動選択
        ↓
        適用
        ↓
        自動へ戻す
        ↓
        適用
        ↓
        HR01設定用ブラウザ終了
        ↓
        60秒待機
        ↓
        操作後Squid経由IP確認
        ↓
        IP比較

    Returns:
        tuple:
            (before_ip, after_ip)
    """

    driver = None

    before_ip = None
    after_ip = None

    try:

        print()
        print("=" * 60)
        print("HR01 グローバルIP変更開始")
        print("=" * 60)

        # ------------------------------------------
        # 操作前 Squid経由IP確認
        # ------------------------------------------

        print()
        print("【操作前IP確認】")

        before_ip = get_squid_global_ip()

        # ------------------------------------------
        # HR01設定用ブラウザ起動
        # ------------------------------------------

        driver = open_browser()

        # ------------------------------------------
        # web.setting
        # ------------------------------------------

        open_web_setting(
            driver,
        )

        # ------------------------------------------
        # ログイン
        # ------------------------------------------

        login_web_setting(
            driver,
        )

        # ------------------------------------------
        # ネットワーク設定
        # ------------------------------------------

        configure_network(
            driver,
        )

        print()
        print("=" * 60)
        print("web.setting 自動操作完了")
        print("=" * 60)

    finally:

        # ------------------------------------------
        # HR01設定用ブラウザ終了
        # ------------------------------------------

        close_browser(
            driver,
        )

    # ------------------------------------------
    # 60秒待機
    # ------------------------------------------

    print()
    print("=" * 60)
    print("モバイル回線安定待ち")
    print("=" * 60)

    print(
        f"{IP_RECHECK_WAIT}秒待機します..."
    )

    time.sleep(
        IP_RECHECK_WAIT
    )

    print(
        f"{IP_RECHECK_WAIT}秒待機完了"
    )

    # ------------------------------------------
    # 操作後 Squid経由IP確認
    # ------------------------------------------

    print()
    print("【操作後IP確認】")

    after_ip = get_squid_global_ip()

    # ------------------------------------------
    # IP比較
    # ------------------------------------------

    print_ip_result(
        before_ip,
        after_ip,
    )

    print()
    print("=" * 60)
    print("HR01 グローバルIP変更完了")
    print("=" * 60)

    return (
        before_ip,
        after_ip,
    )