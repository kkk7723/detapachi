from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import gspread
from google.oauth2.service_account import Credentials


@dataclass(frozen=True)
class ScrapingTarget:
    machine_number: str
    url: str


def open_worksheet(
    credentials_file: Path,
    scopes: tuple[str, ...],
    spreadsheet_name: str,
    worksheet_name: str,
):
    credentials = Credentials.from_service_account_file(
        str(credentials_file),
        scopes=list(scopes),
    )

    client = gspread.authorize(credentials)
    spreadsheet = client.open(spreadsheet_name)
    worksheet = spreadsheet.worksheet(worksheet_name)

    print(
        f"[SHEET] 認証完了: "
        f"{spreadsheet_name} / {worksheet_name}"
    )

    return worksheet


def get_target_site(worksheet) -> str:
    target_site = (worksheet.acell("B1").value or "").strip()

    if not target_site:
        raise ValueError(
            "スプレッドシートB1に対象サイトURLがありません"
        )

    return target_site


def get_target_flag(now: datetime | None = None) -> str:
    current = now or datetime.now()
    return "2" if 0 <= current.hour < 9 else "1"


def load_scraping_targets(
    worksheet,
    target_flag: str,
) -> list[ScrapingTarget]:
    rows = worksheet.get("A4:G")
    targets: list[ScrapingTarget] = []

    for row in rows:
        if len(row) < 7:
            continue

        row_flag = row[6].strip()
        if row_flag != target_flag:
            continue

        machine_number = row[1].strip()
        url = row[5].strip() if len(row) >= 6 else ""

        if not machine_number:
            continue

        targets.append(
            ScrapingTarget(
                machine_number=machine_number,
                url=url,
            )
        )

    print(
        f"[SHEET] target_flag={target_flag}, "
        f"対象={len(targets)}件"
    )

    return targets