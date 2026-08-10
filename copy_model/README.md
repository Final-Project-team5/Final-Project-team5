# 문구 모델 (광고 카피 생성 API)

담당: 김도혁 — 문구 모델 (서빙 보조)

GPT-5.4 Mini/Nano API 기반 광고 문구(headline/sub) 생성 모듈.
생성된 `headline`/`sub`는 프론트를 거쳐 포스터 모델 `/generate/refine`의
`text` 필드로 그대로 전달됨.

## 실행

```bash
pip install -r requirements.txt
cp .env.example .env   # API 키 입력 (커밋 금지!)

# 서버 실행 (포스터 모델과 포트 분리)
uvicorn copy_model.api:app --reload --port 8001

# API 키 없이 프론트 연동 테스트 (mock 모드)
COPY_MOCK=1 uvicorn copy_model.api:app --port 8001

# CLI 단독 테스트
COPY_MOCK=1 python test_local.py --category food --product "딸기 생크림 케이크"
```

## 프론트 연동 (CORS)

브라우저에서 직접 호출할 수 있도록 CORS가 설정되어 있습니다.
기본 허용 출처는 아래와 같아, 별도 설정 없이 바로 fetch/axios로 호출 가능합니다.

- `http://localhost:5173`, `http://127.0.0.1:5173` (Vite 개발 서버)
- `http://localhost:3000`, `http://127.0.0.1:3000`
- `http://localhost:4173`, `http://127.0.0.1:4173` (Vite preview)

다른 포트를 쓰시면 환경변수로 추가하시면 됩니다.

```bash
COPY_CORS_ORIGINS="http://localhost:5174,http://localhost:3000" uvicorn copy_model.api:app --port 8001
```

현재 허용 목록은 `GET /health` 응답의 `cors_origins`에서 확인할 수 있습니다.

```js
// 프론트 호출 예시
const res = await fetch("http://localhost:8001/suggest/options", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ message: "푸드" }),
});
const data = await res.json();
```

## API

### GET /health

서버 상태·설정 확인용. 연동 시 첫 호출로 사용하면 편합니다.
`mock` 필드로 현재 mock 모드 여부를, `limits`로 글자 수 제한을,
`cors_origins`로 허용된 출처를 확인할 수 있습니다.

### POST /generate/copy

요청:

```json
{
  "category": "food",
  "product": "딸기 생크림 케이크",
  "keywords": ["수제", "당일생산"],
  "tone": "warm",
  "request": "신메뉴 출시 강조",
  "num_candidates": 3
}
```

- `category`: `food` | `beauty` | `goods`
- `tone`: `warm`(감성) | `energetic`(발랄) | `luxury`(고급) | `simple`(간결)

응답:

```json
{
  "candidates": [
    {
      "id": "c1",
      "headline": "오늘 갓 구운 행복 한 조각",
      "sub": "매일 아침 매장에서 직접 굽는 수제 케이크",
      "headline_chars": 14,
      "sub_chars": 22,
      "over_limit": false,
      "regulation_flags": [],
      "safe": true
    }
  ],
  "meta": { "elapsed": 1.2, "model": "gpt-5.4-mini", "mock": false }
}
```

- `safe` — 시안별 규제 통과 여부. block 위반이 없으면 `true`.
  프론트는 `regulation_flags`를 순회하지 않고 이 값만 보고 사용 가능 여부를 판단할 수 있습니다.
  (warn만 있으면 `safe: true` — 근거가 있으면 쓸 수 있는 표현이므로 안내만 함)
- `regulation_flags` — 걸린 규제 표현 상세 (배지·대체 표현 안내용). block이 앞에 정렬됨
- `include_en: true` — 영어 현지화 문구 병행 생성 (직역 아닌 transcreation, 글로벌 타깃 고도화 옵션. **팀 합의 전 기본 OFF**)

### POST /suggest/options (챗봇 슬롯필링)

정해진 순서로 질문하며 광고 문구에 필요한 정보를 채워나감.
UI는 프론트 파트 담당, 이 엔드포인트는 LLM 로직만 제공.

**고정 플로우 (mode: "fixed", 기본값)** — PM진우님 제안안 반영

| 단계 | 질문 | 슬롯 | 복수선택 |
|---|---|---|---|
| 1 | 현재 운영하시는 업종은 어떤 것인가요? | category | - |
| 2 | 어떤 제품이나 가게를 홍보하시나요? | product | - |
| 3 | 원하시는 포스터의 느낌은 어떤 것인가요? | tone | - |
| 4 | 강조하고 싶은 점을 골라주세요 | keywords | ✅ |
| 5 | 추가로 반영했으면 하는 내용이 있으신가요? | request | - |

