# utils/today_mode_utils.py

from __future__ import annotations

import re
import time
from typing import Any

from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.by import By


# =========================================================
# 本日欄DB定義
# =========================================================

DB_TODAY_SCHEMA = {
    "確変突入回数": "INTEGER",
    "確変突入率": "INTEGER",
    "継続回数": "INTEGER",
    "継続率": "INTEGER",
    "最終スタート": "INTEGER",
    "最大継続": "INTEGER",
    "最大放出数": "INTEGER",
    "出玉数": "INTEGER",
    "初当り回数": "INTEGER",
    "初当り確率": "INTEGER",
    "大当り過去最高": "INTEGER",
    "大当り回数": "INTEGER",
    "大当り確率": "INTEGER",
    "累計スタート": "INTEGER",
}


def to_int_or_none(value: Any) -> int | None:
    """
    文字列から整数を取得する。

    対応例:
    1,234
    ▲230
    －230
    1/281
    1/281.4
    """
    if value is None:
        return None

    text = str(value).strip()

    translation = str.maketrans(
        "０１２３４５６７８９／．",
        "0123456789/.",
    )
    text = text.translate(translation)

    if text.startswith("1/"):
        text = text[2:].lstrip()

    negative = text.startswith(
        ("▲", "-", "－", "−")
    )

    match = re.search(
        r"(\d+(?:\.\d+)?)",
        text,
    )

    if not match:
        return None

    try:
        number = int(float(match.group(1)))
    except ValueError:
        return None

    return -number if negative else number


def normalize_today_label(value: Any) -> str:
    text = "" if value is None else str(value)
    text = text.strip()
    text = text.replace("/", "")

    return re.sub(
        r"\s+",
        "",
        text,
    )


DB_TODAY_KEYMAP = {
    normalize_today_label(column): column
    for column in DB_TODAY_SCHEMA
}


def cast_today_value(
    db_column: str,
    value: Any,
) -> int | str | None:
    if value is None:
        return None

    column_type = DB_TODAY_SCHEMA.get(
        db_column,
        "TEXT",
    )

    if column_type == "INTEGER":
        return to_int_or_none(value)

    return str(value).strip()


def convert_today_pairs_to_db_data(
    labels: list[str],
    values: list[str],
) -> dict[str, Any]:
    """
    ラベルと値をDBカラム形式の辞書へ変換する。
    """
    result: dict[str, Any] = {}

    for label, value in zip(
        labels,
        values,
    ):
        normalized_label = normalize_today_label(
            label
        )

        db_column = DB_TODAY_KEYMAP.get(
            normalized_label
        )

        if not db_column:
            continue

        result[db_column] = cast_today_value(
            db_column,
            None if value == "" else value,
        )

    return result


# =========================================================
# 共通処理
# =========================================================

def pad_values(
    values: list[str],
    expected_length: int,
) -> list[str]:
    if len(values) < expected_length:
        return values + [""] * (
            expected_length - len(values)
        )

    return values[:expected_length]


def find_in_any_frame(
    driver,
    xpath: str,
    timeout: int = 8,
):
    """
    トップページとiframeを探索し、
    XPathに一致する最初の要素を返す。
    """
    deadline = time.time() + timeout

    while time.time() < deadline:
        driver.switch_to.default_content()

        elements = driver.find_elements(
            By.XPATH,
            xpath,
        )

        if elements:
            return elements[0]

        frames = driver.find_elements(
            By.TAG_NAME,
            "iframe",
        )

        for frame in frames:
            try:
                driver.switch_to.default_content()
                driver.switch_to.frame(
                    frame
                )

                elements = driver.find_elements(
                    By.XPATH,
                    xpath,
                )

                if elements:
                    return elements[0]

            except Exception:
                continue

        time.sleep(0.2)

    driver.switch_to.default_content()

    raise TimeoutException(
        f"要素が見つかりませんでした: {xpath}"
    )


# =========================================================
# MODE 1
# =========================================================

