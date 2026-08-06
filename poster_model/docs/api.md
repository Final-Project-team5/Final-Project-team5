# 포스터 이미지 API 현황

이번 PR 기준 이미지 생성 API의 **구현된 것 / 아직 안 된 것**을 정리한 문서입니다.
프론트 연동 시 이 문서만 보고 현재 가능한 범위를 판단할 수 있게 하는 것이 목적입니다.

서버 실행:

```bash
uvicorn api:app --host 0.0.0.0 --port 8000
```

---

## 전체 흐름

```text
POST /generate/drafts   시안 여러 장 (가벼운 모델, 문구 없음)
        ↓ 사용자가 하나 선택
POST /generate/refine   고품질 렌더링 + 문구 합성 + AI 표시
```

문구 합성은 **refine 단계에만** 있습니다. draft는 배경·그림자·제품까지만 만듭니다.

서버는 상태를 저장하지 않습니다. draft 응답에 담겨 내려온 값(`background` 등)을
클라이언트가 refine 요청에 **그대로 되돌려 보내야** 같은 결과가 나옵니다.

---

## 현재 구현된 API

### 1. 문구 입력 (`text`)

| 필드 | 타입 | 기본값 | 설명 |
|---|---|---|---|
| `headline` | str | `""` | 큰 제목. `\n`으로 직접 줄바꿈 가능 |
| `sub` | str | `""` | 보조 문구 |
| `x`, `y` | float 0~1 | `None` | 문구 기준점 좌표(비율). 둘 다 주면 좌표 모드 |
| `position` | `top`\|`center`\|`bottom` | `top` | 하위 호환 폴백. `x`,`y`가 오면 무시 |
| `align` | `left`\|`center`\|`right` | `left` | 정렬. 좌표 모드에서는 `x`가 어느 지점인지도 결정 |
| `style` | `plain`\|`bar` | `bar` | `plain`=외곽선, `bar`=반투명 배경 박스 |
| `headline_size` | float 0~1 | `None` | 짧은 변 대비 폰트 비율. 생략 시 config 기본값 |
| `sub_size` | float 0~1 | `None` | 동일 |

**크기 권장 범위** (`pipeline/config.py`의 `TONE_PRESETS`):

| 톤 | headline_size | 비고 |
|---|---|---|
| `minimal_product` | 0.09 ~ 0.13 | 절제된 톤. 얇은 외곽선 + 짙은 단색 |
| `bold_promo` | 0.18 ~ 0.28 | 큰 타이포. 흰색 + 굵은 외곽선 |

**자동 맞춤**: 요청한 크기를 우선 쓰고, 지정 영역을 벗어날 때만 최소한으로 축소합니다.
줄바꿈은 **공백 기준 어절 단위**이며, 한 어절이 한 줄보다 길 때만 글자 단위로 쪼갭니다.

### 2. 배경 (`background_mode`)

draft 요청 필드입니다.

| 필드 | 값 | 기본값 |
|---|---|---|
| `background_mode` | `ai` \| `solid` \| `gradient` | `ai` |
| `bg_colors` | `["#RRGGBB", ...]` | `None` (카테고리 기본 팔레트) |
| `gradient_direction` | `vertical` \| `horizontal` \| `diagonal` | `None` |

- `ai`: diffusion으로 배경 생성. 느리지만 표현이 풍부합니다.
- `solid` / `gradient`: **diffusion을 완전히 생략**하고 PIL로만 배경을 칠합니다. 훨씬 빠릅니다.

draft 응답의 각 항목에 실제 적용된 `background`가 담겨 내려옵니다.
refine 요청에 그대로 넣어야 같은 배경이 재현됩니다.

### 3. 문구 레이어 순서 (`headline_z_order` / `sub_z_order`)

제품이 문구 일부를 자연스럽게 가리는 연출을 위한 필드입니다.

| 필드 | 값 | 기본값 |
|---|---|---|
| `headline_z_order` | `front` \| `behind` | `front` |
| `sub_z_order` | `front` \| `behind` | `front` |
| `sub_x`, `sub_y` | float 0~1 | `None` |

렌더링 순서는 항상 고정입니다.

```text
배경 → 그림자 → behind 문구 → 제품 합성 → front 문구 → AI 생성물 표시
```

**하위 호환**: 두 필드 모두 기본값이 `front`라, 이 필드를 보내지 않는 기존 요청은
지금까지와 완전히 동일한 코드 경로를 탑니다(`render_text` 1회 호출, 제품 재합성 없음).

**제약 (400으로 거부)**

1. `behind`는 `original_image`가 있는 경로에서만 지원됩니다. 원본 없이 도는
   img2img 폴백 경로에는 "제품 뒤"라는 레이어가 존재하지 않습니다.
2. 두 z_order가 **서로 다르면** `style="plain"`만 허용합니다. 레이어를 나눠 그려야 해서
   `bar`는 배경 박스가 두 번 그려집니다. 두 값이 **같으면** 기존처럼 한 번에 그리므로
   `bar`를 그대로 쓸 수 있습니다.
3. 두 z_order가 다르고 좌표 모드(`x`,`y`)를 쓰면 `sub_x`/`sub_y`가 필수입니다.
   없으면 sub가 headline과 같은 자리에 겹쳐 그려집니다.

**알려진 제한**: `headline`이 여러 줄일 때 `y`는 블록 전체의 시작점이라 **줄별로 위치를
따로 지정할 수 없습니다.** 둘째 줄 위치는 `y + headline_size × 1.35`로 자동 결정됩니다.
그래서 "첫 줄은 완전 노출 + 둘째 줄만 부분 가림"과 "큰 타이포"를 동시에 만족시키기
어렵습니다. 측정 근거는 `docs/local_validation.md` 참고.

