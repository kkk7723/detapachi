import time
from urllib.parse import urlparse

from selenium.common.exceptions import (
    TimeoutException,
    WebDriverException,
)
from selenium.webdriver.common.by import By

from utils.scraping_value_utils import normalize_dai_number


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