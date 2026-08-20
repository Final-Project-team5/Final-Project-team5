# Design Planner (`poster_model/dynamic/`)

포스터의 **디자인 결정**을 담당하는 레이어다. `pipeline/` 은 건드리지 않는다.

---

## 1. 왜 필요한가

지금 production 은 "제품 사진 + 고정 밴드 레이아웃" 으로 1:1 포스터를 만든다.
레이아웃이 코드에 박혀 있어서, 다른 구성을 원하면 Renderer 를 고쳐야 한다.

`dynamic/` 은 그 경로를 그대로 두고 옆에 층을 하나 더 만든다. **레이아웃을
데이터로 표현**해서, 다른 포스터를 만들 때 코드가 아니라 값이 바뀌게 한다.

---

## 2. 전체 흐름

```
CreativeBrief          사실
    ↓  Design Planner (LLM)          디자인 의사결정 전체
RenderSpec             디자인 결정
    ↓  validate                      스키마 + 교차 필드. 통과 못하면 여기서 끝
    ↓  Resolver (grid·palette·fonts·text·background·geometry)
RenderPlan             px
    ↓  Renderer
픽셀  +  RenderEvidence  실제로 합성한 것
    ↓  Safety Validator
SafetyResult           관측값 (가림 · 대비 · 넘침)
    ↓  실패 시 SafetyFeedback → Planner 가 **다시 설계**
```

`SystemPolicy` 는 이 흐름의 옆에 있다 — 어느 한 층에 속하지 않고
Validator 와 Safety 가 함께 참조하는 최소 기준이다.

### 각 자료구조의 책임 경계

| | 담는 것 | **담지 않는 것** |
|---|---|---|
| `CreativeBrief` | 사실. 업종·제품·카피·참고 정보·선호색 | 디자인 결정 (grid·palette·motif 필드가 아예 없다) · 원본 픽셀 |
| `RenderSpec` | 디자인 결정. 무엇을 어디에 어떤 관계로 | px 좌표 · 실제 RGB · 폰트 파일 · 프롬프트 문자열 |
| `RenderPlan` | 확정된 px 과 RGB. Renderer 가 그대로 쓰는 값 | 결정의 근거 (그건 Spec 에 있다) |
| `RenderEvidence` | Renderer 가 **실제로** 합성한 영역·마스크 | 판정 (통과/실패는 Safety 가 정한다) |
| `SystemPolicy` | 최소 안전 기준값 | 디자인 취향 · 미적 판단 |

**이렇게 나눈 이유는 하나다.** Renderer 가 "spot 이니까 이 색" 이라고 정하면
그건 디자인 판단이고, 그러면 디자인을 바꿀 때마다 Renderer 를 고쳐야 한다.
색과 좌표는 Plan 에서 끝난다. Renderer 는 받은 값을 그린다.

`RenderEvidence` 가 따로 있는 이유도 같다. Safety 가 "이만큼 가려졌다" 를
판단하려면 **Spec 이 의도한 것**이 아니라 **Renderer 가 실제로 그린 것**을
재야 한다. 둘이 어긋나면 그 자체가 버그이고, 증거를 따로 남겨야 그걸 볼 수
있다.

각 층 사이는 **거부로 연결된다.** 값이 모자라면 다음 층이 임의 기본값을
만들지 않고 그 자리에서 실패한다. 조용한 fallback 이 하나 생기면 "왜 이 색이
나왔는가" 를 아무도 설명할 수 없게 된다.

---

## 3. 모듈 지도

### 계약 · 자료구조

| 파일 | 역할 |
|---|---|
| `spec.py` | `RenderSpec` 자료구조와 필드 제약. **무엇을 결정할 수 있는가**의 정의 |
| `brief.py` | `CreativeBrief` — 사실 입력. `content_ref` 해석 |
| `errors.py` | 거부 사유. 코드마다 어디서 왜 났는지가 붙는다 |
| `policy.py` | `SystemPolicy` — 최소 안전 기준 |
| `color_roles.py` | 색 역할(`bg·ink·spot·emphasis`)의 **단일 출처** |

### 검증

| 파일 | 역할 |
|---|---|
| `validate.py` | 스키마 검증 + 교차 필드 규칙. **`CROSS_FIELD_RULES` 의 단일 출처** |
| `diversity.py` | 후보들이 "정말 다른 디자인" 인지 Spec 수준에서 측정 |

