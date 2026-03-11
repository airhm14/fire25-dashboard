# -*- coding: utf-8 -*-
"""Regime Gate — AI 전략 생성 전 현재 상태 분류.

오케스트레이터는 전략 생성 전에 반드시 이 모듈로 regime을 먼저 분류한다.
분류 결과가 AI 전략의 허용 범위를 결정한다.

Regimes:
  NORMAL / DEFCON / PUDDLE_1 / PUDDLE_2 / PUDDLE_3 / PUDDLE_4 / SMART_SHOULDER
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class RegimeResult:
    """Regime classification with rationale."""
    regime: str
    confidence: float
    reasons: list[str]
    puddle_stage: int          # 0 if not puddle
    defcon_active: bool
    smart_shoulder_triggered: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "regime": self.regime,
            "confidence": round(self.confidence, 2),
            "reasons": self.reasons,
            "puddle_stage": self.puddle_stage,
            "defcon_active": self.defcon_active,
            "smart_shoulder_triggered": self.smart_shoulder_triggered,
        }


def classify(
    *,
    defcon_triggered: bool = False,
    puddle_stage: int = 0,
    puddle_alert: bool = False,
    smart_shoulder_triggered: bool = False,
    market_regime: str = "CORRECTION",
    market_confidence: float = 0.5,
) -> RegimeResult:
    """Classify the current regime from existing signal outputs.

    Priority (highest first):
      1. PUDDLE_1~4 (active drawdown / recovery)
      2. DEFCON (calm + high momentum → savings mode)
      3. SMART_SHOULDER (QQQM over-concentration risk)
      4. NORMAL (default)
    """
    reasons: list[str] = []

    # --- Puddle takes highest priority (active signal) ---
    if puddle_stage >= 1:
        regime = f"PUDDLE_{puddle_stage}"
        reasons.append(f"웅덩이 {puddle_stage}단계 감지 (alert={puddle_alert})")
        return RegimeResult(
            regime=regime,
            confidence=0.9 if puddle_alert else 0.7,
            reasons=reasons,
            puddle_stage=puddle_stage,
            defcon_active=defcon_triggered,
            smart_shoulder_triggered=smart_shoulder_triggered,
        )

    # --- DEFCON ---
    if defcon_triggered:
        reasons.append("DEFCON: VIX ≤ 14 & RSI ≥ 70 → 저축 모드")
        return RegimeResult(
            regime="DEFCON",
            confidence=0.85,
            reasons=reasons,
            puddle_stage=0,
            defcon_active=True,
            smart_shoulder_triggered=smart_shoulder_triggered,
        )

    # --- Smart Shoulder ---
    if smart_shoulder_triggered:
        reasons.append("Smart Shoulder: QQQM >77% + SMA20 하향돌파 + 전고점 후 조정")
        return RegimeResult(
            regime="SMART_SHOULDER",
            confidence=0.80,
            reasons=reasons,
            puddle_stage=0,
            defcon_active=False,
            smart_shoulder_triggered=True,
        )

    # --- NORMAL ---
    reasons.append(f"기본 상태 (시장 레짐: {market_regime})")
    return RegimeResult(
        regime="NORMAL",
        confidence=market_confidence,
        reasons=reasons,
        puddle_stage=0,
        defcon_active=False,
        smart_shoulder_triggered=False,
    )
