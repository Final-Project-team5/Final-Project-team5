# 포스터 이미지 API 현황

`api.py`의 실제 구현을 기준으로 작성한 문서입니다. 필드명·타입·기본값·필수 여부·
validation 조건이 코드와 일치합니다.

프론트 연동 시 이 문서만 보고 현재 가능한 범위를 판단할 수 있게 하는 것이 목적입니다.

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
        ↓ 문구만 다시 고치고 싶을 때
POST /compose/text      diffusion 없이 문구만 재합성 (아래 참고)
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
| `aspect_ratio` | `1:1` \| `3:1` \| `3:4` | 선택 | `null` | **생략하면 기존과 동일한 1:1.** `solid`/`gradient`에서만 지원 |
| `placement` | object | 선택 | `null` | 제품 배치 override. 구조는 아래 참고. `solid`/`gradient`에서만 지원 |

- `ai` — diffusion으로 배경 생성. 느리지만 표현이 풍부합니다.
- `solid` / `gradient` — **diffusion을 완전히 생략**하고 PIL로만 배경을 칠합니다. 훨씬 빠릅니다.

#### 출력 비율 (`aspect_ratio`)

용도별 비율을 지원합니다. 짧은 변을 고정하고 긴 변을 계산합니다.

| 값 | 용도 | draft 크기 | refine(최종) 크기 |
|---|---|---|---|
| `1:1` (기본) | SNS | 768 × 768 | 1024 × 1024 |
| `3:1` | 배너 | 2304 × 768 | 3072 × 1024 |
| `3:4` | 상세페이지 | 768 × 1024 | 1024 × 1368 |

**필드를 보내지 않으면 기존과 완전히 동일한 1:1 결과**가 나옵니다. 픽셀 단위로
같습니다. `aspect_ratio: "1:1"`을 명시해도 결과는 같습니다.

`3:4`의 긴 변이 1366이 아니라 **1368**인 것은 8의 배수로 맞추기 때문입니다.

**지원 조건**

| 조합 | 결과 |
|---|---|
| `1:1` + `background_mode="ai"` | 200 (기존) |
| **`3:1` + `background_mode="ai"`** | **200** |
| `3:4` + `background_mode="ai"` | **400** (아래 참고) |
| 비정사각 + `mode="text2img"` | **400** (제품 이미지가 없어 배치할 대상이 없음) |
| `placement` + `background_mode="ai"` | **400** (`placement`는 `solid`/`gradient` 전용) |
| `placement` + `mode="text2img"` | **400** |

`solid`/`gradient`는 세 비율 모두 지원합니다. **AI 배경은 `1:1`과 `3:1`만**
지원하며, `3:4`는 제품 마스크 바깥에 구조가 생성되는 현상이 확인돼 기술적으로
미지원 상태입니다.

```json
{"error": "aspect_ratio_not_supported_for_ai",
 "message": "aspect_ratio '3:4'는 AI 배경에서 아직 지원하지 않습니다. ...",
 "requested": "3:4", "supported": ["1:1", "3:1"]}
```

`supported` 목록이 응답에 담기므로 프론트가 하드코딩하지 않고 이 값으로 UI를
구성할 수 있습니다.

지원하지 않는 조합을 조용히 정사각으로 떨어뜨리지 않고 명시적으로 거부합니다.

#### 제품 배치 (`placement`)

보내지 않으면 서버가 비율에 맞는 기본 배치를 계산합니다. **대부분의 경우 보낼
필요가 없습니다.** 사용자가 직접 위치·크기를 조정하는 UI가 있을 때만 씁니다.

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| `scale_factor` | float | 선택 | **서버 기본 배율 대비 배수.** `1.0`이 기본값 그대로, `0.85`는 15% 작게. `0 < v <= 3` |
| `x` | float | 선택 | **제품 bbox 중심점**의 캔버스 가로 정규화 좌표. `0 <= v <= 1` |
| `y` | float | 선택 | **제품 bbox 중심점**의 캔버스 세로 정규화 좌표. `0 <= v <= 1` |

**`x` / `y`는 좌상단이 아니라 중심점입니다.** 중심 기준이라 배율을 바꿔도 잡아둔
위치가 움직이지 않습니다. `text.x` / `text.y`와 같은 0~1 정규화 규약입니다.

**셋 다 선택이며 일부만 보낼 수 있습니다.** 보내지 않은 값은 서버가 채웁니다.
`scale_factor`만 보내면 바뀐 배율에 맞춰 좌표를 다시 계산합니다(원래 좌표를
그대로 쓰면 제품이 영역에서 벗어납니다).

