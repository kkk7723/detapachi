from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path


# ==================================================
# Notebookテスト用店舗
# ==================================================
#
# JupyterLabから実行するときは、
# この1か所だけ変更する。
#
# 例:
# NOTEBOOK_SITE = "gigaslot"
# NOTEBOOK_SITE = "iwakuni_tekisasu_s"
#
# .pyとして実行するときは、
# --siteで指定した店舗が優先される。
# ==================================================

NOTEBOOK_SITE = "friend3_p"


# ==================================================
# プロジェクトルート検出
# ==================================================

def find_project_root(
    start_path: Path,
) -> Path:
    """
    config/、scripts/、utils/ が存在する場所を
    プロジェクトルートとして返す。

    Jupyter Notebookと.py実行の両方に対応する。
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
            and (candidate / "scripts").is_dir()
            and (candidate / "utils").is_dir()
        ):
            return candidate

    raise RuntimeError(
        "PROJECT_ROOTを特定できません。"
        f" 開始位置: {start_path}"
    )


if "__file__" in globals():
    # .py実行時
    PROJECT_ROOT = find_project_root(
        Path(__file__)
    )
else:
    # Jupyter Notebook実行時
    PROJECT_ROOT = find_project_root(
        Path.cwd()
    )


# ==================================================
# Pythonのimportパスへプロジェクトルートを追加
# ==================================================
#
# これを入れることで、
# Notebookからでも以下をimportできる。
#
# from config.common import DEFAULT_SITE
# from utils.xxx import ...
# ==================================================

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(
        0,
        str(PROJECT_ROOT),
    )


SCRIPTS_DIR = (
    PROJECT_ROOT
    / "scripts"
)


print(
    f"[INFO] PROJECT_ROOT: "
    f"{PROJECT_ROOT}"
)
print(
    f"[INFO] SCRIPTS_DIR: "
    f"{SCRIPTS_DIR}"
)
print(
    f"[INFO] config存在: "
    f"{(PROJECT_ROOT / 'config').is_dir()}"
)
print(
    f"[INFO] utils存在: "
    f"{(PROJECT_ROOT / 'utils').is_dir()}"
)


# ==================================================
# 共通設定
# ==================================================

from config.common import DEFAULT_SITE


# ==================================================
# 店舗指定
# ==================================================

def parse_args() -> argparse.Namespace:
    """
    .py実行時の店舗指定を受け取る。

    --siteを省略した場合は、
    config/common.pyのDEFAULT_SITEを使用する。

    choicesは設けない。
    config/<店舗名>.py が存在すれば使用できる。
    """
    parser = argparse.ArgumentParser(
        description=(
            "店舗別スクリプトを"
            "指定された順番に実行します。"
        )
    )

    parser.add_argument(
        "--site",
        default=DEFAULT_SITE,
        help=(
            "configフォルダ内の店舗設定名。"
            "例: gigaslot"
        ),
    )

    return parser.parse_args()


if "__file__" in globals():
    # .py実行時
    # --siteで指定された店舗を使用する。
    # 省略時はDEFAULT_SITE。
    args = parse_args()

else:
    # Jupyter Notebook実行時
    # ファイル上部のNOTEBOOK_SITEを使用する。
    args = argparse.Namespace(
        site=NOTEBOOK_SITE,
    )


site_name = str(
    args.site
).strip()


if not site_name:
    raise ValueError(
        "対象店舗が空です。"
    )


# ==================================================
# 店舗設定存在チェック
# ==================================================

config_file = (
    PROJECT_ROOT
    / "config"
    / f"{site_name}.py"
)


if not config_file.is_file():
    raise FileNotFoundError(
        "店舗設定が見つかりません: "
        f"{config_file}"
    )


print(
    f"[INFO] DEFAULT_SITE: "
    f"{DEFAULT_SITE}"
)

if "__file__" not in globals():
    print(
        f"[INFO] NOTEBOOK_SITE: "
        f"{NOTEBOOK_SITE}"
    )

print(
    f"[INFO] 対象店舗: "
    f"{site_name}"
)
print(
    f"[INFO] 店舗設定: "
    f"{config_file}"
)


# ==================================================
# 実行設定
# ==================================================

# スクリプト間の待機秒数
WAIT_SECONDS = 1

# 途中でエラーが発生しても、
# 後続スクリプトを実行する。
CONTINUE_ON_ERROR = True


# ==================================================
# 実行対象
# ==================================================
#
# タプル形式:
# (
#     scripts直下のフォルダ名,
#     Pythonファイル名,
# )
#
# 実行順序は、このリストの上から順番。
# ==================================================

scripts = [
    # ----------------------------------------------
    # スクレイピング
    # ----------------------------------------------
    (
        "scraping",
        "新scraping_p.py",
    ),

    # ----------------------------------------------
    # DB・スプレッドシート処理
    # ----------------------------------------------
    (
        "database",
        "dbからスプレへ機種名書き込み.py",
    ),
    (
        "database",
        "スプレ天井設定から店舗別p.py",
    ),
    (
        "database",
        "スプレから一括ボーダーdb書き込みp.py",
    ),
    (
        "database",
        "dbにwebpURLを書き込み.py",
    ),
    (
        "database",
        "dbに台番号url書き込み.py",
    ),
    (
        "database",
        "dbに宵越し累計ゲーム数書き込みp.py",
    ),
    (
        "database",
        "dbに宵越し最終種別書き込みp.py",
    ),
    (
        "database",
        "dbに天井残りゲーム数計算p.py",
    ),
    (
        "database",
        "svg計算.py",
    ),
    (
        "database",
        "累計出玉pt計算.py",
    ),
    (
        "database",
        "累計通常ゲーム数初当り確率.py",
    ),
    (
        "database",
        "出玉数初当り確率最終回転率.py",
    ),
    (
        "database",
        "出玉数noボナ回転率計算.py",
    ),
    (
        "database",
        "svgnoボナ回転率計算.py",
    ),
    (
        "database",
        "svg最終回転率計算初当たり.py",
    ),

    # ----------------------------------------------
    # メール
    # ----------------------------------------------
    (
        "mail",
        "メール一括条件判定p.py",
    ),

    # ----------------------------------------------
    # HTML生成
    # ----------------------------------------------
    (
        "generate",
        "machine_pages.py",
    ),
    (
        "generate",
        "machine_list.py",
    ),
    (
        "generate",
        "date_pages.py",
    ),
    (
        "generate",
        "date_index.py",
    ),
    (
        "generate",
        "shop_index.py",
    ),
    (
        "generate",
        "root_index.py",
    ),

    # ----------------------------------------------
    # サーバーアップロード
    # ----------------------------------------------
    (
        "upload",
        "upload.py",
    ),
]


# ==================================================
# 実行前チェック
# ==================================================

print()
print("=" * 70)
print("実行前チェック")
print("=" * 70)
print(
    f"対象店舗: "
    f"{site_name}"
)
print(
    f"実行スクリプト数: "
    f"{len(scripts)}"
)
print(
    f"エラー時継続: "
    f"{CONTINUE_ON_ERROR}"
)
print(
    f"待機秒数: "
    f"{WAIT_SECONDS}秒"
)


existing_script_count = 0
missing_scripts: list[Path] = []


for folder, filename in scripts:
    script_path = (
        SCRIPTS_DIR
        / folder
        / filename
    )

    if script_path.is_file():
        existing_script_count += 1
    else:
        missing_scripts.append(
            script_path
        )


print(
    f"存在確認OK: "
    f"{existing_script_count}件"
)
print(
    f"ファイルなし: "
    f"{len(missing_scripts)}件"
)


if missing_scripts:
    print()
    print(
        "[WARN] 以下のファイルが"
        "見つかりません:"
    )

    for missing_path in missing_scripts:
        print(
            f"  - {missing_path}"
        )


print("=" * 70)


# ==================================================
# 順番に実行
# ==================================================

start_time = time.time()

success_count = 0
failure_count = 0
missing_count = 0
skipped_count = 0

success_scripts: list[str] = []
failed_scripts: list[str] = []
missing_script_names: list[str] = []


for index, (
    folder,
    filename,
) in enumerate(
    scripts,
    start=1,
):
    script_path = (
        SCRIPTS_DIR
        / folder
        / filename
    )

    print()
    print("=" * 70)
    print(
        f"[{index}/{len(scripts)}]"
    )
    print(
        f"[RUN] {script_path}"
    )
    print("=" * 70)

    # ----------------------------------------------
    # ファイル存在確認
    # ----------------------------------------------

    if not script_path.is_file():
        print(
            "[ERROR] ファイルがありません: "
            f"{script_path}"
        )

        missing_count += 1

        missing_script_names.append(
            str(script_path)
        )

        if not CONTINUE_ON_ERROR:
            print(
                "[STOP] CONTINUE_ON_ERROR=Falseのため"
                "処理を停止します。"
            )
            break

        continue

    # ----------------------------------------------
    # 子スクリプトへ渡すコマンド
    # ----------------------------------------------

    command = [
        sys.executable,
        str(script_path),
        "--site",
        site_name,
    ]

    print(
        "[COMMAND] "
        + " ".join(command)
    )

    script_start_time = (
        time.time()
    )

    # ----------------------------------------------
    # 実行
    # ----------------------------------------------

    try:
        subprocess.run(
            command,
            check=True,

            # 全スクリプトでPROJECT_ROOTを
            # カレントディレクトリとして統一する。
            cwd=str(PROJECT_ROOT),
        )

        script_elapsed = (
            time.time()
            - script_start_time
        )

        success_count += 1

        success_scripts.append(
            filename
        )

        print(
            f"[OK] {filename}"
        )
        print(
            f"[TIME] "
            f"{script_elapsed:.2f}秒"
        )

    except subprocess.CalledProcessError as exc:
        script_elapsed = (
            time.time()
            - script_start_time
        )

        failure_count += 1

        failed_scripts.append(
            filename
        )

        print(
            f"[ERROR] "
            f"{filename} 実行失敗"
        )
        print(
            f"[ERROR] 終了コード: "
            f"{exc.returncode}"
        )
        print(
            f"[TIME] "
            f"{script_elapsed:.2f}秒"
        )

        if not CONTINUE_ON_ERROR:
            print(
                "[STOP] エラーが発生したため"
                "処理を停止します。"
            )
            break

    except KeyboardInterrupt:
        print()
        print(
            "[STOP] ユーザー操作により"
            "中断されました。"
        )

        raise

    except Exception as exc:
        script_elapsed = (
            time.time()
            - script_start_time
        )

        failure_count += 1

        failed_scripts.append(
            filename
        )

        print(
            f"[ERROR] {filename}: "
            f"{type(exc).__name__}: {exc}"
        )
        print(
            f"[TIME] "
            f"{script_elapsed:.2f}秒"
        )

        if not CONTINUE_ON_ERROR:
            print(
                "[STOP] エラーが発生したため"
                "処理を停止します。"
            )
            break

    # ----------------------------------------------
    # 次のスクリプトまで待機
    # ----------------------------------------------

    if (
        index < len(scripts)
        and WAIT_SECONDS > 0
    ):
        print(
            f"[WAIT] "
            f"{WAIT_SECONDS}秒待機"
        )

        time.sleep(
            WAIT_SECONDS
        )


# ==================================================
# 結果
# ==================================================

total_elapsed = (
    time.time()
    - start_time
)


print()
print("=" * 70)
print("連続実行完了")
print("=" * 70)
print(
    f"対象店舗: "
    f"{site_name}"
)
print(
    f"実行予定: "
    f"{len(scripts)}件"
)
print(
    f"成功: "
    f"{success_count}件"
)
print(
    f"失敗: "
    f"{failure_count}件"
)
print(
    f"ファイルなし: "
    f"{missing_count}件"
)
print(
    f"スキップ: "
    f"{skipped_count}件"
)
print(
    f"合計時間: "
    f"{total_elapsed:.2f}秒"
)


if success_scripts:
    print()
    print("[成功したスクリプト]")

    for filename in success_scripts:
        print(
            f"  - {filename}"
        )


if failed_scripts:
    print()
    print("[失敗したスクリプト]")

    for filename in failed_scripts:
        print(
            f"  - {filename}"
        )


if missing_script_names:
    print()
    print("[見つからなかったファイル]")

    for filename in missing_script_names:
        print(
            f"  - {filename}"
        )


print("=" * 70)