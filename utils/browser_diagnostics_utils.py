import json

def get_request_headers_for_domain(
    driver,
    domain: str,
) -> list[dict]:
    """
    Chrome performance logから、
    指定domainへ送信されたDocumentリクエストだけ取得する。

    CSS / JS / 画像 / XHR等は除外する。
    Cookie値はログへ出さない。
    """
    results = []

    try:
        logs = driver.get_log(
            "performance"
        )

    except Exception as exc:
        return [
            {
                "error": (
                    f"{type(exc).__name__}: "
                    f"{exc}"
                )
            }
        ]

    for entry in logs:
        try:
            message = json.loads(
                entry["message"]
            )

            message = message.get(
                "message",
                {}
            )

            if (
                message.get("method")
                != "Network.requestWillBeSent"
            ):
                continue

            params = message.get(
                "params",
                {}
            )

            # ==============================================
            # メインDocumentだけ
            # ==============================================
            if params.get("type") != "Document":
                continue

            request = params.get(
                "request",
                {}
            )

            url = request.get(
                "url",
                ""
            )

            if domain not in url:
                continue

            headers = request.get(
                "headers",
                {}
            )

            sanitized_headers = {}

            for key, value in headers.items():
                lower_key = key.lower()

                if lower_key == "cookie":
                    sanitized_headers[key] = (
                        "(present)"
                        if value
                        else "(empty)"
                    )

                else:
                    sanitized_headers[key] = value

            results.append(
                {
                    "url": url,
                    "method": request.get(
                        "method"
                    ),
                    "type": params.get(
                        "type"
                    ),
                    "headers": sanitized_headers,
                }
            )

        except Exception:
            continue

    return results

def print_request_headers(
    requests: list[dict],
) -> None:
    """
    Documentリクエストの主要ヘッダーだけログ出力する。
    """
    print()
    print(
        "========== [REQUEST HEADERS] =========="
    )

    if not requests:
        print(
            "[REQUEST] 対象Documentリクエストなし"
        )

        print(
            "======================================="
        )

        return

    for index, request in enumerate(
        requests,
        start=1,
    ):
        if "error" in request:
            print(
                "[REQUEST ERROR] "
                f"{request['error']}"
            )
            continue

        print()
        print(
            f"[DOCUMENT {index}] "
            f"{request.get('method')} "
            f"{request.get('url')}"
        )

        headers = (
            request.get("headers")
            or {}
        )

        wanted_headers = (
            "User-Agent",
            "user-agent",
            "sec-ch-ua",
            "Sec-CH-UA",
            "sec-ch-ua-mobile",
            "Sec-CH-UA-Mobile",
            "sec-ch-ua-platform",
            "Sec-CH-UA-Platform",
            "Accept-Language",
            "accept-language",
            "Referer",
            "referer",
            "Cookie",
            "cookie",
        )

        printed = set()

        for header_name in wanted_headers:
            if header_name not in headers:
                continue

            canonical_name = (
                header_name.lower()
            )

            if canonical_name in printed:
                continue

            printed.add(
                canonical_name
            )

            print(
                f"[HEADER] "
                f"{header_name}: "
                f"{headers[header_name]}"
            )

    print()
    print(
        "======================================="
    )

def log_request_headers(
    driver,
    domain: str,
) -> list[dict]:
    """
    指定domainへの実Request Headersを取得し、
    ログ出力する。
    """
    requests = (
        get_request_headers_for_domain(
            driver,
            domain,
        )
    )

    print_request_headers(
        requests
    )

    return requests


def get_browser_identity(driver) -> dict:
    """
    JavaScript上から確認できる
    ブラウザ識別情報を取得する。

    ブラウザ設定や通信内容は変更しない。
    """
    identity = driver.execute_script(
        """
        return {
            userAgent: navigator.userAgent || null,
            platform: navigator.platform || null,
            language: navigator.language || null,
            languages: navigator.languages || [],
            webdriver: navigator.webdriver,
            hardwareConcurrency:
                navigator.hardwareConcurrency || null,
            deviceMemory:
                navigator.deviceMemory || null,
            maxTouchPoints:
                navigator.maxTouchPoints || 0,
            cookieEnabled:
                navigator.cookieEnabled,
            vendor:
                navigator.vendor || null,
            product:
                navigator.product || null,
            appVersion:
                navigator.appVersion || null,
            appName:
                navigator.appName || null
        };
        """
    )

    return identity or {}


