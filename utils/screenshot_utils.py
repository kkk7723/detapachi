# utils/screenshot_utils.py

from __future__ import annotations

import time
from io import BytesIO
from pathlib import Path
from typing import Iterable

from PIL import Image
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.by import By


def find_element_in_frames(
    driver,
    *,
    by: str,
    value: str,
    timeout: int = 8,
):
    """
    トップページとiframe内を探索し、
    最初に見つかった要素を返す。

    要素を発見した場合は、その要素が存在するframeへ
    切り替わった状態になる。
    """
    deadline = time.time() + timeout

    while time.time() < deadline:
        driver.switch_to.default_content()

        try:
            elements = driver.find_elements(by, value)

            if elements:
                return elements[0]
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

                elements = driver.find_elements(
                    by,
                    value,
                )

                if elements:
                    return elements[0]

            except Exception:
                continue

        time.sleep(0.2)

    driver.switch_to.default_content()

    raise TimeoutException(
        f"要素が見つかりませんでした: "
        f"by={by}, value={value}"
    )


def save_element_as_webp(
    driver,
    *,
    by: str,
    value: str,
    output_path: str | Path,
    timeout: int = 8,
    quality: int = 80,
    method: int = 6,
) -> Path | None:
    """
    指定要素だけをWebP形式で保存する。

    SeleniumからPNGバイト列を取得するが、
    PNGファイルはディスクへ保存しない。
    メモリ上でWebPへ変換して保存する。
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    try:
        element = find_element_in_frames(
            driver,
            by=by,
            value=value,
            timeout=timeout,
        )

        dimensions = driver.execute_script(
            """
            const element = arguments[0];
            const rect = element.getBoundingClientRect();

            return {
                width: Math.ceil(rect.width),
                height: Math.ceil(rect.height)
            };
            """,
            element,
        ) or {}

        width = int(dimensions.get("width", 0))
        height = int(dimensions.get("height", 0))

        if width <= 0 or height <= 0:
            print(
                f"[SHOT] 要素寸法が0のためスキップ: "
                f"{output_path.name}"
            )
            return None

        driver.execute_script(
            "arguments[0].scrollIntoView({block:'start'});",
            element,
        )

        time.sleep(0.1)

        # Seleniumが生成するPNGをメモリ上で取得
        png_bytes = element.screenshot_as_png

        if not png_bytes:
            print(
                f"[SHOT] 画像データ取得失敗: "
                f"{output_path.name}"
            )
            return None

        # PNGファイルを作らずWebPへ保存
        with Image.open(BytesIO(png_bytes)) as image:
            image.convert("RGB").save(
                output_path,
                format="WEBP",
                quality=quality,
                method=method,
            )

        print(
            f"[SHOT] WebP saved: {output_path}"
        )

        return output_path

    except Exception as exc:
        print(
            f"[SHOT] WebP保存失敗 "
            f"({output_path.name}): {exc}"
        )
        return None

    finally:
        try:
            driver.switch_to.default_content()
        except Exception:
            pass


def save_machine_elements_as_webp(
    driver,
    *,
    dai_number: str,
    target_date: str,
    output_dir: str | Path,
    targets: Iterable[dict],
    quality: int = 80,
) -> dict[str, Path | None]:
    """
    1台について複数要素を個別のWebPとして保存する。

    targets例:
    [
        {
            "name": "history",
            "by": By.XPATH,
            "value": "//tbody[@id='tblHISTb']",
        },
        {
            "name": "today",
            "by": By.ID,
            "value": "tblDAbv2",
        },
    ]
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    results: dict[str, Path | None] = {}

    for target in targets:
        name = str(target["name"])
        by = target["by"]
        value = str(target["value"])
        timeout = int(target.get("timeout", 8))

        output_path = (
            output_dir
            / f"{target_date}_{dai_number}_{name}.webp"
        )

        results[name] = save_element_as_webp(
            driver,
            by=by,
            value=value,
            output_path=output_path,
            timeout=timeout,
            quality=quality,
        )

    return results