def collect_today_mode1(
    driver,
) -> tuple[list[str], list[str]]:
    """
    MODE1:

    左側ラベルセルと本日値セルの
    .outer をDOM上の同じ段で対応させる。

    値が空欄の場合も .outer 自体は保持するため、
    後続データが前へズレない。

    文字列として値を詰めてから
    ラベルに割り当てる処理は行わない。
    """

    root = driver.find_element(
        By.ID,
        "tblDAbv2",
    )

    # =====================================================
    # 左側ラベルセル
    # =====================================================

    label_cell = root.find_element(
        By.CSS_SELECTOR,
        "td.row-header",
    )

    # まず実際のラベルデータ部分を狙う
    label_rows = label_cell.find_elements(
        By.XPATH,
        (
            "./div/table/tbody/tr/td/"
            "div["
            "contains("
            "concat(' ', normalize-space(@class), ' '),"
            "' outer '"
            ")"
            "]"
        ),
    )

    # サイト側の微妙なDOM差異用
    if not label_rows:
        label_rows = label_cell.find_elements(
            By.CSS_SELECTOR,
            (
                ":scope > div > table > tbody > tr > "
                "td > div.outer"
            ),
        )

    # 最終フォールバック
    if not label_rows:
        label_rows = label_cell.find_elements(
            By.CSS_SELECTOR,
            "div.outer",
        )

    if not label_rows:
        raise RuntimeError(
            "MODE1: ラベル側 .outer が見つかりません"
        )

    # =====================================================
    # 本日値セル
    #
    # td自身の直下に
    #
    # div.outer
    #   > div.inner.nc-text-align-right
    #
    # を持つ値セルを取得する。
    #
    # .// ではなく ./ を使うことで、
    # 親tdやネストされた別テーブルを誤取得しない。
    # =====================================================

    value_cells = root.find_elements(
        By.XPATH,
        (
            ".//td["
            "./div["
            "contains("
            "concat(' ', normalize-space(@class), ' '),"
            "' outer '"
            ")"
            "]"
            "/div["
            "contains("
            "concat(' ', normalize-space(@class), ' '),"
            "' inner '"
            ")"
            " and "
            "contains("
            "concat(' ', normalize-space(@class), ' '),"
            "' nc-text-align-right '"
            ")"
            "]"
            "]"
        ),
    )

    if not value_cells:
        raise RuntimeError(
            "MODE1: 本日値セルが見つかりません"
        )

    # =====================================================
    # MODE1では最初の値列が本日列
    # =====================================================

    today_cell = value_cells[0]

    today_rows = today_cell.find_elements(
        By.XPATH,
        (
            "./div["
            "contains("
            "concat(' ', normalize-space(@class), ' '),"
            "' outer '"
            ")"
            "]"
        ),
    )

    if not today_rows:
        raise RuntimeError(
            "MODE1: 本日側 .outer が見つかりません"
        )

    print(
        "[TODAY MODE1] "
        f"label_outer={len(label_rows)} "
        f"today_outer={len(today_rows)}"
    )

    # =====================================================
    # DOM上の同じ段を直接対応
    # =====================================================

    labels: list[str] = []
    values: list[str] = []

    row_count = min(
        len(label_rows),
        len(today_rows),
    )

    for index in range(
        row_count
    ):
        # -------------------------------------------------
        # ラベル
        # -------------------------------------------------

        label_inners = (
            label_rows[index]
            .find_elements(
                By.CSS_SELECTOR,
                ":scope > div.inner",
            )
        )

        label = ""

        if label_inners:
            label = (
                label_inners[0]
                .get_attribute(
                    "textContent"
                )
                or ""
            )

        label = (
            label
            .replace(
                "\xa0",
                " ",
            )
            .strip()
        )

        # -------------------------------------------------
        # 本日値
        # -------------------------------------------------

        value_inners = (
            today_rows[index]
            .find_elements(
                By.CSS_SELECTOR,
                ":scope > div.inner",
            )
        )

        value = ""

        if value_inners:
            value = (
                value_inners[0]
                .get_attribute(
                    "textContent"
                )
                or ""
            )

        value = (
            value
            .replace(
                "\xa0",
                " ",
            )
            .strip()
        )

        # -------------------------------------------------
        # DOM上で対応を確定した「後」に
        # 空ラベルを除外する
        #
        # 値が空欄でもvalueは "" のまま保持される
        # -------------------------------------------------

        if not label:
            continue

        normalized_label = normalize_today_label(
            label
        )

        # DB保存対象以外は無視
        if normalized_label not in DB_TODAY_KEYMAP:
            continue

        labels.append(
            label
        )

        values.append(
            value
        )

        print(
            "[TODAY MODE1] "
            f"{label!r} -> "
            f"{value!r} "
            f"(dom={index})"
        )

    return (
        labels,
        values,
    )


# =========================================================
# MODE 2
# =========================================================

def collect_today_mode2(
    driver,
) -> tuple[list[str], list[str]]:
    """
    MODE 2:
    tbody[id^="tblDAb"] の各trから、
    td[0]をラベル、td[1]を値として取得する。
    """
    tbody = find_in_any_frame(
        driver,
        "//tbody[starts-with(@id,'tblDAb')]",
        timeout=10,
    )

    rows = tbody.find_elements(
        By.XPATH,
        "./tr",
    )

    labels: list[str] = []
    values: list[str] = []

    def normalize(value: Any) -> str:
        return (
            "" if value is None else str(value)
        ).replace(
            "\u00a0",
            " ",
        ).replace(
            "\r",
            "\n",
        ).replace(
            "\n",
            " ",
        ).strip()

    for row in rows:
        cells = row.find_elements(
            By.TAG_NAME,
            "td",
        )

        if len(cells) < 2:
            continue

        label = (
            normalize(cells[0].text)
            or normalize(
                cells[0].get_attribute(
                    "textContent"
                )
            )
        )

        value = (
            normalize(cells[1].text)
            or normalize(
                cells[1].get_attribute(
                    "textContent"
                )
            )
        )

        if label or value:
            labels.append(label)
            values.append(value)

    length = min(
        len(labels),
        len(values),
    )

    return (
        labels[:length],
        values[:length],
    )


