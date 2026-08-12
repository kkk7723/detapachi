import json


def load_cookies(browser, cookie_file):
    try:
        with open(cookie_file, "r") as file:
            cookies = json.load(file)

        for cookie in cookies:
            if "sameSite" in cookie:
                cookie.pop("sameSite")

            browser.add_cookie(cookie)

        print(
            f"[COOKIE] Cookies loaded: "
            f"{cookie_file}"
        )

    except FileNotFoundError:
        print(
            f"[COOKIE] No cookies found: "
            f"{cookie_file}"
        )