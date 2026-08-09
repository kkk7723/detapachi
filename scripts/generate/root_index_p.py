#!/usr/bin/env python3

from __future__ import annotations

import importlib
import sys
from datetime import datetime
from pathlib import Path

from jinja2 import (
    Environment,
    FileSystemLoader,
    select_autoescape,
)


# ==================================================
# プロジェクトルート検出
# ==================================================

def find_project_root(
    start: Path,
) -> Path:
    current = start.resolve()

    if current.is_file():
        current = current.parent

    for candidate in (
        current,
        *current.parents,
    ):
        if (
            (candidate / "config").is_dir()
            and (candidate / "templates").is_dir()
        ):
            return candidate

    raise RuntimeError(
        f"PROJECT_ROOTを特定できません: {start}"
    )


if "__file__" in globals():
    PROJECT_ROOT = find_project_root(
        Path(__file__)
    )
else:
    PROJECT_ROOT = find_project_root(
        Path.cwd()
    )


if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(
        0,
        str(PROJECT_ROOT),
    )


print(f"[INFO] PROJECT_ROOT: {PROJECT_ROOT}")


# ==================================================
# 共通設定
# ==================================================

from config.common import (
    OUTPUT_DIR,
    TEMPLATES_DIR,
)


# ==================================================
# 出力先
# ==================================================

output_dir = Path(
    OUTPUT_DIR
)

output_dir.mkdir(
    parents=True,
    exist_ok=True,
)

output_path = (
    output_dir
    / "index-p.html"
)


# ==================================================
# 店舗設定取得
# ==================================================

shops = []

config_dir = (
    PROJECT_ROOT
    / "config"
)

for config_file in sorted(
    config_dir.glob("*.py")
):
    if config_file.stem.startswith("_"):
        continue

    if config_file.stem == "common":
        continue

    module = importlib.import_module(
        f"config.{config_file.stem}"
    )

    if not hasattr(
        module,
        "SITE_OUTPUT_DIR",
    ):
        continue

    shop_name = getattr(
        module,
        "SHOP_NAME",
        getattr(
            module,
            "GSHEET_NAME",
            config_file.stem,
        ),
    )

    shops.append(
        {
            "name": str(shop_name),
            "directory": config_file.stem,
        }
    )


print(
    f"[INFO] 店舗数: "
    f"{len(shops)}"
)


# ==================================================
# Jinja2
# ==================================================

environment = Environment(
    loader=FileSystemLoader(
        str(TEMPLATES_DIR)
    ),
    autoescape=select_autoescape(
        [
            "html",
            "xml",
        ]
    ),
    trim_blocks=True,
    lstrip_blocks=True,
)

environment.globals[
    "RUN_DATETIME"
] = datetime.now().strftime(
    "%Y-%m-%d %H:%M:%S"
)


# ==================================================
# ルートトップ生成
# ==================================================

template = environment.get_template(
    "index.html"
)

html = template.render(
    SHOPS=shops,
)

output_path.write_text(
    html,
    encoding="utf-8",
)

print(
    f"✅ ルートトップ生成完了: "
    f"{output_path}"
)