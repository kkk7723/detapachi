#!/usr/bin/env python
# coding: utf-8

# In[1]:


from __future__ import annotations

import argparse
import importlib
import math
import re
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from bs4 import BeautifulSoup


# =========================================================
# プロジェクトルート設定
# =========================================================

def find_project_root(
    start_path: Path,
) -> Path:
    """
    config/ と utils/ が存在するディレクトリを
    detaslotのプロジェクトルートとして返す。
    """
    current = start_path.resolve()

    if current.is_file():
        current = current.parent

    for candidate in [
        current,
        *current.parents,
    ]:
        if (
            (candidate / "config").is_dir()
            and (candidate / "utils").is_dir()
        ):
            return candidate

    raise RuntimeError(
        "detaslotのプロジェクトルートを"
        "特定できませんでした。"
        f" 開始位置: {start_path}"
    )


if "__file__" in globals():
    # scripts/database/*.py から実行
    PROJECT_ROOT = find_project_root(
        Path(__file__)
    )
else:
    # scripts/database/*.ipynb から実行
    PROJECT_ROOT = find_project_root(
        Path.cwd()
    )


if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(
        0,
        str(PROJECT_ROOT),
    )


print(
    f"[INFO] PROJECT_ROOT: "
    f"{PROJECT_ROOT}"
)
print(
    f"[INFO] config存在: "
    f"{(PROJECT_ROOT / 'config').is_dir()}"
)
print(
    f"[INFO] utils存在: "
    f"{(PROJECT_ROOT / 'utils').is_dir()}"
)


# =========================================================
# 共通設定
# =========================================================

from config.common import (
    DEFAULT_SITE,
    TABLE_NAME,
    require_file,
)


# ==================================================
# 店舗選択
# ==================================================

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--site",
        default=DEFAULT_SITE,
        help="config名",
    )

    return parser.parse_args()


if "__file__" in globals():
    # .py実行時
    # --site指定があればそれを使用し、
    # 指定がなければDEFAULT_SITEを使用
    args = parse_args()
else:
    # Notebook実行時
    args = argparse.Namespace(
        site=DEFAULT_SITE,
    )


config_file = (
    PROJECT_ROOT
    / "config"
    / f"{args.site}.py"
)

if not config_file.is_file():
    raise FileNotFoundError(
        f"店舗設定が見つかりません: {config_file}"
    )



try:
    site_config = importlib.import_module(
        f"config.{args.site}"
    )
except ModuleNotFoundError as exc:
    raise SystemExit(
        f"[ERROR] 店舗設定が見つかりません: "
        f"config/{args.site}.py"
    ) from exc


if not hasattr(site_config, "DB_PATH"):
    raise AttributeError(
        f"config/{args.site}.py に "
        "DB_PATH が設定されていません。"
    )


db_path = Path(
    site_config.DB_PATH
)

source_column = "svgデータ"
destination_column = "svg差枚"
execution_date_column = "実行日"


print(f"[INFO] 対象店舗: {args.site}")
print(f"[INFO] 使用DB: {db_path}")
print(f"[INFO] 対象テーブル: {TABLE_NAME}")
print(
    f"[INFO] 計算元カラム: "
    f"{source_column}"
)
print(
    f"[INFO] 書き込み先カラム: "
    f"{destination_column}"
)


# =========================================================
# SQLite共通
# =========================================================

def quote_identifier(
    identifier: str,
) -> str:
    """
    SQLiteのテーブル名・カラム名を
    []で安全に囲む。
    """
    return (
        "["
        + str(identifier).replace(
            "]",
            "]]",
        )
        + "]"
    )


def get_table_columns(
    connection: sqlite3.Connection,
    table_name: str,
) -> set[str]:
    """
    SQLiteテーブルに存在するカラム名を取得する。
    """
    cursor = connection.execute(
        f"PRAGMA table_info("
        f"{quote_identifier(table_name)}"
        f")"
    )

    return {
        str(row[1])
        for row in cursor.fetchall()
    }


def is_missing_value(
    value: Any,
) -> bool:
    """
    None、NaN、pandasの欠損値を判定する。
    """
    if value is None:
        return True

    try:
        return bool(
            pd.isna(value)
        )
    except (
        TypeError,
        ValueError,
    ):
        return False


# =========================================================
# SVG解析用正規表現
# =========================================================

NUMBER_PATTERN = re.compile(
    r"[-+]?\d+(?:\.\d+)?"
)

TRANSLATE_PATTERN = re.compile(
    r"translate\(\s*([-\d.]+)\s*,\s*([-\d.]+)\s*\)"
)

PATH_Y_PATTERN = re.compile(
    r"M[0-9.]+,([0-9.]+)\s+L",
    re.IGNORECASE,
)


