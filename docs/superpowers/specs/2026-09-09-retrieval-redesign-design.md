# 검색 재설계 — 필터 우선, 목적 기반 랭킹

2026-09-09

## 왜

지금 코스를 고르는 과정 전부는 세 줄이다.

```python
docs = store.similarity_search(query, k=k*3)           # FAISS 코사인
candidates = [중복 제거, 벡터 순위 유지]
anchors = rerank_courses_by_area(candidates, area)[:k]
```

`rerank_courses_by_area`의 실체는 `sorted(courses, key=lambda c: 0 if _in_area(c) else 1)`
— 정렬 키가 0 아니면 1이다. 순위를 실제로 정하는 건 코사인 유사도 하나뿐이고,
`rag.py`에는 `score`나 `weight`라는 단어조차 없다.

그 결과 사용자에게 받은 6개 슬롯 중 검색에 닿는 건 둘뿐이다.

| 슬롯 | 검색에 쓰이나 |
|---|---|
| `region` | 쿼리 문자열 + 사후 이진 정렬 |
| `category` | 쿼리 문자열 |
| `travel_dates` | 아니오 — k값과 일수 검증에만 |
| `pace` | 아니오 — 생성 프롬프트와 validator |
| `restrictions` | 아니오 — 생성 프롬프트 한 줄 |
| `companion` | **아무 데도 안 씀** |

측정으로 확인한 것들:

- `"Hongdae cafe Seoul travel itinerary"` 검색 상위 8개에 홍대 코스가 없다.
  임베딩 텍스트가 `제목 + 출처 + 테마 + POI목록`인데, 제목이 `"If you are a backpacker"`
  같은 여행자 유형이라 동네 신호가 들어가지 않는다. `Source: Visit Seoul`은 76개 코스에
  똑같이 들어가는 잡음이고, 테마 13개 중 `Culture`는 83%·`Modern Seoul`은 74%에 붙어
  변별력이 없다.
- 앱이 묻던 관심사 7개 중 `Cafe`·`Beauty`·`Activity`는 **매칭되는 코스가 0개**였다.
- `parse_day_segments`가 지역 개수로 날짜를 자동 분할한다. 3일 + 홍대·성수면
  Day1 홍대 / Day2-3 성수. 사용자에게 물어본 적이 없다.

## 무엇을

검색을 **필터 먼저, 랭킹 나중**으로 뒤집는다. 날짜별 지역·관심사는 사용자가 직접 정하고,
순위는 사용자가 적은 여행 목적과 코스 `purpose`의 의미 유사도로 매긴다.

```
채팅 6턴          travel_dates · category · companion · pace · restrictions · purpose
   ↓
Day Planner 화면   Day 1 [지역] [관심사]  Day 2 [지역] [관심사]  …
   ↓  POST /day-plan
retrieve_node ──→ 각 날마다 retrieval.select_anchors(day_spec, k)
              ──→ plan_node → Gemini → validator → critic   (변경 없음)
```

## 결정 사항

브레인스토밍에서 확정한 것들과 근거.

