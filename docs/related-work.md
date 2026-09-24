# 관련 연구 정리 — LLM 기반 여행 일정 생성과 검증·수리

SeoulFit이 서 있는 연구 흐름을 팀 공유용으로 정리한 문서다.
우리 시스템과 구조가 겹치는 논문만 골랐고, 각 항목은 ① 무엇을 했나 ② 우리 코드의 어느 부분과 대응하나 순으로 적었다.

확인 범위: 전부 abstract 및 공개 페이지 기준으로 확인했고, 본문 전체를 읽고 검증한 것은 아니다.
게재 여부는 표에 따로 표기했다 (arXiv 단계인 논문은 인용 전 최종 게재 확인 필요).

---

## 1. 한눈에 보기

| 논문 | 시점 | 게재 | 생성 | 검증·수리 |
|---|---|---|---|---|
| TravelPlanner | 2024.02 | ICML 2024 | 벤치마크 | 벤치마크 |
| ITINERA | 2024.02 | EMNLP 2024 Industry | ✅ | ✗ |
| LLM-Modulo | 2024.05 | arXiv | ✗ | ✅ |
| ChinaTravel | 2024.12 | **ICLR 2026** | ✅ | ✅ (DSL) |
| Formal Verification (Hao et al.) | 2025 | **NAACL 2025** | ✅ | ✅ (SMT solver) |
| Personal Travel Solver | 2025 | **ACL 2025** | ✅ | ✅ (numerical solver) |
| TP-RAG / EvoRAG | 2025.04 | **EMNLP 2025 Main** | ✅ | △ (진화적 개선) |
| **ATLAS** | 2025.09 | arXiv / OpenReview | ✅ | ✅ (critique 루프) |
| Iti-Validator | 2025.10 | arXiv | ✗ | ✅ |
| Replan, Repair, or Edit? | 2026.09 | arXiv | ✗ | ✅ (비교 연구) |

---

## 2. 핵심 논문 — ATLAS

**ATLAS: Constraints-Aware Multi-Agent Collaboration for Real-World Travel Planning**
Jihye Choi, Jinsung Yoon, Jiefeng Chen, Somesh Jha, Tomas Pfister (Google Cloud AI Research + UW-Madison, 2025.09)
https://arxiv.org/abs/2509.25586 · https://openreview.net/pdf?id=mIYGiBf9Pm

### 무엇을 했나

일정 생성과 제약 위반 수리를 하나의 멀티에이전트 프레임워크 안에 넣었다. 세 축으로 구성된다.

1. **Dynamic constraint management** — 대화가 진행되며 추가·변경되는 제약을 명시적으로 추적한다.
   명시적 제약뿐 아니라 암묵적 제약, 실행 중 변하는 제약까지 대상으로 삼는다.
2. **Iterative plan critique** — 생성된 일정을 비평해 위반을 찾아내고 그 내용을 되먹여 다시 생성한다.
3. **Adaptive interleaved search** — 검색과 계획을 분리하지 않고 번갈아 수행한다.

**결과**

- TravelPlanner 벤치마크: pass rate 23.3% → 44.4%
- 실시간 정보 검색 + 멀티턴 피드백이 있는 실제 환경: **84%** (ReAct 59%, 단일 에이전트 27%)

저자들은 실환경 travel planning에서 정량적 성과를 보인 최초 연구라고 주장한다.

### 우리 프로젝트와의 관계

ATLAS의 세 축이 우리 백엔드 구조와 거의 일대일로 대응한다.

| ATLAS | SeoulFit |
|---|---|
| dynamic constraint management | LangGraph `TravelState` + 멀티턴 intake (한 번에 하나씩 슬롯 채우기) |
| iterative plan critique | `critic_repair.py`, `guardrail_gate.py` |
| adaptive interleaved search | `retrieve_node` → `plan_node` 사이 TourAPI·ODsay·Google Places 실시간 호출 |
| 실환경 평가 (라이브 정보 + 멀티턴) | 우리 평가 환경 그대로 |

특히 두 번째 실험 설정 — 정적 데이터셋이 아니라 **살아있는 API와 멀티턴 대화가 있는 환경** — 이
우리가 TravelPlanner식 정적 평가를 쓰지 않는 이유를 그대로 설명해준다.
ATLAS가 없었다면 생성 논문 한 편과 검증 논문 한 편을 따로 인용해야 했는데, 이 한 편으로 대체된다.

**차이점(= 우리 기여 지점)**: ATLAS의 critique는 범용 제약을 다룬다.
우리 critic은 한국 공공데이터에서 나온 실제 제약을 검사한다 — TourAPI 영업시간(휴무일 체크),
ODsay 대중교통 실이동시간, 식사 슬롯(`meal_slots.py`), 일자별 방문 개수 상한.
또 ATLAS는 여행 **전** 계획 단계에서 끝나지만, 우리는 여행 **중** 재최적화까지 간다 (아래 5절).

---

## 3. 생성 쪽에서 참고할 두 편

### TP-RAG / EvoRAG — 우리 anchor course 구조의 직접 근거

**TP-RAG: Benchmarking Retrieval-Augmented LLM Agents for Spatiotemporal-Aware Travel Planning**
Ni et al., EMNLP 2025 Main · https://arxiv.org/abs/2504.08694 · https://aclanthology.org/2025.emnlp-main.626/

실제 여행기에서 추출한 **동선(trajectory) 자체를 검색해** LLM에 넣는 방식을 벤치마크로 만들고,
EvoRAG라는 방법도 함께 제안했다. 데이터는 실제 쿼리 2,348건, 정밀 주석 POI 85,575개,
고품질 참조 동선 18,784개.

핵심 발견 두 가지:
- 참조 동선을 넣으면 **공간 효율(spatial efficiency)과 POI 타당성(POI rationality)이 유의미하게 올라간다**
- 그런데 참조들끼리 서로 충돌하고 노이즈가 섞여 있어서, 그냥 넣는 것만으로는 부족하다

EvoRAG는 계획 후보 집단을 세대에 걸쳐 진화시키며 이 충돌을 해소한다.

**우리와의 관계**: 우리가 FAISS에 넣고 `select_anchors`로 뽑는 것이 개별 POI가 아니라
**완성된 추천 코스**다. 이건 정확히 TP-RAG가 말하는 reference trajectory 검색이다.
"왜 POI 단위가 아니라 코스 단위로 검색하는가"에 대한 답이 이 논문의 첫 번째 발견이고,
여러 코스를 섞을 때 생기는 모순(중복 장소, 엉킨 동선)이 두 번째 발견과 같은 문제다.

단, EvoRAG의 개선 방식은 명시적 critic 없이 집단을 진화시키는 search 기반이라
우리 규칙 기반 `critic_repair.py`와는 경로가 다르다. 생성·검색 쪽 근거로만 쓴다.

### ITINERA — 생성 단계의 역할 분리

**ITINERA: Integrating Spatial Optimization with Large Language Models for Open-domain Urban Itinerary Planning**
Tang et al., EMNLP 2024 Industry Track · https://arxiv.org/abs/2402.07204

"홍대에서 조용한 카페 위주로 반나절" 같은 자유 서술형 요청으로 도시 내 도보 일정을 만든다.
① 요청을 조건 단위로 분해 → ② POI DB에서 후보 선별 → ③ **cluster-aware spatial optimization**으로
지리적 군집 기준 순서 결정 → ④ LLM이 최종 서술 생성.

주장은 역할 분리다. **장소 선택권과 순서 결정권을 LLM에게 주지 말 것** —
선별은 DB에, 순서는 공간 최적화에 맡기고 LLM은 서술만 한다.

**우리와의 관계**: 요청 지역(홍대·성수 등)을 전부 커버하도록 강제하는 로직과
`DAY_PLAN_REGION_ORDER` 지역 순서 결정이 ③에 해당한다.
후보 코스와 Google Places에 없는 POI를 제거하는 규칙도 같은 문제의식이다.
다만 ITINERA는 반나절~하루 단일 경로이고, 우리는 다일차 + 식사 + 영업시간까지 다룬다.