**최소 요청 — 실제로 필수인 필드는 `message` 하나입니다.**

```json
// 1단계 시작 (mode·step은 기본값으로 동작)
{ "message": "푸드" }

// 2단계 이후 — 응답의 next_step을 step에, 들고 있던 spec을 함께
{ "message": "떡볶이", "step": 2, "spec": { "category": "food" } }
```

| 필드 | 필수 | 설명 |
|---|---|---|
| `message` | ✅ | 사용자가 선택한 선택지 텍스트 또는 "기타"로 직접 입력한 문장 |
| `mode` | - | 기본값 `"fixed"` (고정 5단계). 메인 흐름은 생략 |
| `step` | - | 기본값 `1`. 응답의 `next_step`을 그대로 넣으면 됨 |
| `spec` | - | 지금까지 채워진 값. 서버가 상태를 저장하지 않으므로 프론트가 들고 매 요청에 전달 |
| `history` | - | `mode: "auto"`에서만 사용. fixed 모드에서는 `spec`이 상태를 대신하므로 불필요 |
| `target_slots` | - | 특정 항목만 물어볼 때만 사용 (아래 참고) |

전체 필드를 명시한 요청:

```json
{
  "message": "푸드",
  "mode": "fixed",
  "step": 1,
  "spec": {}
}
```

응답:

```json
{
  "spec": { "category": "food" },
  "done": false,
  "step": 1,
  "next_step": 2,
  "total_steps": 5,
  "question": "어떤 제품이나 가게를 홍보하시나요?",
  "options": ["떡볶이", "김밥", "분식 세트", "음료"],
  "allow_multiple": false,
  "confirm_message": "'푸드' 업종으로 설정했어요. 왼쪽 화면에서 확인해보세요!",
  "meta": { "elapsed": 1.1, "model": "gpt-5.4-mini" }
}
```

프론트 연동 가이드:

- `spec`은 프론트가 상태로 들고 있다가 다음 요청에 그대로 전달 (stateless — 포스터 모델과 동일 방식)
- `step` / `total_steps`로 진행률(1/5) 표시
- `options` 아래에 항상 **"기타(직접 입력)"** 칸을 노출 (자유 입력도 그대로 `message`로 보내면 됨)
- `allow_multiple: true`면 복수 선택 UI로 전환
- `spec.keywords` → 메인 화면 키워드 칩에 그대로 매핑
- `confirm_message` → 칩 자동 추가 + 하이라이트 연출과 함께 챗봇 말풍선으로 표시.
  슬롯 종류에 맞는 표현으로 내려감 (업종/제품 → "설정했어요·정했어요",
  느낌 → "분위기를 잡았어요", 강조점 → "키워드로 추가했어요").
  빈 문자열이면 표시 안 함 / 프론트 고정 문구를 쓰고 무시해도 무방
- `done: true`가 되면 `spec`을 그대로 `/generate/copy` 요청 바디로 사용
  → 이때 "제공해주신 정보를 바탕으로 제작 중입니다" 로딩 화면 진입

**특정 항목만 물어보기 (`target_slots`)** — 서브 패널 도우미 용도

메인 화면에서 이미 업종·제품을 고른 사용자가 "톤만 다시 추천해줘"처럼
일부 항목만 다시 정하고 싶을 때 사용. 지정한 항목만 채우고 `done: true`로 끝남.

```json
// 요청 — 톤만 물어보기
{
  "message": "활기찬 느낌",
  "step": 1,
  "target_slots": ["tone"],
  "spec": { "category": "food", "product": "떡볶이" }
}
// 응답 — total_steps가 1로 줄고 바로 완료
{
  "spec": { "category": "food", "product": "떡볶이", "tone": "energetic" },
  "done": true,
  "step": 1, "next_step": null, "total_steps": 1,
  "confirm_message": "'활기찬 분식집 느낌'으로 분위기를 잡았어요. 왼쪽 화면에서 확인해보세요!"
}
```

- `target_slots` 생략 → 전체 5단계 (메인 흐름)
- `target_slots: ["tone"]` → 톤만 (서브 패널 도우미)
- `target_slots: ["tone", "keywords"]` → 2단계 흐름 (원래 순서 유지)
- 이미 채워진 값은 `spec`으로 함께 보내면 선택지 생성에 맥락으로 반영됨

