# utils/network_utils.py

from __future__ import annotations

import asyncio
import subprocess
import threading
import time
from typing import Any

import requests
from tapo import ApiClient


# =========================================================
# プロキシ選択
# =========================================================

def resolve_proxy(
    batch_index: int,
    mode: str,
    proxy_list: list[str],
    rotate_every: int,
) -> str | None:
    """
    プロキシ設定から、今回使用するプロキシURLを返す。

    mode:
        "none" : プロキシを使わない
        "list" : proxy_listから順番に選択
        その他 : modeの値を直接プロキシとして使用
    """
    normalized_mode = (mode or "none").strip().lower()

    if normalized_mode == "none":
        return None

    if normalized_mode != "list":
        raw = (mode or "").strip()

        if not raw or raw.lower() == "none":
            return None

        return raw if "://" in raw else f"http://{raw}"

    if not proxy_list:
        return None

    step = max(1, int(rotate_every or 1))
    index = (batch_index // step) % len(proxy_list)
    selected = str(proxy_list[index]).strip()

    if not selected or selected.lower() == "none":
        return None

    return selected if "://" in selected else f"http://{selected}"


# =========================================================
# コマンド共通
# =========================================================

def run_command(
    command: list[str],
    *,
    check: bool = False,
) -> subprocess.CompletedProcess[str]:
    """コマンドを実行し、標準出力と標準エラーを返す。"""
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=check,
    )


# =========================================================
# IP確認
# =========================================================

def get_global_ip(
    interface: str,
    timeout: int = 10,
) -> str:
    """指定インターフェース経由のグローバルIPを取得する。"""
    result = subprocess.run(
        [
            "curl",
            "--interface",
            interface,
            "--silent",
            "--show-error",
            "--max-time",
            str(timeout),
            "https://api.ipify.org",
        ],
        capture_output=True,
        text=True,
        check=True,
    )

    global_ip = result.stdout.strip()

    if not global_ip:
        raise RuntimeError(
            f"グローバルIPが空です: interface={interface}"
        )

    return global_ip


def get_squid_ip(
    squid_proxy: str,
    timeout: int = 10,
) -> str:
    """Squidプロキシ経由のグローバルIPを取得する。"""
    proxies = {
        "http": squid_proxy,
        "https": squid_proxy,
    }

    response = requests.get(
        "https://api.ipify.org",
        proxies=proxies,
        timeout=timeout,
    )
    response.raise_for_status()

    global_ip = response.text.strip()

    if not global_ip:
        raise RuntimeError(
            f"Squid経由グローバルIPが空です: proxy={squid_proxy}"
        )

    return global_ip


def verify_hr01_global_ip(
    *,
    hr01_interface: str,
    squid_proxy: str,
    timeout: int = 20,
    require_match: bool = True,
) -> tuple[str, str]:
    """
    HR01直接IPとSquid経由IPを取得して表示する。

    Squid経由IPがメガ・エッグ固定IPならNG。
    それ以外なら処理を続行する。
    """
    print("\n--- グローバルIP確認 ---")

    hr01_ip = get_global_ip(
        hr01_interface,
        timeout=timeout,
    )
    print(f"HR01直接IP: {hr01_ip}")

    squid_ip = get_squid_ip(
        squid_proxy,
        timeout=timeout,
    )
    print(f"Squid経由IP: {squid_ip}")

    # メガ・エッグの固定グローバルIP
    megaegg_ip = "219.105.53.125"

    # ==========================================
    # Squidがメガ・エッグから出ていたらNG
    # ==========================================
    if squid_ip == megaegg_ip:
        raise RuntimeError(
            "Squidがメガ・エッグ回線から"
            "アクセスしています。"
            f" Squid={squid_ip!r}"
        )

    # ==========================================
    # メガ・エッグでなければOK
    # ==========================================
    if hr01_ip == squid_ip:
        print(
            f"グローバルIP確認OK: {squid_ip}"
        )
    else:
        print(
            "[IP INFO] HR01直接IPと"
            "Squid経由IPは異なりますが、"
            "Squidはメガ・エッグIPではないため"
            "許容します"
        )

        print(
            f"[IP INFO] HR01={hr01_ip}, "
            f"Squid={squid_ip}"
        )

    return hr01_ip, squid_ip


