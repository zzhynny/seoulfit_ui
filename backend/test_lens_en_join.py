"""seoul.json 한↔영 조인이 엉뚱한 장소를 붙이지 않는지 확인한다.

주소가 뒤바뀌면 사용자가 다른 건물 앞에 서게 되므로, 커버리지보다
오매칭 0 이 중요하다.
"""
import re

from dotenv import load_dotenv

load_dotenv()  # lens.py 는 임포트 시점에 GEMINI_API_KEY 를 요구한다

import lens  # noqa: E402


def _phone(row: dict) -> str:
    d = re.sub(r"\D", "", row.get("cmmn_telno") or "")
    d = d[2:] if d.startswith("82") else d
    d = d.lstrip("0")
    return d if len(d) >= 8 else ""


def test_pairs_are_plausible():
    paired = [r for r in lens._SEOUL_ROWS if r.get("_en")]
    assert paired, "no Korean row got an English twin"

    for r in paired:
        en = r["_en"]
        assert en.get("lang_code_id") == "en", r["_slug"]

        # 우편번호가 다르면 다른 장소다.
        kz = re.match(r"\s*(\d{5})", r.get("new_address") or r.get("address") or "")
        ez = re.match(r"\s*(\d{5})", en.get("new_address") or en.get("address") or "")
        if kz and ez:
            assert kz.group(1) == ez.group(1), f"{r['_slug']}: {kz.group(1)} != {ez.group(1)}"

        # 전화번호가 양쪽에 다 있으면 같아야 한다. 영문 레코드는 국가번호
        # 82 를 붙이고 시외국번 0 을 떼는 경우가 있어 양쪽을 맞춰 비교한다.
        # 자릿수 잘림(한쪽이 상대의 접두사)은 같은 번호로 본다.
        kp, ep = _phone(r), _phone(en)
        if kp and ep:
            assert kp.startswith(ep) or ep.startswith(kp), \
                f"{r['_slug']}: phone {kp} != {ep}"


def test_english_twin_is_actually_english():
    hangul = re.compile(r"[가-힣]")
    bad = [
        r["_slug"] for r in lens._SEOUL_ROWS
        if r.get("_en") and hangul.search(r["_en"].get("post_sj") or "")
    ]
    assert not bad, f"English twin still in Korean: {bad[:5]}"


def test_known_neighbour_collisions_are_rejected():
    """주소 키가 같은 블록 이웃을 묶던 사례들. 페어 검증이 빠지면 되살아난다."""
    by_slug = {r["_slug"]: r for r in lens._SEOUL_ROWS}
    for slug, wrong in (
        ("반포대교-야경", "Sebitseom"),
        ("서울올림픽기념관", "Baekje"),
        ("서대문형무소역사관", "Independence Park"),
    ):
        en = by_slug[slug].get("_en")
        assert en is None or wrong.lower() not in (en.get("post_sj") or "").lower(), \
            f"{slug} paired to {en.get('post_sj')!r}"


def test_no_row_pairs_to_itself():
    for r in lens._SEOUL_ROWS:
        en = r.get("_en")
        if en:
            assert en.get("post_url") != r.get("post_url")


if __name__ == "__main__":
    test_pairs_are_plausible()
    test_english_twin_is_actually_english()
    test_known_neighbour_collisions_are_rejected()
    test_no_row_pairs_to_itself()
    n = sum(1 for r in lens._SEOUL_ROWS if r.get("_en"))
    print(f"ok — {n}/{len(lens._SEOUL_ROWS)} paired, 0 mismatches")
