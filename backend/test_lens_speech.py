"""/lens/speech caching and the Tavily fallback's empty-field rule — no network."""
from types import SimpleNamespace

from dotenv import load_dotenv

load_dotenv()  # lens.py 는 임포트 시점에 GEMINI_API_KEY 를 요구한다

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import lens  # noqa: E402


def test_speech_is_generated_once_per_text(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(lens, "AUDIO_DIR", tmp_path)
    monkeypatch.setattr(lens, "_tts", lambda text: calls.append(text) or b"ID3fake")
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    app = FastAPI()
    app.include_router(lens.router)
    client = TestClient(app)

    first = client.post("/lens/speech", json={"text": "Hello Seoul"})
    second = client.post("/lens/speech", json={"text": "Hello Seoul"})

    assert first.status_code == 200
    assert first.json() == second.json()
    assert first.json()["url"].startswith("/static/lens_audio/")
    assert calls == ["Hello Seoul"]
    assert client.post("/lens/speech", json={"text": ""}).status_code == 422


def test_web_fallback_leaves_unknown_fields_empty(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "test")
    monkeypatch.setattr(lens, "_web_search", lambda q: "Some cafe, 10:00 ~ 22:00 daily.")
    fake = SimpleNamespace(models=SimpleNamespace(generate_content=lambda **kw: SimpleNamespace(
        text='{"address": "", "hours": "10:00 ~ 22:00", "open_days": "Every day", '
             '"closed_days": "N/A", "subway": "", "tags": "cafe"}'
    )))
    monkeypatch.setattr(lens, "_gemini_client", fake)

    facts = lens._web_public_data({"name_english": "Some Cafe", "name_korean": "카페", "confidence": 80})

    assert facts["hours"] == "10:00 ~ 22:00"
    assert facts["address"] == "" and facts["subway"] == "" and facts["closed_days"] == ""
    assert lens._web_public_data({"name_english": "Unknown", "confidence": 0}) == {}