def get_client_hints(driver) -> dict:
    """
    navigator.userAgentData から
    Client Hints関連情報を取得する。

    非対応ブラウザでは空dictを返す。
    """
    try:
        result = driver.execute_async_script(
            """
            const done = arguments[arguments.length - 1];

            (async () => {
                try {
                    if (!navigator.userAgentData) {
                        done({});
                        return;
                    }

                    const basic = {
                        brands:
                            navigator.userAgentData.brands || [],
                        mobile:
                            navigator.userAgentData.mobile,
                        platform:
                            navigator.userAgentData.platform || null
                    };

                    let highEntropy = {};

                    try {
                        highEntropy =
                            await navigator.userAgentData
                            .getHighEntropyValues([
                                "architecture",
                                "bitness",
                                "formFactors",
                                "fullVersionList",
                                "model",
                                "platformVersion",
                                "uaFullVersion",
                                "wow64"
                            ]);
                    } catch (error) {
                        highEntropy = {
                            error:
                                String(error)
                        };
                    }

                    done({
                        ...basic,
                        highEntropy
                    });

                } catch (error) {
                    done({
                        error:
                            String(error)
                    });
                }
            })();
            """
        )

        return result or {}

    except Exception as exc:
        return {
            "error": (
                f"{type(exc).__name__}: "
                f"{exc}"
            )
        }


def get_browser_environment(driver) -> dict:
    """
    timezone・画面サイズ・viewport等を取得する。

    読み取りのみ。
    """
    environment = driver.execute_script(
        """
        return {
            timezone:
                Intl.DateTimeFormat()
                .resolvedOptions()
                .timeZone || null,

            timezoneOffset:
                new Date().getTimezoneOffset(),

            screen: {
                width:
                    window.screen.width,
                height:
                    window.screen.height,
                availWidth:
                    window.screen.availWidth,
                availHeight:
                    window.screen.availHeight,
                colorDepth:
                    window.screen.colorDepth,
                pixelDepth:
                    window.screen.pixelDepth
            },

            viewport: {
                innerWidth:
                    window.innerWidth,
                innerHeight:
                    window.innerHeight,
                outerWidth:
                    window.outerWidth,
                outerHeight:
                    window.outerHeight,
                devicePixelRatio:
                    window.devicePixelRatio
            }
        };
        """
    )

    return environment or {}


def get_cookie_state(driver) -> list[dict]:
    """
    Seleniumから現在のCookie状態を取得する。

    セキュリティ上、
    Cookieのvalue自体は返さない。
    """
    cookies = driver.get_cookies()

    cookie_state = []

    for cookie in cookies:
        cookie_state.append(
            {
                "name":
                    cookie.get("name"),

                "domain":
                    cookie.get("domain"),

                "path":
                    cookie.get("path"),

                "secure":
                    cookie.get("secure"),

                "httpOnly":
                    cookie.get("httpOnly"),

                "sameSite":
                    cookie.get("sameSite"),

                "expiry":
                    cookie.get("expiry"),
            }
        )

    return cookie_state


def print_browser_identity(
    identity: dict,
) -> None:
    print()
    print(
        "========== [BROWSER IDENTITY] =========="
    )

    print(
        "[BROWSER] User-Agent: "
        f"{identity.get('userAgent')}"
    )

    print(
        "[BROWSER] platform: "
        f"{identity.get('platform')}"
    )

    print(
        "[BROWSER] language: "
        f"{identity.get('language')}"
    )

    print(
        "[BROWSER] languages: "
        f"{identity.get('languages')}"
    )

    print(
        "[BROWSER] vendor: "
        f"{identity.get('vendor')}"
    )

    print(
        "[BROWSER] webdriver: "
        f"{identity.get('webdriver')}"
    )

    print(
        "[BROWSER] hardwareConcurrency: "
        f"{identity.get('hardwareConcurrency')}"
    )

    print(
        "[BROWSER] deviceMemory: "
        f"{identity.get('deviceMemory')}"
    )

    print(
        "[BROWSER] maxTouchPoints: "
        f"{identity.get('maxTouchPoints')}"
    )

    print(
        "[BROWSER] cookieEnabled: "
        f"{identity.get('cookieEnabled')}"
    )

    print(
        "========================================"
    )


