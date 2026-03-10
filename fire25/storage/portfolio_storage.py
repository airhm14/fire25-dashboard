# -*- coding: utf-8 -*-
"""Google Sheets portfolio persistence layer.

Extracted from the main dashboard file so it can be tested and
imported independently.  Uses stdlib ``datetime.timezone`` instead
of ``pytz`` for KST formatting.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import streamlit as st

KST = timezone(timedelta(hours=9))


def get_google_sheets_client():
    """Create a Google Sheets client using Streamlit secrets."""
    try:
        from google.oauth2.service_account import Credentials
        import gspread

        if "gcp_service_account" not in st.secrets:
            return None, "Google Sheets 연동 설정이 없습니다."

        credentials = Credentials.from_service_account_info(
            st.secrets["gcp_service_account"],
            scopes=[
                "https://www.googleapis.com/auth/spreadsheets",
                "https://www.googleapis.com/auth/drive",
            ],
        )
        client = gspread.authorize(credentials)
        return client, None
    except ImportError:
        return None, "gspread 패키지가 설치되어 있지 않습니다."
    except Exception as e:
        return None, f"Google Sheets 연결 실패: {e}"


def _get_sheet_url() -> str:
    return st.secrets.get("spreadsheet_url", "")


def load_portfolio_from_sheets() -> tuple[dict | None, str | None]:
    """Load the latest portfolio snapshot from Google Sheets."""
    client, error = get_google_sheets_client()
    if error:
        return None, error

    try:
        sheet_url = _get_sheet_url()
        if not sheet_url:
            return None, "스프레드시트 URL이 설정되지 않았습니다."

        spreadsheet = client.open_by_url(sheet_url)
        worksheet = spreadsheet.worksheet("Portfolio")

        all_data = worksheet.get_all_values()
        if len(all_data) <= 1:
            return None, "저장된 데이터가 없습니다."

        last_row = all_data[-1]

        return {
            "date": last_row[0],
            "qqqm_qty": float(last_row[1]) if last_row[1] else 0,
            "schd_qty": float(last_row[2]) if last_row[2] else 0,
            "iau_qty": float(last_row[3]) if last_row[3] else 0,
            "sgov_qty": float(last_row[4]) if last_row[4] else 0,
            "cash_deposit": float(last_row[5]) if last_row[5] else 0,
            "new_cash": float(last_row[6]) if last_row[6] else 0,
            "total_value": float(last_row[7]) if last_row[7] else 0,
        }, None
    except Exception as e:
        msg = str(e)
        if "WorksheetNotFound" in msg or "worksheet" in msg.lower():
            return None, "포트폴리오 워크시트를 찾을 수 없습니다. 저장 버튼을 한 번 눌러 생성하세요."
        return None, f"데이터 불러오기 실패: {msg}"


def save_portfolio_to_sheets(
    qqqm: float,
    schd: float,
    iau: float,
    sgov: float,
    cash: float,
    new_cash: float,
    total_value: float,
) -> tuple[bool, str]:
    """Append a portfolio snapshot row to Google Sheets."""
    client, error = get_google_sheets_client()
    if error:
        return False, error

    try:
        sheet_url = _get_sheet_url()
        if not sheet_url:
            return False, "스프레드시트 URL이 설정되지 않았습니다."

        spreadsheet = client.open_by_url(sheet_url)

        try:
            worksheet = spreadsheet.worksheet("Portfolio")
        except Exception:
            worksheet = spreadsheet.add_worksheet(title="Portfolio", rows=1000, cols=10)
            worksheet.append_row(
                ["Date", "QQQM", "SCHD", "IAU", "SGOV", "Cash", "NewCash", "TotalValue"]
            )

        now = datetime.now(KST).strftime("%Y-%m-%d %H:%M")
        worksheet.append_row(
            [now, qqqm, schd, iau, sgov, cash, new_cash, round(total_value, 2)]
        )
        return True, "저장 완료"
    except Exception as e:
        return False, f"저장 실패: {e}"