**`extra` 필드는 422로 거부합니다.** 응답 `meta.placement`에 있는 `source`와
`region_overflow`는 response-only이므로 요청에 넣으면 422입니다. 자세한 것은
아래 [round-trip 주의](#placement-round-trip-주의)를 보세요.

서버는 override를 받아도 제품과 그림자가 캔버스를 벗어나지 않는지 **다시
검증**합니다. 벗어나면 잘라내지 않고 400으로 거부하며, 복구용 기본 배치를
`suggested`로 함께 내려줍니다. 그림자 크기는 제품 모양에 따라 달라져
클라이언트가 미리 계산할 수 없으므로 이 검증은 서버에만 있을 수 있습니다.

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
| `aspect_ratio` | O | O | O | O | 아니오 | **resolved 값.** 요청에서 생략해도 `"1:1"`이 들어갑니다 |
| `canvas` | O | O | O | O | 아니오 | `{"width": int, "height": int}` 실제 출력 크기 |
| `placement` | O | O | O | O | **예** | 최종 배치. 배치 개념이 없는 경로(`text2img`)는 `null` |

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
           "diffusion": false, "background_mode": "solid", "resolution": 768,
           "aspect_ratio": "3:1",
           "canvas": {"width": 2304, "height": 768},
           "placement": {"source": "auto", "scale_factor": 1.0,
                         "x": 0.7681, "y": 0.4512, "region_overflow": false}}
}
```

**`resolution`은 int 그대로입니다.** 짧은 변 픽셀 값이며 타입도 의미도 바뀌지
않았습니다. 비정사각의 실제 크기는 새 키 `canvas`를 보세요. 기존 키는 하나도
변경되지 않았고 세 키가 추가되기만 했습니다.

#### `meta.placement` — resolved 배치

| 필드 | 타입 | 방향 | 설명 |
|---|---|---|---|
| `source` | `identity` \| `auto` \| `override` | **response-only** | `identity`는 1:1 기본 경로, `auto`는 서버 계산, `override`는 클라이언트 지정이 있었음 |
| `scale_factor` | float | 요청·응답 | 서버 기본 배율 대비 배수 |
| `x` | float | 요청·응답 | 제품 bbox 중심의 가로 정규화 좌표 |
| `y` | float | 요청·응답 | 제품 bbox 중심의 세로 정규화 좌표 |
| `region_overflow` | bool | **response-only** | 제품이 권장 영역을 벗어났음을 알리는 경고. 오류는 아닙니다 |

**request echo가 아니라 최종 상태입니다.** `{"scale_factor": 0.8}`만 보내도
응답에는 서버가 계산한 `x`, `y`가 채워져 돌아옵니다.

### 오류 응답

**400 — 엔드포인트 내부의 조건부 validation**

| 조건 | 메시지 |
|---|---|
| `mode="inpaint"`인데 `image` 없음 | `inpaint 모드에는 image가 필요합니다.` |
| `background_mode≠"ai"`인데 `image` 없음 | `solid/gradient 배경 모드는 image가 필요합니다.` |
| `bg_colors`에 `#RRGGBB` 형식이 아닌 값 | `색상은 #RRGGBB 형식이어야 합니다: {값}` |
| `background_mode`가 `solid`/`gradient`인데 `bg_colors`가 **빈 배열** | `solid/gradient 배경에는 bg_colors가 최소 1개 필요합니다.` |
| `placement` + `background_mode="ai"` | `placement는 solid/gradient 배경에서만 지원합니다...` |
| AI 배경 + 지원하지 않는 비율(현재 `3:4`) | `{"error": "aspect_ratio_not_supported_for_ai", "supported": [...]}` |
| 비정사각 `aspect_ratio` 또는 `placement` + `mode="text2img"` | `...는 제품 이미지가 있는 요청에서만 지원합니다...` |
| `placement`가 캔버스를 벗어남 | 구조화된 detail (아래 참고) |
| `placement`의 최종 확대가 품질 상한 초과 | 구조화된 detail (아래 참고) |
| base64 디코딩 실패 | `이미지 디코딩 실패: {오류}` |

**`placement` 거부는 문자열이 아니라 객체로 내려옵니다.**

```json
{"detail": {"error": "placement_unsafe",
            "message": "배치가 캔버스를 벗어납니다(shadow_clipped).",
            "reasons": ["shadow_clipped"],
            "canvas": {"width": 3072, "height": 1024},
            "footprint": [2064, 741, 2656, 1031],
            "suggested": {"source": "auto", "scale_factor": 1.0,
                          "x": 0.7681, "y": 0.458, "region_overflow": false}}}
```

```json
{"detail": {"error": "placement_over_max_upscale",
            "message": "확대 배율 상한을 초과합니다...",
            "requested_scale": 1.616, "max_scale_factor": 1.0309,
            "suggested": {"source": "auto", "scale_factor": 1.0,
                          "x": 0.7681, "y": 0.458, "region_overflow": false}}}
```

`suggested`를 그대로 쓰면 한 번의 재요청으로 복구됩니다(단, `scale_factor`/`x`/`y`
세 필드만 뽑아서 보내야 합니다). `max_scale_factor`는 **이 제품에서 허용되는 최대
배수**로, 제품마다 다릅니다. 확대할수록 제품 디테일이 뭉개지므로 캔버스를 벗어나지
않더라도 상한을 넘으면 거부합니다.

**422 — Pydantic 필드 타입·범위·Literal validation 실패**

| 조건 |
|---|
| `mode`가 `inpaint`/`text2img`가 아님 (필수 필드) |
| `category`가 `food`/`beauty`/`goods`가 아님 |
| `num_images`가 1~4 밖 |
| `background_mode`가 `ai`/`solid`/`gradient`가 아님 |
| `gradient_direction`이 `vertical`/`horizontal`/`diagonal`이 아님 |
| `aspect_ratio`가 `1:1`/`3:1`/`3:4`가 아님 |
| `placement.scale_factor`가 **0 이하**이거나 3 초과 (`gt=0`, `le=3`) |
| `placement.x`, `placement.y`가 0~1 범위를 벗어남 |
| `placement`에 `scale_factor`/`x`/`y` 외의 키가 있음 (**extra 금지**) |
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
| `aspect_ratio` | `1:1` \| `3:1` \| `3:4` | 선택 | `null` | 생략하면 `draft_image` 크기에서 추론. 아래 참고 |
| `placement` | object | 선택 | `null` | drafts와 같은 `scale_factor`/`x`/`y` 구조 |

#### 출력 비율은 draft 크기에서 **항상** 추론합니다

`aspect_ratio`를 보내지 않아도 서버가 `draft_image`의 가로세로에서 비율을
판정합니다. 사용자가 3:1 시안을 골랐는데 프론트가 필드를 빠뜨렸을 때 조용히
1:1로 떨어지는 것을 막기 위해서입니다.

| draft 크기 | 판정 |
|---|---|
| 768 × 768, 1024 × 1024 (정사각 전부) | `1:1` |
| 2304 × 768, 3072 × 1024 | `3:1` |
| 768 × 1024, 1024 × 1368 | `3:4` |

**정확한 비율값이 아니어도 됩니다.** 지원 비율 대비 상대 오차 0.5% 이내면
같은 비율로 봅니다. 3:4의 실제 출력이 `1024 × 1368`(= 0.7485)이라 정확히 0.75가
아니고, draft(짧은 변 768)와 refine(1024)의 반올림 결과도 미세하게 다르기
때문입니다. 프론트에서 재인코딩하며 몇 px 달라지는 것도 허용됩니다.

`aspect_ratio`를 함께 보내면 **추론값과 교차 검증**합니다.

| 상황 | 결과 |
|---|---|
| 명시값 없음 + 추론 성공 | 추론값 사용 |
| 명시값 있음 + 추론값과 일치 | 그대로 사용 |
| 명시값 있음 + 추론값과 **불일치** | **400** `aspect_ratio_mismatch` |
| 지원 비율 tolerance 밖 (예: 1920 × 1080) | **400** `aspect_ratio_unsupported` |

drafts와 같은 조건이 적용됩니다. **AI 배경은 `1:1`과 `3:1`만** 지원하고 `3:4`는
400이며, `placement`는 `solid`/`gradient` 전용입니다.

**비정사각 AI refine은 `original_image`가 필수입니다.** 없으면 제품 마스크·배치·
원본 재합성이 빠져 제품이 보존되지 않는 다른 경로로 빠지기 때문에 거부합니다.
`1:1`은 기존대로 `original_image` 없이도 동작합니다(img2img 폴백 유지).

```json
{"error": "original_image_required_for_nonsquare_ai",
 "message": "비정사각 AI 배경 refine에는 original_image가 필요합니다. ...",
 "aspect_ratio": "3:1"}
```

비율은 요청 필드뿐 아니라 **`draft_image`에서 추론된 값으로도** 검사합니다.
`aspect_ratio`를 보내지 않고 3:4 draft를 넣어도 400입니다.

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
| `x` | float | 선택 | `null` | 0~1 비율 좌표. **`y`와 함께** 있어야 좌표 모드. `align`이 기준점을 정한다 |
| `y` | float | 선택 | `null` | 0~1 비율 좌표. **텍스트 블록의 중심** |
| `position` | `top` \| `center` \| `bottom` | 선택 | `"top"` | 하위 호환 폴백 |
| `align` | `left` \| `center` \| `right` | 선택 | `"left"` | 좌표 모드에서 `x`가 텍스트의 어느 지점인지 결정. **중심 기준으로 쓰려면 `"center"`를 명시** |
| `style` | `plain` \| `bar` | 선택 | `"bar"` | `plain`=외곽선, `bar`=반투명 배경 박스 |
| `headline_size` | float | 선택 | `null` | **0 초과 1 이하.** 짧은 변 대비 비율 |
| `sub_size` | float | 선택 | `null` | 동일 |
| `headline_z_order` | `front` \| `behind` | 선택 | `"front"` | 제품보다 앞/뒤 |
| `sub_z_order` | `front` \| `behind` | 선택 | `"front"` | 제품보다 앞/뒤 |
| `sub_x` | float | 선택 | `null` | 0~1. z_order가 다를 때 sub 전용 좌표 |
| `sub_y` | float | 선택 | `null` | 0~1 |
| `font_id` | str | 선택 | `null` | 사용자가 고른 폰트. **headline과 sub에 공통 적용.** 아래 참고 |

#### 폰트 선택 (`font_id`)

폰트는 **하나만** 고릅니다. 고른 폰트 하나가 `headline`과 `sub`에 **공통 적용**됩니다.
`headline_font_id` / `sub_font_id`처럼 나누지 않습니다.

**계약상 지원 ID 5종**

| `font_id` | 폰트 |
|---|---|
| `pretendard` | Pretendard Regular |
| `nanummyeongjo` | 나눔명조 Bold |
| `gmarketsans` | Gmarket Sans Medium |
| `galmuri11` | Galmuri11 |
| `nanumpen` | 나눔손글씨 펜 |

**`font_id`를 보내지 않으면 기존 기본 렌더링 동작이 그대로 유지됩니다.** 즉
headline과 sub가 각각 서버가 정한 기본 폰트로 그려집니다. 기존 클라이언트는
아무것도 바꾸지 않아도 결과가 동일합니다.

