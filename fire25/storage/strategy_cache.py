# -*- coding: utf-8 -*-
"""Strategy Cache — strategy_hash 기반 전략 캐시.

동일 입력(같은 strategy_hash)이면 AI를 재호출하지 않고
기존 전략 결과를 재사용한다.

저장: strategy_cache.json (로컬 파일)
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any

# 캐시 파일 경로 (fire25-dashboard 루트 기준)
_CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__),
))), "")
CACHE_FILE = os.path.join(_CACHE_DIR, "strategy_cache.json")

# 캐시 최대 보관 항목 수
MAX_CACHE_ENTRIES = 50


def _load_raw() -> dict[str, Any]:
    """Load raw cache dict from file."""
    if not os.path.exists(CACHE_FILE):
        return {}
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {}


def _save_raw(data: dict[str, Any]) -> None:
    """Save raw cache dict to file."""
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, default=str)
    except Exception:
        pass


def get_cached_strategy(strategy_hash: str) -> dict[str, Any] | None:
    """해시로 캐시 조회. 히트 시 전략 dict, 미스 시 None."""
    cache = _load_raw()
    entry = cache.get(strategy_hash)
    if not entry or not isinstance(entry, dict):
        return None
    return entry.get("strategy")


def store_strategy(
    strategy_hash: str,
    strategy: dict[str, Any],
    context_snapshot: dict[str, Any] | None = None,
) -> None:
    """전략 + 해시를 캐시에 저장."""
    cache = _load_raw()

    cache[strategy_hash] = {
        "strategy": strategy,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "context_regime": (context_snapshot or {}).get("regime", ""),
    }

    # 오래된 항목 정리 (MAX 초과 시 가장 오래된 것부터 제거)
    if len(cache) > MAX_CACHE_ENTRIES:
        sorted_keys = sorted(
            cache.keys(),
            key=lambda k: cache[k].get("timestamp", ""),
        )
        for old_key in sorted_keys[: len(cache) - MAX_CACHE_ENTRIES]:
            del cache[old_key]

    _save_raw(cache)


def clear_cache() -> None:
    """캐시 초기화."""
    _save_raw({})
