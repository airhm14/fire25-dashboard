# -*- coding: utf-8 -*-
"""PUDDLE 비중 동적 계수 산출 모듈 — TEAM FIRE 25.

동일 입력 → 동일 출력 (deterministic).
부동소수점 반올림: 소수점 1자리.

지원 단계: PUDDLE_2, PUDDLE_3, PUDDLE_4
PUDDLE_1은 매수 금지(투입률 0%)이므로 대상 아님.
"""

from __future__ import annotations

# ── 단계별 기본 비중 및 상·하한 캡 ─────────────────────────────────
_STAGE_CONFIG: dict[int, dict[str, float]] = {
    2: {"base_pct": 10.0, "min_pct": 5.0,  "max_pct": 15.0},
    3: {"base_pct": 25.0, "min_pct": 12.0, "max_pct": 35.0},
    4: {"base_pct": 50.0, "min_pct": 25.0, "max_pct": 65.0},
}

_COEFF_MIN: float = 0.5
_COEFF_MAX: float = 1.5


def _vix_adjustment(vix: float) -> float:
    """VIX 기준 계수 조정값 반환.

    Args:
        vix: 현재 VIX 지수.

    Returns:
        VIX 조정값 (+0.2 ~ -0.3).
    """
    if vix < 20:
        return 0.2
    elif vix < 25:
        return 0.0
    elif vix < 30:
        return -0.1
    else:
        return -0.3


def _drawdown_adjustment(drawdown_from_200ma: float) -> float:
    """200일 이동평균 대비 낙폭 기준 계수 조정값 반환.

    낙폭이 클수록 매수 기회로 간주하여 계수를 높임.

    Args:
        drawdown_from_200ma: 200일선 대비 낙폭. 음수 (예: -0.12 = 12% 하락).

    Returns:
        낙폭 조정값 (0.0 ~ +0.3).
    """
    dd_abs = abs(drawdown_from_200ma)
    if dd_abs < 0.05:
        return 0.0
    elif dd_abs < 0.10:
        return 0.1
    elif dd_abs < 0.20:
        return 0.2
    else:
        return 0.3


def _breadth_adjustment(breadth_score: float) -> float:
    """섹터 breadth 기준 계수 조정값 반환.

    breadth가 높을수록 시장 참여도가 넓어 매수 우호적.

    Args:
        breadth_score: 섹터 breadth 점수 (0~1).

    Returns:
        breadth 조정값 (-0.2 ~ +0.1).
    """
    if breadth_score > 0.5:
        return 0.1
    elif breadth_score >= 0.3:
        return 0.0
    else:
        return -0.2


def _build_reason(
    vix: float,
    vix_adj: float,
    drawdown_adj: float,
    breadth_adj: float,
    cap_applied: bool,
    capped_pct: float,
) -> str:
    """계수 산출 이유 문자열 생성 (사람이 읽을 수 있는 형태).

    Args:
        vix: 입력 VIX 값 (메시지 구체화용).
        vix_adj: VIX 조정값.
        drawdown_adj: 낙폭 조정값.
        breadth_adj: breadth 조정값.
        cap_applied: 상·하한 캡 적용 여부.
        capped_pct: 캡 적용 후 최종 비중.

    Returns:
        이유 문자열.
    """
    parts: list[str] = []

    if vix_adj > 0:
        parts.append(f"VIX {vix:.0f} 낮아 상향 조정")
    elif vix_adj == -0.1:
        parts.append(f"VIX {vix:.0f} (25~30) 하향 조정")
    elif vix_adj == -0.3:
        parts.append(f"VIX {vix:.0f} 30 이상으로 하향 조정")

    if drawdown_adj > 0:
        parts.append("낙폭 확대로 매수 기회 가중")

    if breadth_adj > 0:
        parts.append("breadth 강세")
    elif breadth_adj < 0:
        parts.append("breadth 약세")

    if cap_applied:
        parts.append(f"캡 적용 → {capped_pct}%")

    return ", ".join(parts) if parts else "표준 계수 적용"


def compute_puddle_sizing(
    puddle_stage: int,
    vix: float,
    drawdown_from_200ma: float,
    breadth_score: float,
) -> dict:
    """PUDDLE 단계별 동적 비중 계수 산출.

    PUDDLE_2~4에 대해 VIX, 낙폭, breadth를 종합하여
    기본 투입 비중에 계수를 곱한 조정 비중을 반환한다.
    상·하한 캡은 단계별로 고정.

    Args:
        puddle_stage: PUDDLE 단계 (2, 3, 4).
        vix: 현재 VIX 지수.
        drawdown_from_200ma: 200일선 대비 낙폭. 음수 (예: -0.12).
        breadth_score: 섹터 breadth 점수 (0~1).

    Returns:
        dict:
            puddle_stage (int): 입력 단계.
            base_pct (float): 기본 비중 (%).
            coefficient (float): 최종 계수 (0.5~1.5, 소수점 1자리).
            adjusted_pct (float): base_pct × coefficient.
            capped_pct (float): 상·하한 캡 적용 후 비중.
            cap_applied (bool): 캡 적용 여부.
            coefficient_breakdown (dict): vix_adj, drawdown_adj, breadth_adj.
            reason (str): 사람이 읽을 수 있는 이유.
    """
    config = _STAGE_CONFIG.get(puddle_stage)
    if config is None:
        # PUDDLE_1 또는 미지원 단계 — 투입 비중 없음
        return {
            "puddle_stage": puddle_stage,
            "base_pct": 0.0,
            "coefficient": 0.0,
            "adjusted_pct": 0.0,
            "capped_pct": 0.0,
            "cap_applied": False,
            "coefficient_breakdown": {
                "vix_adj": 0.0,
                "drawdown_adj": 0.0,
                "breadth_adj": 0.0,
            },
            "reason": "PUDDLE_1 또는 미지원 단계 — 매수 비중 없음",
        }

    base_pct: float = config["base_pct"]
    min_pct: float = config["min_pct"]
    max_pct: float = config["max_pct"]

    vix_adj: float = _vix_adjustment(vix)
    drawdown_adj: float = _drawdown_adjustment(drawdown_from_200ma)
    breadth_adj: float = _breadth_adjustment(breadth_score)

    # 계수 산출: 1.0 + 합산 조정, 0.5~1.5 클리핑
    raw_coeff: float = 1.0 + vix_adj + drawdown_adj + breadth_adj
    coefficient: float = round(
        max(_COEFF_MIN, min(_COEFF_MAX, raw_coeff)), 1
    )

    adjusted_pct: float = round(base_pct * coefficient, 1)

    # 상·하한 캡 적용
    cap_applied: bool = adjusted_pct < min_pct or adjusted_pct > max_pct
    capped_pct: float = round(max(min_pct, min(max_pct, adjusted_pct)), 1)

    reason = _build_reason(vix, vix_adj, drawdown_adj, breadth_adj, cap_applied, capped_pct)

    return {
        "puddle_stage": puddle_stage,
        "base_pct": base_pct,
        "coefficient": coefficient,
        "adjusted_pct": adjusted_pct,
        "capped_pct": capped_pct,
        "cap_applied": cap_applied,
        "coefficient_breakdown": {
            "vix_adj": round(vix_adj, 1),
            "drawdown_adj": round(drawdown_adj, 1),
            "breadth_adj": round(breadth_adj, 1),
        },
        "reason": reason,
    }