---

## 4. 검증·수리 이론의 출발점

**Robust Planning with LLM-Modulo Framework: Case Study in Travel Planning**
Gundawar, Verma, Guan, Valmeekam, Bhambri, Kambhampati (2024.05) · https://arxiv.org/abs/2405.20625

전제는 **LLM은 자기 계획의 오류를 스스로 검증하지 못한다**는 것.
그래서 LLM을 생성기로만 쓰고, 정답성은 바깥의 **외부 critic 묶음**이 책임진다.
계획이 나오면 각 critic이 제약 위반을 판정하고, 통과 못 하면 위반 내용을 프롬프트에 넣어 재생성시킨다.

결과: Chain-of-Thought·ReAct·Reflexion은 사실상 0%에 그친 반면,
이 구조는 GPT-4-Turbo 기준 baseline 대비 **4.6배**, GPT-3.5-Turbo는 0% → 5%.

**우리와의 관계**: 우리가 LLM 자기검증(self-critique) 대신 파이썬 검증 코드를 둔 설계의 근거다.
`critic_repair.py`의 각 검사 — 휴무일, 식사 슬롯, 일자별 상한 — 이 각각 하나의 critic에 해당한다.
"왜 LLM에게 스스로 고치라고 하지 않았나"라는 질문에 대한 답이 이 논문의 수치다.

---

## 5. 여행 중 수리(on-trip)에 관한 별도 근거

**Replan, Repair, or Edit? A Unified Empirical Evaluation of Travel Agents for Itinerary Revision under Resource Disruptions**
Yuan et al. (2026.09) · https://arxiv.org/abs/2609.19654

일정이 깨졌을 때 고치는 세 가지 방식을 같은 조건에서 비교했다 —
전면 재계획(LLM-Z3), 고전적 plan repair(IPyHOPPER), LLM 기반 국소 수정(iTIMO).
상황은 항공편 취소·숙소 불가·**관광지 휴업**, 단일 disruption 500건 + 복합 disruption 200건.

결과:
- 복합 disruption은 LLM-Z3(Gemini)가 성공률 최고
- 단일 disruption은 IPyHOPPER가 거의 동등하면서 **기존 일정을 훨씬 많이 보존**
- 수리 방식이 전면 재계획보다 편집 횟수가 적음
- 비용: LLM 방식은 토큰 소모, IPyHOPPER는 LLM 추론 비용 0

**우리와의 관계**: 우리가 전체 일정을 다시 생성하지 않고 문제 지점만 교체하는 설계
(swap candidates, 재최적화)의 직접 근거다. "기존 일정 보존"이 사용자 경험상 중요한 이유와,
단일 문제 상황에서는 국소 수정이 맞다는 실증이 여기 있다.
관광지 휴업이 disruption 유형에 들어있다는 점에서 우리 closure check와도 맞닿는다.

---

## 6. 연구 흐름이 어떻게 발전했나

