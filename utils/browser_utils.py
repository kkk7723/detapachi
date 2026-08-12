import os
import re
import time

import psutil
from selenium.webdriver.support.ui import WebDriverWait
from seleniumbase import Driver

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
    # Driver起動ucmode変更など
    # ==============================================

    ANDROID_UA = (
        "Mozilla/5.0 "
        "(Linux; Android 10; K) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/139.0.0.0 "
        "Mobile Safari/537.36"
    )
    
    driver = Driver(
        uc=True,
        agent=ANDROID_UA,
        log_cdp=True,
        headed=True,
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

    driver._detaslot_process_pids = (
        new_process_ids
    )

    driver._detaslot_profile_dir = (
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
        600,
        1080,
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

    driver._detaslot_driver_pid = (
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


def wait_browser_ready(driver, timeout=10):
    """Chrome起動直後の準備完了待ち（about:blank → readyState 確認 → no-op JS）"""
    driver.get("about:blank")
    WebDriverWait(driver, timeout).until(
        lambda d: d.execute_script("return document.readyState") in ("interactive", "complete")
    )
    driver.execute_script("return 1")  # no-op：Executorが生きてるか確認


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
        "_detaslot_profile_dir",
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