# =========================================================
# HR01ネットワーク準備待機
# =========================================================

def wait_for_hr01_network(
    hr01_interface: str,
    hr01_gateway: str,
    *,
    timeout: int = 180,
    interval: int = 3,
) -> str:
    """
    HR01側ネットワークが使用可能になるまで待機する。

    確認内容:
    - インターフェースが存在する
    - インターフェースをUPにする
    - IPv4アドレスが付いている
    - ゲートウェイへpingできる
    """
    print("\n--- HR01ネットワーク準備待機 ---")

    deadline = time.time() + timeout
    last_status = ""

    while time.time() < deadline:
        link_result = run_command(
            [
                "ip",
                "link",
                "show",
                "dev",
                hr01_interface,
            ]
        )

        if link_result.returncode != 0:
            last_status = f"インターフェース未検出: {hr01_interface}"
            print(f"[HR01] {last_status}")
            time.sleep(interval)
            continue

        up_result = run_command(
            [
                "sudo",
                "ip",
                "link",
                "set",
                "dev",
                hr01_interface,
                "up",
            ]
        )

        if up_result.returncode != 0:
            last_status = (
                "インターフェースUP失敗: "
                f"{up_result.stderr.strip()}"
            )
            print(f"[HR01] {last_status}")
            time.sleep(interval)
            continue

        addr_result = run_command(
            [
                "ip",
                "-4",
                "-o",
                "addr",
                "show",
                "dev",
                hr01_interface,
                "scope",
                "global",
            ]
        )

        ipv4_info = addr_result.stdout.strip()

        if not ipv4_info:
            last_status = f"IPv4アドレス待機中: {hr01_interface}"
            print(f"[HR01] {last_status}")

            nmcli_result = run_command(
                [
                    "nmcli",
                    "device",
                    "connect",
                    hr01_interface,
                ]
            )

            if (
                nmcli_result.returncode != 0
                and nmcli_result.stderr.strip()
            ):
                print(
                    "[HR01] nmcli再接続結果: "
                    f"{nmcli_result.stderr.strip()}"
                )

            time.sleep(interval)
            continue

        print(f"[HR01] IPv4確認: {ipv4_info}")

        ping_result = run_command(
            [
                "ping",
                "-I",
                hr01_interface,
                "-c",
                "1",
                "-W",
                "2",
                hr01_gateway,
            ]
        )

        if ping_result.returncode == 0:
            print(
                "[HR01] ゲートウェイ疎通確認成功: "
                f"{hr01_gateway}"
            )
            return ipv4_info

        last_status = f"ゲートウェイ応答待機中: {hr01_gateway}"
        print(f"[HR01] {last_status}")
        time.sleep(interval)

    raise RuntimeError(
        "HR01ネットワークが使用可能になりませんでした。"
        f" interface={hr01_interface}"
        f" gateway={hr01_gateway}"
        f" timeout={timeout}"
        f" last_status={last_status}"
    )


# =========================================================
# HR01ルーティング
# =========================================================

def reset_hr01_route(
    hr01_interface: str,
    hr01_gateway: str,
    route_table: str = "hr01",
) -> None:
    """HR01用ルーティングテーブルを再設定する。"""
    print("\n--- HR01ルート再設定 ---")

    gateway_parts = hr01_gateway.split(".")

    if len(gateway_parts) != 4:
        raise ValueError(
            f"不正なHR01ゲートウェイです: {hr01_gateway!r}"
        )

    gateway_network = (
        f"{gateway_parts[0]}."
        f"{gateway_parts[1]}."
        f"{gateway_parts[2]}.0/24"
    )

    flush_result = run_command(
        [
            "sudo",
            "ip",
            "route",
            "flush",
            "table",
            route_table,
        ]
    )

    if flush_result.returncode != 0 and flush_result.stderr.strip():
        print(
            "[HR01] ルートテーブル初期化警告: "
            f"{flush_result.stderr.strip()}"
        )

    network_result = run_command(
        [
            "sudo",
            "ip",
            "route",
            "replace",
            gateway_network,
            "dev",
            hr01_interface,
            "scope",
            "link",
            "table",
            route_table,
        ]
    )

    if network_result.returncode != 0:
        raise RuntimeError(
            "HR01直結ルート設定失敗: "
            f"{network_result.stderr.strip()}"
        )

    default_result = run_command(
        [
            "sudo",
            "ip",
            "route",
            "replace",
            "default",
            "via",
            hr01_gateway,
            "dev",
            hr01_interface,
            "table",
            route_table,
        ]
    )

    if default_result.returncode != 0:
        raise RuntimeError(
            "HR01デフォルトルート設定失敗: "
            f"{default_result.stderr.strip()}"
        )

    result = run_command(
        [
            "ip",
            "route",
            "show",
            "table",
            route_table,
        ]
    )

    print(result.stdout.strip())