**silent fallback은 없습니다.** 요청한 폰트를 쓸 수 없으면 다른 폰트로 조용히
바꾸지 않고 400으로 거부합니다. 사용자가 고른 폰트가 아닌 결과가 나가면 프론트가
무엇이 잘못됐는지 알 방법이 없기 때문입니다.

| 상황 | 응답 |
|---|---|
| 지원 목록에 없는 ID | **400** `font_not_supported` (+ `supported`, `available`) |
| 지원 ID이지만 서버에 TTF 자산이 없음 | **400** `font_asset_missing` (+ `font_id`, `available`) |

두 오류를 나눈 이유는 프론트가 받아야 할 신호가 다르기 때문입니다. 앞은
클라이언트가 계약에 없는 값을 보낸 것이고, 뒤는 서버 자산을 채우면 해결됩니다.

```json
{"error": "font_asset_missing",
 "message": "font_id 'gmarketsans'는 지원 목록에 있지만 서버에 폰트 파일이 아직 없습니다. ...",
 "font_id": "gmarketsans",
 "available": ["pretendard", "nanummyeongjo"]}
```

`available`은 **지금 이 서버에서 실제로 렌더링 가능한 ID** 목록입니다. 자산이
병합되면 자동으로 5종이 됩니다.

**적용 범위**

```text
/generate/refine    text.font_id 지원
/compose/text       text.font_id 지원 (같은 TextSpec)
add_ai_notice       사용자 선택과 무관하게 기존 body 폰트 유지
```

AI 생성물 표시는 사용자 문구가 아니라 시스템 표시라 선택 폰트를 따라가지 않습니다.

**`font_weight`는 현재 API 범위에 없습니다.** `font_id` 하나가 특정 폰트 파일
하나를 직접 가리킵니다(예: `gmarketsans`는 Medium 고정). 굵기를 별도로 고르는
파라미터는 없습니다.

빈 문자열(`""`)은 미전달과 동일하게 취급됩니다. 타입이 문자열이 아니면 422입니다.

#### 좌표 기준

**좌표 모드는 `x`와 `y`가 둘 다 있어야 동작합니다.** 하나라도 빠지면 `position`
프리셋(top/center/bottom)으로 폴백합니다.

| | 기준점 |
|---|---|
| `y` | **텍스트 블록의 세로 중심** |
| `x` + `align="center"` | **텍스트 블록의 가로 중심** |
| `x` + `align="left"` | 텍스트의 왼쪽 변 |
| `x` + `align="right"` | 텍스트의 오른쪽 변 |

프론트 미리보기가 텍스트 박스 중심을 기준으로 쓰기로 해서 `y`를 중심 기준으로
맞췄습니다. **`x`는 `align`이 결정하므로, 중심 기준으로 쓰려면 `align="center"`를
명시해야 합니다.** `align`의 기본값은 하위 호환 때문에 `"left"`로 두었습니다.

```json
"text": {"headline": "여름 한정 특가", "x": 0.5, "y": 0.42, "align": "center"}
```

`auto_fit`으로 글자가 줄어들어도 **블록 중심은 그대로 유지**됩니다. 실제 적용된
값은 응답 `meta.text`의 `y_anchor` / `block_top_px` / `block_height_px`로 확인할 수
있습니다.

> **폰트 metric 주의** — 위 기준은 *텍스트 박스*의 중심입니다. 글자 자체(잉크)는
> 폰트의 ascent/descent 때문에 박스 안에서 위쪽에 치우칩니다. 실측으로 블록 중심과
> 잉크 중심이 최대 46px(1024 기준) 차이 났고, 보조 문구 유무에 따라 편차가
> 달라집니다. CSS `line-height`와 PIL의 줄 높이 계산이 다르면 미리보기와 이만큼
> 어긋날 수 있어, 프론트 integration 때 샘플로 대조할 항목입니다.

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
측정 근거는 `그림자_로컬검증_가이드.md` 참고.

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
| `aspect_ratio` | O | O | O | O | 아니오 | **resolved 값.** 요청에서 생략해도 판정 결과가 들어갑니다 |
| `canvas` | O | O | O | O | 아니오 | `{"width": int, "height": int}` 실제 출력 크기 |
| `placement` | O | O | O | O | **예** | 최종 배치. 제품 배치가 없는 경로는 `null` |
| `warnings` | 조건부 | 조건부 | 조건부 | 조건부 | 아니오 | 판정에 애매함이 있을 때만 추가되는 문자열 배열 |

`mode`와 `area_ratio`는 drafts에서는 모든 경로에 있지만, **refine에서는
`solid`/`gradient` 경로에만 있습니다.** AI 경로에서 이 값을 읽으면 `KeyError`가 납니다.

`layout`은 네 경로 모두 키가 존재하지만, AI 경로에서 `original_image`를 보내지 않으면
값이 `null`입니다(제품 마스크가 없어 bbox를 계산할 수 없음).

