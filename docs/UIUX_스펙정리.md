# 애드지니 UI/UX 스펙 정리

> 최종 정리일: **2026-08-28**
> 기준: 최신 팀 결정과 현재 `main` 코드, 최근 머지 PR을 함께 확인한다. UI/UX·기획은 최신 날짜의 결정을 우선하고, 실제 구현 상태는 현재 코드를 우선한다.
> 주의: 기획과 현재 구현이 다르면 **“기획상 A / 현재 구현 B”**로 구분한다. 이번 정리에서는 2026-08-28 기준 최신 `main`과 최근 머지 PR을 재검증해 기존의 오래된 `미구현`·`확인 필요` 표기를 갱신했다.

---

## 0. 상태 표기

| 상태 | 의미 |
| --- | --- |
| **확정** | 팀 또는 PM이 최종 결정한 기획·계약 |
| **구현 완료** | 최신 작업 기록상 코드 반영과 정적 검증이 끝난 상태 |
| **부분 구현** | 코드가 있으나 실서버/E2E 검증 또는 일부 연동이 남은 상태 |
| **미구현** | 확정됐지만 코드 반영 전인 상태 |
| **논의 중** | 방향이나 세부 정책이 확정되지 않은 상태 |
| **보류** | 1차 범위에서 제외했거나 추후 고도화 대상으로 넘긴 상태 |
| **폐기** | 과거에 검토했으나 최신 결정으로 사용하지 않는 상태 |

---

## 1. 서비스 컨셉과 범위

### 1-1. 서비스 컨셉 — 확정

- 애드지니는 소상공인을 위한 **광고 문구 및 포스터 자동 생성 서비스**다.
- 핵심 차별점은 단순히 예쁜 문구가 아니라 **광고 규제 위험을 검사한 문구**를 제공하는 것이다.
- 표시광고법·식품표시광고법·화장품법 등의 금지·주의 표현을 검사하며, 결과는 `block`과 `warn`으로 구분한다.
- 모델 품질을 응답 속도보다 우선한다.
- 생성형 AI 결과물은 이미지 내부 워터마크와 화면의 “AI 생성 콘텐츠” 고지로 표시한다.
- 브랜드명은 **애드지니**, 주요 색상은 보라·파랑 계열이며 핑크는 제한적인 포인트 색상으로 사용한다.

### 1-2. 지원 업종 — 확정

| 유형 | 업종 | 입력 이미지 |
| --- | --- | --- |
| product | 푸드(`food`), 뷰티(`beauty`), 굿즈(`goods`) | 제품 사진 필수 |
| service | 학원(`academy`), 체육관·도장(`sports`) | 사진 없이 진행 |

- product는 2026-08-14 결정부터 **img2img 고정**이다. “사진 없이 제품형 진행”은 지원하지 않는다.
- service는 공간·장면을 생성하는 text2img 흐름이며 현재 1:1 AI 배경만 지원한다.
- K-컬처 정체성 강화는 **보류**다.

### 1-3. 담당 범위 — 확정

| 파트 | 담당 |
| --- | --- |
| 문구 생성, 규제 검증, 챗봇 질문·선택지 | 김도혁 |
| 포스터 생성, 제품 합성, 업스케일, 문구 삽입, 크롭, 이미지 내 AI 표기 | 황지우 |
| 화면 구성, API 연동, 결과 표시, 시안 선택, 편집, 다운로드 | 김소원 |
| 서빙 인프라 | 하태진 |
| PM | 정진우 |

---

## 2. 최신 전체 사용자 플로우

### 2-1. 공통 진입

```text
홈
→ 새로 만들기
→ 0단계: 제품형 / 서비스형 선택(프론트 고정 질문)
→ 업종 및 용도 선택
→ 정보 수집
→ 문구 시안 생성·규제 검증
→ 배경 방식 선택
→ 이미지 초안 3장 생성
→ 초안 1장 선택
→ 문구 위치·크기·서체 조정
→ 고품질화
→ 최종 결과 다운로드
```

### 2-2. product 흐름 — 확정

1. `business_type=product` 선택
2. 업종 선택: 푸드 / 뷰티 / 굿즈
3. 용도 선택: SNS(1:1) / 배너(3:1) / 상세페이지(3:4)
4. 제품 사진 필수 업로드
5. Vision 모델이 제품을 인식하고 사용자가 **[맞아요] / [수정할게요] / 재업로드**로 제품 정보를 확정
6. 제품 확정 후 같은 사진 단계 안에서 **배경 참고 이미지(선택)**를 업로드하거나 **배경 없이 진행** 선택
7. 배경 참고 이미지가 있으면 별도 Background Vision으로 `background_context`를 분석
8. 톤, 강조포인트, 필요 시 사실값 후속질문 1개, 추가 요청 입력
9. 문구 3개 생성 및 규제 검증
10. 지원 매트릭스 안에서 AI 또는 심플 배경 선택
11. 초안 생성 → 선택 → 문구 편집 → 고품질화 → 다운로드

업로드 안내 문구:

> 최대한 깨끗한 배경(단색)에 제품이 1개만 나오도록 찍어주세요.

배경 참고 이미지 안내:

> 원하는 배경 분위기가 있다면 참고 이미지를 올려주세요.

- 제품 사진과 배경 참고 이미지는 **역할이 다른 별도 입력**으로 관리한다.
- 배경 참고 이미지는 제품 Vision 인식에 사용하지 않는다.
- 배경 참고 이미지 자체를 Poster API에 직접 추가 필드로 보내지는 않으며, 분석된 `background_context`가 이후 시각 프롬프트 구체화에 활용될 수 있다.

