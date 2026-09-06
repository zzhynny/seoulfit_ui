from typing import Optional, Any
from typing_extensions import TypedDict
from langgraph.graph.message import add_messages
from typing import Annotated


class TravelState(TypedDict, total=False):
    travel_dates: Optional[str]        # 여행 날짜/기간 (자유 텍스트, LLM 추출 원본)
    trip_start_date: Optional[str]     # 여행 시작일 ISO "YYYY-MM-DD". 날짜 질문은 클라이언트
                                        # 날짜 선택기로만 답할 수 있어서(graph._parse_picked_dates)
                                        # 항상 채워진다 — 못 읽으면 슬롯을 비우는 대신 다시 묻는다.
                                        # Generator(planner.py)는 아직 이 값을 쓰지 않음
                                        # — 넘겨받을 준비만 된 상태.
    category: Optional[str]            # 관심사 카테고리
    restrictions: Optional[str]        # 식이/신체 제약
    companion: Optional[str]           # 동행자
    pace: Optional[str]                # 여행 스타일
    region: Optional[str]              # 서울 지역
    current_step: str                  # start | collecting | confirm | retrieving | planning | critic | done
    pending: Optional[str]             # 지금 답을 기다리는 슬롯 이름 (collect_node가 한 턴에 하나씩 질문)
    asked: list[str]                   # 이미 질문한 슬롯들. 같은 걸 두 번 묻지 않기 위한 기록이라
                                        # 값이 비어도 다시 묻지 않는다 (건너뛰기 = 빈 슬롯)
    confirmed: bool                    # 최종 컨펌 여부
    messages: Annotated[list, add_messages]  # 대화 히스토리 (reducer 적용)

    # RAG + planning
    retrieved_courses: list[dict[str, Any]]   # FAISS 검색 결과 코스 리스트 (flat merge of all segment anchors)
    day_segments: Optional[list[dict[str, Any]]]  # per-day-segment anchor courses (Index A)
    itinerary: Optional[dict[str, Any]]       # 최종 일정 (구조화된 JSON)

    # Planner → critic_repair handoff
    planning_context: Optional[dict[str, Any]]
    critic_report: Optional[dict[str, Any]]
