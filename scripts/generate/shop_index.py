#!/usr/bin/env python
# coding: utf-8

# In[2]:


#!/usr/bin/env python3

from __future__ import annotations

import argparse
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

    for candidate in [
        current,
        *current.parents,
    ]:
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
print(
    f"[INFO] config存在: "
    f"{(PROJECT_ROOT / 'config').is_dir()}"
)
print(
    f"[INFO] templates存在: "
    f"{(PROJECT_ROOT / 'templates').is_dir()}"
)


# ==================================================
# 共通設定
# ==================================================

from config.common import (
    DEFAULT_SITE,
    TEMPLATES_DIR,
)


# ==================================================
# 店舗選択
# ==================================================

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="店舗別トップページを生成します。"
    )

    parser.add_argument(
        "--site",
        default=DEFAULT_SITE,
        help="configフォルダ内の店舗設定名",
    )

    return parser.parse_args()


if "__file__" in globals():
    # .py実行時
    args = parse_args()
else:
    # Notebook実行時
    args = argparse.Namespace(
        site=DEFAULT_SITE,
    )


site_name = str(args.site).strip()

if not site_name:
    raise ValueError(
        "店舗名が空です。"
    )


config_file = (
    PROJECT_ROOT
    / "config"
    / f"{site_name}.py"
)

if not config_file.is_file():
    raise FileNotFoundError(
        f"店舗設定が見つかりません: {config_file}"
    )


try:
    site_config = importlib.import_module(
        f"config.{site_name}"
    )
except ModuleNotFoundError as exc:
    raise SystemExit(
        f"[ERROR] 店舗設定の読み込みに失敗しました: "
        f"config/{site_name}.py"
    ) from exc


required_settings = (
    "SITE_OUTPUT_DIR",
)

for setting_name in required_settings:
    if not hasattr(
        site_config,
        setting_name,
    ):
        raise AttributeError(
            f"config/{site_name}.py に "
            f"{setting_name} が設定されていません。"
        )


# ==================================================
# 店舗別設定
# ==================================================

shop_name = str(
    getattr(
        site_config,
        "SHOP_NAME",
        getattr(
            site_config,
            "GSHEET_NAME",
            site_name,
        ),
    )
)

output_dir = Path(
    site_config.SITE_OUTPUT_DIR
)

output_dir.mkdir(
    parents=True,
    exist_ok=True,
)


print(f"[INFO] 対象店舗: {site_name}")
print(f"[INFO] 店舗名: {shop_name}")
print(f"[INFO] 出力先: {output_dir}")
print(f"[INFO] テンプレート: {TEMPLATES_DIR}")


# ==================================================
# Jinja2
# ==================================================

environment = Environment(
    loader=FileSystemLoader(
        str(TEMPLATES_DIR)
    ),
    autoescape=select_autoescape([
        "html",
        "xml",
    ]),
    trim_blocks=True,
    lstrip_blocks=True,
)


environment.globals[
    "SHOP_NAME"
] = shop_name

environment.globals[
    "PROJECT_DIR"
] = site_name

environment.globals[
    "SITE_KEY"
] = site_name

environment.globals[
    "RUN_DATETIME"
] = datetime.now().strftime(
    "%Y-%m-%d %H:%M:%S"
)


# ==================================================
# トップページ生成
# ==================================================

template = environment.get_template(
    "shops/index.html"
)

html = template.render()

output_path = (
    output_dir
    / "index.html"
)

output_path.write_text(
    html,
    encoding="utf-8",
)


print(
    f"✅ トップページ生成完了: "
    f"{output_path}"
)


# In[ ]:




