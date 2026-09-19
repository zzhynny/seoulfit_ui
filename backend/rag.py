"""여행 기간 파싱. 코스 검색은 retrieval.py 로 옮겼다.

이 파일은 FAISS 인덱스 빌드·임베딩 청크·구간 분할까지 들고 있었다. 그 중
검색에 해당하는 부분은 전부 retrieval.py 에 있고, 여기에는 자유 텍스트를
일수로 바꾸는 코드만 남았다. 시작일은 graph.py 의 날짜 피커가 직접 준다.
"""

from __future__ import annotations

import re
from datetime import datetime


# ---------------------------------------------------------------------------
# Duration parsing
# ---------------------------------------------------------------------------

_MONTH_RE = re.compile(
    r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\b",
    re.IGNORECASE,
)


def _looks_like_single_date(text: str) -> bool:
    """True if the text reads as one calendar date (e.g. 'June 23', '6/23',
    '2026-06-23') rather than a duration. Used to stop a day-of-month from being
    misread as a day count — a single visit date is one day.
    """
    return bool(
        _MONTH_RE.search(text)
        or re.search(r"\d{4}-\d{1,2}-\d{1,2}", text)
        or re.search(r"\b\d{1,2}\s*/\s*\d{1,2}\b", text)
    )


def _days_from_date_range(text: str) -> int:
    """Compute the inclusive number of days spanned by a date range, or 0 if the
    text isn't a recognizable range.

    Handles ISO ranges ('2026-06-23 to 2026-06-24'), month-name ranges
    ('june 23 to 24', 'june 30 - july 2'), and bare day-of-month ranges
    ('23-24'). Inclusive: June 23→24 is 2 days.
    """
    # ISO dates first — splitting on '-' would otherwise break them apart.
    iso = re.findall(r"\d{4}-\d{1,2}-\d{1,2}", text)
    if len(iso) >= 2:
        try:
            d0 = datetime.strptime(iso[0], "%Y-%m-%d").date()
            d1 = datetime.strptime(iso[-1], "%Y-%m-%d").date()
            span = abs((d1 - d0).days) + 1
            if 1 <= span <= 60:
                return span
        except ValueError:
            pass
    elif len(iso) == 1:
        # A single ISO date is not a range; bail before the '-' split below
        # tears '2026-06-23' into '2026' and '23'.
        return 0

    # Split on range separators: to / through / until / ~ / dashes.
    parts = re.split(r"\s*(?:to|through|until|thru|~|–|—|-)\s*", text)
    if len(parts) < 2:
        return 0
    start_part, end_part = parts[0].strip(), parts[-1].strip()

    # Try real date parsing (carries the start's month into a bare end day).
    try:
        from dateutil import parser as _dp

        base = datetime(2000, 1, 1)
        start = _dp.parse(start_part, fuzzy=True, default=base)
        end = _dp.parse(end_part, fuzzy=True, default=start)
        span = (end.date() - start.date()).days + 1
        if span < 1:
            # Cross-month range: end day-of-month < start (e.g. "June 30 to 2"
            # → July 2). dateutil inferred the same month; advance by one month.
            month = end.month % 12 + 1
            year = end.year + (1 if end.month == 12 else 0)
            end = end.replace(year=year, month=month)
            span = (end.date() - start.date()).days + 1
        if 1 <= span <= 60:
            return span
    except (ValueError, OverflowError, ImportError):
        pass

    # Fallback: two day-of-month numbers in the same month ('june 23 to 24').
    n0 = re.search(r"(\d{1,2})", start_part)
    n1 = re.search(r"(\d{1,2})", end_part)
    if n0 and n1:
        a, b = int(n0.group(1)), int(n1.group(1))
        if 0 <= (b - a) <= 60:
            return (b - a) + 1
    return 0


def _parse_num_days(duration: str | None, override: int | None = None) -> int:
    """Parse the number of trip days from a free-text duration/date string.

    Order matters: explicit '4 days'/'1 week' win, then date ranges like
    'June 23 to 24' (→ 2), and only a small bare number is trusted as a day
    count — so '23' from a date never becomes a 23-day trip.

    `override`, when given a positive int, short-circuits all of the above:
    an explicit day count from the caller is authoritative and the free-text
    `duration` (which may be stale, missing, or ambiguous) is never even
    inspected. No caller passes one today -- graph.py's date-picker flow
    instead guarantees `duration` itself always ends in a parseable
    "(N days)" suffix (see graph._describe_trip) -- but this stays available
    as a seam for a future caller that has the count without the text.
    """
    if override is not None and override > 0:
        return override
    if not duration:
        return 1
    text = duration.lower().strip()

    week_match = re.search(r"(\d+)\s*week", text)
    if week_match:
        return int(week_match.group(1)) * 7

    # Explicit day count (incl. Korean 일) — preferred over a night count so
    # '2박 3일' (2 nights / 3 days) reads as 3.
    day_match = re.search(r"(\d+)\s*(?:days?|일)", text)
    if day_match:
        return max(1, int(day_match.group(1)))
    night_match = re.search(r"(\d+)\s*(?:nights?|박)", text)
    if night_match:
        return max(1, int(night_match.group(1)))

    # Date range → inclusive span.
    span = _days_from_date_range(text)
    if span:
        return span

    # A single calendar date (no range) is a one-day visit — don't let its
    # day-of-month (e.g. '23' in 'June 23') become a 23-day trip.
    if _looks_like_single_date(text):
        return 1

    # Bare number, only if it's a plausible trip length (avoid reading a
    # day-of-month like '23' as a 23-day trip).
    num_match = re.search(r"\b(\d{1,2})\b", text)
    if num_match:
        n = int(num_match.group(1))
        if 1 <= n <= 30:
            return n
    return 1