### 2-3. service 흐름 — 확정

1. `business_type=service` 선택
2. 업종 선택: 학원 / 체육관·도장
3. 용도는 SNS(1:1)만 제공
4. 사진 업로드 단계는 표시하지 않음
5. 서비스 정보, 톤, 강조포인트, 필요 시 사실값 후속질문 1개, 추가 요청 입력
6. 문구 생성·검증 후 AI 배경으로 진행

서비스 업종 선택 화면에는 “업종은 계속 추가될 예정이에요”와 같은 짧은 안내를 제공한다.

### 2-4. 챗봇 단계 — 2026-08-21 확정 / 2026-08-28 구현 상태 갱신

- 0단계 질문은 프론트에서 고정 제공하며 현재 문구는 **“어떤 광고를 만들어 드릴까요?”**다.
- 이후 챗봇은 `business_type`을 `spec`에 포함해 stateless 방식으로 호출한다.
- 전체 단계 수는 **product 7단계 / service 6단계**를 유지한다.
- product의 사진 업로드·Vision·배경 참고 선택은 **4/7 안의 sub-flow**로 처리하고 별도 진행률 단계를 추가하지 않는다.
- 마지막 구간은 **톤 → 강조포인트 → 필요 시 조건부 후속질문 최대 1개 → 추가요청** 순서다.
- 조건부 후속질문은 별도 step이 아니라 **강조포인트 단계의 서브질문**이다.
  - product: 후속질문이 떠도 6/7 유지
  - service: 후속질문이 떠도 5/6 유지
- 강조포인트를 복수 선택하면 사실 확인이 필요한 항목 중 우선순위가 가장 높은 1개만 묻는다.
  - 가격·할인 등 숫자 사실값 > 위치·거리·영업시간 등 위치/시간 사실값
- 사실값 트리거가 없으면 후속질문 없이 바로 추가요청으로 이동한다.
- 후속질문과 추가요청 모두 **건너뛰기**를 지원한다.
- 추가요청은 기존 프리셋 칩 없이 **한 줄 자유입력**으로 받는다.
- 질문 렌더링은 서버의 `input_type`, 입력 제한은 `max_length`, 규제 UX는 `regulation`을 기준으로 처리한다.
- **2026-08-28 현재 구현:** PR #104가 `main`에 반영되어 위 FE 연동이 구현 완료됐다.
- **2026-08-28 현재 구현:** product Vision 인식·확정/수정/재업로드 분기, 선택 배경의 Background Vision, service 고정 흐름도 현재 `main`에 구현되어 있다.

### 2-5. 챗봇 자유입력 규제 UX — 2026-08-21 확정

- `/suggest/options`의 `input_type`을 UI 렌더링 기준으로 사용한다.
  - `select`: 기존 선택 칩 UI 유지
  - `text`: 한 줄 자유입력 UI 표시
- `max_length`는 `text` 입력에 적용한다. 2026-08-21 구현값은 사실값 후속질문 30자, 추가요청 40자다. 서버가 내려주는 값을 최종 기준으로 삼아 FE에서 글자 수 표시와 제출 제한을 제공한다.
- 후속질문과 추가요청의 자유입력은 제출 즉시 규제 검사 결과를 처리한다.
  - `regulation.severity === "block"`: 저장·다음 진행을 차단하고 사유/플래그와 `suggestion_text`를 안내한 뒤 재입력받는다.
  - `regulation.severity === "warn"`: 경고를 표시하되 저장·진행은 허용한다.
  - `regulation === null`: 별도 경고 없이 정상 진행한다.
- 사용자가 확정한 사실값만 `spec.highlight_fact`에 `blocktype`(`token`/`extra`)으로 태깅해 저장하고 향후 `allowed_facts` 입력 경로로 사용한다. Planner나 카피가 근거 없는 가격·할인율·위치·시간을 만들어내는 근거로 사용해서는 안 된다.
- **2026-08-28 구현 완료:** FE는 `input_type="text"`, `max_length`, `regulation` 응답을 실제 UI에 연결했고, `block` 재입력 / `warn` 진행 허용 / 스킵 및 진행률 유지까지 구현했다. mock 규제 기준도 실제 백엔드 규칙과 맞추는 방향으로 정리됐다.

---

## 3. 비율과 배경 지원 매트릭스 — 확정

2026-08-20 기준 지원 범위는 다음과 같다.

| 유형 | 비율 | AI 배경 | 심플 배경 |
| --- | --- | --- | --- |
| product | 1:1 | 지원 | 지원 |
| product | 3:1 | 지원 | 지원 |
| product | 3:4 | 미지원 | 지원, 심플로 직행 |
| service | 1:1 | 지원, AI로 직행 | 미지원 |
| service | 3:1 | 미지원 | 미지원 |
| service | 3:4 | 미지원 | 미지원 |

UI 처리 원칙:

- product 3:4에서는 AI 선택을 거친 뒤 경고하는 대신 **심플 배경 설정으로 바로 이동**한다.
- service 1:1에서는 배경 종류 선택 화면을 거치지 않고 **AI 생성으로 바로 이동**한다.
- 지원하지 않는 service 비율은 용도 선택지 자체에서 노출하지 않는다.
- “AI 비정사각 전체 미지원”은 구식 정보다. product 3:1 AI는 지원한다.

---

## 4. 배경 선택 UI

### 4-1. AI / 심플 첫 선택 화면 — 2026-08-20 확정·구현 완료

