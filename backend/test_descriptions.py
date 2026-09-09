"""125개 설명문 전수 검증을 CI 에 넣는다.

손으로 돌리던 스크립트였다. course_data_v6.json 을 고치면 설명문이 어긋나는데,
실제로 market 타입을 재분류했을 때 두 건이 깨졌다 — 그때는 우연히 돌려봐서 알았다.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "scripts"))

from validate_descriptions import DESCRIPTIONS, validate  # noqa: E402


def test_every_description_matches_its_course():
    assert validate(DESCRIPTIONS) == 0


def test_faiss_is_gone():
    import pathlib
    root = pathlib.Path(__file__).parent
    assert not (root / "vectorstore").exists()
    assert not (root / "build_index.py").exists()
    assert "faiss" not in (root / "requirements.txt").read_text()