# =========================================================
# MODE 3
# =========================================================

def collect_mode3_groups(
    driver,
) -> list[list[tuple[str, str]]]:
    groups: list[
        list[
            tuple[
                str,
                str,
            ]
        ]
    ] = []

    lists = driver.find_elements(
        By.CSS_SELECTOR,
        "ul.nc-border-a",
    )

    for item_list in lists:
        rows = item_list.find_elements(
            By.TAG_NAME,
            "li",
        )

        items: list[
            tuple[
                str,
                str,
            ]
        ] = []

        for row in rows:
            try:
                title_elements = row.find_elements(
                    By.CSS_SELECTOR,
                    ".title",
                )

                value_elements = row.find_elements(
                    By.CSS_SELECTOR,
                    ".value",
                )

                title = (
                    title_elements[0].text
                    if title_elements
                    else ""
                ).replace(
                    "\u00a0",
                    " ",
                ).strip()

                value = (
                    value_elements[0].text
                    if value_elements
                    else ""
                ).replace(
                    "\u00a0",
                    " ",
                ).strip()

                items.append(
                    (
                        title,
                        value,
                    )
                )

            except Exception:
                items.append(
                    (
                        "",
                        "",
                    )
                )

        if items:
            groups.append(
                items
            )

    return groups


def collect_today_mode3(
    driver,
    max_iframe_depth: int = 4,
) -> tuple[list[str], list[str]]:
    """
    MODE 3:
    ul.nc-border-a > li の
    .titleと.valueを取得する。
    """
    expected_labels = set(
        DB_TODAY_KEYMAP
    )

    best_group: list[
        tuple[
            str,
            str,
        ]
    ] | None = None

    best_score = (
        -1,
        -1,
    )

    def score_group(
        group: list[
            tuple[
                str,
                str,
            ]
        ],
    ) -> tuple[int, int]:
        titles = [
            normalize_today_label(
                title
            )
            for title, _ in group
        ]

        matching_count = sum(
            1
            for title in titles
            if title in expected_labels
        )

        return (
            matching_count,
            len(group),
        )

    def inspect_current_context() -> None:
        nonlocal best_group
        nonlocal best_score

        groups = collect_mode3_groups(
            driver
        )

        for group in groups:
            score = score_group(
                group
            )

            if score > best_score:
                best_group = group
                best_score = score

    try:
        driver.switch_to.default_content()
        inspect_current_context()

    except Exception:
        pass

    def inspect_frames(
        depth: int,
    ) -> None:
        if depth > max_iframe_depth:
            return

        frames = driver.find_elements(
            By.TAG_NAME,
            "iframe",
        )

        for frame_index in range(
            len(frames)
        ):
            try:
                driver.switch_to.frame(
                    frame_index
                )

                inspect_current_context()

                inspect_frames(
                    depth + 1
                )

            except Exception:
                pass

            finally:
                driver.switch_to.parent_frame()

    try:
        driver.switch_to.default_content()

        inspect_frames(
            1
        )

    finally:
        driver.switch_to.default_content()

    if not best_group:
        raise RuntimeError(
            "MODE3のtitle/valueペアが"
            "見つかりませんでした"
        )

    labels = [
        title
        for title, _ in best_group
    ]

    values = [
        value
        for _, value in best_group
    ]

    return (
        labels,
        values,
    )


# =========================================================
# MODE分岐
# =========================================================

MODE_COLLECTORS = {
    1: collect_today_mode1,
    2: collect_today_mode2,
    3: collect_today_mode3,
}


def collect_today_pairs(
    driver,
    mode: int,
) -> tuple[list[str], list[str]]:
    """
    指定されたMODEに対応する取得関数を呼び出す。
    """
    collector = MODE_COLLECTORS.get(
        mode
    )

    if collector is None:
        raise ValueError(
            f"未対応のTODAY_MODEです: {mode}"
        )

    labels, values = collector(
        driver
    )

    labels = [
        "" if label is None else str(label)
        for label in labels
    ]

    values = [
        "" if value is None else str(value)
        for value in values
    ]

    return (
        labels,
        pad_values(
            values,
            len(labels),
        ),
    )


def collect_today_data(
    driver,
    mode: int,
) -> dict[str, Any]:
    """
    MODEに応じて本日欄を取得し、
    DB保存用の辞書を返す。
    """
    labels, values = collect_today_pairs(
        driver,
        mode,
    )

    # =====================================================
    # RAW確認
    # =====================================================

    print()
    print(
        "========== 本日欄 RAW =========="
    )

    for index, (
        label,
        value,
    ) in enumerate(
        zip(
            labels,
            values,
        ),
        start=1,
    ):
        print(
            f"{index:02d} | "
            f"{label!r} -> "
            f"{value!r}"
        )

    print(
        "=============================="
    )
    print()

    # =====================================================
    # DB保存形式へ変換
    # =====================================================

    data = convert_today_pairs_to_db_data(
        labels,
        values,
    )

    print(
        f"[本日] MODE={mode} "
        f"rows={len(labels)} "
        f"保存件数={len(data)}"
    )

    return data