- 기존 세로형 카드, 선형 아이콘, 둥근 모서리, 보라색 강조 스타일을 유지한다.
- 카드 안 예시 썸네일을 이전보다 크게 표시하고 카드 높이도 함께 키운다.
- 심플 배경 대표 이미지는 애드지니의 블루·퍼플 계열을 연하게 낮춘 **파스텔 블루→퍼플 그라데이션**을 사용한다.
- 대표 이미지는 UI 예시일 뿐, 실제 추천 `bg_colors` 로직과 연결하지 않는다.
- 지원 매트릭스에 따라 선택 화면 자체가 생략될 수 있다.

### 4-2. 심플 배경 설정 — 2026-08-20 확정·구현 완료

심플 배경을 고른 뒤 별도 phase를 여러 번 이동하지 않고, **한 화면의 세로형 progressive disclosure**로 설정한다.

```text
배경 형태: 단색 / 그라데이션
        ↓
색상 방식: 알아서 추천 / 직접 선택
        ↓ 직접 선택일 때만 펼침
색상 선택 영역
```

- 처음부터 모든 옵션을 펼쳐 놓지 않는다.
- 단색 / 그라데이션 선택 후 알아서 추천 / 직접 선택을 고른다.
- 직접 선택일 때만 같은 화면 아래쪽에 색상 선택 영역이 확장된다.
- 단색 직접 선택은 HEX 1개, 그라데이션 직접 선택은 HEX 2개를 사용한다.
- 그라데이션 방향은 현재 `diagonal`이다.
- 과거의 “형태 선택 → 추천 방식 선택 → 색상 선택” 별도 화면·phase 구조는 **폐기**됐다.

### 4-3. 심플 배경 API 전달 규칙 — 2026-08-20 확정

| 선택 | 요청 규칙 |
| --- | --- |
| 알아서 추천 | `bg_colors` 생략 |
| 단색 직접 선택 | `background_mode: "solid"`, `bg_colors: [HEX 1개]` |
| 그라데이션 직접 선택 | `background_mode: "gradient"`, `bg_colors: [HEX 2개]`, `gradient_direction: "diagonal"` |

category 전달 규칙:

- product의 `food | beauty | goods`는 `/generate/drafts`의 `category`로 전달한다.
- service의 `academy | sports`는 포스터 API category 계약에 없는 값이므로 전달하지 않는다.
- 알아서 추천에서는 product category를 활용해 포스터 서버가 기본 색상·팔레트를 정할 수 있다.
- Design Planner는 아직 실제 연동 전이므로 추천 결과를 Design Planner가 산출한다고 표현하지 않는다.

### 4-4. Design Planner Core — 2026-08-28 production 미연동

- **기획상:** 기존 Design Planner Core는 `CreativeBrief → RenderSpec → RenderPlan`처럼 전체 디자인 결정을 구조화하는 계층이다.
- **현재 구현:** Core 자체는 여전히 production의 `/generate/drafts`·`/generate/refine` 흐름에 연결되어 있지 않다.
- 따라서 현재 서비스가 Core의 grid/zone/typography/palette 결정을 받아 포스터를 생성한다고 표현하면 안 된다.
- 기존 사용자 UX인 **시안 생성 → 사용자 시안 선택 → 문구 위치·크기·서체 편집 → refine** 구조는 그대로 유지한다.
- visual style(실사/애니메이션/일러스트 등)을 별도 사용자 선택 UI로 제공하는 기능은 여전히 확정·구현된 기능이 아니다.

### 4-5. 이미지 생성용 Visual Prompt 보조 경로 — 2026-08-28 구현 완료

Design Planner Core와 별개로, 사용자 입력을 이미지 모델이 이해하기 쉬운 영어 시각 지시로 구체화하는 **경량 Visual Prompt 경로**가 production 흐름에 연결됐다.

- `POST /generate/visual-prompt`가 챗봇의 완성된 `spec`을 읽어 시각 정보를 구체화한다.
- `tone`, `keywords`, `request`, 업종 정보와 사용 가능한 `background_context`를 바탕으로 배경·조명·색감·분위기·구성 등의 영어 시각 프롬프트를 만든다.
- 챗봇 완료 시 문구 생성과 Visual Prompt 생성을 **병렬(`Promise.all`)**로 호출한다.
- Visual Prompt는 한 제작 흐름에서 1회 생성해 `spec.visual_prompt`로 보관하고, drafts와 refine이 같은 값을 재사용한다.
- Visual Prompt 생성이 실패하면 기존 `buildPrompt()` 조합으로 fallback해 포스터 제작 흐름 자체는 막지 않는다.
- 이 기능은 **Design Planner Core의 production 연동을 의미하지 않는다.** 현재 구현 범위는 이미지 생성용 프롬프트 보조다.

---

## 5. 화면별 상세

### 화면 -1 — 홈 — 구현 완료

- 좌측 고정 사이드바: 로고, 새로 만들기, 오늘의 광고 규제 한 줄, AI 생성 사전 고지
- 메인: “오늘은 어떤 광고를 만들어볼까요?”와 예시 결과 카드
- 최근 작업 목록은 저장소·DB가 필요한 기능이므로 1차에서 제외한다.

### 화면 A — 챗봇 — 구현 완료