# =========================================================
# HR01再起動
# =========================================================

async def reboot_hr01(
    *,
    tapo_username: str,
    tapo_password: str,
    tapo_ip: str,
    hr01_interface: str,
    hr01_gateway: str,
    squid_proxy: str,
    power_off_wait: int = 60,
    startup_wait: int = 60,
    network_wait_timeout: int = 180,
) -> None:
    """
    Tapo P110を使ってHR01を再起動し、
    ネットワーク準備・ルート再設定・IP確認まで行う。
    """
    if not tapo_username:
        raise ValueError("Tapoユーザー名が設定されていません")

    if not tapo_password:
        raise ValueError("Tapoパスワードが設定されていません")

    client = ApiClient(
        tapo_username,
        tapo_password,
    )

    device = await client.p110(tapo_ip)

    print("========== HR01再起動開始 ==========")

    print("HR01 電源OFF")
    await device.off()

    print(f"{power_off_wait}秒待機...")
    await asyncio.sleep(power_off_wait)

    print("HR01 電源ON")
    await device.on()

    print(f"HR01初期起動待ち {startup_wait}秒...")
    await asyncio.sleep(startup_wait)

    wait_for_hr01_network(
        hr01_interface=hr01_interface,
        hr01_gateway=hr01_gateway,
        timeout=network_wait_timeout,
        interval=3,
    )

    reset_hr01_route(
        hr01_interface=hr01_interface,
        hr01_gateway=hr01_gateway,
    )

    # HR01再起動処理内でもIPを表示する。
    # 呼び出し側では対象URLアクセス直前に再度確認する。
    verify_hr01_global_ip(
        hr01_interface=hr01_interface,
        squid_proxy=squid_proxy,
        timeout=20,
        require_match=True,
    )

    print("========== HR01再起動完了 ==========")


# =========================================================
# Jupyter対応同期ラッパー
# =========================================================

def _run_coroutine_in_thread(
    coroutine,
) -> Any:
    """別スレッドのイベントループでcoroutineを同期実行する。"""
    result: dict[str, Any] = {}
    error: dict[str, BaseException] = {}

    def runner() -> None:
        try:
            result["value"] = asyncio.run(coroutine)
        except BaseException as exc:
            error["exception"] = exc

    thread = threading.Thread(
        target=runner,
        daemon=False,
    )

    thread.start()
    thread.join()

    if "exception" in error:
        raise error["exception"]

    return result.get("value")


def reboot_hr01_sync(
    *,
    tapo_username: str,
    tapo_password: str,
    tapo_ip: str,
    hr01_interface: str,
    hr01_gateway: str,
    squid_proxy: str,
    power_off_wait: int = 60,
    startup_wait: int = 60,
    network_wait_timeout: int = 180,
) -> None:
    """通常の.py実行とJupyterの両方から同期的に呼び出す。"""
    coroutine = reboot_hr01(
        tapo_username=tapo_username,
        tapo_password=tapo_password,
        tapo_ip=tapo_ip,
        hr01_interface=hr01_interface,
        hr01_gateway=hr01_gateway,
        squid_proxy=squid_proxy,
        power_off_wait=power_off_wait,
        startup_wait=startup_wait,
        network_wait_timeout=network_wait_timeout,
    )

    try:
        asyncio.get_running_loop()

    except RuntimeError:
        asyncio.run(coroutine)

    else:
        _run_coroutine_in_thread(coroutine)