| 결정 | 근거 |
|---|---|
| 목적을 사용자에게 묻는다 (선택 입력) | "출장 중 반나절", "엄마랑 둘이"는 5개 라벨로 표현 불가. 코스 125개에 `purpose`를 이미 써뒀다 |
| 목적 매칭은 임베딩 | 어휘 겹침으로는 "프로포즈" ↔ "couple"을 못 잡는다 |
| 목적 미입력 시 다른 슬롯으로 문장 합성 | 다수 경로. 합성이 `companion`·`pace`를 검색에 처음 쓰이게 한다 |
| 관심사 단일 선택 | 복수 AND는 120개 조합 중 12개(10%)가 붕괴. 단일은 60개 중 1개 |
| 완화는 관심사부터, 지역은 유지 | 지역이 틀린 앵커는 하루 동선 전체를 망가뜨린다. 프롬프트가 "앵커 순서를 뼈대로 쓰라"고 지시하기 때문 |
| 날짜별 설정은 전용 화면 | 채팅으로 물으면 7일 × 3항목 = 25턴. 각 턴이 Gemini 호출 하나 |
| 관심사는 채팅에서 한 번 묻고 모든 날의 기본값 | 대부분은 날짜별로 다르게 하고 싶어 하지 않는다 |
| 지역은 채팅에서 빼고 화면에서만 | 지역은 날짜마다 다른 게 정상 |
| 검색 로직을 `retrieval.py`로 분리 | `rag.py`가 이미 778줄에 임베딩·청크·재시도·일수파싱·구간분할을 다 갖고 있다 |
| FAISS 제거 | 125개는 전수 계산이 더 빠르고 정확하다. FAISS는 필터링된 부분집합 검색을 못 한다 |
| `constraints`·품질 감점은 이번 범위 밖 | vegan 1건·luxury 1건이라 필터로 쓰면 풀이 빈다 |

## 아키텍처

### 새로 생기는 것

| 파일 | 책임 |
|---|---|
| `backend/retrieval.py` | 필터 2단 + 유사도 정렬 + 완화 사다리. 공개 함수 `select_anchors` 하나 |
| `backend/build_vectors.py` | 코스 `purpose` 125개를 임베딩해 `.npz`로 저장. 1회성 배치 |
| `backend/dataset/course_vectors.npz` | `ids` (125,) + `vectors` (125, 3072) float32, L2 정규화 완료 |
| `POST /day-plan` | 화면이 날짜별 지역·관심사를 저장 |
| `lib/screens/trip/day_planner_screen.dart` | N개 행. 기본값이 채워진 채로 열림 |

### 없어지는 것

| | 이유 |
|---|---|
| `rag.rerank_courses_by_area` | 지역 필터로 흡수 |
| `rag.retrieve_for_segments` | `select_anchors`로 대체 |
| `rag.parse_day_segments` | 사용자가 직접 지정 |
| `rag.build_query` | 이미 dead code |
| `rag.segment_k` | `day_spec` 하나가 하루라 항상 2를 반환한다 |
| `rag.build_or_load_vectorstore` | FAISS 제거 |
| `backend/build_index.py` | `build_vectors.py`로 대체 |
| `backend/vectorstore/` | `index.pkl`이 코스 dict 사본을 들고 있어 staleness 함정이었다 |
| `rag.py`의 staleness 경고 | 사본이 없어지므로 불필요 |
| `graph._recommend_region` | 관심사→지역 매핑. 관심사를 채팅에서 받지만 지역은 화면 기본값이 대신한다 |

## `retrieval.py`

```python
def select_anchors(day_spec, k, *, exclude=(), vectors=None) -> Selection:
    """day_spec = {day, region, interest, purpose_vec}
       exclude  = 앞선 날에 이미 앵커로 쓴 base course id
       vectors  = None 이면 유사도 정렬 없이 필터 결과만
       Selection = (courses, relaxed, sims)"""
```

### 필터 사다리

```
① 지역 필터    코스 POI 중 하나라도 요청 지역이면 통과 (geo.area_matches_requested, 인접 포함)
② 관심사 필터  코스 interests 에 선택값이 있으면 통과
③ 유사도 정렬  남은 후보의 purpose 벡터 × 질의 벡터 → 상위 k

k 미달   →  ② 해제 재시도                relaxed="interest"
그래도 0 →  [] 반환, 앵커 없이 진행       relaxed="none_available"
```

지역 임계값은 두지 않는다. `>0`과 `≥10%`가 12개 지역 전부에서 같은 결과를 냈다 —
코스당 POI가 4~8개라 하나만 맞아도 이미 12~25%다.

### 통과 개수 (실측, 125행 기준)