- business type에 맞춰 product와 service 흐름을 분기한다.
- product 용도는 SNS / 배너 / 상세페이지, service 용도는 SNS만 노출한다.
- product는 **7단계**, service는 **6단계** 진행률을 사용한다.
- product 사진은 필수이며 “없음” 선택지를 제공하지 않는다.
- Vision 인식 결과는 자동 확정하지 않고 **[맞아요] / [수정할게요] / 재업로드** 흐름을 제공한다.
- 제품 확정 뒤 같은 4/7 단계에서 배경 참고 이미지(선택)를 별도로 받고, 업로드하지 않을 경우 **배경 없이 진행**할 수 있다.
- service는 사진 업로드 UI를 표시하지 않는다.
- 톤과 강조포인트 선택 UI를 유지한다.
- 강조포인트 뒤 서버가 `input_type: "text"`인 조건부 후속질문을 반환하면 같은 강조포인트 단계에서 한 줄 입력과 건너뛰기를 표시한다.
- 후속질문 노출 전후로 진행률은 증가하지 않는다.
- 추가요청은 프리셋 없이 한 줄 자유입력, 서버 `max_length`, 건너뛰기를 사용한다.
- `regulation.severity`가 `block`이면 같은 질문에서 재입력 전 진행을 막고, `warn`이면 안내 후 진행을 허용한다.
- 재시도 시 기존 사용자 답변 말풍선이 중복되지 않도록 처리되어 있다.
- **2026-08-28 기준:** 위 신규 필드 및 조건부 후속질문 FE 연결은 PR #104 머지로 구현 완료됐으며, 현재 `main`에서도 확인된다.

### 화면 B — 문구 선택·규제 검증 — 구현 완료

- 문구 시안 3개 중 하나를 선택한다.
- `block`은 선택·진행 불가, `warn`은 경고를 유지하되 진행 가능하다.
- 사용자가 수정한 문구는 `/validate/copy`로 다시 검사한다.
- 규제 사유와 가능한 경우 대체 표현을 함께 보여준다.
- 문구는 프론트에서 임의로 자르지 않는다. 서버 축약, `over_limit`, 후처리 자동 줄바꿈으로 처리한다.
- LLM 하이브리드 재검증은 인수인계 문서상 브랜치별 상태가 달라 **현재 배포 코드 확인 필요**다.

### 화면 C — 배경 선택 및 초안 선택 — 구현 완료·주요 실서버 경로 검증 완료

- 지원 매트릭스에 따라 AI / 심플을 선택하거나 해당 경로로 직행한다.
- 심플 배경 설정은 2026-08-20 한 화면 progressive disclosure 방식을 사용한다.
- 초안은 3장 고정으로 표시한다.
- draft 이미지의 순수 base64에는 화면 표시 시에만 data URI prefix를 붙인다.
- 재생성·실패 재시도 UI를 제공한다.
- product drafts에는 `category: food | beauty | goods`를 전달하고 service에는 poster category를 전달하지 않는다.
- product/service 구분은 `subject_kind`로 명시해 service가 product baseline을 타지 않도록 한다.
- 챗봇 완료 시 생성된 `visual_prompt`가 있으면 이를 drafts prompt로 사용하고, 없으면 기존 조립 prompt로 fallback한다.
- 실제 서버에서 product 및 service 대표 경로의 `subject_kind` 전달과 이미지 생성이 검증됐다.

### 화면 D — 문구 편집 — 구현 완료 / 2026-08-28 서버 정합성 개선 완료

- 선택한 시안 위에서 문구 위치를 드래그하고 CSS로 즉시 미리보기 한다.
- 좌표는 0~1 중심 기준이며 `text.align: "center"`를 명시한다.
- 폰트 크기는 **작게 / 보통 / 크게** 3단계 프리셋이다.
- headline과 sub에 공통으로 적용되는 서체 1개를 선택한다.
- `text.style`은 `plain`으로 명시한다.
- 서버 호출은 “완성하기” 시점에 한 번 수행하며 중복 제출을 막는 lock이 있다.
- FE 미리보기는 backend 최종 렌더링과 동일한 TTF 5종을 `@font-face`로 로드한다.
  - Pretendard Regular
  - NanumMyeongjo Bold
  - GmarketSans Medium
  - Galmuri11
  - NanumPen
- Vite dev 환경에서도 `poster_model/assets/fonts`를 읽을 수 있도록 serving allow 설정이 반영되어 있다.
- 외곽선은 기존 `text-shadow` 대신 서버 stroke에 가까운 `-webkit-text-stroke` + `paint-order: stroke fill` 구조를 사용한다.
- headline/sub 크기와 stroke는 서버와 동일하게 **캔버스 짧은 변(`min(width, height)`)** 기준으로 계산한다.
- 줄바꿈은 과거 글자 수 고정 방식이 아니라 **실제 렌더 폭** 기준으로 계산한다.
  - 사용 가능 폭 = 캔버스 폭 − 2 × (짧은 변 × `TEXT_MARGIN_RATIO`)
  - 폰트 크기 = 짧은 변 × size preset
  - 폭을 넘을 때 어절 단위로 줄바꿈하고, 한 어절이 너무 길 때만 글자 단위로 분리
- 선택한 웹폰트가 처음 사용되는 시점의 fallback 측정 오류를 막기 위해 `document.fonts.load()` 완료 후 다시 `measureText()`한다.
- **3:1 배너는 별도 size preset**을 사용한다.
  - small: headline `0.085`, sub `0.050`
  - medium: headline `0.122`, sub `0.072`
  - large: headline `0.160`, sub `0.094`