### 4. 응답 meta

기존 `meta.text`(단일 dict)는 **구조를 그대로 유지**하고, 레이어 정보는 additive로
`meta.text_layers`에 따로 담깁니다.

```json
{
  "meta": {
    "text": { "applied_headline_px": 163, "applied_headline_ratio": 0.16, "shrunk": false },
    "text_layers": {
      "headline": { "z_order": "behind", "x": 0.5, "y": 0.02, "applied_size": 0.16 },
      "sub":      { "z_order": "front",  "x": 0.5, "y": 0.88, "applied_size": 0.05 }
    },
    "layout": { "bbox_w_ratio": 0.62, "bbox_h_ratio": 0.66,
                "center_x_ratio": 0.5, "center_y_ratio": 0.50 }
  }
}
```

`meta.layout`은 제품 bbox를 이미지 대비 비율로 알려줍니다. 클라이언트가 문구 좌표를
계산할 때 쓰라고 내려주는 값입니다(서버는 자동 배치를 하지 않습니다).

---

## 요청 예시

### 기본 (front/front, 기존 형식 그대로)

```json
POST /generate/refine
{
  "draft_image": "<base64>",
  "original_image": "<base64>",
  "category": "food",
  "text": {
    "headline": "오늘만 20% 할인",
    "sub": "매장 방문 시 즉시 적용됩니다",
    "x": 0.08, "y": 0.08,
    "align": "left", "style": "bar",
    "headline_size": 0.075, "sub_size": 0.04
  }
}
```

### headline만 제품 뒤로

```json
POST /generate/refine
{
  "draft_image": "<base64>",
  "original_image": "<base64>",
  "category": "food",
  "background": { "mode": "solid", "colors": ["#F0DCC8"], "direction": null },
  "text": {
    "headline": "MELON\nKICK",
    "sub": "달콤함이 톡! 새로운 에너지",
    "x": 0.5, "y": 0.02,
    "sub_x": 0.5, "sub_y": 0.88,
    "align": "center", "style": "plain",
    "headline_size": 0.16, "sub_size": 0.05,
    "headline_z_order": "behind",
    "sub_z_order": "front"
  }
}
```

---

## 아직 미구현

| 항목 | 상태 | 비고 |
|---|---|---|
| `product_placement` API | **실험 검증 완료 / 미반영** | 제품 x·y·scale 제어. `scripts/verification/placement/verify_product_placement.py`에 구현되어 있고 실제 이미지 검증까지 끝났으나 `pipeline`·`api.py`에는 반영 전 |
| SNS 1:1 / 배너 3:1 / 상세 3:4 | 미구현 | 현재 **1:1 정사각(1024×1024)만** 나옴. 요청에 비율 파라미터가 없고 내부에서 정사각으로 고정 |
| 여러 비율 일괄 반환 | 미구현 | 응답이 이미지 1장 고정 |
| 사용자 폰트 선택 | 미구현 | 폰트 역할(`headline`/`body`/`elegant`/`accent`)은 `config.FONTS`에 있으나 API로 노출 안 됨. Gmarket Sans Bold 파일 미확보 상태 |
| 챗봇 문구 자동 전달 연동 | 미구현 | 문구는 클라이언트가 직접 넣어야 함 |
| 제품·문구 자동 배치 | 미구현 | 서버는 좌표를 계산하지 않음. `meta.layout`을 보고 클라이언트가 계산 |
| 멀티라인 줄별 독립 좌표 | 미구현 | 위 "알려진 제한" 참고 |

### 비율 지원 시 참고

`prepare_image()`가 `ImageOps.fit(img, (size, size))`, `render_flat_background()`도
`(size, size)`로 정사각을 강제합니다. 비정사각 지원은 이 둘을 가로·세로 분리로
고치면 되고 `overlay.py`는 이미 W/H를 따로 다뤄 수정이 필요 없습니다.

다만 **AI 배경의 3:1**은 모델이 정사각 근처 비율로 학습돼 있어 품질 검증이 필요합니다.
단색·그라데이션은 diffusion을 쓰지 않아 3:1도 부담이 없습니다.

---

## 검증 스크립트

| 명령 | 필요 조건 | 내용 |
|---|---|---|
| `PYTHONPATH="$PWD" python tests/test_zorder_api.py` | 없음 | z_order 4개 조합·validation·하위호환 자동 판정 |
| `PYTHONPATH="$PWD" python scripts/verification/api/smoke_zorder_api.py` | 서버 + GPU | 실제 API로 behind/front 및 front/front 회귀 확인 |
| `PYTHONPATH="$PWD" python scripts/verification/api/smoke_api_endpoints.py` | 서버 + GPU | draft→refine 기본 흐름 |
| `PYTHONPATH="$PWD" python scripts/verification/placement/verify_product_placement.py` | rembg | 제품 배치(미반영 기능) 검증 |
| `PYTHONPATH="$PWD" python scripts/verification/zorder/verify_zorder_behind.py` | rembg | z_order 실험(자동 배치 포함, 미반영) |
| `PYTHONPATH="$PWD" python scripts/verification/poster/verify_poster_real.py <name>` | 서버 + GPU | 실제 제품 포스터 생성 |
| `PYTHONPATH="$PWD" python scripts/verification/typography/verify_autofit.py` | 없음 | 자동 크기 맞춤 비교 이미지 |
| `PYTHONPATH="$PWD" python scripts/verification/shadow/check_shadow_shapes.py` | rembg | 제품 실루엣·그림자 진단 |
| `PYTHONPATH="$PWD" python scripts/verification/shadow/batch_verify_shadow.py` | 서버 + GPU | 그림자 배치 검증 |

결과물은 각각 `outputs/verification/<카테고리>/`에 저장되며 git에는 포함되지 않습니다.
