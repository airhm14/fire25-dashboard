# -*- coding: utf-8 -*-
"""Regime Gate — AI 전략 생성 전 현재 상태 분류.

오케스트레이터는 전략 생성 전에 반드시 이 모듈로 regime을 먼저 분류한다.
분류 결과가 AI 전략의 허용 범위를 결정한다.

Regimes:
  NORMAL / DEFCON / PUDDLE_1 / PUDDLE_2 / PUDDLE_3 / PUDDLE_4 / SMART_SHOULDER

Regime Persistence Filter:
  새 regime이 3거래일 연속 유지되어야 공식 전환.
  3일 미만이면 이전 regime 유지 (노이즈 필터).

Advanced PUDDLE Detection:
  - Trend signal: SMA50 기울기
  - Drawdown signal: 고점 대비 낙폭
  - Volatility signal: VIX 수준
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# ── Module-level state for persistence filter ────────────────────
_prev_regime: str = "NORMAL"
_candidate_regime: str = "NORMAL"
_candidate_days: int = 0
PERSISTENCE_DAYS: int = 3  # 3거래일 연속 유지 필요


@dataclass
class RegimeResult:
    """Regime classification with rationale."""
    regime: str
    confidence: float
    reasons: list[str]
    puddle_stage: int          # 0 if not puddle
    defcon_active: bool
    smart_shoulder_triggered: bool
    persistence_pending: bool = False   # True if new regime not yet confirmed

    def to_dict(self) -> dict[str, Any]:
        return {
            "regime": self.regime,
            "confidence": round(self.confidence, 2),
            "reasons": self.reasons,
            "puddle_stage": self.puddle_stage,
            "defcon_active": self.defcon_active,
            "smart_shoulder_triggered": self.smart_shoulder_triggered,
            "persistence_pending": self.persistence_pending,
        }


# ── Advanced PUDDLE detection ────────────────────────────────────

def _detect_puddle_advanced(
    *,
    puddle_stage: int,
    puddle_alert: bool,
    drawdown_pct: float = 0.0,
    vix: float = 20.0,
    sma50_slope: float = 0.0,
) -> tuple[int, list[str]]:
    """Classify PUDDLE stage using Trend + Drawdown + Volatility signals.

    Returns (stage, reasons).
    If puddle_stage is already set by upstream (existing pipeline), use it.
    Otherwise, derive from 3-signal composite.
    """
    if puddle_stage >= 1:
        # Upstream already determined stage
        reasons = [f"웅덩이 {puddle_stage}단계 (upstream, alert={puddle_alert})"]
        return puddle_stage, reasons

    # Composite signal detection
    signals = 0
    reasons: list[str] = []

    # Trend signal: SMA50 하향
    if sma50_slope < -0.001:
        signals += 1
        reasons.append(f"Trend↓ (SMA50 slope={sma50_slope:.4f})")

    # Drawdown signal
    dd = abs(drawdown_pct)
    if dd >= 5:
        signals += 1
        reasons.append(f"Drawdown={dd:.1f}%")

    # Volatility signal
    if vix >= 25:
        signals += 1
        reasons.append(f"VIX={vix:.1f} (elevated)")

    # Map signal count to stage
    if signals >= 3 and dd >= 20:
        return 4, reasons
    elif signals >= 2 and dd >= 15:
        return 3, reasons
    elif signals >= 2 and dd >= 10:
        return 2, reasons
    elif signals >= 1 and dd >= 5:
        return 1, reasons

    return 0, []


# ── Regime persistence filter ────────────────────────────────────

def _apply_persistence(raw_regime: str) -> tuple[str, bool]:
    """Apply the 3-trading-day persistence filter.

    Returns (effective_regime, pending).
    - If raw_regime matches previous confirmed regime → keep it.
    - If raw_regime is new → count days; only switch after PERSISTENCE_DAYS.
    """
    global _prev_regime, _candidate_regime, _candidate_days

    if raw_regime == _prev_regime:
        # Same as confirmed — reset any candidate
        _candidate_regime = raw_regime
        _candidate_days = 0
        return raw_regime, False

    # New candidate
    if raw_regime == _candidate_regime:
        _candidate_days += 1
    else:
        _candidate_regime = raw_regime
        _candidate_days = 1

    if _candidate_days >= PERSISTENCE_DAYS:
        # Confirmed transition
        _prev_regime = raw_regime
        _candidate_days = 0
        return raw_regime, False

    # Not yet confirmed — keep previous regime
    return _prev_regime, True


def classify(
    *,
    defcon_triggered: bool = False,
    puddle_stage: int = 0,
    puddle_alert: bool = False,
    smart_shoulder_triggered: bool = False,
    market_regime: str = "CORRECTION",
    market_confidence: float = 0.5,
    # Advanced PUDDLE inputs (optional)
    drawdown_pct: float = 0.0,
    vix: float = 20.0,
    sma50_slope: float = 0.0,
    # Persistence control
    apply_persistence: bool = True,
) -> RegimeResult:
    """Classify the current regime from existing signal outputs.

    Priority (highest first):
      1. PUDDLE_1~4 (active drawdown / recovery)
      2. DEFCON (calm + high momentum → savings mode)
      3. SMART_SHOULDER (QQQM over-concentration risk)
      4. NORMAL (default)
    """
    reasons: list[str] = []

    # --- Advanced PUDDLE detection ---
    adv_stage, adv_reasons = _detect_puddle_advanced(
        puddle_stage=puddle_stage,
        puddle_alert=puddle_alert,
        drawdown_pct=drawdown_pct,
        vix=vix,
        sma50_slope=sma50_slope,
    )

    # --- Puddle takes highest priority (active signal) ---
    if adv_stage >= 1:
        raw_regime = f"PUDDLE_{adv_stage}"
        reasons.extend(adv_reasons)

        effective, pending = (
            _apply_persistence(raw_regime) if apply_persistence else (raw_regime, False)
        )
        return RegimeResult(
            regime=effective,
            confidence=0.9 if puddle_alert else 0.7,
            reasons=reasons + ([f"Persistence: {raw_regime} 확인 대기중"] if pending else []),
            puddle_stage=adv_stage,
            defcon_active=defcon_triggered,
            smart_shoulder_triggered=smart_shoulder_triggered,
            persistence_pending=pending,
        )

    # --- DEFCON ---
    if defcon_triggered:
        raw_regime = "DEFCON"
        reasons.append("DEFCON: VIX ≤ 14 & RSI ≥ 70 → 저축 모드")

        effective, pending = (
            _apply_persistence(raw_regime) if apply_persistence else (raw_regime, False)
        )
        return RegimeResult(
            regime=effective,
            confidence=0.85,
            reasons=reasons + ([f"Persistence: DEFCON 확인 대기중"] if pending else []),
            puddle_stage=0,
            defcon_active=True,
            smart_shoulder_triggered=smart_shoulder_triggered,
            persistence_pending=pending,
        )

    # --- Smart Shoulder ---
    if smart_shoulder_triggered:
        raw_regime = "SMART_SHOULDER"
        reasons.append("Smart Shoulder: QQQM >77% + SMA20 하향돌파 + 전고점 후 조정")

        effective, pending = (
            _apply_persistence(raw_regime) if apply_persistence else (raw_regime, False)
        )
        return RegimeResult(
            regime=effective,
            confidence=0.80,
            reasons=reasons + ([f"Persistence: SMART_SHOULDER 확인 대기중"] if pending else []),
            puddle_stage=0,
            defcon_active=False,
            smart_shoulder_triggered=True,
            persistence_pending=pending,
        )

    # --- NORMAL ---
    raw_regime = "NORMAL"
    reasons.append(f"기본 상태 (시장 레짐: {market_regime})")

    effective, pending = (
        _apply_persistence(raw_regime) if apply_persistence else (raw_regime, False)
    )
    return RegimeResult(
        regime=effective,
        confidence=market_confidence,
        reasons=reasons,
        puddle_stage=0,
        defcon_active=False,
        smart_shoulder_triggered=False,
        persistence_pending=pending,
    )


def reset_persistence() -> None:
    """Reset persistence state (for testing or session restart)."""
    global _prev_regime, _candidate_regime, _candidate_days
    _prev_regime = "NORMAL"
    _candidate_regime = "NORMAL"
    _candidate_days = 0