- 1:1과 3:4는 기존 size preset을 유지한다.
- 2026-08-28 기준 서체 5종 × 크기 3단계 × 비율 3종 × 문구 길이 3종 교차 검증에서 미리보기 줄 수와 실제 서버 출력 줄 수가 일치했고, 3:1도 시안 선택부터 최종 생성까지 정합성을 확인했다.
- 브라우저와 PIL의 래스터라이저 차이 때문에 안티앨리어싱·모서리까지 픽셀 단위로 완전히 같다고 보장하지는 않는다.
- **현재 구현상 주의:** real refine 정합성은 맞췄지만 mock refine의 내부 텍스트 합성은 아직 기존 글자 수 기준 줄바꿈을 사용하므로, mock 최종 이미지의 줄바꿈은 real 서버 결과와 다를 수 있다.

### 화면 E — 최종 결과 — 구현 완료

- 고품질 결과, 확정 문구, 규제 상태, “AI 생성 콘텐츠” 캡션을 표시한다.
- 다운로드와 처음부터 다시 만들기를 제공한다.
- 최종 화면의 사이즈 토글은 없다.
- “같은 배경으로 다른 비율 만들기” 버튼은 없다.

### 로딩 화면 — 구현 완료

- 초안 생성과 고품질화를 서로 다른 로딩 단계로 보여준다.
- 체크리스트는 실제 서버 진행률이 아닌 **예상 시간 기반 연출**이다.
- 초안 로딩 중 스켈레톤 카드 3장은 표시하지 않는다.
- 실시간 polling/SSE 진행률은 보류다.

---

## 6. API 및 상태 전달 원칙

### 6-1. 공통

- 문구와 포스터 API는 stateless이므로 프론트가 누적 `spec`과 필요한 원본 데이터를 보관해 다음 요청에 전달한다.
- mock과 real 응답 차이는 API 어댑터에서 흡수하고 화면 컴포넌트 계약은 유지한다.
- 내부 디버깅 메시지를 사용자에게 그대로 노출하지 않는다.

### 6-2. `/suggest/options` — 2026-08-21 계약 / FE 구현 완료

- 요청은 사용자의 답변, 현재 step, 누적 `spec`을 전달하는 stateless 구조다.
- FE는 다음 응답 필드를 실제 렌더링 기준으로 사용한다.

| 필드 | 값/형태 | FE 처리 |
| --- | --- | --- |
| `input_type` | `select` 또는 `text` | select는 칩, text는 한 줄 입력 |
| `max_length` | 정수 또는 `null` | text 입력의 글자 수 표시·제출 제한 |
| `regulation` | `{severity, flags, suggestion_text}` 또는 `null` | block/warn/null UX 분기 |

- 후속질문은 강조포인트와 같은 step/진행률을 유지하며 `total_steps`를 늘리지 않는다.
- 후속질문과 추가요청은 스킵할 수 있다.
- `regulation`이 `block`이면 같은 질문에서 재입력을 받고 다음 단계로 진행하지 않는다.
- `warn`이면 경고를 표시하지만 답변 저장과 다음 진행은 허용한다.
- **2026-08-28 현재 구현:** PR #104 머지로 FE 연동 완료.

### 6-3. `/generate/drafts`

- `aspect_ratio`는 `1:1 | 3:1 | 3:4` 중 지원 매트릭스에 맞는 값을 보낸다.
- AI는 `background_mode: "ai"`를 사용한다.
- 심플 단색·그라데이션은 각각 `solid`·`gradient`를 사용한다.
- 알아서 추천이면 `bg_colors`를 보내지 않는다.
- product에만 `category: food | beauty | goods`를 보낸다.
- service의 `academy | sports`는 category로 보내지 않는다.
- `subject_kind`를 product/service에 맞게 명시한다.
- `visual_prompt`가 있으면 drafts prompt로 사용하고 없으면 기존 prompt builder로 fallback한다.
- product의 원본 사진은 refine까지 상태로 유지한다.

### 6-4. `/generate/refine`

- 선택한 draft의 원본 base64와 `background`를 그대로 전달한다.
- product는 `original_image`를 항상 전달한다.
- drafts와 동일한 Visual Prompt를 `prompt`로 재사용한다.
- product인 경우에만 `category: food | beauty | goods`를 전달하고 service의 `academy | sports`는 category로 보내지 않는다.
- `subject_kind`를 product/service에 맞게 전달한다.
- 중심 좌표와 `align: "center"`, `style: "plain"`, 선택한 `font_id`, headline/sub size를 명시한다.
- 이미지 내부 AI 고지는 후처리에서 적용한다.
- **2026-08-28 구현 완료:** PR #133에서 refine category 누락을 수정해 drafts/refine이 같은 category 판정 로직을 사용한다.

### 6-5. `/generate/visual-prompt` — 2026-08-28 구현 완료

- 챗봇이 완성한 `spec`을 읽어 이미지 생성에 사용할 영어 시각 프롬프트를 만든다.
- product/service 구분은 `subject_kind`로 전달한다.
- background Vision 결과인 `background_context`가 있으면 사용자가 명시하지 않은 축을 보완하는 데 활용할 수 있다.
- ChatFlow 완료 시 `/generate/copy`와 병렬 호출한다.
- 생성 결과는 `spec.visual_prompt`에 저장하고 drafts/refine에서 재사용한다.
- 호출 실패 시 기존 prompt builder로 fallback해 사용자 플로우는 계속 진행한다.

---

## 7. 엣지 케이스 및 예외 처리 — 2026-08-28 갱신

