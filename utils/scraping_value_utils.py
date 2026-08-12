import math
import re


def to_int_or_none(s: str):
    """
    文字列から整数を抽出。
    - '▲230' や 全角マイナス '－230' / '−230' も負数として解釈
    - 桁以外は無視（カンマ、空白、単位など）
    - '1/281' や '１／２８１' / '1/281.4' 形式は '1/' を削除して分母だけを数値化
    - 小数点は無視して整数化（切り捨て）
    """
    if s is None:
        return None

    s = str(s).strip()

    # 全角数字・全角スラッシュ→半角
    trans_map = str.maketrans(
        "０１２３４５６７８９／．",
        "0123456789/.",
    )
    s_norm = s.translate(trans_map)

    # 先頭が "1/" の場合は削除
    if s_norm.startswith("1/"):
        s = s_norm[2:].lstrip()
    else:
        s = s_norm

    # マイナス記号・負数表現の検出
    negative = False

    if s.startswith(
        (
            "▲",
            "-",
            "－",
            "−",
        )
    ):
        negative = True

    # 数字または小数点を抽出
    m = re.search(
        r"(\d+(?:\.\d+)?)",
        s,
    )

    if not m:
        return None

    # 小数点があれば切り捨て
    try:
        val = math.floor(
            float(m.group(1))
        )

    except ValueError:
        return None

    return -val if negative else val


def normalize_dai_number(value) -> str:
    """台番号表記を比較用の数字文字列へ統一する。"""
    match = re.search(
        r"\d+",
        str(value or ""),
    )

    if not match:
        return ""

    return str(
        int(match.group())
    )


def normalize_update_date_text(
    text: str,
) -> str:
    """取得更新日の表示文字列を YYYY/MM/DD HH:MM 形式へ正規化する。"""
    value = str(text or "")

    value = value.replace(
        "\xa0",
        " ",
    )

    value = value.replace(
        "\u3000",
        " ",
    )

    value = re.sub(
        r"\s+",
        " ",
        value,
    )

    value = re.sub(
        r"\s*更新\s*$",
        "",
        value,
    )

    return value.strip()