### 해석 (Spec → Plan)

| 파일 | 역할 |
|---|---|
| `grid.py` | 비율·밀도 → 열 수와 baseline |
| `palette.py` | 역할 → 실제 RGB. `product·brand·preferred·fixed` 네 갈래 |
| `fonts.py` | 서체 해석과 문자열 폭 측정 |
| `text.py` | 줄바꿈 |
| `geometry.py` | `ProductGeometry` — 제품 마스크에서 나온 사실 |
| `background.py` | 배경 의미 → `ResolvedBackground` |
| `assets.py` | 픽셀 asset 입력 계약 |
| `plan.py` | 위를 모아 `RenderPlan`(px) 을 만든다 |

### 실행 · 관측

| 파일 | 역할 |
|---|---|
| `render.py` | `RenderPlan` → 픽셀 |
| `evidence.py` | Renderer 가 **실제로 합성한 것**을 그대로 남긴다 |
| `safety.py` | 가림·대비·넘침 **측정**. 고치지 않는다 |

### Planner

| 파일 | 역할 |
|---|---|
| `planner_io.py` | 서비스 입력 ↔ `CreativeBrief` 경계, capability 표 |
| `planner_prompt.py` | 스키마 투영 · 프롬프트 구성 · strict 호환 검사 |
| `planner.py` | LLM 호출 (OpenAI SDK 는 지연 import) |
| `__init__.py` | 공개 API |

### 이름이 비슷해서 헷갈리는 쌍

| 쌍 | 가르는 질문 |
|---|---|
| `spec.py` ↔ `validate.py` | spec 은 **무엇을 쓸 수 있는가**(필드·타입·enum), validate 는 **그 조합이 말이 되는가**(필드 사이 관계). `mode=generated` 인데 `visual_style` 이 없다 — 타입은 맞으므로 spec 은 통과시키고 validate 가 거부한다 |
| `grid.py` ↔ `plan.py` | grid 는 **좌표계**를 만든다(열 수·baseline). plan 은 그 좌표계 **위에 요소를 앉힌다**. grid 는 카피를 모르고, plan 은 열 수를 스스로 정하지 않는다 |
| `plan.py` ↔ `render.py` | plan 이 끝나면 **모든 값이 확정**돼 있다. render 는 판단하지 않고 그린다. render 에 `if` 로 색이나 위치를 고르는 코드가 생기면 경계가 무너진 것이다 |
| `palette.py` ↔ `color_roles.py` | color_roles 는 **표**다(역할 이름, 명도/채도 매핑). palette 는 그 표에 seed 를 넣어 **실제 RGB 를 계산**한다. 값이 바뀌면 color_roles 를, 계산 방식이 바뀌면 palette 를 고친다 |
| `planner_io.py` ↔ `planner_prompt.py` ↔ `planner.py` | io 는 **경계**(서비스 입력↔Brief, capability 표), prompt 는 **스키마 투영과 문자열 구성**, planner 는 **호출과 파싱**. LLM SDK 를 아는 것은 `planner.py` 하나뿐이고 나머지 둘은 SDK 를 모른다 |

---

## 4. 지켜지는 계약 5가지

### 4-1. Planner 출력은 **실행 가능한 subset** 이다

`RenderSpec` 스키마 전체를 그대로 LLM 에 주지 않는다. 지금 Renderer 가 실제로
처리할 수 있는 것만 투영한다.

```
*.row_anchor      정수 row index 제거 — fixture/debug 전용 문법이다
canvas.ratio      현재 supported_ratios 만
layers            제거 — canonical stack 은 시스템 불변식이다
palette.roles     Renderer 가 색을 만들 줄 아는 이름만
typography        family × weight 를 실제 렌더 가능한 5조합으로
```

투영 결과는 OpenAI structured output `strict:true` 와 호환된다.
`strict_preflight()` 가 API 호출 없이 offline 으로 검사한다.

### 4-2. Validator 가 아는 규칙은 Planner 에게도 알려준다

JSON Schema 로는 조건부 관계를 표현할 수 없다 (`if/then/else` 미지원). 그래서
교차 필드 규칙을 `capabilities` 에 실어 보낸다. **단일 출처는 규칙을 실제로
강제하는 `validate.py`** 다 — 프롬프트에 값을 손으로 복사해 두지 않는다.