def print_client_hints(
    client_hints: dict,
) -> None:
    print()
    print(
        "========== [CLIENT HINTS] =========="
    )

    if not client_hints:
        print(
            "[CH] navigator.userAgentData "
            "なし"
        )

    else:
        print(
            "[CH] "
            + json.dumps(
                client_hints,
                ensure_ascii=False,
                indent=2,
                default=str,
            )
        )

    print(
        "===================================="
    )


def print_browser_environment(
    environment: dict,
) -> None:
    print()
    print(
        "========== [BROWSER ENV] =========="
    )

    print(
        "[ENV] timezone: "
        f"{environment.get('timezone')}"
    )

    print(
        "[ENV] timezoneOffset: "
        f"{environment.get('timezoneOffset')}"
    )

    screen = (
        environment.get("screen")
        or {}
    )

    print(
        "[ENV] screen: "
        f"{screen}"
    )

    viewport = (
        environment.get("viewport")
        or {}
    )

    print(
        "[ENV] viewport: "
        f"{viewport}"
    )

    print(
        "==================================="
    )


def print_cookie_state(
    cookies: list[dict],
) -> None:
    print()
    print(
        "========== [COOKIE STATE] =========="
    )

    print(
        f"[COOKIE CHECK] count="
        f"{len(cookies)}"
    )

    if not cookies:
        print(
            "[COOKIE CHECK] Cookieなし"
        )

    for index, cookie in enumerate(
        cookies,
        start=1,
    ):
        print(
            f"[COOKIE CHECK] "
            f"{index}: "
            f"name={cookie.get('name')!r}, "
            f"domain={cookie.get('domain')!r}, "
            f"path={cookie.get('path')!r}, "
            f"secure={cookie.get('secure')}, "
            f"httpOnly={cookie.get('httpOnly')}, "
            f"sameSite={cookie.get('sameSite')!r}, "
            f"expiry={cookie.get('expiry')}"
        )

    print(
        "===================================="
    )


def log_browser_diagnostics(
    driver,
) -> dict:
    """
    ブラウザ診断情報をまとめて取得し、
    ログ出力する。

    取得対象:
    - User-Agent
    - platform / language
    - navigator.webdriver
    - hardwareConcurrency
    - deviceMemory
    - touch情報
    - Client Hints
    - timezone
    - screen / viewport
    - Cookie状態

    ブラウザ設定・ヘッダー・Cookie値などは
    変更しない。
    """

    print()
    print(
        "=========================================="
    )
    print(
        "========== BROWSER DIAGNOSTICS =========="
    )
    print(
        "=========================================="
    )

    result = {
        "identity": {},
        "client_hints": {},
        "environment": {},
        "cookies": [],
    }

    # ==============================================
    # Browser identity
    # ==============================================

    try:
        result["identity"] = (
            get_browser_identity(
                driver
            )
        )

        print_browser_identity(
            result["identity"]
        )

    except Exception as exc:
        print(
            "[DIAG ERROR] "
            "Browser Identity取得失敗: "
            f"{type(exc).__name__}: "
            f"{exc}"
        )

    # ==============================================
    # Client Hints
    # ==============================================

    try:
        result["client_hints"] = (
            get_client_hints(
                driver
            )
        )

        print_client_hints(
            result["client_hints"]
        )

    except Exception as exc:
        print(
            "[DIAG ERROR] "
            "Client Hints取得失敗: "
            f"{type(exc).__name__}: "
            f"{exc}"
        )

    # ==============================================
    # Browser environment
    # ==============================================

    try:
        result["environment"] = (
            get_browser_environment(
                driver
            )
        )

        print_browser_environment(
            result["environment"]
        )

    except Exception as exc:
        print(
            "[DIAG ERROR] "
            "Browser Environment取得失敗: "
            f"{type(exc).__name__}: "
            f"{exc}"
        )

    # ==============================================
    # Cookie
    # ==============================================

    try:
        result["cookies"] = (
            get_cookie_state(
                driver
            )
        )

        print_cookie_state(
            result["cookies"]
        )

    except Exception as exc:
        print(
            "[DIAG ERROR] "
            "Cookie状態取得失敗: "
            f"{type(exc).__name__}: "
            f"{exc}"
        )

    print()
    print(
        "=========================================="
    )
    print(
        "========== DIAGNOSTICS END =============="
    )
    print(
        "=========================================="
    )
    print()

    return result