```
지역            풀  Culture   Food  Shopping  K-POP  Nature
Jongno       74      66      37      33      24      44
Itaewon      32      29       8      14       9      25
Gangnam      29      20       9      21       8      19
Myeongdong   29      25      12      20       7      21
Hongdae      24      15       8       8       8      16
Bukchon      21      20       8      10       7       8
Insadong     21      20       8      10       7       8
Apgujeong    15      10       5       9       5      10
Mapo         15       8       5       3       6      12
Seongsu      12       6       8       7       2      10
Dongdaemun   12       8      10       8       4       8
Sinchon       5       3       2       1       3       3

k=3 을 못 채우는 칸: 3/60 — Seongsu × K-POP & Hallyu (2),
Sinchon × Food & Cafes (2), Sinchon × Shopping (1)
```

`k = 3` 고정. 예전 `segment_k(구간일수 + 1)`는 한 구간이 여러 날을 덮을 때의 값이었는데,
이제 `day_spec` 하나가 하루라 항상 2가 되어 의미가 없다. 하루에 앵커 3개면 LLM 이
고를 여지가 있고, 필터가 3개를 못 채우는 칸은 60개 중 셋뿐이라 완화 사다리로 덮인다.
`segment_k`는 삭제한다.

(위 수치는 구현 후 실측으로 갱신했다. 설계 시점에는 한 칸으로 적었는데, 그때는
관심사 태그를 자동 규칙으로 매겼고 이후 125개를 손으로 다시 붙였다.)

### 중복 방지

```
같은 날     한 원본 코스에서 최대 1행 (VS_MVP_011_DAY2 와 _DAY4 가 같이 들어가지 않게)
날짜 사이   exclude 로 앞선 날의 base id 를 넘김
```

지금은 둘 다 없어서, 제목이 같은 문서 5개가 `k`를 잡아먹는다.

`exclude`는 **최선 노력**이다. 얇은 지역에서는 앞선 날들이 후보를 다 써버릴 수 있다
— 신촌은 풀이 5개인데 3일을 신촌으로 잡으면 셋째 날에 남는 게 없다. 제외하고 나서
`k`에 못 미치면 제외를 풀고 다시 뽑되, 같은 날 안의 원본 코스 중복 방지는 유지한다.

### 알려진 한계

지역 필터가 `POI 하나라도`이므로 통과한 풀의 상당수는 그 지역 POI가 하나뿐이다
— 동대문 83%, 압구정 73%, 마포 67%, 북촌·명동·인사동 62%. 유사도만으로 정렬하면
그런 코스가 1등이 될 수 있다. 이번에는 두지 않고, 문제가 확인되면 동점 처리에
매칭 개수를 쓰거나 1개짜리를 뒤로 미는 식으로 손본다.

## 임베딩

**코스 쪽**: `purpose`만. `description`은 장소 나열이라 목적 신호를 희석시키고,
장소는 이미 지역 필터가 처리한다. 코스당 벡터 1개.

**질의 쪽**: 사용자가 적은 문장, 없으면 합성 문장. 일정 생성당 **임베딩 1회**
(모든 날이 같은 목적을 쓴다).

```python
# 합성 예
"A relaxed three-day trip for a family with children, focused on shopping."
#  pace       dates          companion            category
```

**검색**:

```python
Z = np.load("dataset/course_vectors.npz")
V, IDS = Z["vectors"], list(Z["ids"])        # 서버 기동 시 1회, 1.5MB

rows = [IDS.index(cid) for cid in pool]
sims = V[rows] @ q                            # 정규화돼 있으므로 내적 = 코사인
top  = [pool[i] for i in sims.argsort()[::-1][:k]]
```

74×3072 내적은 마이크로초 단위이고 근사가 아니다. `numpy`는 이미 설치돼 있고
`faiss-cpu`가 빠진다.

## 인텍스트

### 채팅 (여행 전체) — 6턴

```
travel_dates   달력 (기존)
category       관심사 5개 칩 (기존, 모든 날의 기본값이 된다)
companion      solo / couple / friends / family (기존)
pace           packed / relaxed (기존)
restrictions   none / vegetarian / halal … (기존)
purpose        자유 입력, 건너뛰기 가능 (신규)
```

