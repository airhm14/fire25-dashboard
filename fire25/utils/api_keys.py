# -*- coding: utf-8 -*-
"""API Key 로더.

우선순위:
  1. Streamlit Cloud Secrets  (st.secrets["KEY"])
  2. 로컬 .streamlit/secrets.toml  (st.secrets가 자동으로 읽음)
  3. 시스템 환경변수  (os.environ.get("KEY"))

Streamlit 세션 외부(테스트, 직접 스크립트 실행)에서는
st.secrets 접근이 예외를 발생시키므로 자동으로 환경변수 fallback.
"""

from __future__ import annotations

import os


def get_api_key(key_name: str) -> str:
    """API key를 Streamlit Secrets → 환경변수 순서로 조회.

    Args:
        key_name: 환경변수/secrets 키 이름.
            예: "GEMINI_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY"

    Returns:
        조회된 키 문자열. 없으면 빈 문자열.
    """
    try:
        import streamlit as st
        val = st.secrets[key_name]
        if val:
            return str(val)
    except Exception:
        pass
    return os.environ.get(key_name, "")
