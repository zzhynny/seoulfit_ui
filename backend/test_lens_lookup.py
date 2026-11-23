"""seoul.json lookup: a place that isn't in the dataset must miss (-> Tavily),
not borrow a longer-named row that merely contains its name -- a park
narrated with a luggage locker's address, a stream with its museum's.
Parenthetical names (숭례문(남대문), 동대문디자인플라자 (DDP)) still match.
"""
from dotenv import load_dotenv

load_dotenv()  # lens.py 는 임포트 시점에 GEMINI_API_KEY 를 요구한다

import lens


def found(*names):
    row, _ = lens._lookup_in_seoul_json(list(names))
    return (row or {}).get("post_sj", "").strip() or None


def test_a_name_inside_a_longer_row_name_is_not_a_match():
    assert found("청계천", "청계광장") is None          # not 청계천박물관
    assert found("낙산공원", "낙산") is None            # not 낙산 물품보관소
    assert found("남대문시장") is None                  # not 남대문시장 관광안내소
    assert found("인사동", "인사동길") is None          # not 안녕인사동


def test_parenthetical_row_names_still_match():
    assert found("숭례문") == "숭례문(남대문)"
    assert found("동대문디자인플라자") == "동대문디자인플라자 (DDP)"


def test_exact_and_more_specific_queries_still_match():
    assert found("경복궁") == "경복궁"
    assert found("경복궁 근정전") == "경복궁"           # part of a listed complex
    assert found("알 수 없음", "Unknown") is None