| 상황 | 최신 처리 | 상태 |
| --- | --- | --- |
| 문구에 `block` 존재 | 선택·진행 차단, 사유·대체 표현 제공, 수정 후 재검증 | 확정/구현 완료 |
| 문구에 `warn`만 존재 | 경고 배지 유지, 사용자는 진행 가능 | 확정/구현 완료 |
| 사실값 강조포인트가 없음 | 후속질문 없이 추가요청으로 이동 | 확정/구현 완료 |
| 사실값 강조포인트가 복수 | 가격·할인 등 숫자 사실값 > 위치·시간 순으로 최상위 1개만 질문 | 확정/구현 완료 |
| 후속질문 노출 | 강조포인트 서브질문으로 표시하고 진행률 유지 | 확정/구현 완료 |
| 후속질문 건너뛰기 | 사실값을 저장하지 않고 추가요청으로 이동 | 확정/구현 완료 |
| 자유입력 규제 `block` | 대체 표현 안내, 저장·진행 차단, 같은 자리에서 재입력 | 확정/구현 완료 |
| 자유입력 규제 `warn` | 경고 표시 후 저장·진행 허용 | 확정/구현 완료 |
| 자유입력 규제 `null` | 정상 저장·진행 | 확정/구현 완료 |
| 추가요청 | 프리셋 없이 한 줄 자유입력, `max_length` 적용, 스킵 가능 | 확정/구현 완료 |
| product에서 사진 없이 진행 시도 | 자동 text2img 전환하지 않고 업로드 단계에서 차단 | 확정 |
| Vision 인식 결과 확인 | 자동 확정하지 않고 맞아요/수정/재업로드 분기 | 확정/구현 완료 |
| 배경 참고 이미지 없음 | product 확정 후 같은 단계에서 배경 없이 진행 가능 | 확정/구현 완료 |
| 배경 참고 이미지 분석 실패/부적합 | `background_context`를 제외하고 제품 광고 흐름은 계속 진행 | 구현 완료 |
| service에서 사진 업로드 시도 | 업로드 단계 자체를 노출하지 않음 | 확정/구현 완료 |
| product 3:4 선택 | AI/심플 선택 화면 없이 심플 설정으로 직행 | 확정/구현 완료 |
| service 1:1 선택 | 배경 선택 화면 없이 AI로 직행 | 확정/구현 완료 |
| service 3:1·3:4 | 용도 선택지에서 미노출 | 확정/구현 완료 |
| 알아서 추천 | `bg_colors` 생략; product category만 전달 | 확정/구현 완료 |
| 직접 선택 + 단색 | HEX 1개만 전달 | 확정/구현 완료 |
| 직접 선택 + 그라데이션 | HEX 2개와 `diagonal` 방향 전달 | 확정/구현 완료 |
| product category 전달 | `food/beauty/goods` allowlist를 사용해 drafts/refine에 동일 기준 적용 | 구현 완료 |
| service category 값 전달 | `academy/sports`를 poster category로 보내지 않음 | 구현 완료 |
| service가 product 이미지처럼 생성됨 | `subject_kind: service`를 drafts/refine에 전달 | 구현 완료 |
| Visual Prompt 생성 실패 | 기존 `buildPrompt()`로 fallback해 제작 흐름 유지 | 구현 완료 |
| 이미지 생성 실패·타임아웃 | 단계별 재시도와 사용자 친화적 오류 제공 | 구현 완료 |
| 중복 요청 | ChatFlow ref guard, DraftSelect 요청 취소/가드, PosterEditor submit lock 등으로 방지 | 구현 완료 |
| 순수 base64 표시 | 렌더링할 때만 `data:image/png;base64,` 접두어 추가 | 확정/구현 완료 |
| refine category 누락 | product category를 refine까지 전달, service는 생략 | 구현 완료 |
| 3:1 미리보기 글자 크기 과대 | width가 아니라 캔버스 짧은 변 기준으로 계산 | 구현 완료 |
| 선택 폰트가 늦게 로드됨 | `document.fonts.load()` 후 실제 폰트로 다시 폭 측정 | 구현 완료 |
| 문구 줄바꿈 불일치(real) | 실제 렌더 폭 기준으로 계산해 서버와 맞춤 | 구현 완료 |
| 문구 줄바꿈 불일치(mock) | mock refine 내부 합성은 아직 글자 수 기준 | **현재 구현상 차이** |
| 문구가 이미지 밖으로 이탈 | 안전 여백, 서버 auto-fit·자동 줄바꿈 사용; 프론트 임의 절단 금지 | 확정/구현 완료 |
| 사용자 뒤로가기·이전 답변 수정 | 1차 스코프 제외 | 보류 |
| 로딩이 길어짐 | 초안/고품질화 두 단계를 구분하고 예상 시간 기반 상태 표시 | 확정/구현 완료 |
| 실제 진행률 요구 | 현재 API로는 불가; polling/SSE 별도 설계 필요 | 보류 |
| Design Planner Core 결과 기대 | Core는 production 미연동. 현재는 별도 Visual Prompt 보조 경로만 사용 | 미구현(Core) / 구현 완료(Visual Prompt) |
| visual style 선택 기대 | 사용자 선택 UI로 확정하지 않음 | 논의 중/미구현 |
| 같은 배경으로 다른 비율 요청 | 최종 화면에서 제공하지 않음 | 1차 제외/폐기된 UI |

### 과거 edge case 중 폐기·대체된 내용

