"""레이트 리밋과 요청 크기 상한 자체 점검.

    backend/venv/bin/python -m pytest backend/test_rate_limit.py

익명 공개 배포라 이 두 가지가 비용·쿼터를 막는 유일한 방벽이다. 둘 다 조용히
무력화되는 종류라서 — 리밋은 헤더 한 줄로 우회되고, 상한은 없어도 평소엔
멀쩡히 동작한다 — 눈으로는 회귀를 못 잡는다.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pytest  # noqa: E402
from pydantic import ValidationError  # noqa: E402

import api  # noqa: E402


class _Req:
    """_client_ip 가 보는 최소한의 요청."""

    def __init__(self, xff=None, peer="203.0.113.9"):
        self.headers = {"x-forwarded-for": xff} if xff else {}
        self.client = type("C", (), {"host": peer})()


def test_the_client_ip_is_the_hop_our_proxy_added():
    """X-Forwarded-For 의 왼쪽은 클라이언트가 위조할 수 있다.

    첫 홉을 믿으면 `-H 'X-Forwarded-For: <아무거나>'` 로 매 요청이 새 버킷이
    되어 리밋이 사라진다. 프록시가 직접 덧붙이는 마지막 홉만 믿어야 한다.
    """
    assert api._client_ip(_Req(xff="1.1.1.1, 2.2.2.2, 10.0.0.5")) == "10.0.0.5"
    assert api._client_ip(_Req(xff="evil-spoof")) == "evil-spoof"  # 홉이 하나면 그게 프록시다
    assert api._client_ip(_Req()) == "203.0.113.9", "헤더가 없으면 소켓 주소"


def test_forwarded_header_is_ignored_without_a_proxy(monkeypatch):
    """TRUST_PROXY=0 이면 헤더를 아예 안 읽는다.

    단 이것만으로는 안 막힌다 — uvicorn 의 ProxyHeadersMiddleware 가 기본으로
    켜져 있고 X-Forwarded-For 의 첫 값으로 request.client.host 를 덮어쓰므로,
    아래 fallback 이 이미 위조된 값을 읽게 된다. 실측 결과 `--no-proxy-headers`
    와 TRUST_PROXY=0 을 둘 다 걸어야 실제로 429 가 났다. 배포 커맨드에서
    --no-proxy-headers 가 빠지면 이 테스트는 통과하는데 서버는 뚫린다.
    """
    monkeypatch.setattr(api, "_TRUST_PROXY", False)
    assert api._client_ip(_Req(xff="1.1.1.1")) == "203.0.113.9"


def test_eviction_keeps_live_counters():
    """딕셔너리를 통째로 clear() 하면 한도를 채운 쪽까지 같이 풀려난다.

    위조 IP 로 10,000건을 채우는 것만으로 전원의 리밋을 리셋할 수 있었다.
    """
    now = 1_000_000.0
    api._rate_hits.clear()
    api._rate_hits["offender"] = (now, api._RATE_LIMIT + 50)      # 지금 한도 초과 중
    api._rate_hits.update({f"stale{i}": (now - 999, 1) for i in range(10_001)})

    # 미들웨어의 정리 구문과 같은 식.
    for k in [k for k, (t, _) in api._rate_hits.items() if now - t >= api._RATE_WINDOW]:
        del api._rate_hits[k]

    assert "offender" in api._rate_hits, "진행 중인 창을 지우면 리밋이 리셋된다"
    assert len(api._rate_hits) == 1, "만료된 창은 지워져야 한다"
    api._rate_hits.clear()


def test_expensive_endpoints_are_metered():
    """리스트를 받아 항목마다 외부 호출을 하는 경로가 리밋 밖에 있으면 안 된다."""
    for path in ("/transit-legs", "/poi-closure-check", "/revalidate",
                 "/swap-candidates", "/events", "/chat", "/analyze-landmark"):
        assert path in api._METERED_PATHS, f"{path} 가 계량 대상에서 빠졌다"


def test_list_requests_are_bounded():
    """/transit-legs 는 정거장 쌍마다 ODsay 를 부른다 — 상한이 없으면 한 요청이
    수백 초 동안 워커를 붙잡는다."""
    stop = {"name": "x", "lat": 37.5, "lng": 127.0}
    api.TransitLegsRequest(stops=[stop] * 40)
    with pytest.raises(ValidationError):
        api.TransitLegsRequest(stops=[stop] * 41)

    item = {"poi_name": "x", "visit_date": "2026-09-20"}
    api.ClosureCheckRequest(items=[item] * 40)
    with pytest.raises(ValidationError):
        api.ClosureCheckRequest(items=[item] * 41)


def test_free_text_is_bounded():
    """긴 문자열은 Gemini 컨텍스트 요금이 되고, POI 이름은 캐시 파일에 영구히 남는다."""
    api.ChatRequest(thread_id="t" * 16, message="x" * 2000)
    with pytest.raises(ValidationError):
        api.ChatRequest(thread_id="t" * 16, message="x" * 2001)

    with pytest.raises(ValidationError):
        api.PoiSummaryRequest(name="x" * 201)


def test_wildcard_cors_is_refused():
    """FRONTEND_ORIGIN=* 는 환경변수 한 줄로 방벽을 통째로 여는 지름길이다."""
    with pytest.raises(RuntimeError, match=r"\*"):
        api._normalize_origin("*")
    assert api._normalize_origin("example.com") == "https://example.com"
    assert api._normalize_origin("https://example.com/") == "https://example.com"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