```
2014~2022   TTDP / Orienteering Problem — 조합최적화 시대
            POI 집합에서 시간창·영업시간·이동시간 제약 하에 최적 경로를 푼다.
            강점: 해의 타당성이 보장됨.  약점: 자유 서술형 요청을 못 받는다.
                ↓
2024.02     TravelPlanner (ICML 2024)
            LLM에게 통째로 맡기면 성공률 1% 미만(원 논문 GPT-4-Turbo 기준).
            "LLM은 긴 호흡의 제약 만족 계획을 못 짠다"를 수치로 못 박은 논문.
            이후 모든 후속 연구의 공통 시험대가 된다.
                ↓
2024.02     ITINERA — 생성 안에서 역할을 나눈다
            선별은 DB, 순서는 공간 최적화, 서술만 LLM.
                ↓
2024.05     LLM-Modulo — 검증을 LLM 바깥으로 빼낸다
            외부 critic이 판정하고 되먹인다. 4.6배.
            → 이 시점부터 "생성기 LLM + 외부 검증기" 구도가 표준이 된다.
                ↓
2024.12 ~   검증기를 무엇으로 만들 것인가로 갈라진다
2025        · ChinaTravel (ICLR 2026): DSL 기반 제약 검증, neuro-symbolic.
              사람 참가자 1,154명 쿼리에서 제약 만족률 37.0%, 순수 신경망 대비 10배
            · Hao et al. (NAACL 2025): 자연어를 SMT로 번역해 solver로 품.
              TravelPlanner 93.9% (o1-preview 10%). 불가능하면 unsatisfiable core로
              실패 이유와 수정 제안 제시
            · Personal Travel Solver (ACL 2025): LLM + 수치 solver, 선호까지 반영
                ↓
2025.04     TP-RAG / EvoRAG (EMNLP 2025) — 검색 대상을 POI에서 동선으로 올린다
            실제 여행기 동선을 참조로 넣으니 공간 효율과 POI 타당성이 올라감
                ↓
2025.09     ATLAS — 정적 벤치마크에서 실환경으로
            라이브 검색 + 멀티턴 + critique 루프. 실환경 84%.
            평가 기준 자체가 "정적 데이터셋 pass rate"에서 "실제 정보로 되는가"로 이동
                ↓
2025.10 ~   수리가 세분화된다
2026        · Iti-Validator: 생성은 남에게 맡기고 검증·교정만 전문화(가드레일)
            · TripPulse: 리뷰 10만건으로 정성적 요소(쾌적함·혼잡도)까지 반영
            · Replan/Repair/Edit: "전면 재계획 vs 국소 수리" 자체를 실험으로 비교
              → 관심사가 계획 생성에서 **계획 유지·보수**로 넘어가는 중
```

**큰 줄기 세 가지**

1. **검증의 외부화** — LLM에게 검증을 맡기는 시도는 실패했고, 외부 검증기(critic/solver/DSL)로 수렴했다.
   우리가 파이썬 검사 코드를 둔 것은 이 흐름 위에 있다.
2. **평가 환경의 현실화** — 정적 벤치마크 pass rate → 라이브 API·멀티턴 환경 성공률.
   우리 셋업(공공데이터 실시간 호출)이 현재 프론티어와 같은 방향이다.
3. **관심사의 이동** — "어떻게 잘 만들 것인가"에서 "깨졌을 때 어떻게 최소 편집으로 고칠 것인가"로.
   우리 on-trip 재최적화가 여기 해당한다.

---

## 7. SeoulFit의 위치

| 축 | 선행 연구 | SeoulFit |
|---|---|---|
| 생성 | TP-RAG(동선 검색), ITINERA(공간 최적화) | 추천 코스 anchor 검색 + 지역 커버리지 강제 |
| 검증 | LLM-Modulo(범용 critic), ChinaTravel(DSL), Hao et al.(SMT) | 한국 공공데이터 기반 규칙 critic (영업시간·이동시간·식사·상한) |
| 실환경 | ATLAS | 동일 (TourAPI·ODsay·E-Gen 실시간) |
| 여행 중 | Replan/Repair/Edit | swap 후보 국소 교체 |
| 그 외 | — | 랜드마크 인식(Gemini Vision), 응급실·여권분실 등 on-trip 지원 |

**빈틈**: 위 논문 중 어느 것도 (a) 실제 국가 공공데이터 제약을 critic으로 쓰고
(b) 계획 단계를 넘어 여행 중 실행까지 다루지 않는다.
생성 계열은 계획 수립에서 끝나고, TTDP 계열은 최적화에서 끝난다.

---

## 부록 — 판단 보류한 논문

- **DynamoTrip: Self-Healing Multi-Agent LLM Framework** — 문제 정의(constraint amnesia,
  entity hallucination)와 위반 슬롯만 겨냥해 재생성하는 방식이 우리와 매우 가깝지만,
  ResearchGate에만 있고 저자·게재처가 확인되지 않는다. 참고만 하고 인용은 보류.
