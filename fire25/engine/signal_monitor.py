# -*- coding: utf-8 -*-
"""조기 경보 신호 판정 모듈 — TEAM FIRE 25.

실행 규칙 (execution_rule): 조건 충족 시 buy_blocked=True, 자동 매수 차단.
알림 신호 (alert): 조건 충족 시 alerts에 추가, 차단 없음.

[실행 규칙 — 4종]
  QQQM_MA50_BREAK     : QQQM 50일선 하회 → 신규 매수 차단
  QQQM_CAP_VIOLATION  : 매수 후 QQQM 80% 초과 → 해당 매수 차단
  DUPLICATE_PUDDLE_BUY: 동일 PUDDLE 단계 중복 매수 → 차단
  COOLDOWN_VIOLATION  : 쿨다운 잔여일 > 0 → 차단

[알림 신호 — 3종]
  VIX_SPIKE           : VIX ≥ 20 & QQQM < 200일선 × 1.05 → 리밸런싱 검토 권고
  YIELD_CURVE_STRESS  : 장단기 금리차 < -0.5 → SGOV 비중 확대 검토 권고
  SGOV_CAP_WARNING    : SGOV > 18% (DEFCON 제외) → SGOV 20% 상한 근접 경고
"""

from __future__ import annotations

from typing import Any


def evaluate_signals(
    *,
    qqqm_price: float,
    qqqm_ma50: float,
    qqqm_ma200: float,
    qqqm_current_pct: float,
    qqqm_after_buy_pct: float | None = None,
    vix: float,
    spread_10y_2y: float,
    sgov_current_pct: float,
    regime: str,
    puddle_stage: int | None = None,
    last_puddle_buy_stage: int | None = None,
    cooldown_remaining_days: int = 0,
) -> dict[str, Any]:
    """조기 경보 신호 판정.

    실행 규칙 위반이 하나라도 있으면 buy_blocked=True.
    알림 신호는 차단 없이 alerts 리스트에만 추가.

    Args:
        qqqm_price: 현재 QQQM 가격.
        qqqm_ma50: QQQM 50일 이동평균.
        qqqm_ma200: QQQM 200일 이동평균.
        qqqm_current_pct: 현재 포트폴리오 내 QQQM 비중 (%).
        qqqm_after_buy_pct: 매수 후 예상 QQQM 비중 (%). None이면 검사 생략.
        vix: 현재 VIX 지수.
        spread_10y_2y: 장단기 금리차 (10년 - 2년, 단위: %).
        sgov_current_pct: 현재 포트폴리오 내 SGOV 비중 (%).
        regime: 현재 Regime 문자열 (예: "PUDDLE_2", "NORMAL").
        puddle_stage: 현재 PUDDLE 단계. None이면 중복 매수 검사 생략.
        last_puddle_buy_stage: 마지막으로 매수한 PUDDLE 단계. None이면 검사 생략.
        cooldown_remaining_days: 쿨다운 잔여일. 0이면 차단 없음.

    Returns:
        dict:
            buy_blocked (bool): 실행 규칙 위반 존재 여부.
            block_reasons (list[dict]): 차단 사유 목록 (code, type, message).
            alerts (list[dict]): 알림 신호 목록 (code, type, message).
    """
    block_reasons: list[dict[str, str]] = []
    alerts: list[dict[str, str]] = []

    # ── 실행 규칙 (자동 차단) ───────────────────────────────────────

    # 1. QQQM_MA50_BREAK: QQQM이 50일 이평선 하회
    if qqqm_price < qqqm_ma50:
        block_reasons.append({
            "code": "QQQM_MA50_BREAK",
            "type": "execution_rule",
            "message": "QQQM이 50일 이평선 아래. 신규 매수 차단.",
        })

    # 2. QQQM_CAP_VIOLATION: 매수 후 QQQM 80% 상한 초과
    if qqqm_after_buy_pct is not None and qqqm_after_buy_pct > 80.0:
        block_reasons.append({
            "code": "QQQM_CAP_VIOLATION",
            "type": "execution_rule",
            "message": (
                f"매수 후 QQQM 비중 {qqqm_after_buy_pct:.1f}% > 80% 상한. 해당 매수 차단."
            ),
        })

    # 3. DUPLICATE_PUDDLE_BUY: 동일 PUDDLE 단계 중복 매수
    if (
        puddle_stage is not None
        and last_puddle_buy_stage is not None
        and puddle_stage == last_puddle_buy_stage
    ):
        block_reasons.append({
            "code": "DUPLICATE_PUDDLE_BUY",
            "type": "execution_rule",
            "message": f"PUDDLE_{puddle_stage} 동일 단계 중복 매수 차단.",
        })

    # 4. COOLDOWN_VIOLATION: 쿨다운 잔여일 존재
    if cooldown_remaining_days > 0:
        block_reasons.append({
            "code": "COOLDOWN_VIOLATION",
            "type": "execution_rule",
            "message": f"쿨다운 {cooldown_remaining_days}일 잔여. 매수 차단.",
        })

    # ── 알림 신호 (차단 없음) ────────────────────────────────────────

    # 1. VIX_SPIKE: VIX ≥ 20 (200일선 조건 제거 — MA50 이탈은 별도 실행 규칙에서 처리)
    if vix >= 20:
        alerts.append({
            "code": "VIX_SPIKE",
            "type": "alert",
            "message": "리밸런싱 검토 권고",
        })

    # 2. YIELD_CURVE_STRESS: 장단기 금리차 역전 심화
    if spread_10y_2y < -0.5:
        alerts.append({
            "code": "YIELD_CURVE_STRESS",
            "type": "alert",
            "message": "SGOV 비중 확대 검토 권고",
        })

    # 3. SGOV_CAP_WARNING: SGOV 20% 상한 근접 (DEFCON 제외)
    if sgov_current_pct > 18.0 and regime.upper() != "DEFCON":
        alerts.append({
            "code": "SGOV_CAP_WARNING",
            "type": "alert",
            "message": "SGOV 20% 상한 근접 경고",
        })

    return {
        "buy_blocked": len(block_reasons) > 0,
        "block_reasons": block_reasons,
        "alerts": alerts,
    }