**자유 진행 (mode: "auto")** — LLM이 미수집 슬롯 중 다음 질문을 판단.
자유 대화 위주 흐름으로 갈 경우 사용. `history`에 대화 이력 전달.

## 시안 다양성 보장

시안 3개를 주는 이유는 **선택지 제공**인데, 서로 비슷하게 나오면 의미가 없습니다.
("오늘 갓 구운 빵 / 매일 갓 구운 빵 / 신선하게 구운 빵")

생성 후 시안끼리 유사도를 재서, 임계값을 넘는 시안만 **다른 방향으로 재생성**합니다.

```json
"meta": {
  "diversity_score": 1.0,        // 1.0에 가까울수록 서로 다름
  "max_pair_similarity": 0.0,    // 가장 비슷한 쌍의 유사도
  "diversity_retried": 0,        // 재생성 시도 횟수
  "diversity_ok": true           // 재생성 후에도 중복이 남으면 false
}
```

### 임계값 근거 (실측)

라벨링한 21쌍으로 유사도 분포를 측정해 임계값을 정했습니다.

| 구간 | 유사도 범위 |
|---|---|
| 서로 다른 시안 (10쌍) | 0.000 ~ 0.118 |
| **임계값** | **0.25** |
| 사실상 같은 시안 (8쌍) | 0.300 ~ 0.700 |

- 두 구간 사이 값이라 오탐(다른 시안을 중복으로 판정)·미탐 모두 0
- 애매한 쌍도 합리적으로 갈림
  - "촉촉함을 채우는" ↔ "건조함을 달래는" (0.231) → 통과 *(소구점이 다름)*
  - "매콤한 떡볶이" ↔ "얼큰한 떡볶이" (0.429) → 검출 *(사실상 같은 말)*
- 환경변수 `COPY_DIVERSITY_THRESHOLD`로 조정 가능

### 측정 방식과 한계

- **문자 bigram 자카드 유사도** — API 비용 0, 키 불필요
- 한국어는 조사·어미 변화가 많아 어절 단위 비교로는 "구운 빵"과 "구운빵"을 다르게 봅니다.
  문자 bigram이 이런 표기 차이에 강합니다.
- **한계**: 표면적 유사도라 "저렴한"과 "가성비 좋은"처럼 **표현은 다르지만 의미가 같은 경우는 잡지 못합니다.**
  의미 기반 판정이 필요하면 임베딩으로 확장할 수 있습니다 (API 키·비용 추가).
- 재생성은 기본 1회로 제한합니다 (응답 시간 보호). 재시도 후에도 중복이 남으면
  `diversity_ok: false`로 표시하고 그대로 내보냅니다.

> 위 측정은 실제 LLM 출력이 아니라 **수기로 작성한 라벨링 샘플** 기준입니다.
> API 키 수령 후 실제 생성 결과로 재측정해 임계값을 보정할 예정입니다.

## 글자 수 제한 (팀 합의사항 반영)

- headline **20자**, sub **30자** (공백 포함) — 지우님 요청 기준
- 프론트에서 자르지 않고 **생성 단계에서 보장**: 프롬프트 명시 + 초과 시 LLM 축약 재시도 1회
- 그래도 초과하면 `over_limit: true`로 표시 (포스터 쪽 자동 줄바꿈이 최종 안전망)
- 기준 변경 시 코드 수정 없이 환경변수(`COPY_HEADLINE_MAX`, `COPY_SUB_MAX`)로 조정

## 규제 필터링 (핵심 차별점)

3중 방어 구조:

1. **생성 프롬프트 내 금지 규칙** — 최상급·확정 표현, 의학적 효능 단정 등을 생성 단계에서 차단
2. **룰 기반 자동 검사** (비용 0) — 생성 결과마다 `regulation_flags` 자동 첨부.
   표시광고법 공통 + 식품표시광고법(푸드) + 화장품법(뷰티) 대표 금지/주의 표현 사전
3. **`POST /validate/copy`** — 사용자 수정 문구 재검증용. `use_llm: true`면
   LLM이 맥락상 위반까지 판단하고 안전한 대체 문구 제안

```json
// POST /validate/copy 요청
{ "category": "beauty", "headline": "여드름 없애는 앰플", "sub": "부작용 전혀 없음", "use_llm": false }
// 응답
{ "safe": false,
  "flags": [
    { "matched": "여드름 없애", "severity": "block",
      "reason": "화장품법 §13: 질환명 언급은 의약품 오인 광고",
      "suggestion": "'피부 진정에 도움을 주는'" },
    { "matched": "부작용 전혀 없", "severity": "block",
      "reason": "화장품법 §13: 안전성 단정·부작용 부재 단정 금지",
      "suggestion": "'순한 성분으로 만든'" }
  ] }
```