- “제품 사진 없이 시작하면 text2img로 자동 전환” → product 사진 필수 / service 별도 흐름으로 대체.
- “사진 유무와 용도를 독립 선택해 미지원 조합이 생길 수 있음” → product와 service의 고정 지원 매트릭스로 대체.
- “3:4에서 AI를 준비 중으로 비활성 표시” → product 3:4는 심플로 직행하는 최신 UX로 대체.
- “service에서 flat 칩을 숨김” → service 1:1은 배경 선택 자체를 생략하고 AI로 직행하는 규칙으로 구체화.
- “심플 배경을 여러 화면에서 순차 선택” → 한 화면 progressive disclosure로 대체.
- “poster category에 모든 업종 전달” → product만 전달하고 service 값은 생략하는 규칙으로 정정.
- “강조포인트 다음에 곧바로 프리셋형 추가요청” → 필요 시 후속질문 최대 1개를 같은 강조포인트 단계에서 받은 뒤, 프리셋 없는 한 줄 추가요청으로 대체.
- “마지막 단계 여부로 자유입력 UI 추론” → 서버의 `input_type`을 직접 사용하는 계약으로 대체.
- “Design Planner Core가 포스터 레이아웃 전체를 production에서 결정” → 현재 production에는 연결하지 않고, 별도 Visual Prompt 보조 경로만 사용.
- “폰트 크기를 바꿔도 줄바꿈 지점 고정” → 서버와 미리보기 정합성을 위해 실제 렌더 폭과 현재 폰트 크기에 따라 재계산하는 방식으로 대체.

---

## 8. 보류·논의 중·미구현

| 항목 | 상태 | 비고 |
| --- | --- | --- |
| Design Planner Core production 연동 | 미구현 | 기존 drafts→편집→refine UX 유지. Visual Prompt 보조 경로와 구분 |
| visual style 변경 | 논의 중/미구현 | 실사/애니/일러스트 등 별도 사용자 선택 UI는 확정하지 않음 |
| 최근 작업 목록·이력 저장 | 보류 | 스토리지·DB·URL 필요 |
| 결과 공유 | 보류 | 저장·조회 인프라 필요 |
| 검색·필터 | 보류 | 이력 저장 이후 검토 |
| 같은 배경으로 다른 비율 만들기 | 보류 | flat 재합성, AI 크롭/outpainting이 각각 필요 |
| 챗봇 뒤로가기 | 보류 | spec 스냅샷과 이전 단계 재요청 설계 필요 |
| 실시간 생성 진행률 | 보류 | job API + polling/SSE 필요 |
| 문구 배경 `bar` UI | 보류 | 현재는 `plain` 고정 |
| K-컬처 브랜딩 강화 | 보류 | 고도화 단계에서 재논의 |
| 그라데이션 동일 색상 2개 허용 정책 | 논의 중 | 시각적으로 단색과 같아지는 경우 |
| 규제 LLM 하이브리드 배포 상태 | 확인 필요 | 이번 문서 최신화 범위에서 copy_model 배포 상태까지 별도 재검증하지 않음 |
| mock refine 줄바꿈 정합성 | 미구현 | PosterEditor/real 서버는 폭 기준, mock 합성은 기존 글자 수 기준 |

---

## 9. 변경 히스토리

### 2026-08-28 — 최신 기준

- 최신 `main`과 최근 머지 PR 기준으로 구현 상태를 재검증하고 문서의 오래된 `미구현`·`확인 필요` 표기를 갱신.
- PR #104 반영: 챗봇의 `input_type`, `max_length`, `regulation`, 조건부 사실값 후속질문, 스킵, product 7/service 6 진행률 유지 FE 연동을 **구현 완료**로 갱신.
- 현재 `main` 기준 product Vision 인식의 맞아요/수정/재업로드, 선택 배경 참고 이미지 및 Background Vision sub-flow 구현 상태 반영.
- PR #127 반영: Design Planner Core와 별개로 `/generate/visual-prompt` 기반 경량 Visual Prompt 보조 경로가 production에 연결됨. 문구 생성과 병렬 호출하고 drafts/refine에서 같은 prompt 재사용.
- PR #133 반영: `/generate/refine`에도 product category를 전달하고 service category는 생략하도록 수정. backend와 동일한 폰트 5종을 FE 미리보기에 연결.
- PR #135 반영: Vite dev에서도 실제 폰트가 로드되도록 serving 범위를 조정하고, 미리보기 외곽선을 서버 stroke에 가까운 방식으로 변경.
- PR #143 반영: 3:1에서 headline/sub/stroke가 과대 표시되던 문제를 해결하기 위해 FE도 서버와 동일한 **짧은 변 기준**으로 계산.
- PR #147 반영: 글자 수 고정 줄바꿈을 제거하고 **실제 렌더 폭 기준**으로 서버와 맞춤. 선택 폰트는 `document.fonts.load()` 완료 뒤 재측정. 3:1 전용 size preset 적용. PR #147은 2026-08-28 현재 `main`에 머지 완료.
- 현재 구현상 mock refine 텍스트 합성은 아직 기존 글자 수 기준 줄바꿈을 사용하므로 real 서버와 mock의 최종 줄바꿈은 차이가 날 수 있음을 명시.

### 2026-08-21 — 유효한 선행 결정

- 톤과 강조포인트를 유지하고 마지막 구간을 **톤 → 강조포인트 → 조건부 후속질문 최대 1개 → 추가요청**으로 확정.
- 후속질문은 강조포인트 단계의 서브질문으로 처리해 product 7단계/service 6단계와 `total_steps`를 유지.
- 복수 강조포인트는 가격·할인 등 숫자 사실값 > 위치·시간 순으로 최상위 1개만 질문하며 통합 질문은 사용하지 않음.
- 후속질문과 추가요청에 건너뛰기 지원.
- 추가요청 프리셋을 삭제하고 `max_length`가 적용되는 한 줄 자유입력으로 변경.
- `/suggest/options`의 `input_type(select|text)`, `max_length`, `regulation` 필드 기반 FE 처리와 block/warn/null UX 확정.
- 백엔드 후속질문 계약과 오탐 방지 수정은 PR #100 머지로 구현 완료, FE 연결은 미구현으로 구분.
- Design Planner Core는 production 미연동 상태이며, 기존 drafts→사용자 편집→refine UX 유지 방향을 확인.
- Planner는 추천·보조 역할로 재정의 논의 중이며, 초기 목표를 tone/keywords/request를 material/lighting/texture/mood/composition 등 이미지 생성 지시로 구체화하는 베이직한 기능으로 정리.
- visual style은 시안 선택 이후 적용 가능 여부를 기술 검증한 뒤 UI/UX 위치를 결정하기로 하고 현재는 논의 중·미구현으로 유지.