`aspect_ratio` / `canvas` / `placement`의 의미와 필드 구성은
[drafts의 `meta.placement`](#metaplacement--resolved-배치)와 동일합니다.
`resolution`은 여기서도 int(짧은 변) 그대로이며, 기존 키는 변경 없이 추가만 됐습니다.

#### placement round-trip 주의

drafts 응답의 배치를 refine에 이어서 적용할 때는 **`scale_factor` / `x` / `y`
세 필드만** 담아 보내세요.

```javascript
// 올바름
const p = draftRes.meta.placement;
refineBody.placement = { scale_factor: p.scale_factor, x: p.x, y: p.y };

// 422 — source, region_overflow는 response-only
refineBody.placement = draftRes.meta.placement;
```

응답 객체를 통째로 보내면 **422**입니다. 모르는 키를 조용히 무시하면
클라이언트가 그 값이 반영된 줄 알게 되므로 명시적으로 거부합니다.

정규화 좌표와 상대 배율을 쓰기 때문에, draft(짧은 변 768)에서 받은 값을 그대로
refine(1024)에 보내면 **같은 구도가 재현**됩니다. 픽셀 좌표를 환산할 필요가 없습니다.

#### `meta.text`의 좌표 관련 키

| 키 | 설명 |
|---|---|
| `coord_mode` | `x`/`y` 좌표 모드로 동작했는지 |
| `y_anchor` | 좌표 모드면 `"center"`, 프리셋이면 `position` 값 |
| `block_top_px` | 실제로 그려진 텍스트 블록의 상단 y (픽셀) |
| `block_height_px` | 텍스트 블록의 전체 높이 (픽셀) |

`block_top_px + block_height_px / 2`가 좌표 모드에서 `y * height`와 일치합니다.

#### `meta.ignored_fields` — 요청됐지만 적용되지 않은 필드

`sub_x` / `sub_y`는 **sub를 headline과 따로 그릴 때만** 쓰입니다. 즉 headline과 sub가
둘 다 있고 `z_order`가 서로 다를 때뿐입니다. 그 외에는 sub도 headline과 같은 좌표
(`x`, `y`)로 그려지므로 `sub_x` / `sub_y`는 무시됩니다.

무시된 경우 응답에 그 사실이 남습니다.

```json
"ignored_fields": ["sub_x", "sub_y"]
```

| 상황 | 응답 |
|---|---|
| 같은 `z_order`인데 `sub_x`만 보냄 | `["sub_x"]` |
| 같은 `z_order`인데 둘 다 보냄 | `["sub_x", "sub_y"]` |
| `sub`가 비어 있는데 `sub_x`를 보냄 | `["sub_x"]` |
| 다른 `z_order` — 실제로 사용됨 | **키 없음** |
| 아무것도 안 보냄 | **키 없음** |

무시된 필드가 없으면 **키 자체가 없습니다.** `meta.get("ignored_fields")`로
접근하세요.

`text_layers`의 좌표도 **실제 적용값**입니다. 같은 `z_order`에서 `sub_x`를 보내면
`text_layers.sub.x`에는 `sub_x`가 아니라 실제로 쓰인 `x`가 담깁니다.

이 조합을 400으로 막지 않는 이유는 `/generate/refine`과 `/compose/text`가 **같은
`TextSpec` 객체**를 그대로 받아야 하기 때문입니다. 한쪽만 거부하면 프론트가 호출
전에 필드를 지우는 전처리를 넣어야 하고, 빠뜨리면 편집이 통째로 실패합니다.
**두 엔드포인트에 같은 기준이 적용됩니다.**

#### `meta.text` / `meta.text_layers`

문구가 실제로 합성됐을 때만 추가되는 필드입니다. `text`를 아예 안 보내거나
`headline`과 `sub`가 모두 빈 문자열이면 **두 키 다 존재하지 않습니다.**

| 필드 | 설명 |
|---|---|
| `meta.text` | **기존 구조 그대로 유지.** 실제 적용된 폰트 크기(px·비율), `shrunk`, `style`, `font_id` 등 |
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
| `draft_image` 비율이 지원 목록 tolerance 밖 | `{"error": "aspect_ratio_unsupported", ...}` |
| 명시 `aspect_ratio`와 draft 추론값 불일치 | `{"error": "aspect_ratio_mismatch", "requested": ..., "inferred_from_draft": ...}` |
| `placement` + `background.mode="ai"` | `placement는 solid/gradient 배경에서만 지원합니다...` |
| AI 배경 + 지원하지 않는 비율(현재 `3:4`) | `{"error": "aspect_ratio_not_supported_for_ai", "supported": [...]}` |
| 비정사각 AI 배경인데 `original_image` 없음 | `{"error": "original_image_required_for_nonsquare_ai", "aspect_ratio": ...}` |
| `placement`가 캔버스를 벗어남 | `{"error": "placement_unsafe", ..., "suggested": {...}}` |
| `placement`의 최종 확대가 품질 상한 초과 | `{"error": "placement_over_max_upscale", ..., "suggested": {...}}` |
| `text.font_id`가 지원 목록에 없음 | `{"error": "font_not_supported", "supported": [...], "available": [...]}` |
| `text.font_id`는 지원하지만 서버에 TTF 자산이 없음 | `{"error": "font_asset_missing", "font_id": ..., "available": [...]}` |
| base64 디코딩 실패 | `이미지 디코딩 실패: {오류}` |

**호환성 주의 — `draft_image` 비율 검사가 새로 생겼습니다.**

`aspect_ratio`를 보내지 않아도 draft 크기를 항상 판정하므로, **지원 목록에 없는
비율의 이미지를 `draft_image`로 보내면 이제 400**입니다. 이전에는 그런 요청이
정사각으로 왜곡되어 처리됐습니다.

정상 흐름은 영향이 없습니다. `/generate/drafts` 응답을 그대로 쓰면 항상 지원
비율이고, **정사각 이미지는 크기와 관계없이 `1:1`로 판정**되므로 프론트에서
리사이즈·재인코딩을 하더라도 기존과 동일하게 동작합니다.

**422 — Pydantic 필드 타입·범위·Literal validation 실패**

| 조건 |
|---|
| `x`, `y`, `sub_x`, `sub_y`가 0~1 범위를 벗어남 (`ge=0`, `le=1`) |
| `headline_size`, `sub_size`가 **0 이하**이거나 1 초과 (`gt=0`, `le=1`) |
| `align`이 `left`/`center`/`right`가 아님 |
| `position`이 `top`/`center`/`bottom`이 아님 |
| `style`이 `plain`/`bar`가 아님 |
| `headline_z_order`, `sub_z_order`가 `front`/`behind`가 아님 |
| `font_id`가 문자열이 아님 (허용값 검사는 Literal이 아니라 400으로 처리) |
| `background.mode`가 `solid`/`gradient`/`ai`가 아님 |
| `background.direction`이 `vertical`/`horizontal`/`diagonal`이 아님 |
| `category`가 `food`/`beauty`/`goods`가 아님 |
| `aspect_ratio`가 `1:1`/`3:1`/`3:4`가 아님 |
| `placement.scale_factor`가 **0 이하**이거나 3 초과 |
| `placement.x`, `placement.y`가 0~1 범위를 벗어남 |
| `placement`에 `scale_factor`/`x`/`y` 외의 키가 있음 (**extra 금지**) |
| 필수 필드(`draft_image`) 누락 또는 타입 불일치 |

---

## POST /compose/text

**diffusion을 돌지 않고** 이미 만들어진 이미지에 문구만 다시 합성합니다. 문구
위치·크기만 바꿀 때 SDXL을 다시 실행하지 않기 위한 경로입니다. GPU 수초~수십초가
걸리는 `/generate/*`와 달리 CPU에서 수백 ms에 끝납니다.

### 표준 흐름

```text
POST /generate/refine   text 없이, ai_notice=false
        ↓ 프론트가 "문구·표시 없는 고품질 이미지"를 보관
POST /compose/text      base_image = 위 결과, text = 편집한 문구
        ↓ 사용자가 위치·크기를 바꿀 때마다 이 호출만 반복
```

> **`base_image`에는 문구와 AI 생성 표시가 없어야 합니다.** 서버는 이미 픽셀에
> 구워진 문구나 표시를 구분할 수 없어 검증하지 못합니다. 문구가 있는 이미지를
> 넣으면 겹쳐 그려지고, 표시가 있는 이미지에 `ai_notice=true`를 주면 표시가 두 번
> 들어갑니다. 이 조건은 계약으로만 지켜집니다.

### 요청

| 필드 | 타입 | 필수 | 기본값 | 설명 |
|---|---|---|---|---|
| `base_image` | str (base64) | **필수** | — | 문구·AI 표시가 없는 바탕 이미지 |
| `text` | object | **필수** | — | `/generate/refine`과 **같은 `TextSpec`** |
| `ai_notice` | bool | 선택 | `true` | 문구 합성 뒤 최상단에 적용 |

`text`가 refine과 같은 모델이라 프론트는 편집 화면에서 만든 문구 객체를 두
엔드포인트에 그대로 쓸 수 있습니다.

**`style`을 명시해 보내세요.** 기본값이 `"bar"`라 생략하면 문구 뒤에 반투명 박스가
깔립니다. 현재 프론트 UI 기준으로는 `"plain"`을 명시하는 것이 맞습니다.

**`font_id`도 refine과 동일하게 동작합니다.** 같은 `TextSpec`이므로 문구를 다시
합성할 때 폰트만 바꿔서 재요청할 수 있습니다. 지원 ID·오류 코드·미전달 시 동작은
[폰트 선택](#폰트-선택-font_id)과 같습니다.

**좌표는 [문구 필드](#좌표-기준)의 계약과 동일합니다** — `y`는 텍스트 블록의 중심,
`x`는 `align` 기준점이며 중심으로 쓰려면 `align="center"`를 명시합니다. `x`와 `y`는
항상 함께 보냅니다.

### 이번 단계에서 지원하지 않는 것

```text
제품 뒤 문구(z_order="behind")   400. 제품 마스크와 합성 전 배경이 필요한데
                                 이 경로에는 그 재료가 없습니다
제품 위치·크기 편집               /generate/refine의 placement를 사용하세요
비율 변경                        draft 생성 시점에 결정됩니다
```

### 응답

```json
{
  "image": "<PNG base64, prefix 없음>",
  "meta": {
    "elapsed": 0.31,
    "diffusion": false,
    "resolution": 1024,
    "canvas": {"width": 3072, "height": 1024},
    "ai_notice": true,
    "text": { ... },
    "text_layers": {"headline": {...}, "sub": {...}}
  }
}
```

`text` / `text_layers`는 **refine과 같은 형식**이라 프론트가 같은 코드로 다룰 수
있습니다. `resolution`은 짧은 변, `canvas`는 `base_image`의 실제 크기입니다.

`sub_x` / `sub_y`를 보내면 이 경로에서는 쓰이지 않고
[`meta.ignored_fields`](#metaignored_fields--요청됐지만-적용되지-않은-필드)에
기록됩니다. refine의 같은 `z_order` 경로와 동일한 기준입니다.

`aspect_ratio`와 `placement`는 **내려가지 않습니다.** 이 API는 비율을 정하지도
제품을 배치하지도 않습니다.

### 오류 응답

**400**

| 조건 | 메시지 |
|---|---|
| `headline`과 `sub`가 모두 비어 있음 | `합성할 문구가 없습니다. headline 또는 sub 중 하나는 필요합니다.` |
| `headline_z_order` 또는 `sub_z_order`가 `behind` | `{"error": "text_behind_not_supported", "supported": ["front"]}` |
| `text.font_id`가 지원 목록에 없음 | `{"error": "font_not_supported", "supported": [...], "available": [...]}` |
| `text.font_id`는 지원하지만 서버에 TTF 자산이 없음 | `{"error": "font_asset_missing", "font_id": ..., "available": [...]}` |
| base64 디코딩 실패 | `이미지 디코딩 실패: {오류}` |

**422** — `TextSpec`의 기존 검증이 그대로 적용됩니다(`x`/`y` 0~1, `headline_size`
0 초과 1 이하, `align`·`style`·`position`·`z_order` Literal). `base_image`나 `text`
누락도 422입니다.

---

## 그 외 엔드포인트

| 메서드 | 경로 | 요청 | 응답 | 용도 |
|---|---|---|---|---|
| POST | `/compose/text` | 위 참고 | `{"image": ..., "meta": ...}` | diffusion 없이 문구만 재합성 |
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
    "headline_size": 0.075, "sub_size": 0.04,
    "font_id": "pretendard"
  }
}
```

`font_id`는 선택입니다. 생략하면 서버 기본 폰트로 그려집니다. 지정하면 headline과
sub가 **모두** 그 폰트로 그려집니다.

### 3:1 배너 (비율 지정, 배치는 서버에 맡김)

```json
POST /generate/drafts
{"mode": "inpaint", "image": "<base64>", "category": "beauty",
 "background_mode": "solid", "bg_colors": ["#F5F1EC"],
 "aspect_ratio": "3:1"}
```

응답 `meta`에서 배치를 받아 refine에 이어 붙입니다.

```json
POST /generate/refine
{"draft_image": "<고른 시안>", "original_image": "<원본>",
 "background": {"mode": "solid", "colors": ["#F5F1EC"], "direction": null},
 "placement": {"scale_factor": 1.0, "x": 0.7681, "y": 0.458},
 "text": {"headline": "여름 한정", "x": 0.06, "y": 0.35, "align": "left"}}
```

`aspect_ratio`는 draft 크기(2304 × 768)에서 자동으로 `3:1`로 판정되므로 생략해도
됩니다. `placement`도 생략하면 서버 기본 배치가 적용됩니다.

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

### 문구만 재합성 (폰트 변경)

`/generate/refine`을 다시 돌리지 않고 폰트만 바꿉니다. diffusion을 타지 않아 빠릅니다.

```json
POST /compose/text
{
  "base_image": "<문구·AI 표시가 없는 refine 결과>",
  "text": {
    "headline": "여름 한정 특가",
    "sub": "오늘 하루만 20% 할인",
    "x": 0.5, "y": 0.5,
    "align": "center", "style": "plain",
    "headline_size": 0.09, "sub_size": 0.04,
    "font_id": "nanummyeongjo"
  },
  "ai_notice": true
}
```

`font_id`만 바꿔 다시 호출하면 같은 위치·크기에 다른 폰트로 그려집니다. 사용자가
폰트를 고르는 UI는 이 호출만 반복하면 됩니다.

---

## 아직 미구현

| 항목 | 상태 | 비고 |
|---|---|---|
| AI 배경의 3:4 생성 | 미구현 | `3:1`은 지원합니다. `3:4`만 400입니다. 투명 제품(유리병)에서 AI가 제품 마스크 바깥으로 구조를 이어 그리는 현상이 반복 확인됐고, 불투명 제품에서는 재현되지 않았으나 위험 제품을 자동으로 구분할 방법이 없어 보류 중입니다 |
| 여러 비율 일괄 반환 | 미구현 | 응답이 이미지 1장 고정. 비율별로 요청을 나눠 보내야 함 |
| 제품 자동 배치의 문구 연동 | 미구현 | 현재 기본 배치는 **문구 내용을 보지 않습니다.** 문구 길이에 맞춰 제품 크기를 조정하는 기능은 실험 단계 |
| 폰트 목록 조회 API (`GET /fonts`) | 미구현 | 지원 ID 5종은 이 문서에 고정되어 있습니다. 프론트가 목록을 서버에서 받아오는 경로는 아직 없습니다 |
| `font_weight` 파라미터 | 미구현 | `font_id` 하나가 특정 파일 하나를 가리킵니다. 굵기를 따로 고르는 파라미터는 없습니다 |
| headline·sub 폰트 개별 선택 | 미구현 | 폰트는 하나만 골라 양쪽에 공통 적용합니다 |
| 챗봇 문구 자동 전달 연동 | 미구현 | 문구는 클라이언트가 직접 넣어야 함 |
| 문구 자동 배치 | 미구현 | 서버는 **문구** 좌표를 계산하지 않음. `meta.layout`을 보고 클라이언트가 계산. 제품 배치는 서버가 계산하며 `meta.placement`로 내려감 |
| 멀티라인 줄별 독립 좌표 | 미구현 | 위 "알려진 제한" 참고 |

### 비율·배치 기능 요약

| 항목 | 상태 |
|---|---|
| `solid` / `gradient`의 1:1 · 3:1 · 3:4 | **지원** |
| **AI 배경의 1:1 · 3:1** | **지원** |
| 서버 기본 제품 배치 | **지원** (비율별 자동 계산) |
| 클라이언트 배치 override (부분 지정 포함) | **지원** |
| 배치 안전성 서버 재검증 | **지원** (벗어나면 400 + `suggested`) |
| AI 배경의 3:4 | 미지원 (400) |
| `text2img`의 비정사각·배치 | 미지원 (400) |
| 문구 내용 기반 자동 배치 | 미지원 (실험 단계) |
| **`font_id`로 폰트 선택** (refine·compose 공통) | **지원** (계약상 5종 / 현재 브랜치 자산 2종) |

기본 배치는 문구 내용에 의존하지 않습니다. 비율마다 제품이 놓일 영역이 정해져
있고, 그 안에서 제품과 그림자가 잘리지 않는 최대 크기로 배치합니다. 문구 영역은
비워두므로 클라이언트가 `text.x` / `text.y`로 문구를 배치하면 됩니다.

배치 파라미터의 구체적인 값(영역 분할 비율, 확대 상한 등)은 **내부 구현이며 API
계약이 아닙니다.** 실사용 피드백에 따라 조정될 수 있고, 조정되어도 요청/응답
필드는 바뀌지 않습니다.

---

## 검증 스크립트

| 명령 | 필요 조건 | 내용 |
|---|---|---|
| `PYTHONPATH="$PWD" python tests/test_zorder_api.py` | 없음 | z_order 4개 조합·validation·하위호환 자동 판정 |
| `PYTHONPATH="$PWD" python tests/test_background_validation.py` | 없음 | 배경 색상 validation(빈 배열·형식·모드별 차이) 자동 판정 |
| `PYTHONPATH="$PWD" python tests/test_drafts_canvas_api.py` | 없음 | drafts의 비율·배치 요청/응답 계약, 1:1 회귀 자동 판정 |
| `PYTHONPATH="$PWD" python tests/test_refine_canvas_api.py` | 없음 | refine의 비율 추론·교차검증·placement round-trip 자동 판정 |
| `PYTHONPATH="$PWD" python tests/test_ai_nonsquare_api.py` | 없음 | 3:1 AI 경로, 1:1 AI 회귀(파이프 인자 수준), 3:4 AI 400 유지 자동 판정 |
| `PYTHONPATH="$PWD" python tests/test_text_coords.py` | 없음 | 문구 좌표 계약(y=블록 중심), 프리셋 경로 픽셀 회귀 |
| `PYTHONPATH="$PWD" python tests/test_text_compose_api.py` | 없음 | `/compose/text` 동작·좌표·ai_notice 순서·오류·기존 계약 회귀 |
| `PYTHONPATH="$PWD" python tests/test_font_id.py` | 없음 | `font_id` whitelist·400 두 종류·headline/sub 공통 적용·미전달 시 픽셀 회귀 |
| `PYTHONPATH="$PWD" python tests/test_aspect_contract.py` | 없음 | 비율 추론 tolerance, 배치 좌표 변환 단위 검증 |
| `PYTHONPATH="$PWD" python tests/test_output_size.py` | 없음 | 출력 캔버스 크기 계산 |
| `PYTHONPATH="$PWD" python tests/test_placement.py` | 없음 | 비율별 기본 배치, 제품·그림자 clipping |
| `PYTHONPATH="$PWD" python tests/test_canvas_bridge.py` | 없음 | W×H 캔버스 변환, 1:1 항등 경로 |
| `PYTHONPATH="$PWD" python scripts/verification/api/smoke_zorder_api.py` | 서버 + GPU | 실제 API로 behind/front 및 회귀 확인 |
| `PYTHONPATH="$PWD" python scripts/verification/api/smoke_api_endpoints.py` | 서버 + GPU | draft→refine 기본 흐름 |
| `PYTHONPATH="$PWD" python scripts/verification/placement/verify_product_placement.py` | rembg | 제품 배치(미반영 기능) 검증 |
| `PYTHONPATH="$PWD" python scripts/verification/zorder/verify_zorder_behind.py` | rembg | z_order 실험(자동 배치 포함, 미반영) |
| `PYTHONPATH="$PWD" python scripts/verification/poster/verify_poster_real.py <name>` | 서버 + GPU | 실제 제품 포스터 생성 |
| `PYTHONPATH="$PWD" python scripts/verification/typography/verify_autofit.py` | 없음 | 자동 크기 맞춤 비교 이미지 |
| `PYTHONPATH="$PWD" python scripts/verification/shadow/check_shadow_shapes.py` | rembg | 제품 실루엣·그림자 진단 |
| `PYTHONPATH="$PWD" python scripts/verification/shadow/batch_verify_shadow.py` | 서버 + GPU | 그림자 배치 검증 |

결과물은 각각 `outputs/verification/<카테고리>/`에 저장되며 git에는 포함되지 않습니다.