- `severity`: `block`(사용 불가 수준) / `warn`(맥락 확인 필요). block이 앞에 오도록 정렬됨
- `suggestion`: 대체 표현 예시 — 프론트에서 "이렇게 바꿔보세요" 안내에 사용 가능
- 프론트 처리 제안: block → 빨간 배지 + 대체 표현 안내, warn → 노란 배지만

### 룰 사전 현황 (`regulation_rules.py`)

| 카테고리 | 전체 | block | warn | 주요 근거 |
|---|---|---|---|---|
| food | 19 | 6 | 13 | 표시광고법, 식품표시광고법 §8, 건강기능식품법 §18, 식약처 고시 |
| beauty | 17 | 5 | 12 | 표시광고법, 화장품법 §13 |
| goods | 13 | 0 | 13 | 표시광고법, 상표법, 환경성 표시·광고 고시 |

주요 검출 사례:

- **푸드** — 질병 치료·예방("치료", "항암"), 체중 감량("다이어트 효과"), 기능성 표방("면역력 강화", "피로 회복"), 인증 없는 천연·유기농, 숙취해소
- **뷰티** — 의약품 오인("치료", "병원급"), 질환명("아토피", "여드름 없애기"), 기능성 초과("주름 제거", "보톡스 효과"), 안전성 단정("부작용 전혀 없음"), 의료인 추천
- **굿즈** — 타 브랜드 연상("명품급"), 그린워싱("친환경"), 라이선스("공식 굿즈"), 한정판·평생보증

> 본 룰은 데모용 1차 사전이며 법률 자문이 아닙니다. 실제 서비스 시 최신 고시·심의 기준 확인이 필요합니다.

## 평가 (eval/)

생성 품질을 수치로 측정하는 도구. 프로젝트 가이드의 "모델 성능 및 서비스 사용성 평가"에 대응.

### 규제 준수 지표 (`eval/metrics.py`)

키 없이 즉시 계산 가능한 지표:

- **violation_rate** — block 표현이 포함된 시안 비율 (낮을수록 좋음)
- **safe_rate** — block이 없는 시안 비율 (`1 - violation_rate`)
- **warn_rate** — warn 이상 플래그가 있는 시안 비율
- **length_ok_rate** — 글자수 제한을 지킨 시안 비율
- **avg_diversity** — 시안 세트의 평균 다양성

### 규제 규칙 A/B 실험 (`eval/run_regulation_ab.py`)

**가설**: LLM은 매력적인 카피를 만들도록 학습돼 있어, 규제 지침 없이 생성하면
규제 위반 표현이 더 많이 나온다.

**실험**: 같은 제품 세트에 대해
- A) 규제 지침을 뺀 프롬프트 (baseline)
- B) 규제 지침을 넣은 프롬프트 (우리 방식)

두 그룹의 위반율을 룰 검사로 비교합니다. (측정은 비용 0, 생성만 API 비용)

```bash
# 실제 실측 (API 키 필요)
OPENAI_API_KEY=sk-... python -m eval.run_regulation_ab --n 10

# 파이프라인 검증 (mock — 고정 샘플이라 A/B 차이 없음, 흐름 확인용)
COPY_MOCK=1 python -m eval.run_regulation_ab --n 3
```

> mock 모드는 고정 샘플이라 규칙 유무 차이가 나오지 않습니다.
> 실제 위반율 비교는 반드시 API 키로 실행해야 하며, 그 수치가
> "규제 필터링이 왜 필요한가"에 대한 실측 근거가 됩니다.

이 실험 설계는 프롬프트에 규제 지침을 넣을지 여부(`include_regulation`)만 다르게 두어,
같은 조건에서 규칙의 효과만 분리 측정하도록 했습니다.

## TODO

- [ ] API 키 수령 후 A/B 실험 실측 → 위반율 비교 데이터 확보
- [ ] 적합도·창의성 등 LLM 판단 지표 추가 (LLM-as-Judge)
- [ ] 규제 룰 사전 확충 + AI허브 법률 DB RAG 근거 제시 (고도화)
- [ ] 키워드 추출/추천 (챗봇 방향 팀 확정 후)
- [ ] AI 생성물 고지 문구 (AI 기본법 제31조) — 포스터/프론트 파트와 협의