실제 LLM 실행에서 나온 검증 실패의 대부분은 모델 잘못이 아니라 **규칙을 안
알려준 것**이었다. 이 통로가 그 격차를 닫는다.

### 4-3. 색은 네 갈래가 **독립**이다

```
product     product_signals.palette (HEX) 를 seed 로
brand       brand_palette 를 그대로
preferred   brief.preferred_color 를 seed 로
fixed       fixed_values 를 그대로   (Planner 경로에서는 제외)
```

어느 것을 쓸지는 Planner 가 고른다. **고른 갈래의 입력이 없으면 다른 갈래로
넘어가지 않고 거부한다.** `preferred_color` 가 있다고 `source=preferred` 가
강제되지도 않는다 — 선호이지 지시가 아니다.

### 4-4. Safety 는 관측만 한다

가림·대비·여백을 재고 그 사실만 돌려준다. 자동 보정도, 자동 retry 도 없다.
무엇을 바꿀지는 Planner 가 다시 정한다.

```
measured 182756 / threshold 0
detail   "무엇의 교집합을 어떻게 쟀는가"     ← observation-only
```

`detail` 이 처방을 담지 않는다는 것은 문구 blacklist 가 아니라 **레지스트리
테스트**로 잠근다.

또 하나 — `passed=True` 여도 **검사하지 못한 항목을 함께 싣는다**
(`unsupported_checks` · `deferred_checks`). "통과" 를 "모든 안전성이 증명됐다"
로 읽지 않게 하려는 것이다.

### 4-5. production 과 분리된다

```
dynamic/ → pipeline · api  import        0건
```

테스트가 `sys.modules` 에 `pipeline` 이 없다는 것까지 확인한다. 실수로 의존이
생기면 그 자리에서 깨진다.

---

## 5. 팀 파이프라인 연동

`copy_model` 이 만든 `spec` dict 를 그대로 넣지 않는다. adapter 경계에서
정규화한다 (`planner_io.service_request_from_team_spec`).

```
spec["product"]                      →  product_identity.confirmed_product
spec["product_context"]
    .confirmation_source             →  provenance (디자인 판단에서 제외)
    .recognition_status              →  ✗ 가져오지 않는다 (확정 이전 상태)
    .next_action                     →  ✗ 가져오지 않는다 (flow control)
spec["aspect_ratio"]                 →  output_ratio
spec["background_context"]           →  background_context (확인 필드 6개)
```

가져오지 않는 항목과 그 이유는 `planner_io.TEAM_SPEC_EXCLUDED` 에 적혀 있다.

### `background_context` 는 확인된 필드만 받는다

`copy_model/background.py:BackgroundContext` 에서 코드로 확인한 6개다.

```
palette · lighting · texture · mood · composition · usable
```

★ **`palette` 는 자연어다** (`"웜 베이지"`). `product_signals.palette` 는
HEX 다. 두 값은 같은 자리에 넣을 수 없다 — `resolve_palette()` 는 HEX 를
파싱하므로 자연어를 주면 거부한다. `background_context` 는 Planner 가 읽는
**참고 서술**이지 색 계산 입력이 아니다.

★ **`usable=false` 면 한 필드도 프롬프트에 싣지 않는다.** 못 쓴다고 표시한
분석에서 일부만 골라 쓰면 그 판단을 우리가 뒤집는 것이 된다.

6개 밖의 key 는 `unconfirmed` 에 보존만 하고 내보내지 않는다. 이름이 같아
보인다고 의미가 같다고 보지 않는다.

---

## 6. 테스트

### 어느 계층을 보는가

| 테스트 | 검증 계층 | 깨지면 의심할 곳 |
|---|---|---|
| `test_renderspec_schema` | Spec 계약 · 교차 필드 | `spec.py` · `validate.py` |
| `test_grid_resolver` | 좌표계 결정성 | `grid.py` |
| `test_render_plan` | Spec → Plan (px·anchor) | `plan.py` · `fonts.py` · `text.py` |
| `test_renderer` | Plan → 픽셀. 같은 Plan 은 같은 픽셀 | `render.py` |
| `test_fixture_diversity` | 다른 Spec → 구조적으로 다른 포스터 | `render.py` · `palette.py` · `color_roles.py` |
| `test_safety` | 픽셀 → 관측값 | `safety.py` · `evidence.py` |
| `test_planner_contract` | Brief ↔ Spec 경계, 후보 다양성 | `planner_io.py` · `diversity.py` |
| `test_planner_llm` | 프롬프트·스키마 투영·유출 차단 (FakeLLM) | `planner_prompt.py` · `planner.py` |
| `test_schema_05_paths` | 팀 spec → Brief adapter, 5경로 결정성 | `planner_io.py` · `brief.py` · `palette.py` |

`fixtures_renderspec.py` 는 테스트가 아니라 네 개 고정 Spec(A·B·C·D)을 주는
공용 모듈이다. 여러 테스트가 같은 Spec 을 쓰므로 차이가 전부 코드에서 온다.

### 실행

```bash
cd poster_model
python tests/test_renderspec_schema.py
python tests/test_grid_resolver.py
python tests/test_render_plan.py
python tests/test_renderer.py
python tests/test_fixture_diversity.py
python tests/test_safety.py
python tests/test_planner_contract.py
python tests/test_planner_llm.py
python tests/test_schema_05_paths.py
```

**LLM 호출과 네트워크 호출이 없다.** `test_planner_llm` 은 FakeLLM 으로 계약만
확인한다.

테스트는 저장소 안에 산출물을 남기지 않는다. 렌더 결과를 눈으로 보고 싶으면
경로를 지정한다.

```bash
DYNAMIC_TEST_OUT=/tmp/poster python tests/test_renderer.py
```

`tests/_assets/` 의 제품 마스크·컷아웃은 **실제 세그멘테이션 결과**다. 합성
사각형으로 바꾸면 가림·대비 측정이 실제 제품 실루엣이 아닌 값을 재게 되어
Safety 테스트의 의미가 약해진다.

---

## 7. 구현 상태

### 이번 PR 에 들어 있는 것 — 코드로 동작하고 테스트로 잠겨 있다

```
CreativeBrief → RenderSpec → RenderPlan → 픽셀 → RenderEvidence → SafetyResult
    전 구간이 동작한다.  fixture Spec 으로 실제 포스터가 나온다.

RenderSpec 0.5 스키마 + 교차 필드 검증
Grid · Palette · Fonts · Text · Background · Geometry resolver
Renderer (1:1) · RenderEvidence
Safety Validator (관측 전용) · SafetyFeedback
Planner 프롬프트 구성 · strict 스키마 투영 · 후보 파싱과 거부
후보 다양성 측정
팀 spec → CreativeBrief adapter
```

### 아직 production 에 연결되지 않은 것

**`dynamic/` 은 `api.py` 어디에서도 호출되지 않는다.** 이번 PR 은 계층을
추가할 뿐 기존 요청 경로를 바꾸지 않는다. `/generate` 는 지금까지처럼
`pipeline/` 만 탄다.

```
api.py → dynamic/          호출 0건       ← 다음 단계에서 연결
dynamic/ → pipeline · api  import 0건     ← 계속 이렇게 유지한다
```

연결에 필요한 것: 요청 → `ServiceRequest` 변환 지점, Planner 실행 위치
(동기/비동기), 실패 시 기존 경로로 되돌릴지 여부. 셋 다 아직 정하지 않았다.

### 기능 자체가 미구현이거나 보류인 것

| 항목 | 상태 |
|---|---|
| `background.mode = "provided_asset"` (사용자 배경 사진 보존) | 보류 — MVP 는 참고 분석만 |
| Asset Preparation 계층 | 보류 — 위와 함께 |
| capability API (`/capabilities`) | 미구현 — 프론트가 지원 조합을 미리 알 수 있게 |
| preview / select / refine 통합 계약 | 열림 — 3시안 생성 비용 포함 |
| `/vision/product` production wiring | 계약은 닫힘, 연결은 미구현 |
| 1:1 외 비율 | Renderer `supported_ratios` 에 달렸다 |
| 자동 retry · Safety 자동 보정 | **설계상 넣지 않는다** |

### 프론트와 아직 안 맞는 곳

프론트는 배경을 2값(`ai` · `flat`)으로 보내는데 서버·`RenderSpec` 은
3값(`solid`/`flat` · `gradient` · `generated`)이다. 현재 프론트 코드에
`flat → gradient` 임시 매핑이 주석으로 적혀 있다. **이것을 최종 계약으로
굳히지 않았다** — capability API 로 풀 자리다.