# =========================================================
# SVG解析関数
# =========================================================

def number_from_text(
    value: Any,
) -> float | None:
    """
    テキストから最初の数値を取得する。
    """
    if value is None:
        return None

    text = (
        str(value)
        .replace("\u00a0", "")
        .replace(",", "")
        .strip()
    )

    match = NUMBER_PATTERN.search(
        text
    )

    if not match:
        return None

    try:
        return float(
            match.group(0)
        )
    except (
        TypeError,
        ValueError,
    ):
        return None


def xy_from_transform(
    transform: str | None,
) -> tuple[
    float | None,
    float | None,
]:
    """
    SVGのtransform属性にある
    translate(x, y)から座標を取得する。
    """
    if not transform:
        return None, None

    match = TRANSLATE_PATTERN.search(
        transform
    )

    if not match:
        return None, None

    try:
        return (
            float(match.group(1)),
            float(match.group(2)),
        )
    except (
        TypeError,
        ValueError,
    ):
        return None, None


def y_from_path_data(
    path_data: str | None,
) -> float | None:
    """
    SVG pathのd属性からY座標を取得する。
    """
    if not path_data:
        return None

    match = PATH_Y_PATTERN.search(
        path_data
    )

    if not match:
        return None

    try:
        return float(
            match.group(1)
        )
    except (
        TypeError,
        ValueError,
    ):
        return None


def collect_grid_y(
    soup: BeautifulSoup,
) -> list[float]:
    """
    AmChartsの横グリッド線のY座標を取得する。
    """
    y_positions: list[float] = []

    for path in soup.find_all(
        "path",
        class_=True,
    ):
        class_names = " ".join(
            path.get(
                "class",
                [],
            )
        )

        if (
            "amcharts-axis-grid"
            not in class_names
        ):
            continue

        if (
            "amcharts-axis-zero-grid"
            in class_names
        ):
            continue

        y_position = y_from_path_data(
            path.get("d", "")
        )

        if y_position is not None:
            y_positions.append(
                y_position
            )

    return y_positions


def collect_right_axis_labels(
    soup: BeautifulSoup,
) -> list[
    tuple[float, float]
]:
    """
    グラフ右側の軸ラベルについて、
    Y座標と数値の組を取得する。
    """
    pairs: list[
        tuple[float, float]
    ] = []

    text_elements = soup.find_all(
        "text",
        {
            "class": "amcharts-axis-label",
        },
    )

    right_side_elements = [
        element
        for element in text_elements
        if (
            element.get("text-anchor")
            or ""
        ).strip() == "end"
    ]

    candidates = (
        right_side_elements
        if right_side_elements
        else text_elements
    )

    for element in candidates:
        value = number_from_text(
            element.get_text()
        )

        if value is None:
            continue

        _, y_position = xy_from_transform(
            element.get("transform")
            or ""
        )

        if y_position is None:
            continue

        pairs.append((
            y_position,
            value,
        ))

    return pairs


def map_grids_to_values(
    grid_y_list: list[float],
    label_pairs: list[
        tuple[float, float]
    ],
) -> list[
    tuple[float, float]
]:
    """
    各グリッド線へ最も近い軸ラベル値を対応付ける。
    """
    if (
        not grid_y_list
        or not label_pairs
    ):
        return []

    sorted_labels = sorted(
        label_pairs,
        key=lambda pair: pair[0],
    )

    mapped_pairs: list[
        tuple[float, float]
    ] = []

    for grid_y in sorted(
        grid_y_list
    ):
        _, label_value = min(
            sorted_labels,
            key=lambda pair: abs(
                pair[0] - grid_y
            ),
        )

        mapped_pairs.append((
            grid_y,
            label_value,
        ))

    return mapped_pairs


def fit_linear(
    pairs: list[
        tuple[float, float]
    ],
) -> tuple[
    float | None,
    float | None,
]:
    """
    Y座標から差枚値を求める一次式を作る。

    戻り値:
        切片、傾き

        value = intercept + slope * y
    """
    if not pairs:
        return None, None

    y_values = np.array(
        [
            pair[0]
            for pair in pairs
        ],
        dtype=float,
    )

    value_values = np.array(
        [
            pair[1]
            for pair in pairs
        ],
        dtype=float,
    )

    if len(
        np.unique(y_values)
    ) < 2:
        return None, None

    slope, intercept = np.polyfit(
        y_values,
        value_values,
        1,
    )

    return (
        float(intercept),
        float(slope),
    )


