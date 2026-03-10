# -*- coding: utf-8 -*-
"""Portfolio history retrieval and charting from Google Sheets."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from .portfolio_storage import get_google_sheets_client


def get_portfolio_history() -> tuple[pd.DataFrame | None, str | None]:
    """Load all portfolio history rows from Google Sheets."""
    client, error = get_google_sheets_client()
    if error:
        return None, error

    try:
        sheet_url = st.secrets.get("spreadsheet_url", "")
        spreadsheet = client.open_by_url(sheet_url)
        worksheet = spreadsheet.worksheet("Portfolio")

        all_data = worksheet.get_all_values()
        if len(all_data) <= 1:
            return None, "히스토리 데이터가 없습니다."

        headers = all_data[0]
        data = all_data[1:]

        history_df = pd.DataFrame(data, columns=headers)
        history_df["TotalValue"] = pd.to_numeric(history_df["TotalValue"], errors="coerce")
        history_df["Date"] = pd.to_datetime(
            history_df["Date"], format="%Y-%m-%d %H:%M", errors="coerce"
        )
        return history_df, None
    except Exception as e:
        return None, f"히스토리 불러오기 실패: {e}"


def render_portfolio_history(gs_available: bool, is_personal_mode: bool) -> None:
    """Render the portfolio history section inside Streamlit."""
    if gs_available and is_personal_mode:
        with st.expander("포트폴리오 히스토리", expanded=False):
            history_df, history_error = get_portfolio_history()

            if history_error:
                st.info(f"안내: {history_error}")
            elif history_df is not None and len(history_df) > 0:
                _render_history_chart(history_df)
                _render_recent_records(history_df)
    elif is_personal_mode and not gs_available:
        st.info("개인 모드 히스토리를 보려면 Google Sheets 연동이 필요합니다.")
    else:
        st.markdown(
            """
            <div style="background: rgba(59,130,246,0.08); border:1px solid rgba(59,130,246,0.35); border-radius:10px; padding:14px;">
              <p style="margin:0; color:#e2e8f0; font-weight:600;">공개 모드 안내</p>
              <p style="margin:8px 0 0 0; color:#94a3b8;">
                공개 모드에서는 개인 포트폴리오 히스토리를 저장/조회하지 않습니다.
              </p>
            </div>
            """,
            unsafe_allow_html=True,
        )


def _render_history_chart(history_df: pd.DataFrame) -> None:
    chart_df = history_df[["Date", "TotalValue"]].dropna().copy()
    chart_df = chart_df.sort_values("Date")
    if chart_df.empty:
        st.warning("차트 데이터가 없습니다.")
        return

    st.subheader("포트폴리오 가치 추이")

    period_options = [
        "전체", "최근 1주", "최근 1개월", "최근 3개월",
        "최근 6개월", "최근 1년", "사용자 지정",
    ]
    selected_period = st.selectbox("조회 기간", period_options, index=0, label_visibility="collapsed")

    today = pd.Timestamp.now()
    delta_map = {
        "최근 1주": 7, "최근 1개월": 30, "최근 3개월": 90,
        "최근 6개월": 180, "최근 1년": 365,
    }

    if selected_period in delta_map:
        start_date = today - pd.Timedelta(days=delta_map[selected_period])
        filtered_df = chart_df[chart_df["Date"] >= start_date]
    elif selected_period == "사용자 지정":
        cd1, cd2 = st.columns(2)
        min_d = chart_df["Date"].min().date()
        max_d = chart_df["Date"].max().date()
        with cd1:
            start_d = st.date_input("시작일", value=min_d, min_value=min_d)
        with cd2:
            end_d = st.date_input("종료일", value=max_d, max_value=max_d)
        filtered_df = chart_df[
            (chart_df["Date"].dt.date >= start_d)
            & (chart_df["Date"].dt.date <= end_d)
        ]
    else:
        filtered_df = chart_df

    if filtered_df.empty:
        st.warning("선택한 기간에 데이터가 없습니다.")
        return

    min_val = filtered_df["TotalValue"].min()
    max_val = filtered_df["TotalValue"].max()
    rng = max_val - min_val
    y_min = (min_val - rng * 0.05) if rng > 0 else min_val * 0.95
    y_max = (max_val + rng * 0.05) if rng > 0 else max_val * 1.05

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=filtered_df["Date"], y=filtered_df["TotalValue"],
        mode="lines+markers", name="총 자산",
        line=dict(color="#10b981", width=2),
        marker=dict(size=6, color="#10b981"),
        hovertemplate="<b>%{x|%Y-%m-%d %H:%M}</b><br>총 자산: $%{y:,.2f}<extra></extra>",
    ))

    max_idx = filtered_df["TotalValue"].idxmax()
    min_idx = filtered_df["TotalValue"].idxmin()
    fig.add_trace(go.Scatter(
        x=[filtered_df.loc[max_idx, "Date"]],
        y=[filtered_df.loc[max_idx, "TotalValue"]],
        mode="markers+text", name="고점",
        marker=dict(size=12, color="#ef4444", symbol="triangle-up"),
        text=[f"${filtered_df.loc[max_idx, 'TotalValue']:,.2f}"],
        textposition="top center", textfont=dict(color="#ef4444", size=11),
    ))
    fig.add_trace(go.Scatter(
        x=[filtered_df.loc[min_idx, "Date"]],
        y=[filtered_df.loc[min_idx, "TotalValue"]],
        mode="markers+text", name="저점",
        marker=dict(size=12, color="#3b82f6", symbol="triangle-down"),
        text=[f"${filtered_df.loc[min_idx, 'TotalValue']:,.2f}"],
        textposition="bottom center", textfont=dict(color="#3b82f6", size=11),
    ))

    fig.update_layout(
        title=dict(text=f"포트폴리오 가치 추이 ({selected_period})", font=dict(size=16, color="#f1f5f9")),
        xaxis=dict(title="날짜", gridcolor="rgba(148,163,184,0.2)", tickformat="%m/%d",
                   rangeslider=dict(visible=True, thickness=0.05)),
        yaxis=dict(title="자산 가치 (USD)", gridcolor="rgba(148,163,184,0.2)",
                   tickformat="$,.0f", range=[y_min, y_max]),
        plot_bgcolor="rgba(15,23,42,0.8)", paper_bgcolor="rgba(15,23,42,0)",
        font=dict(color="#94a3b8"), hovermode="x unified", showlegend=True,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1, font=dict(size=11)),
        margin=dict(l=10, r=10, t=50, b=10), height=450,
    )
    st.plotly_chart(fig, width="stretch", config={
        "displayModeBar": True, "displaylogo": False,
        "modeBarButtonsToRemove": ["lasso2d", "select2d"],
    })

    # Period statistics
    st.markdown("---")
    st.markdown("**선택 기간 통계**")
    p_first = filtered_df["TotalValue"].iloc[0]
    p_last = filtered_df["TotalValue"].iloc[-1]
    p_chg = p_last - p_first
    p_pct = (p_chg / p_first * 100) if p_first > 0 else 0.0
    p_max = filtered_df["TotalValue"].max()
    p_min = filtered_df["TotalValue"].min()

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("시작", f"${p_first:,.2f}")
    c2.metric("현재", f"${p_last:,.2f}", f"{p_pct:+.2f}%")
    c3.metric("최고", f"${p_max:,.2f}", f"+${p_max - p_first:,.2f}")
    c4.metric("최저", f"${p_min:,.2f}", f"${p_min - p_first:,.2f}")


def _render_recent_records(history_df: pd.DataFrame) -> None:
    st.markdown("---")
    st.subheader("최근 기록")
    display_df = history_df.tail(10).sort_values("Date", ascending=False).copy()
    display_df["TotalValue"] = display_df["TotalValue"].apply(
        lambda x: f"${x:,.2f}" if pd.notna(x) else "-"
    )
    display_df["Date"] = pd.to_datetime(display_df["Date"]).dt.strftime("%Y-%m-%d %H:%M")
    st.dataframe(display_df, width="stretch", hide_index=True)
