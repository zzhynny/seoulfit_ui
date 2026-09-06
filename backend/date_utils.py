"""
여행 일정용 순수 계산 유틸 — 외부 API/패키지 의존 없음 (stdlib datetime만 사용).

- date_for_day: 여행 시작일 + Day 번호 -> 실제 date 객체
- weekday_for_day: 위와 동일한 날짜의 요일 문자열 ("월요일" / "Monday")
- is_weekend_day: 그 날이 토/일요일인지
- day_label: 화면 표시용 문자열 (예: "Day 5 (2027-02-05, 금요일)")

Day 번호 규칙: Day 1 = 여행 시작일 그 자체 (첫날).
입력 날짜는 "YYYY-MM-DD" / "YYYY.MM.DD" / "YYYY/MM/DD" 문자열이나
date/datetime 객체 어느 쪽이든 받는다.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta

_DATE_RE = re.compile(r"^(\d{4})[-./](\d{1,2})[-./](\d{1,2})$")

_WEEKDAY_KO = ["월요일", "화요일", "수요일", "목요일", "금요일", "토요일", "일요일"]
_WEEKDAY_EN = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def _parse_start_date(start_date) -> date:
    """"2027-02-01" / "2027.02.01" / "2027/02/01" 문자열이나 date/datetime 객체를 date로 정규화."""
    if isinstance(start_date, datetime):
        return start_date.date()
    if isinstance(start_date, date):
        return start_date
    if isinstance(start_date, str):
        m = _DATE_RE.match(start_date.strip())
        if not m:
            raise ValueError(
                f"지원하지 않는 날짜 형식: {start_date!r} "
                "(YYYY-MM-DD / YYYY.MM.DD / YYYY/MM/DD 만 가능)"
            )
        year, month, day = (int(g) for g in m.groups())
        return date(year, month, day)
    raise TypeError(f"start_date는 str 또는 date/datetime이어야 합니다: {type(start_date)!r}")


def date_for_day(start_date_str, day_number: int) -> date:
    """여행 시작일 + Day 번호 -> 실제 날짜. Day 1 = 시작일 그 자체."""
    if day_number < 1:
        raise ValueError(f"day_number는 1 이상이어야 합니다: {day_number}")
    start = _parse_start_date(start_date_str)
    return start + timedelta(days=day_number - 1)


def weekday_for_day(start_date_str, day_number: int, lang: str = "ko") -> str:
    """date_for_day와 동일한 날짜의 요일 문자열."""
    d = date_for_day(start_date_str, day_number)
    idx = d.weekday()  # 0=월요일 ... 6=일요일
    if lang == "ko":
        return _WEEKDAY_KO[idx]
    if lang == "en":
        return _WEEKDAY_EN[idx]
    raise ValueError(f"지원하지 않는 lang: {lang!r} ('ko' 또는 'en'만 가능)")


def is_weekend_day(start_date_str, day_number: int) -> bool:
    """그 날이 토요일/일요일인지."""
    d = date_for_day(start_date_str, day_number)
    return d.weekday() >= 5  # 5=토요일, 6=일요일


def day_label(start_date_str, day_number: int) -> str:
    """화면 표시용 문자열, 예: 'Day 5 (2027-02-05, 금요일)'."""
    d = date_for_day(start_date_str, day_number)
    wd = weekday_for_day(start_date_str, day_number, lang="ko")
    return f"Day {day_number} ({d.isoformat()}, {wd})"


if __name__ == "__main__":
    # 자체 검증 -- 실제 파이썬 datetime으로 2027-02-01이 월요일임을 먼저 확인한 뒤 작성함.
    assert date_for_day("2027-02-01", 1) == date(2027, 2, 1)
    assert date_for_day("2027-02-01", 5) == date(2027, 2, 5)
    assert date_for_day("2027.02.01", 5) == date(2027, 2, 5)
    assert date_for_day("2027/02/01", 5) == date(2027, 2, 5)
    assert date_for_day(date(2027, 2, 1), 5) == date(2027, 2, 5)
    assert date_for_day(datetime(2027, 2, 1, 9, 30), 5) == date(2027, 2, 5)

    assert weekday_for_day("2027-02-01", 1, lang="ko") == "월요일"
    assert weekday_for_day("2027-02-01", 1, lang="en") == "Monday"
    assert weekday_for_day("2027-02-01", 5, lang="ko") == "금요일"
    assert weekday_for_day("2027-02-01", 5, lang="en") == "Friday"
    assert weekday_for_day("2027-02-01", 6, lang="ko") == "토요일"
    assert weekday_for_day("2027-02-01", 7, lang="ko") == "일요일"

    assert is_weekend_day("2027-02-01", 1) is False   # 월요일
    assert is_weekend_day("2027-02-01", 5) is False   # 금요일
    assert is_weekend_day("2027-02-01", 6) is True    # 토요일
    assert is_weekend_day("2027-02-01", 7) is True    # 일요일

    assert day_label("2027-02-01", 5) == "Day 5 (2027-02-05, 금요일)"

    try:
        date_for_day("2027-13-01", 1)
    except ValueError:
        pass
    else:
        raise AssertionError("잘못된 월(13월)에 대해 ValueError가 발생해야 함")

    try:
        weekday_for_day("2027-02-01", 1, lang="fr")
    except ValueError:
        pass
    else:
        raise AssertionError("지원 안 하는 lang에 대해 ValueError가 발생해야 함")

    print("date_utils.py 자체 검증 통과 ✅")
