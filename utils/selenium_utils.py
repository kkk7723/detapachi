import time

from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait


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