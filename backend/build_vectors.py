"""코스 purpose 를 임베딩해 dataset/course_vectors.npz 를 만든다.

    ./venv/bin/python build_vectors.py

오프라인 배치다. 서비스 실행 중에는 돌지 않는다. course_descriptions.json 의
purpose 를 고치면 다시 돌려야 한다 — 안 돌리면 그 코스만 순위에서 밀린다
(예전 FAISS 인덱스처럼 조용히 옛 데이터를 쓰는 게 아니다. 그쪽은 index.pkl 에
코스 dict 사본을 통째로 담고 있었다).

description 은 임베딩하지 않는다. 장소 나열이라 목적 신호를 희석시키고, 장소는
이미 지역 필터가 처리한다.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import numpy as np

_HERE = Path(__file__).resolve().parent
DESCRIPTIONS = _HERE / "dataset" / "course_descriptions.json"
OUT = _HERE / "dataset" / "course_vectors.npz"

EMBEDDING_MODEL = "models/gemini-embedding-001"
CHUNK = 50          # rag.py 가 쓰던 값과 같다 — 이 API 의 배치 한도에 맞춘 것


def normalize(matrix: np.ndarray) -> np.ndarray:
    """행마다 L2 정규화. 미리 해두면 검색이 내적 한 번으로 끝난다."""
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0        # 0 벡터는 그대로 둔다 — 나누면 nan 이 된다
    return (matrix / norms).astype("float32")


def build(embed_fn) -> tuple[list[str], np.ndarray]:
    """embed_fn(list[str]) -> ndarray 를 받아 (ids, 정규화된 행렬)."""
    doc = json.loads(DESCRIPTIONS.read_text(encoding="utf-8"))
    entries = doc["courses"]
    ids = [e["course_id"] for e in entries]
    texts = [e["purpose"] for e in entries]
    if not all(texts):
        raise ValueError("purpose 가 빈 코스가 있다 — validate_descriptions.py 를 먼저 통과시켜라")
    return ids, normalize(np.asarray(embed_fn(texts), dtype="float32"))


def save(path: Path, ids: list[str], matrix: np.ndarray) -> None:
    np.savez(path, ids=np.array(ids), vectors=matrix)


def _gemini_embed(texts: list[str]) -> np.ndarray:
    from langchain_google_genai import GoogleGenerativeAIEmbeddings

    key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or ""
    if not key:
        raise SystemExit("GEMINI_API_KEY 가 없다")
    client = GoogleGenerativeAIEmbeddings(model=EMBEDDING_MODEL, google_api_key=key)

    out: list[list[float]] = []
    for i in range(0, len(texts), CHUNK):
        chunk = texts[i:i + CHUNK]
        print(f"  embedding {i + 1}-{i + len(chunk)} / {len(texts)}")
        out.extend(client.embed_documents(chunk))
    return np.asarray(out, dtype="float32")


if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv(_HERE / ".env")
    ids, matrix = build(_gemini_embed)
    save(OUT, ids, matrix)
    print(f"wrote {OUT} — {matrix.shape[0]} vectors x {matrix.shape[1]} dims", file=sys.stderr)