`region` 질문이 빠지고 `purpose`가 들어온다. 턴 수는 6으로 같다.

`FIELD_EXTRACT["purpose"]`는 **정규화하지 않는다** — 사용자 문장을 그대로 저장한다.
라벨로 뭉개면 임베딩할 게 없어진다. `"skip"`·`"없어요"`·빈 답은 `MISSING` → 빈 문자열.

### Day Planner 화면 (날짜별)

```
Day 1   [ Jongno    ▾ ]   [ Shopping ▾ ]
Day 2   [ Itaewon   ▾ ]   [ Shopping ▾ ]
Day 3   [ Gangnam   ▾ ]   [ Shopping ▾ ]
```

지역은 앱이 제시하는 12개, 관심사는 5개. 둘 다 단일 선택.

### 기본값은 서버가 만든다

`day_plan` 단계에 들어가는 **순간** 서버가 `day_specs`를 채워 상태에 저장한다.
화면은 `GET /state`로 그걸 읽어 보여주고, 수정분만 되돌린다.

```
지역   커버리지 넓은 순으로 날짜에 배분
       Jongno(74) · Itaewon(32) · Gangnam(29) · Myeongdong(29)
       Hongdae(24) · Bukchon(21) · Seongsu(12)
관심사  채팅에서 답한 값을 모든 날에
```

기본값 로직은 **서버 한 곳에만** 둔다. 화면과 서버 양쪽에 두면 반드시 어긋난다.
`day_specs`가 항상 존재하므로 "비어 있을 때"라는 분기가 없고, 앱을 닫았다 와도
상태에서 복원된다. 사용자는 반드시 화면에서 값을 보고 넘어간다 — 조용히 정해지는
경로가 없다.

### 흐름

```
collect 6개 완료  →  current_step = "day_plan", day_specs 기본값 저장
                        ↓
                   Day Planner 화면 (탭 한 번으로 통과 가능)
                        ↓  POST /day-plan
                   current_step = "confirm"
                        ↓
                   Confirm Slots  →  "confirm"  →  retrieve → plan → critic
```

`current_step`에 `"day_plan"`이 추가된다. Flutter는 지금 `readyToBuild`를
`current_step == 'confirm'`으로 판단하는데, 그 앞에 화면 진입 CTA가 붙는다.

### API

```
POST /day-plan
  { "thread_id": "...", "days": [ {"day":1,"region":"jongno","interest":"Shopping"}, … ] }
  → day_specs 저장, current_step="confirm", 갱신된 state 반환

GET /state
  → day_specs 추가 반환
```

### planner 쪽 파급

`requested_areas`가 `region` 문자열 추출에서 **`day_specs`의 지역 합집합**으로 바뀐다.
Google Places 보충은 그 합집합을 돌고, 프롬프트의 `=== DAY N CANDIDATES ===` 블록은
`day_specs`가 그대로 만든다.

## 실패와 폴백

| 상황 | 처리 |
|---|---|
| `course_vectors.npz` 없음 / 질의 임베딩 실패 | 유사도 항만 건너뛰고 필터 결과에서 상위 k. 로그 `[retrieval] no vectors — filter-only for day N` |
| 필터가 k 미달 | 관심사 해제 재시도 → 그래도 0이면 앵커 없이 진행 |
| `POST /day-plan` 입력이 어휘 밖 | 400. 조용히 0개를 반환하는 것보다 시끄럽게 실패하는 편이 낫다 |
| 목적 문장 500자 초과 | 앞 300자만 임베딩 |
| 목적이 한국어 | 그대로 임베딩. 코스 `purpose`가 영어라 유사도는 떨어지지만 죽지는 않는다 |
| `npz`의 ids와 `course_descriptions.json`의 id 불일치 | 기동 시 경고 + 없는 id는 유사도 0 |

