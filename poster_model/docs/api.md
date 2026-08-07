# 포스터 이미지 API

`api.py`의 실제 구현을 기준으로 작성한 문서입니다. 필드명·타입·기본값·필수 여부·
validation 조건이 코드와 일치합니다.

서버 실행:

```bash
uvicorn api:app --host 0.0.0.0 --port 8000
```

`http://localhost:8000/docs`에서 자동 생성 스키마도 볼 수 있습니다.

---

## 전체 흐름

```text
POST /generate/drafts   시안 여러 장 (가벼운 모델, 문구 없음)
        ↓ 사용자가 하나 선택
POST /generate/refine   고품질 렌더링 + 문구 합성 + AI 생성물 표시
```

문구 합성은 **refine 단계에만** 있습니다. draft는 배경·그림자·제품까지만 만듭니다.

## 공통 규칙

### 이미지 인코딩

**요청** — base64 문자열. `data:image/png;base64,` 같은 prefix가 있으면 서버가
자동으로 떼어냅니다(있어도 없어도 동작).

**응답** — **prefix 없는 순수 PNG base64**입니다. 프론트에서 붙여 쓰면 됩니다.

```js
const src = `data:image/png;base64,${response.image}`;
```

### 서버는 상태를 저장하지 않습니다

draft 응답에 담겨 내려온 값을 클라이언트가 refine 요청에 **그대로 되돌려 보내야**
같은 결과가 재현됩니다. 특히 `background`가 그렇습니다.

### refine에는 `original_image`를 항상 보내주세요