### 2026-08-20 — 유효한 선행 결정

- 심플 배경 설정을 별도 단계식 화면에서 **한 화면 progressive disclosure**로 변경.
- 단색/그라데이션 → 알아서 추천/직접 선택 → 직접 선택 시에만 색상 영역 확장으로 확정.
- 알아서 추천 시 `bg_colors` 생략.
- product category(`food | beauty | goods`)를 `/generate/drafts`에 전달.
- service category(`academy | sports`)는 poster category 계약에 없으므로 전달하지 않음.
- 배경 지원 매트릭스 확정: product 1:1·3:1은 AI/심플, product 3:4는 심플 직행, service 1:1은 AI 직행.
- AI/심플 첫 선택 카드의 썸네일과 카드 높이를 확대.
- 심플 대표 이미지를 파스텔 블루→퍼플 그라데이션으로 변경.
- Design Planner는 실제 연동 전 상태를 유지.

### 2026-08-14 — 유효한 선행 결정

- product는 제품 사진 필수(img2img 고정).
- 제품명 텍스트 질문을 사진 업로드·Vision 인식으로 대체.
- 용도 선택지를 business type별로 고정하고 “기타” 제거.
- product는 SNS/배너/상세페이지, service는 SNS만 제공.

### 2026-08-13 이전 — 변경 이력

- product 사진 선택형 및 사진 없음 자동 text2img 경로는 이후 결정으로 폐기.
- 최종 화면 사이즈 토글과 같은 배경 다른 비율 버튼은 제거.
- 로딩은 실제 진행률이 아니라 예상 시간 기반 연출로 유지.
- 문구 편집 좌표는 center 기준, `align: center`, `style: plain`으로 정리.

---

## 10. 최종 확인 체크리스트

### 코드·구현 기준 확인 완료

- [x] product 1:1·3:1에서 AI와 심플이 모두 지원되는 구조를 유지한다.
- [x] product 3:4는 심플 배경 설정으로 바로 이동한다.
- [x] service 1:1은 AI 생성으로 바로 이동한다.
- [x] service에는 3:1·3:4 용도를 노출하지 않는다.
- [x] 심플 설정은 한 화면에서 조건부로 펼쳐진다.
- [x] 알아서 추천 요청에는 `bg_colors`를 보내지 않는다.
- [x] 직접 선택 단색은 HEX 1개, 그라데이션은 HEX 2개와 `diagonal` 방향을 보낸다.
- [x] product drafts/refine에는 product category를 전달하고 service에는 poster category를 보내지 않는다.
- [x] product/service를 `subject_kind`로 poster API에 전달한다.
- [x] product 진행률은 7단계, service 진행률은 6단계를 유지한다.
- [x] 조건부 후속질문은 강조포인트와 같은 진행률에서 표시된다.
- [x] 후속질문과 추가요청 모두 건너뛰기를 지원한다.
- [x] 추가요청은 프리셋 없이 한 줄 입력이며 `max_length`를 적용한다.
- [x] `input_type: "text"` 자유입력과 `regulation` block/warn UX가 FE에 연결되어 있다.
- [x] 제품 Vision 결과는 자동 확정하지 않고 맞아요/수정/재업로드 분기를 제공한다.
- [x] 제품 확정 뒤 선택 배경 참고 이미지 또는 배경 없이 진행을 지원한다.
- [x] Visual Prompt는 챗봇 완료 시 1회 생성해 drafts/refine에서 재사용하며 실패 시 fallback한다.
- [x] FE 미리보기에서 backend와 동일한 폰트 5종을 사용한다.
- [x] headline/sub/stroke는 캔버스 짧은 변 기준으로 계산한다.
- [x] 3:1은 별도 size preset을 사용한다.
- [x] 줄바꿈은 실제 렌더 폭과 선택 폰트 기준으로 계산한다.
- [x] 선택 웹폰트가 늦게 로드될 때도 로드 완료 후 다시 측정한다.
- [x] PR #147 기준 3:1 미리보기와 실제 서버 최종 결과의 문구 크기·줄바꿈 정합성을 확인했다.
- [x] Design Planner Core와 현재 구현된 Visual Prompt 보조 경로를 구분해 설명한다.

### 최종 시연 전 별도 확인

- [ ] 최신 `main`으로 최종 전체 E2E를 한 번 더 수행한다.
- [ ] product 1:1 / 3:1 / 3:4 대표 시나리오를 최종 서버 환경에서 확인한다.
- [ ] service 1:1 대표 시나리오를 최종 서버 환경에서 확인한다.
- [ ] 문구 생성 → 시안 생성 → 편집 → refine → 다운로드까지 발표용 흐름이 끊기지 않는지 확인한다.
- [ ] 실제 배포/시연 환경에서 디버깅용 임시 코드가 없는지 최종 확인한다.
- [ ] mock 시연을 사용할 경우 mock refine의 글자 수 기준 줄바꿈과 real 결과 차이를 인지한다.