def get_last_point_y(
    soup: BeautifulSoup,
) -> float | None:
    """
    SVG内のcircle要素から、
    最も右側にある点のY座標を取得する。
    """
    last_point: tuple[
        float,
        float,
    ] | None = None

    for circle in soup.find_all(
        "circle"
    ):
        x_position, y_position = (
            xy_from_transform(
                circle.get("transform")
                or ""
            )
        )

        if (
            x_position is None
            or y_position is None
        ):
            continue

        if (
            last_point is None
            or x_position > last_point[0]
            or (
                x_position
                == last_point[0]
                and y_position
                != last_point[1]
            )
        ):
            last_point = (
                x_position,
                y_position,
            )

    if last_point is None:
        return None

    return last_point[1]


def calculate_svg_difference(
    svg_html: Any,
    *,
    round_mode: str = "round",
    bias: float = 0.0,
) -> int | None:
    """
    SVG文字列から差枚数を計算する。

    round_mode:
        round : 四捨五入
        floor : 切り捨て
        ceil  : 切り上げ
    """
    if svg_html is None:
        return None

    try:
        svg_text = str(
            svg_html
        )
    except Exception:
        return None

    normalized_text = (
        svg_text.strip()
    )

    if (
        not normalized_text
        or normalized_text.lower()
        in {
            "nan",
            "none",
        }
    ):
        return None

    try:
        soup = BeautifulSoup(
            normalized_text,
            "html.parser",
        )

        grid_y_positions = (
            collect_grid_y(
                soup
            )
        )

        label_pairs = (
            collect_right_axis_labels(
                soup
            )
        )

        mapped_pairs = (
            map_grids_to_values(
                grid_y_positions,
                label_pairs,
            )
        )

        # 軸ラベルが取得できなかった場合の補完
        if (
            not mapped_pairs
            and len(grid_y_positions) >= 2
        ):
            sorted_y_positions = sorted(
                grid_y_positions
            )

            if len(
                sorted_y_positions
            ) == 7:
                fallback_values = list(
                    range(
                        20000,
                        -15000,
                        -5000,
                    )
                )

                mapped_pairs = list(
                    zip(
                        sorted_y_positions,
                        fallback_values,
                    )
                )
            else:
                top_y = (
                    sorted_y_positions[0]
                )

                bottom_y = (
                    sorted_y_positions[-1]
                )

                mapped_pairs = [
                    (
                        top_y,
                        20000.0,
                    ),
                    (
                        bottom_y,
                        -10000.0,
                    ),
                ]

        intercept, slope = fit_linear(
            mapped_pairs
        )

        if (
            intercept is None
            or slope is None
        ):
            return None

        last_point_y = get_last_point_y(
            soup
        )

        if last_point_y is None:
            return None

        calculated_value = (
            intercept
            + slope
            * float(last_point_y)
            + float(bias)
        )

        if round_mode == "floor":
            return int(
                math.floor(
                    calculated_value
                )
            )

        if round_mode == "ceil":
            return int(
                math.ceil(
                    calculated_value
                )
            )

        return int(
            round(
                calculated_value
            )
        )

    except Exception as exc:
        print(
            f"[WARN] SVG解析エラー: "
            f"{type(exc).__name__}: {exc}"
        )

        return None


# =========================================================
# DB更新処理
# =========================================================

