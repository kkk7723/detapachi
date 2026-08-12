import time

from selenium.common.exceptions import (
    TimeoutException,
    WebDriverException,
)
from selenium.webdriver.common.by import By


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

            time.sleep(2)  # ← これだけ追加スクロール

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