지금은 임베딩이 실패하면 `retrieve_node`가 예외를 던져 채팅에
`"⚠️ Failed to retrieve courses"`가 뜨고 대화가 멈춘다. 크레딧이 소진된 현재
상태에서 앱을 켜면 정확히 그렇게 된다.

### 앵커 없음 분기의 알려진 구멍

`[ANCHOR COURSE — none available]`이 나가면 Google Places가 그날을 채우는데,
현재 Places 보충은 식당·카페·쇼핑·목적 텍스트 검색만 부르고 **관광지를 안 부른다.**
앵커가 없는 날은 카페와 몰로만 채워진다. 이번 범위에 넣지 않되 기록해둔다.

## 테스트

`select_anchors`는 벡터를 만들지 않고 **받는다**(`vectors=None`이면 필터만).
필터 사다리·완화·중복 방지를 API 호출 0회로 검증할 수 있어야 한다.

```
test_retrieval.py
   지역 필터        홍대 → 24개, 전부 홍대권 POI 를 하나 이상 가짐
   관심사 필터      홍대 + Shopping → 8개
   완화             신촌 + Shopping, k=3 → relaxed="interest"
   앵커 없음        없는 지역 → [], relaxed="none_available"
   같은 날 중복     VS_MVP_011_DAY2 와 _DAY4 가 함께 나오지 않음
   날짜 간 중복     exclude 로 넘긴 base id 가 결과에 없음
   벡터 없음        vectors=None 이어도 k개 반환
   정렬             가짜 벡터 주입 시 코사인 순서

test_day_plan.py
   기본값           3일 → Jongno·Itaewon·Gangnam / 7일 → 7개 지역 전부 다름
   검증             길이 불일치·어휘 밖·day 중복 → 400
   왕복             POST 후 GET /state 가 같은 값

test_descriptions.py
   scripts/validate_descriptions.py 를 pytest 로. 125개 전수 검증을 CI 에 넣는다

test/day_planner_test.dart
   기본값이 채워진 채로 열림 / 변경 후 payload / 7일이면 7행 / state 복원
```

픽스처를 만들지 않고 125개 실제 데이터로 돌린다. 픽스처는 데이터가 바뀔 때
테스트가 거짓말을 하게 만든다.

### 회귀

```
기존 67개 pytest 통과 유지
flutter analyze 0 issues
```

### 손대지 않는 선재 실패

```
test_reorder_supplements.py   seoulfit_ui/benchmark/ 가 없어 glob 0건 → 0.0 < 0.0
test_checkin_store.py         db fixture 를 줄 conftest.py 가 없음 (5 errors)
```

## 전제 조건

**Gemini 크레딧 충전.** `build_vectors.py`가 코스 125개를 임베딩해야 하고,
런타임 질의도 임베딩이 필요하다. 현재 `429 RESOURCE_EXHAUSTED` 상태다.

크레딧 없이도 구현·테스트는 진행할 수 있다 — `select_anchors(vectors=None)`
경로가 필터만으로 동작하고, 그 경로가 테스트 대부분을 덮는다.

## 이번 범위 밖

| | 왜 |
|---|---|
| `constraints` 필터/스코어 | vegan 1건·luxury 1건. Google Places 식당 검색에 제약 키워드를 넣는 쪽이 훨씬 크게 작동한다 |
| 품질 감점 (`area_heavy`·`no_meal`·`thin`) | 필터 둘 + 정렬 하나로 먼저 돌려보고 판단 |
| 앵커 없는 날의 Google Places 관광지 호출 | 별도 작업 |
| 채팅과 생성의 완전 분리 (`POST /itinerary`) | 상태 모델 재작성이라 이번 작업의 두 배. `select_anchors(day_spec)` 인터페이스가 그 길을 막지 않는다 |
| 멀티데이 코스를 통째로 앵커로 쓰기 | "5일 코스를 3일에 어떻게 자를까" 규칙이 필요하다 |
