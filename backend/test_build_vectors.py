"""build_vectors — 임베딩 함수는 주입해서 API 호출 없이 검증한다."""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(__file__))

import build_vectors  # noqa: E402


def test_normalize_makes_unit_rows():
    m = np.array([[3.0, 4.0], [0.0, 2.0]], dtype="float32")
    out = build_vectors.normalize(m)
    assert np.allclose(np.linalg.norm(out, axis=1), 1.0)


def test_normalize_leaves_zero_rows_alone_instead_of_dividing_by_zero():
    m = np.array([[0.0, 0.0], [1.0, 0.0]], dtype="float32")
    out = build_vectors.normalize(m)
    assert np.all(np.isfinite(out))
    assert np.allclose(out[0], 0.0)


def test_build_embeds_every_course_purpose():
    seen = []

    def fake_embed(texts):
        seen.extend(texts)
        return np.tile(np.array([1.0, 0.0], dtype="float32"), (len(texts), 1))

    ids, matrix = build_vectors.build(fake_embed)
    assert len(ids) == 125
    assert matrix.shape == (125, 2)
    assert all(t for t in seen), "빈 purpose 가 임베딩으로 넘어가면 안 된다"


def test_save_and_load_round_trip(tmp_path):
    ids = ["A", "B"]
    matrix = np.array([[1.0, 0.0], [0.0, 1.0]], dtype="float32")
    path = tmp_path / "v.npz"
    build_vectors.save(path, ids, matrix)

    z = np.load(path, allow_pickle=False)
    assert [str(x) for x in z["ids"]] == ids
    assert np.allclose(z["vectors"], matrix)