def main() -> None:
    start_time = time.time()

    require_file(
        db_path,
        "店舗別SQLiteデータベース",
    )

    # -----------------------------------------------------
    # DBカラム確認
    # -----------------------------------------------------

    with sqlite3.connect(
        db_path
    ) as connection:
        table_columns = get_table_columns(
            connection,
            TABLE_NAME,
        )

    required_columns = {
        execution_date_column,
        source_column,
        destination_column,
    }

    missing_columns = [
        column
        for column in required_columns
        if column not in table_columns
    ]

    if missing_columns:
        raise RuntimeError(
            f"{TABLE_NAME} に必要列がありません: "
            f"{missing_columns}"
        )

    print(
        "[DB] 必須カラム確認完了"
    )

    # -----------------------------------------------------
    # DB内の最新日を取得
    # -----------------------------------------------------

    latest_date_sql = f"""
        SELECT
            MAX(
                date(
                    {quote_identifier(execution_date_column)}
                )
            )
        FROM {quote_identifier(TABLE_NAME)}
        WHERE
            {quote_identifier(execution_date_column)}
            IS NOT NULL
            AND TRIM(
                CAST(
                    {quote_identifier(execution_date_column)}
                    AS TEXT
                )
            ) <> ''
    """

    with sqlite3.connect(
        db_path
    ) as connection:
        latest_date_row = connection.execute(
            latest_date_sql
        ).fetchone()

    latest_date = (
        latest_date_row[0]
        if latest_date_row
        else None
    )

    if not latest_date:
        print(
            "[INFO] 有効な実行日がありません。"
        )
        return

    print(
        f"[DB] 最新日: "
        f"{latest_date}"
    )

    # -----------------------------------------------------
    # 最新日のSVGデータだけ取得
    # -----------------------------------------------------

    select_sql = f"""
        SELECT
            ROWID AS _rowid,
            {quote_identifier(execution_date_column)}
                AS execution_datetime,
            {quote_identifier(source_column)}
                AS source_value,
            {quote_identifier(destination_column)}
                AS destination_value
        FROM {quote_identifier(TABLE_NAME)}
        WHERE
            date(
                {quote_identifier(execution_date_column)}
            ) = ?
        ORDER BY ROWID ASC
    """

    with sqlite3.connect(
        db_path
    ) as connection:
        dataframe = pd.read_sql_query(
            select_sql,
            connection,
            params=[
                latest_date,
            ],
        )

    if dataframe.empty:
        print(
            f"[INFO] 最新日の対象データがありません: "
            f"{latest_date}"
        )
        return

    print(
        f"[DB] 対象レコード: "
        f"{len(dataframe)}件"
    )

    # -----------------------------------------------------
    # SVG差枚を計算
    # -----------------------------------------------------

    def calculate_or_none(
        value: Any,
    ) -> int | None:
        if value is None:
            return None

        text = str(value).strip()

        if (
            not text
            or text.lower()
            in {
                "nan",
                "none",
            }
        ):
            return None

        return calculate_svg_difference(
            value,
            round_mode="round",
            bias=0.0,
        )

    dataframe["new_value"] = (
        dataframe["source_value"]
        .apply(
            calculate_or_none
        )
        .astype(object)
    )

    svg_present_count = int(
        dataframe["source_value"]
        .apply(
            lambda value: (
                value is not None
                and bool(
                    str(value).strip()
                )
                and str(value).strip().lower()
                not in {
                    "nan",
                    "none",
                }
            )
        )
        .sum()
    )

    calculated_count = int(
        dataframe["new_value"]
        .apply(
            lambda value: (
                not is_missing_value(
                    value
                )
            )
        )
        .sum()
    )

    print(
        f"[SVG] SVGデータあり: "
        f"{svg_present_count}件"
    )
    print(
        f"[SVG] 差枚計算成功: "
        f"{calculated_count}件"
    )
    print(
        f"[SVG] 差枚計算失敗・空欄: "
        f"{len(dataframe) - calculated_count}件"
    )

    # -----------------------------------------------------
    # 変更が必要な行だけ抽出
    # -----------------------------------------------------

    update_parameters: list[
        tuple[
            int | None,
            int,
        ]
    ] = []

    unchanged_count = 0

    for _, row in dataframe.iterrows():
        new_value = row[
            "new_value"
        ]

        current_value = row[
            "destination_value"
        ]

        new_value_missing = (
            is_missing_value(
                new_value
            )
        )

        current_value_missing = (
            is_missing_value(
                current_value
            )
        )

        # 両方とも空欄なら更新不要
        if (
            new_value_missing
            and current_value_missing
        ):
            unchanged_count += 1
            continue

        # 両方値があり、同じ数値なら更新不要
        if (
            not new_value_missing
            and not current_value_missing
        ):
            try:
                if int(
                    new_value
                ) == int(
                    float(
                        current_value
                    )
                ):
                    unchanged_count += 1
                    continue
            except (
                TypeError,
                ValueError,
                OverflowError,
            ):
                pass

        update_parameters.append((
            (
                None
                if new_value_missing
                else int(new_value)
            ),
            int(row["_rowid"]),
        ))

    print(
        f"[DB] 変更なし: "
        f"{unchanged_count}件"
    )
    print(
        f"[DB] 更新対象: "
        f"{len(update_parameters)}件"
    )

    # -----------------------------------------------------
    # DB更新
    # -----------------------------------------------------

    update_sql = f"""
        UPDATE {quote_identifier(TABLE_NAME)}
        SET
            {quote_identifier(destination_column)}
            = ?
        WHERE
            ROWID = ?
    """

    updated_count = 0

    if update_parameters:
        with sqlite3.connect(
            db_path
        ) as connection:
            cursor = connection.cursor()

            cursor.executemany(
                update_sql,
                update_parameters,
            )

            connection.commit()

            updated_count = len(
                update_parameters
            )

    print(
        f"✅ 更新完了: "
        f"{updated_count}行 "
        f"（{destination_column}）"
    )
    print(
        f"[DB] 対象日: "
        f"{latest_date}"
    )
    print(
        f"[INFO] 所要時間: "
        f"{time.time() - start_time:.2f}秒"
    )


# =========================================================
# 実行
# =========================================================

if __name__ == "__main__":
    main()


# In[ ]:




