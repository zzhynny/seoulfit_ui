# SeoulFit × 한국관광공사 TourAPI 연동 계획

수집한 서울 코스 100~150개를 뼈대로 쓰고, TourAPI로 보강·검증한다.
아래 수치는 전부 개발계정 키로 직접 호출해서 확인한 실측값이다.

- 서비스: `한국관광공사_영문 관광정보서비스_GW` (data.go.kr 15101753)
- Base URL: `https://apis.data.go.kr/B551011/EngService2`
- 트래픽: **오퍼레이션마다 각각 1,000회/일**
- 갱신 주기: 하루 1회

---

## 1. 먼저 알아야 할 것 — 실제 데이터 규모

포털 설명에는 "약 8만 건"이라고 되어 있지만, 목록 조회로 실제 잡히는 건 다르다.

| 구분 | 건수 |
|---|---|
| 전국 전체 | 15,080 |
| 서울 전체 | 4,960 |
| 그중 면세점 (SH04) | 4,102 (83%) |
| **면세점 제외 서울** | **858** |

### 카테고리별 (서울)

| 코드 | 이름 | 건수 |
|---|---|---|
| `EX` | 체험관광 | 278 |
| `VE` | 문화관광 | 247 |
| `FD` | 음식 | 90 |
| `EV` | 축제/공연/행사 | 70 |
| `HS` | 역사관광 | 46 |
| `AC` | 숙박 | 36 |
| `NA` | 자연관광 | 27 |
| `LS` | 레저스포츠 | 16 |
| `SH` | 쇼핑 | 4,150 (대부분 면세점) |

### 여기서 나오는 결론

**TourAPI로 우리 POI DB를 대체할 수 없다.** 서울 음식점이 90개다.

역할이 이렇게 나뉜다.

- **뼈대** — 우리가 수집한 실제 코스 100~150개 (대체 불가 자산)
- **보강·검증** — TourAPI

---

## 2. 1단계 — 코스의 장소를 공식 데이터에 연결

**성격:** 오프라인 배치 1회. 서비스 실행 중에는 돌지 않는다.

코스에서 뽑은 장소 이름은 그냥 텍스트다. 이걸 TourAPI 공식 ID(`contentid`)에 붙인다.
붙고 나면 좌표·카테고리·휴무일을 전부 따라올 수 있다.

### 호출 1 — `searchKeyword2`

```
GET /searchKeyword2
  &keyword={장소명}
  &lDongRegnCd=11        # 서울로 한정
  &numOfRows=10
```

받는 것: `contentid` `contenttypeid` `title` `addr1` `mapx/mapy` `lclsSystm1/2/3` `firstimage`

### 호출 2 — `detailCommon2`

```
GET /detailCommon2&contentId={cid}
```

받는 것: `overview`(긴 설명) `homepage` `tel` `주소` `좌표`

`overview`를 임베딩 텍스트에 추가한다. 지금 126코스 임베딩이 얇은 게 검색 품질 병목인데
여기서 개선된다.

### 주의: 검색 결과 순서를 믿으면 안 된다

`keyword=Gyeongbokgung`으로 실제 검색한 결과다.

```
1위  Andersson Bell Gyeongbokgung Flagship Store [Tax Refund Shop]   <- 쇼핑
2위  DAISO Gyeongbokgung Station Branch [Tax Refund Shop]            <- 쇼핑
3위  Gyeongbokgung Palace (경복궁)                                    <- 정답
```

경복궁 본체가 3위다. 면세점 4,102건이 검색 결과를 오염시킨다.

**필터 순서**

1. `contenttypeid`로 배제 — 랜드마크를 찾는데 79(쇼핑)가 나오면 버린다
2. title에 `[Tax Refund Shop]`이 있으면 제외
3. title이 `English (한글)` 형식이므로 괄호 앞부분만 비교
4. 코스에 좌표가 있으면 500m 이내 우선
5. 애매하면 LLM 1회 판정
6. `match_confidence`를 반드시 저장한다. 못 붙인 장소는 기존 데이터로 그냥 둔다

### 결과물

`course_data.json`에 필드 추가 후 `build_index.py --rebuild`

**호출량:** 750장소 x 2 = 1,500회. 오퍼레이션별로 나뉘므로 각각 하루면 끝난다.

---

## 3. 2단계 — 일정 보강과 검증

### 3-1. Index B를 미리 만든다

서비스 실행 중에 `areaBasedList2`를 부르지 않는다. 미리 다 받아서 우리 인덱스로 만든다.

**왜 그렇게 하나**

| 이유 | 설명 |
|---|---|
| 쿼터 | 일 1,000회다. 런타임 호출이면 사용자 수에 비례해 소진된다. 사전 구축이면 총 수백 회 쓰고 이후 0회 |
| 크기 | 서울 858건. 전량이 메모리에 올라간다. 로컬이 API보다 빠르고 유연하다 |
| 필터 제약 해소 | `lclsSystm1`은 값이 하나만 들어간다. 카테고리 3개 동시 선택은 API로 3회 호출인데 로컬이면 공짜다 |
| 갱신 주기 | 데이터가 하루 1회만 바뀐다. 매번 받을 이유가 없다 |

> Index B는 FAISS 벡터 인덱스가 아니다. 지역·카테고리·거리·휴무일로 거르는 구조화 필터용
> 리스트다. `lclsSystm2` 중분류가 테마 역할을 하므로 임베딩은 하지 않는다.

**호출**

```
GET /areaBasedList2
  &lDongRegnCd=11
  &lclsSystm1={EV|EX|FD|HS|LS|NA|VE}
  &arrange=Q            # 수정일순 + 대표이미지 있는 것만
  &numOfRows=100&pageNo={N}
```

**인덱스를 둘로 나눈다**

| 인덱스 | 내용 | 건수 | 용도 |
|---|---|---|---|
| Index B | EV·EX·FD·HS·LS·NA·VE | 858 | 코스 보강 / 대체 장소 |
| Index T | SH04 면세점 | 4,102 | 택스리펀 레이어 (별도 기능) |

면세점은 코스 후보 풀에 절대 넣지 않는다. 넣으면 일정이 면세점으로 뒤덮인다.

### 3-2. 휴무일 채우기 — `detailIntro2`

```
GET /detailIntro2&contentId={cid}&contentTypeId={tid}
```

**타입마다 필드명이 다르다. 정규화 테이블이 반드시 필요하다.**

| 타입 | 휴무일 | 영업시간 |
|---|---|---|
| 76 관광지 | `restdate` | `usetime` |
| 78 문화시설 | `restdateculture` | `usetimeculture` |
| 79 쇼핑 | `restdateshopping` | `opentime` |
| 82 음식점 | `restdatefood` | `opentimefood` |
| 75 레포츠 | `restdateleports` | `usetimeleports` |

공통 스키마로 통일한다.

```
{ closed_weekdays: [0..6], closed_note: str, hours_raw: str }
```

**채움률 (25건씩 샘플링한 실측)**

| 타입 | 휴무일 | 영업시간 |
|---|---|---|
| 관광지 | 24/25 | 24/25 |
| 음식점 | 25/25 | 25/25 |

거의 다 차 있다. 858건 전량이 하루에 들어온다.

**파싱해야 할 실제 문자열**

```
"N/A (Open all year round)"
"Seollal & Chuseok holidays, Twice a month on Mondays"
"11:30-22:00 (Break time 15:30-17:00)"
```

### 3-3. 코드에 붙이는 법 (중요)

현재 구조를 먼저 알아야 한다.

```
plan  ->  critic_repair  ->  END
```

`critic_repair` 노드 안에서:

```
critic.evaluate(state)           -> before_report (점수 + issues)
repairer.repair(state, report)   -> 고쳐진 itinerary
critic.evaluate(고친 state)      -> after_report (재채점)
```

**루프가 아니다.** `graph.py:378`이 `add_edge("critic_repair", END)`다.
채점 -> 수리 -> 재채점 1패스로 끝난다.

**CriticAgent와 RepairAgent는 분리돼 있다.**

| | 하는 일 |
|---|---|
| CriticAgent | 채점만 한다. `issues` 목록과 점수 4종을 낸다 |
| RepairAgent | 수리만 한다. 고정된 수리 4개를 순서대로 돈다 |

`RepairAgent.repair`가 report에서 꺼내 쓰는 건 `requested_areas` 하나뿐이다.
**`issues`를 읽지 않는다.**

```python
_repair_missing_areas()     # 빠진 지역 채우기
_repair_missing_meals()     # 식사 없는 날 채우기
_repair_underfilled_days()  # 일정 부족한 날 채우기
_remove_duplicates()        # 중복 제거
```

따라서 critic에 이슈만 추가하면 **점수만 떨어지고 일정은 그대로 나간다.**

**휴무일 기능을 동작시키려면 세 곳을 다 건드려야 한다**

| # | 위치 | 하는 일 |
|---|---|---|
| 1 | `planner.py` 후보 선택 | 그날 휴무인 POI를 애초에 안 넣는다. 제일 싸고 효과적 |
| 2 | `CriticAgent._evaluate_closed_days()` (신규) | 빠져나간 게 있으면 이슈로 기록 |
| 3 | `RepairAgent._repair_closed_pois()` (신규) | 실제 교체 수행 |

1번이 핵심이다. 2·3번은 안전망이다. 1번만 해도 대부분 막힌다.

**Index B를 어디에 물리나**

`build_candidate_pool(state)` (critic_repair.py:341)는 지금 후보를 두 군데서만 모은다.

```python
retrieved_courses[].sequence         # FAISS로 검색된 코스의 장소들
planning_context.google_supplement   # Google 보강 장소들
```

여기에 **Index B를 세 번째 소스로 추가**한다. 후보가 늘어나야 대체할 장소가 생긴다.

---

## 4. 3단계 — 여행 중 추천

### 4-1. "근처 카페 찾아줘"

```
GET /locationBasedList2
  &mapX={경도}&mapY={위도}&radius=5000
  &lclsSystm1=FD&lclsSystm2=FD05     # FD05 = Cafes / Teahouses
  &arrange=S                          # 거리순 + 이미지 있는 것만
```

받는 것: 목록 공통 항목 + `dist`(거리 m)

**현실 확인:** 서울 FD가 90건뿐이다. 실측으로 경복궁 반경 3km에 18건 나왔다.

따라서 **Index B 로컬 검색이 메인, API가 보조**다.
로컬 거리계산으로 먼저 뽑고, 결과가 얇을 때만 API를 친다. 쿼터도 안 쓴다.

- 좌표를 100m 격자로 반올림해 캐시한다 (같은 블록 중복 호출 제거)
- 카테고리 다중 선택은 필터 없이 1회 호출한 뒤 로컬에서 거른다

### 4-2. 여행 기간 중 축제

```
GET /searchFestival2
  &eventStartDate={YYYYMMDD}&eventEndDate={YYYYMMDD}
  &lDongRegnCd=11
```

받는 것: 목록 공통 항목 + `eventstartdate` `eventenddate`

**위치 파라미터가 없다.** 시군구까지만 된다. 거리 계산은 응답의 `mapx/mapy`로 로컬에서 한다.

**실측:** 2026-08-19 ~ 09-30 서울 4건. 야놀자를 대체하기엔 부족하다.
**병행한다.** TourAPI는 공식·영문이라 신뢰도가 높고, 야놀자는 물량이 많다.

- 날짜 범위 단위로 캐시한다 (TTL 24h)

### 4-3. 코드에 붙는 곳

| 무엇 | 어디 |
|---|---|
| 근처 추천 | `api.py`에 `/nearby` 신설 |
| 축제 병합 | `api.py:551` `/events`에 source 필드 추가 |
| 현재 위치 재계획 | `RepairAgent` + `geo.py` + ODsay 기존 배선 재사용 |

---

## 5. 공통 모듈

먼저 만들어야 나머지가 깨끗해진다.

### `backend/tourapi/client.py`

**응답 형태가 두 가지다.** 실측 확인.

```python
# 정상 / 제공기관 오류
{"response": {"header": {"resultCode": "0000"}, "body": {...}}}

# GW 파라미터 오류 - 최상위에 resultCode
{"responseTime": "...", "resultCode": "11",
 "resultMsg": "NO_MANDATORY_REQUEST_PARAMETERS_ERROR1(contentId)"}
```

`response` 키가 있는지로 먼저 분기한다.
트래픽 초과나 키 오류는 XML로 올 수 있으니 첫 바이트도 확인한다.

그 외:

- **파라미터명 대소문자가 엄격하다.** `contentId` OK / `contentid` 실패 (실측 확인)
- `_type=json` 필수
- 오퍼레이션별 일일 카운터 (각각 1,000)
- 캐시: 상세 조회 24h TTL

### `backend/tourapi/normalize.py`

- 타입별 필드명을 공통 스키마로 변환
- `cpyrhtDivCd` 분기 — 샘플이 전부 Type3(변경금지)였다. 크롭·오버레이 금지, 원본만 사용
- **국문 잔존 검사** — `smoking` 필드에 "모두 금연석"이 그대로 온다.
  영문 서비스인데도 섞여 있어서 화면 노출 전 검사가 필요하다

---

## 6. TourAPI로 안 되는 것

확인해봤고 안 되는 것들이다. 다른 방법을 찾거나 포기한다.

| 항목 | 상태 |
|---|---|
| `detailInfo2` 반복정보 | 영문 서비스는 비어 있다. 경복궁도 `totalCount: 0` |
| 예약 정보 | `reservationfood` 채움률 1/25 (4%) |
| 카드결제 여부 | 필드 자체가 없다 (교통 타입만 있음) |
| 음식 메뉴 사진 | `detailImage2&imageYN=N` -> 0건 |
| 영어 메뉴 유무 | 없음 |
| 짐 보관함 | 없음 |

**뜻밖의 수확:** 택스리펀은 title에 `[Tax Refund Shop]` 태그가 박혀 있다. 서울 4,102건.
동선 위 면세 매장 표시 기능이 데이터만으로 바로 나온다.

---

## 7. 호출 예산

| 단계 | 오퍼레이션 | 성격 | 대략 |
|---|---|---|---|
| 1 | `searchKeyword2` | 1회성 | ~750 |
| 1 | `detailCommon2` | 1회성 | ~750 |
| 2 | `areaBasedList2` | 1회성 | 수백 |
| 2 | `detailIntro2` | 1회성 | ~858 |
| 3 | `locationBasedList2` | 상시 | 캐시 + 로컬 우선 |
| 3 | `searchFestival2` | 상시 | 날짜 캐시 |

오퍼레이션마다 각각 1,000/일이므로 전부 여유 있게 들어간다. **초기 구축 2~3일.**

---

## 8. 작업 순서

1. **공통 모듈** (`client.py` + `normalize.py`) — 나머지 전부의 전제
2. **1단계 매핑 스크립트** — 매칭률이 나와야 2단계 설계가 확정된다
3. **Index B / Index T 구축**
4. **휴무일 파서 + planner 필터 + critic 규칙 + repair 교체**
5. **3단계 `/nearby`, 축제 병합**

### 지금 가장 큰 미지수

**1단계 매칭 성공률.** 면세점 오염 때문에 필터 없이는 못 쓴다는 건 확인됐지만,
필터를 넣고 나서 몇 %가 붙을지는 돌려봐야 안다.

이 숫자가 낮으면 Index B 의존도를 더 올려야 하므로,
**2단계 착수 전에 1단계 결과 리포트를 먼저 본다.**