스키마상 `Optional`이지만 **실질적으로 필수**입니다. 자세한 이유는 아래
[refine 요청](#post-generaterefine) 절을 참고하세요.

---

## POST /generate/drafts

제품 이미지를 기반으로 광고 배경 시안을 생성합니다. SD1.5 inpainting, 기본 768px.

### 요청

| 필드 | 타입 | 필수 | 기본값 | 설명 |
|---|---|---|---|---|
| `mode` | `inpaint` \| `text2img` | **필수** | — | `inpaint`는 제품 보존, `text2img`는 이미지 없이 생성 |
| `image` | str (base64) | 조건부 | `null` | 제품 사진. `mode="inpaint"` 또는 `background_mode≠"ai"`면 필수 |
| `prompt` | str | 선택 | `null` | 생략 시 `category`의 기본 프롬프트 사용 |
| `category` | `food` \| `beauty` \| `goods` | 선택 | `null` | 생략 시 `goods` |
| `num_images` | int | 선택 | `3` | **1~4** 범위 |
| `background_mode` | `ai` \| `solid` \| `gradient` | 선택 | `"ai"` | 안 보내면 기존 동작과 동일 |
| `bg_colors` | list[str] | 선택 | `null` | `#RRGGBB` 형식. 생략 시 카테고리 기본 팔레트 |
| `gradient_direction` | `vertical` \| `horizontal` \| `diagonal` | 선택 | `null` | 생략 시 `vertical` |

- `ai` — diffusion으로 배경 생성. 느리지만 표현이 풍부합니다.
- `solid` / `gradient` — **diffusion을 완전히 생략**하고 PIL로만 배경을 칠합니다. 훨씬 빠릅니다.

#### `bg_colors`와 `background.colors`의 차이

색상 검증은 두 가지를 봅니다.

| 검사 | 대상 | 결과 |
|---|---|---|
| **형식** | 모든 모드 | `#RRGGBB`가 아니면 **400** |
| **빈 배열** | `solid` / `gradient`만 | 배열이 비어 있으면 **400** |
| — | `ai` | 빈 배열도 **허용** (색상 개념이 없음) |

**개수 상한은 제한하지 않습니다.** 지원 개수를 넘겨도 400이 아니라, 남는 색을 무시하고
동작합니다. 필드를 아예 생략하면(`bg_colors` 미지정) 카테고리 기본 팔레트를 씁니다 —
빈 배열과 다르게 취급되니 주의하세요.

개수에 따른 내부 동작은 다음과 같습니다.

**drafts의 `bg_colors`** (`resolve_background()`) — 시안을 여러 장 만들어야 하므로
**변형 색상을 생성**합니다.

| 모드 | 지정 개수 | 실제 동작 |
|---|---|---|
| `solid` | 1개 | 그 색 + 밝게/어둡게 변형 3가지를 만들어 `num_images`만큼 순환 |
| `solid` | 2개 이상 | **첫 색만 사용**하고 나머지는 무시. 위와 동일하게 변형 생성 |
| `solid` | 미지정 | 카테고리 팔레트(`config.BG_PALETTES`) 사용 |
| `gradient` | 1개 | 그 색 + 팔레트에서 다른 색으로 짝을 만든 뒤 밝기 변형 3쌍 |
| `gradient` | 2개 이상 | **앞의 두 색만 사용**하고 3번째부터는 무시. 밝기 변형 3쌍 |
| `gradient` | 미지정 | 팔레트에서 인접한 색끼리 짝 |

지정한 색과 실제 적용된 색이 다를 수 있으므로(밝기 변형), 응답의
`drafts[].background.colors`에 **실제로 쓰인 색**이 담겨 내려옵니다.

**refine의 `background.colors`** (`render_flat_background()`) — 이미 고른 시안을
재현하는 단계라 **변형을 만들지 않고 받은 색을 그대로** 씁니다.

| 지정 개수 | 실제 동작 |
|---|---|
| 0개(빈 배열) | **400으로 거부.** `mode`가 `solid`/`gradient`면 최소 1개가 필요합니다 |
| 1개 | 단색 배경. `direction`은 무시 |
| 2개 이상 | 앞의 두 색으로 그라데이션, **3번째부터는 무시** |


### 응답

최상위는 `drafts`(배열)와 `meta` 두 키입니다.

| 필드 | 타입 | 설명 |
|---|---|---|
| `drafts[].id` | str | `d1`, `d2`, ... 순번 |
| `drafts[].image` | str | PNG base64 (prefix 없음) |
| `drafts[].seed` | int | `ai`는 난수 시드. **`solid`/`gradient`는 시드 개념이 없어 항상 `0`** |
| `drafts[].background` | object \| `null` | **`ai` 모드에서는 `null`.** `solid`/`gradient`는 실제 적용된 색상 |

`drafts[].background`를 **그대로** refine 요청의 `background`에 넣어주세요.
`ai` 모드에서 `null`이 가는 것은 정상입니다.

#### `meta` — 실행 경로별로 키가 다릅니다

`meta`는 실행 경로에 따라 **키 자체가 없을 수 있습니다.** "키가 없음"과
"키는 있고 값이 `null`"은 다릅니다.

| 키 | inpaint | text2img | solid | gradient | null 가능 | 설명 |
|---|---|---|---|---|---|---|
| `elapsed` | O | O | O | O | 아니오 | 생성 소요 시간(초) |
| `model` | O | O | O | O | **예** | `ai`는 `"sd15"`, `solid`/`gradient`는 항상 `null` |
| `diffusion` | O | O | O | O | 아니오 | diffusion 호출 여부. `ai`만 `true` |
| `background_mode` | O | O | O | O | 아니오 | 요청한 배경 모드 |
| `resolution` | O | O | O | O | 아니오 | 생성 해상도(px). 현재 768 |
| `mode` | O | O | O | O | 아니오 | 전처리 결과. `"raw"` \| `"blur"`, text2img는 `"text2img"` 고정 |
| `area_ratio` | O | **없음** | O | O | 아니오 | 제품이 차지하는 면적 비율 |
| `layout` | O | **없음** | O | O | 아니오 | 제품 bbox 비율. 문구 좌표 계산에 활용 |

`text2img`는 제품 이미지가 없어 마스크를 만들지 않으므로 `area_ratio`와 `layout`이
**키 자체로 존재하지 않습니다.** 클라이언트에서 `meta.get("layout")` 형태로 접근하세요.

```json
{
  "drafts": [
    {"id": "d1", "image": "<base64>", "seed": 0,
     "background": {"mode": "solid", "colors": ["#F5F1EC"], "direction": null}}
  ],
  "meta": {"elapsed": 1.2, "model": null, "mode": "raw", "area_ratio": 0.199,
           "layout": {"bbox_w_ratio": 0.44, "bbox_h_ratio": 0.64,
                      "center_x_ratio": 0.52, "center_y_ratio": 0.46},
           "diffusion": false, "background_mode": "solid", "resolution": 768}
}
```

### 오류 응답

**400 — 엔드포인트 내부의 조건부 validation**

| 조건 | 메시지 |
|---|---|
| `mode="inpaint"`인데 `image` 없음 | `inpaint 모드에는 image가 필요합니다.` |
| `background_mode≠"ai"`인데 `image` 없음 | `solid/gradient 배경 모드는 image가 필요합니다.` |
| `bg_colors`에 `#RRGGBB` 형식이 아닌 값 | `색상은 #RRGGBB 형식이어야 합니다: {값}` |
| `background_mode`가 `solid`/`gradient`인데 `bg_colors`가 **빈 배열** | `solid/gradient 배경에는 bg_colors가 최소 1개 필요합니다.` |
| base64 디코딩 실패 | `이미지 디코딩 실패: {오류}` |

**422 — Pydantic 필드 타입·범위·Literal validation 실패**

| 조건 |
|---|
| `mode`가 `inpaint`/`text2img`가 아님 (필수 필드) |
| `category`가 `food`/`beauty`/`goods`가 아님 |
| `num_images`가 1~4 밖 |
| `background_mode`가 `ai`/`solid`/`gradient`가 아님 |
| `gradient_direction`이 `vertical`/`horizontal`/`diagonal`이 아님 |
| 필수 필드(`mode`) 누락 또는 타입 불일치 |

---

## POST /generate/refine

선택한 시안을 고품질로 렌더링하고 문구를 합성합니다. SDXL 기반, 1024px.

### 요청

| 필드 | 타입 | 필수 | 기본값 | 설명 |
|---|---|---|---|---|
| `draft_image` | str (base64) | **필수** | — | 사용자가 고른 시안 |
| `original_image` | str (base64) | 선택(**권장: 항상 전달**) | `null` | 원본 제품 사진. 아래 설명 참고 |
| `prompt` | str | 선택 | `null` | 생략 시 `category` 기본 프롬프트 |
| `category` | `food` \| `beauty` \| `goods` | 선택 | `null` | 생략 시 `goods` |
| `text` | object | 선택 | `null` | 아래 [문구 필드](#문구-필드-text) 참고 |
| `ai_notice` | bool | 선택 | `true` | AI 생성물 표시를 우측 하단에 합성 |
| `background` | object | 선택 | `null` | draft 응답의 값을 그대로 전달. 구조는 아래 참고 |

#### `background` 중첩 구조 (`BackgroundSpec`)

| 필드 | 타입 | 필수 | 기본값 | 허용값 | 실제 동작 |
|---|---|---|---|---|---|
| `mode` | str | **필수** | — | `solid` \| `gradient` \| `ai` | `solid`/`gradient`면 diffusion을 생략하고 PIL로 배경을 칠합니다. `ai`면 이 필드를 보내도 기존 diffusion 경로를 탑니다 |
| `colors` | list[str] | 선택(**`solid`/`gradient`는 사실상 필수**) | `[]` | `#RRGGBB` | 기본값이 빈 배열이라, `mode`만 `solid`로 주고 이 필드를 빠뜨리면 **400**입니다. 1개면 단색, 2개 이상이면 앞의 두 색으로 그라데이션이며 **3번째부터는 무시**됩니다. `mode="ai"`면 빈 배열도 허용 |
| `direction` | str \| `null` | 선택 | `null` | `vertical` \| `horizontal` \| `diagonal` | 생략 시 `vertical`. `colors`가 1개면 단색이라 무시됩니다 |

draft 응답의 값을 **그대로** 되돌려 보내는 것이 기본 사용법입니다. 직접 구성할 때만
위 규칙을 신경 쓰면 됩니다.

**draft의 `bg_colors`와 동작이 다릅니다.** refine의 `background.colors`는 변형 색상을
만들지 않고 받은 색을 그대로 씁니다. 자세한 비교는
[`bg_colors`와 `background.colors`의 차이](#bg_colors와-backgroundcolors의-차이) 참고.

### `original_image`를 항상 보내야 하는 이유

**없어도 요청은 통과하지만, 제품 보존 단계가 적용되지 않습니다.**

이 파이프라인의 핵심은 생성 결과 위에 원본 제품을 다시 덮어씌워 로고·제품명·포장지
한글을 지키는 것인데, 그 합성 단계가 원본 사진을 필요로 합니다. `original_image` 없이
refine을 호출하면 img2img 폴백 경로로 빠져 **SDXL이 제품까지 재해석**합니다.

`ai` 모드에서도 마찬가지입니다. 배경 모드와 무관하게 항상 전달해주세요.

`original_image`가 없으면 아래 기능도 **400으로 거부**됩니다.

- `headline_z_order="behind"` 또는 `sub_z_order="behind"`
- `background.mode`가 `solid` 또는 `gradient`

### 문구 필드 (`text`)

| 필드 | 타입 | 필수 | 기본값 | 설명 |
|---|---|---|---|---|
| `headline` | str | 선택 | `""` | 큰 제목. `\n`으로 직접 줄바꿈 가능 |
| `sub` | str | 선택 | `""` | 보조 문구 |
| `x` | float | 선택 | `null` | 0~1 비율 좌표. **`y`와 함께** 있어야 좌표 모드 |
| `y` | float | 선택 | `null` | 0~1 비율 좌표 |
| `position` | `top` \| `center` \| `bottom` | 선택 | `"top"` | 하위 호환 폴백 |
| `align` | `left` \| `center` \| `right` | 선택 | `"left"` | 좌표 모드에서는 `x`가 텍스트의 어느 지점인지도 결정 |
| `style` | `plain` \| `bar` | 선택 | `"bar"` | `plain`=외곽선, `bar`=반투명 배경 박스 |
| `headline_size` | float | 선택 | `null` | **0 초과 1 이하.** 짧은 변 대비 비율 |
| `sub_size` | float | 선택 | `null` | 동일 |
| `headline_z_order` | `front` \| `behind` | 선택 | `"front"` | 제품보다 앞/뒤 |
| `sub_z_order` | `front` \| `behind` | 선택 | `"front"` | 제품보다 앞/뒤 |
| `sub_x` | float | 선택 | `null` | 0~1. z_order가 다를 때 sub 전용 좌표 |
| `sub_y` | float | 선택 | `null` | 0~1 |

**좌표 모드는 `x`와 `y`가 둘 다 있어야 동작합니다.** 하나라도 빠지면 `position`
프리셋(top/center/bottom)으로 폴백합니다.

**`headline_size` / `sub_size`는 이미지의 짧은 변(`min(width, height)`) 대비 비율**입니다.
폭 기준이 아닙니다. 현재는 출력이 정사각이라 결과가 같지만, 비율 지원이 들어가면 달라집니다.

크기 권장 범위 (`pipeline/config.py`의 `TONE_PRESETS`):

| 톤 | `headline_size` | 특징 |
|---|---|---|
| `minimal_product` | 0.09 ~ 0.13 | 절제된 톤. 얇은 외곽선 + 짙은 단색 |
| `bold_promo` | 0.18 ~ 0.28 | 큰 타이포. 흰색 + 굵은 외곽선 |

**자동 맞춤** — 요청한 크기를 우선 적용하고, 지정 영역을 벗어날 때만 최소한으로
축소합니다. 줄바꿈은 **공백 기준 어절 단위**이며, 한 어절이 한 줄보다 길 때만
글자 단위로 쪼갭니다. 실제 적용된 크기는 응답 `meta.text`에서 확인할 수 있습니다.

### 문구 레이어 순서 (z-order)

렌더링 순서는 항상 고정입니다.

```text
배경 → 그림자 → behind 문구 → 제품 합성 → front 문구 → AI 생성물 표시
```

`behind`로 지정한 문구는 제품 합성 **전에** 그려지므로, 제품이 그 문구의 일부를
자연스럽게 가립니다.

**하위 호환** — 두 필드 모두 기본값이 `"front"`라, 이 필드를 보내지 않는 기존 요청은
지금까지와 동일한 코드 경로를 탑니다(`render_text` 1회 호출, 제품 재합성 없음).

**제약 (400으로 거부)**

| 조건 | 이유 |
|---|---|
| `behind`인데 `original_image` 없음 | 제품 합성 단계가 없어 "제품 뒤" 레이어가 존재하지 않음 |
| 두 z_order가 **다른데** `style="bar"` | 레이어를 나눠 그려야 해서 배경 박스가 두 번 그려짐. **`plain`만 허용** |
| 두 z_order가 다르고 좌표 모드인데 `sub_x`/`sub_y` 없음 | sub가 headline과 같은 자리에 겹쳐 그려짐 |

두 z_order가 **같으면** 기존처럼 한 번에 그리므로 `bar`도 그대로 쓸 수 있습니다.

**알려진 제한** — `headline`이 여러 줄일 때 `y`는 블록 전체의 시작점이라 **줄별로 위치를
따로 지정할 수 없습니다.** 둘째 줄 위치는 `y + headline_size × 1.35`로 자동 결정됩니다.
측정 근거는 `docs/local_validation.md` 참고.

### 응답

최상위는 `image`와 `meta` 두 키입니다.

| 필드 | 타입 | 설명 |
|---|---|---|
| `image` | str | 최종 PNG base64 (prefix 없음) |
| `meta` | object | 아래 참고 |

#### `meta` — 실행 경로별로 키가 다릅니다

refine은 배경 모드와 `original_image` 유무에 따라 **서로 다른 코드 경로**를 타며,
경로마다 `meta`의 키 구성이 다릅니다.

| 키 | AI + 원본 있음 | AI + 원본 없음 | solid | gradient | null 가능 | 설명 |
|---|---|---|---|---|---|---|
| `elapsed` | O | O | O | O | 아니오 | 소요 시간(초) |
| `model` | O | O | O | O | **예** | `ai`는 `"sdxl"`, `solid`/`gradient`는 항상 `null` |
| `strength` | O | O | O | O | **예** | **refine 응답에만 존재.** `solid`/`gradient`는 항상 `null` |
| `layout` | O | O | O | O | **예** | **`original_image`가 없으면 `null`** |
| `diffusion` | O | O | O | O | 아니오 | `ai`만 `true` |
| `background_mode` | O | O | O | O | 아니오 | `ai` 경로는 항상 `"ai"` |
| `resolution` | O | O | O | O | 아니오 | 현재 1024 |
| `mode` | **없음** | **없음** | O | O | 아니오 | **AI 경로에는 키 자체가 없습니다** |
| `area_ratio` | **없음** | **없음** | O | O | 아니오 | **AI 경로에는 키 자체가 없습니다** |
| `text` | 조건부 | 조건부 | 조건부 | 조건부 | 아니오 | **`text.headline` 또는 `text.sub`가 비어 있지 않을 때만 추가** |
| `text_layers` | 조건부 | 조건부 | 조건부 | 조건부 | 아니오 | 위와 동일 조건 |

`mode`와 `area_ratio`는 drafts에서는 모든 경로에 있지만, **refine에서는
`solid`/`gradient` 경로에만 있습니다.** AI 경로에서 이 값을 읽으면 `KeyError`가 납니다.

`layout`은 네 경로 모두 키가 존재하지만, AI 경로에서 `original_image`를 보내지 않으면
값이 `null`입니다(제품 마스크가 없어 bbox를 계산할 수 없음).

#### `meta.text` / `meta.text_layers`

문구가 실제로 합성됐을 때만 추가되는 필드입니다. `text`를 아예 안 보내거나
`headline`과 `sub`가 모두 빈 문자열이면 **두 키 다 존재하지 않습니다.**

| 필드 | 설명 |
|---|---|
| `meta.text` | **기존 구조 그대로 유지.** 실제 적용된 폰트 크기(px·비율), `shrunk`, `style` 등 |
| `meta.text_layers` | **신규 additive 필드.** `headline`/`sub` 각각의 `z_order`, `x`, `y`, `applied_size` |

`meta.text_layers`의 하위 키는 실제로 그린 문구만 포함합니다. `headline`만 보내면
`text_layers`에 `sub` 키가 없습니다.

**하위 호환**: `meta.text`는 단일 dict 구조를 그대로 유지하고 레이어 정보는
`meta.text_layers`로 **추가만** 했습니다. 기존 클라이언트 코드는 수정이 필요 없습니다.

`meta.text.shrunk`가 `true`면 `auto_fit`이 요청한 크기를 줄인 것입니다. 프론트 미리보기와
결과가 다를 수 있으니 `applied_headline_ratio`로 확인하세요.

```json
{
  "image": "<base64>",
  "meta": {
    "elapsed": 0.4, "model": null, "strength": null, "mode": "raw",
    "area_ratio": 0.199, "diffusion": false,
    "background_mode": "solid", "resolution": 1024,
    "layout": {"bbox_w_ratio": 0.44, "bbox_h_ratio": 0.64,
               "center_x_ratio": 0.52, "center_y_ratio": 0.46},
    "text": {"applied_headline_px": 163, "applied_headline_ratio": 0.16,
             "applied_sub_px": 51, "applied_sub_ratio": 0.05,
             "shrunk": false, "style": "plain", "coord_mode": true},
    "text_layers": {
      "headline": {"z_order": "behind", "x": 0.5, "y": 0.02, "applied_size": 0.16},
      "sub":      {"z_order": "front",  "x": 0.5, "y": 0.88, "applied_size": 0.05}
    }
  }
}
```

위 예시는 **solid 경로**입니다. AI 경로에서는 `mode`와 `area_ratio`가 없고
`model`이 `"sdxl"`, `strength`가 숫자입니다.

### 오류 응답

**400 — 엔드포인트 내부의 조건부 validation**

| 조건 | 메시지 |
|---|---|
| `background.mode`가 `solid`/`gradient`인데 `original_image` 없음 | `solid/gradient 배경 refine에는 original_image가 필요합니다.` |
| `background.colors`에 `#RRGGBB` 형식이 아닌 값 | `색상은 #RRGGBB 형식이어야 합니다: {값}` |
| `background.mode`가 `solid`/`gradient`인데 `colors`가 **빈 배열** | `solid/gradient 배경에는 background.colors가 최소 1개 필요합니다.` |
| z_order가 `behind`인데 제품 합성 경로가 아님(원본 없음) | `z_order="behind"는 제품을 원본에서 다시 합성하는 경로에서만 지원됩니다...` |
| 두 z_order가 다른데 `style="bar"` | `...style="plain"을 쓰거나 두 z_order를 같게 하세요.` |
| 두 z_order가 다르고 좌표 모드인데 `sub_x`/`sub_y` 없음 | `...sub_x와 sub_y를 함께 지정해야 합니다.` |
| base64 디코딩 실패 | `이미지 디코딩 실패: {오류}` |

**422 — Pydantic 필드 타입·범위·Literal validation 실패**

| 조건 |
|---|
| `x`, `y`, `sub_x`, `sub_y`가 0~1 범위를 벗어남 (`ge=0`, `le=1`) |
| `headline_size`, `sub_size`가 **0 이하**이거나 1 초과 (`gt=0`, `le=1`) |
| `align`이 `left`/`center`/`right`가 아님 |
| `position`이 `top`/`center`/`bottom`이 아님 |
| `style`이 `plain`/`bar`가 아님 |
| `headline_z_order`, `sub_z_order`가 `front`/`behind`가 아님 |
| `background.mode`가 `solid`/`gradient`/`ai`가 아님 |
| `background.direction`이 `vertical`/`horizontal`/`diagonal`이 아님 |
| `category`가 `food`/`beauty`/`goods`가 아님 |
| 필수 필드(`draft_image`) 누락 또는 타입 불일치 |

---

## 그 외 엔드포인트

| 메서드 | 경로 | 요청 | 응답 | 용도 |
|---|---|---|---|---|
| GET | `/health` | 없음 | `{"status": "ok", "draft_model": "sd15", "refine_model": "sdxl"}` | 헬스체크. 모델 이름은 `config`의 `DRAFT_MODEL`/`REFINE_MODEL` 값 |
| POST | `/admin/gc` | 없음 | `{"status": "ok"}` | GPU 캐시·가비지 정리. 연속 생성 시 메모리 완화용 |

`/admin/gc`는 본문 없이 POST하면 되고, CUDA가 없는 환경에서도 오류 없이 `ok`를 반환합니다.

---

## 요청 예시

### 기본 (front/front, 기존 형식)

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

### headline만 제품 뒤로 (solid 배경)

```json
POST /generate/refine
{
  "draft_image": "<base64>",
  "original_image": "<base64>",
  "category": "food",
  "background": {"mode": "solid", "colors": ["#F0DCC8"], "direction": null},
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
| `product_placement` (제품 위치·크기 제어) | **실험 검증 완료 / 미반영** | 제품 x·y·scale 제어. `scripts/verification/placement/verify_product_placement.py`에 구현되어 있고 실제 이미지 검증까지 끝났으나 `pipeline`·`api.py`에는 반영 전 |
| SNS 1:1 / 배너 3:1 / 상세 3:4 | 미구현 | 현재 **1:1 정사각(1024×1024)만** 나옴. 요청에 비율 파라미터가 없고 내부에서 정사각으로 고정 |
| 여러 비율 일괄 반환 | 미구현 | 응답이 이미지 1장 고정 |
| 사용자 폰트 선택 | 미구현 | 폰트 역할(`headline`/`body`/`elegant`/`accent`)은 `config.FONTS`에 있으나 API로 노출 안 됨. Gmarket Sans Bold 파일 미확보 상태 |
| 챗봇 문구 자동 전달 연동 | 미구현 | 문구는 클라이언트가 직접 넣어야 함 |
| 제품·문구 자동 배치 | 미구현 | 서버는 좌표를 계산하지 않음. `meta.layout`을 보고 클라이언트가 계산 |
| 멀티라인 줄별 독립 좌표 | 미구현 | 위 "알려진 제한" 참고 |

### 비율 지원 시 참고

`prepare_image()`가 `ImageOps.fit(img, (size, size))`, `render_flat_background()`도
`(size, size)`로 정사각을 강제합니다. 비정사각 지원은 이 둘을 가로·세로 분리로 고치면
되고 `overlay.py`는 이미 W/H를 따로 다뤄 수정이 필요 없습니다.

다만 **AI 배경의 3:1**은 모델이 정사각 근처 비율로 학습돼 있어 품질 검증이 필요합니다.
단색·그라데이션은 diffusion을 쓰지 않아 3:1도 부담이 없습니다.

---

## 검증 스크립트

| 명령 | 필요 조건 | 내용 |
|---|---|---|
| `PYTHONPATH="$PWD" python tests/test_zorder_api.py` | 없음 | z_order 4개 조합·validation·하위호환 자동 판정 |
| `PYTHONPATH="$PWD" python tests/test_background_validation.py` | 없음 | 배경 색상 validation(빈 배열·형식·모드별 차이) 자동 판정 |
| `PYTHONPATH="$PWD" python scripts/verification/api/smoke_zorder_api.py` | 서버 + GPU | 실제 API로 behind/front 및 회귀 확인 |
| `PYTHONPATH="$PWD" python scripts/verification/api/smoke_api_endpoints.py` | 서버 + GPU | draft→refine 기본 흐름 |
| `PYTHONPATH="$PWD" python scripts/verification/placement/verify_product_placement.py` | rembg | 제품 배치(미반영 기능) 검증 |
| `PYTHONPATH="$PWD" python scripts/verification/zorder/verify_zorder_behind.py` | rembg | z_order 실험(자동 배치 포함, 미반영) |
| `PYTHONPATH="$PWD" python scripts/verification/poster/verify_poster_real.py <name>` | 서버 + GPU | 실제 제품 포스터 생성 |
| `PYTHONPATH="$PWD" python scripts/verification/typography/verify_autofit.py` | 없음 | 자동 크기 맞춤 비교 이미지 |
| `PYTHONPATH="$PWD" python scripts/verification/shadow/check_shadow_shapes.py` | rembg | 제품 실루엣·그림자 진단 |
| `PYTHONPATH="$PWD" python scripts/verification/shadow/batch_verify_shadow.py` | 서버 + GPU | 그림자 배치 검증 |

결과물은 각각 `outputs/verification/<카테고리>/`에 저장되며 git에는 포함되지 않습니다.
