# 로컬 검증 가이드

그림자·배경·문구 합성이 의도대로 동작하는지 로컬에서 확인하는 절차와, 지금까지의
실측 기록·알려진 제한을 정리한 문서입니다.

주로 쓰는 스크립트는 `scripts/verification/shadow/check_shadow_shapes.py`,
`scripts/verification/shadow/batch_verify_shadow.py`,
`scripts/verification/api/smoke_api_endpoints.py` 세 가지입니다.

아래 명령은 모두 **`poster_model/` 디렉터리 기준**입니다.

## 0. 사전 준비

```bash
cd poster_model
source .venv/bin/activate          # 없으면 python -m venv .venv 로 먼저 생성
python -c "import torch; print(torch.cuda.is_available())"   # True 나와야 함
```

GPU가 필요한 검증(diffusion 호출)과 필요 없는 검증(rembg 마스크·문구 합성)이 나뉩니다.
각 단계에 표시해두었습니다. 테스트 입력 이미지는 저장소에 포함되어 있지 않으므로
루트 `README.md`의 "테스트 입력 이미지" 절을 참고해 `image/`에 준비해야 합니다.

## 1단계 — 그림자 모양만 빠르게 확인 (GPU 불필요, 수 초)

diffusion 없이 rembg 마스크만으로 그림자가 실루엣에 잘 맞는지 먼저 본다.

```bash
PYTHONPATH="$PWD" python scripts/verification/shadow/check_shadow_shapes.py
```

결과: `outputs/verification/shadow/shadow_shape_check.png` (6장 격자)
- 반투명 흰색 = 실제 제품 실루엣(마스크)
- 빨간 사각형 = 그림자 폭 계산에 쓰인 bbox (참고용, 항상 사각형으로 보임)
- 회색 바닥의 어두운 타원 = 후처리로 그려진 그림자

**1차 실행 결과(완료)**: cake/glass/monster_side/monster_top/snack은 제품이 하나의 덩어리라 bbox 폭
그대로 써도 자연스러웠습니다. cosmetic.jpg는 병 2개가 한 마스크로 잡혀서 그림자 하나가 둘을
가로지르는 문제가 있었고, `add_ground_shadow`를 **연결요소(connected component)별로 개별 그림자를
그리도록** 수정해서 해결했습니다(작은 노이즈 덩어리는 `SHADOW_MIN_AREA_RATIO`로 무시). 다시 돌려서
cosmetic.jpg에 병마다 그림자가 따로 생겼는지 확인해주세요.

## 2단계 — 전체 파이프라인(프롬프트 + 후처리) 확인

터미널 A:
```bash
uvicorn api:app --host 0.0.0.0 --port 8000
```

터미널 B (기존 스크립트, cake.jpg 1장 + 좌표모드/position 폴백 둘 다 확인):
```bash
PYTHONPATH="$PWD" python scripts/verification/api/smoke_api_endpoints.py
```

6장을 확인하려면 (제품마다 draft 768 + refine 1024 저장):
```bash
PYTHONPATH="$PWD" python scripts/verification/shadow/batch_verify_shadow.py
```

**주의**: 6장을 한 번에 돌리다 컴퓨터가 멈추는 문제가 있었어서, 스크립트 기본값을
**한 번에 2장(`LIMIT = 2`)**만 처리하도록 낮췄습니다. 안정적으로 돌면 스크립트 상단의
`LIMIT` 값을 늘려서 재실행하세요. 처리 후엔 `image/*.jpg` 순서대로 앞의 `LIMIT`장만
처리하니, 전체를 보려면 `LIMIT`을 6으로 올리거나 여러 번 나눠 돌리면 됩니다.

결과: `outputs/verification/shadow/shadow_verify_out/{이름}_draft768.png`, `{이름}_refine1024.png`

**확인 포인트**:
- (우려 1) 실제 생성된 배경 위에서 그림자가 자연스러운지
- (우려 4) 프롬프트에 추가한 `"soft contact shadow under product, grounded, sitting on surface"`
  문구가 배경에 이상한 바닥 무늬나 여분의 사물을 만들어내지 않는지
- 그림자가 너무 진하거나 연하면 `config.SHADOW_OPACITY` (기본 110, 0~255) 조정
- 그림자가 너무 퍼지거나 딱딱하면 `config.SHADOW_BLUR` (기본 18px) 조정
- 그림자가 너무 넓거나 좁으면 `config.SHADOW_SQUASH` (기본 0.28, 타원 높이/너비 비율) 조정

## 3단계 — 해상도별 그림자 두께 비교 (우려 3)

2단계에서 나온 같은 제품의 `_draft768.png`와 `_refine1024.png`를 나란히 놓고 비교한다.

```bash
python3 - << 'PY'
from PIL import Image
name = "cake"  # 확인할 이름으로 변경
a = Image.open(f"outputs/verification/shadow/shadow_verify_out/{name}_draft768.png").resize((512,512))
b = Image.open(f"outputs/verification/shadow/shadow_verify_out/{name}_refine1024.png").resize((512,512))
grid = Image.new("RGB", (1024, 512), (255,255,255))
grid.paste(a, (0,0)); grid.paste(b, (512,0))
grid.save("outputs/verification/shadow/res_compare.png")
PY
```

`SHADOW_BLUR`/`SHADOW_OPACITY`가 비율이 아니라 고정 px라서, 1024가 768보다 그림자가
상대적으로 얇고 옅어 보일 가능성이 있다. 눈에 띄게 다르면 두 값을 이미지 크기(unit) 비례로
바꾸는 게 맞다 (다른 텍스트 관련 파라미터처럼 `*_RATIO` 형태로).

## 문제 해결 — 여러 장 연속 생성 시 컴퓨터가 멈추는 경우

원인을 이 세션에서 직접 재현/디버깅은 못 했지만(GPU 없음), 가능성이 높은 순서대로:

1. **WSL2 메모리 설정** — `%UserProfile%\.wslconfig`에 `memory=` 값이 없으면 WSL2가 호스트
   RAM 대부분을 쓸 수 있어, 6장 연속 생성 중 시스템 RAM이 바닥나 스와핑으로 멈춘 것처럼 보일 수
   있습니다. `.wslconfig`에 `memory=10GB` 식으로 상한을 주고 `wsl --shutdown` 후 재시작해보세요.
2. **GPU 메모리 누적** — 다른 터미널에서 `watch -n1 nvidia-smi`로 VRAM 사용량을 보면서 배치를
   돌려서, 이미지마다 VRAM이 계속 늘어나기만 하는지(누수) 확인하세요. 이번에 추가한
   `POST /admin/gc` 엔드포인트를 이미지 사이에 호출하도록 `batch_verify_shadow.py`에 넣어뒀는데,
   그래도 계속 늘어나면 근본적으로는 서버를 주기적으로 재시작하는 수밖에 없습니다.
3. **동시 로딩된 파이프라인 수** — `warmup()`이 SD1.5 inpaint/text2img + SDXL inpaint 3개를
   한꺼번에 메모리에 올려둡니다. 이 검증만 할 땐 SD1.5 text2img는 안 쓰이니, 테스트 중에는
   `pipeline/generate.py`의 `warmup()`에서 `_load(config.DRAFT_MODEL, "text2img")` 줄을
   잠시 주석 처리해 기본 점유량을 줄여볼 수 있습니다(끝나면 원복).
4. 그래도 재현되면 `LIMIT=1`로 한 장씩만 처리하면서 어느 이미지/단계(draft 768 vs refine 1024)에서
   멈추는지 좁혀보는 게 다음 단서가 됩니다.

## 체크리스트 요약

| 항목 | 확인 방법 | 문제 시 조정 |
|---|---|---|
| 그림자 폭이 실제 접지면과 맞는가 | 1단계 `shadow_shape_check.png` | (완료) 연결요소별 그림자로 개선 |
| 여러 제품이 한 사진에 있을 때 그림자가 따로 생기는가 | 1단계 cosmetic.jpg | `SHADOW_MIN_AREA_RATIO`로 노이즈 임계값 조정 |
| 그림자가 자연스러운가 (실제 배경 위) | 2단계 `shadow_verify_out/` | `SHADOW_OPACITY`, `SHADOW_BLUR` |
| 프롬프트 문구 부작용 있는가 | 2단계 결과 배경 육안 확인 | `config.SHADOW_PROMPT_SUFFIX` 문구 수정/제거 |
| 768 vs 1024 그림자 비율 일치하는가 | 3단계 비교 이미지 | 고정 px → 비율 기반으로 전환 |
| 연속 생성 시 멈추지 않는가 | 배치 스크립트 LIMIT 늘려가며 확인 | 위 "문제 해결" 절 참고 |

문제를 발견하면 파라미터 값과 함께 알려주면 바로 반영하겠습니다.


## 부록 — background_mode(solid/gradient/ai) 검증

`scripts/verification/shadow/batch_verify_shadow.py` 상단의 `BACKGROUND_MODE`를 바꿔서 실행하면 된다.

```python
BACKGROUND_MODE = "ai"        # 기존 동작 그대로 (기본값, diffusion 사용)
BACKGROUND_MODE = "solid"     # 단색 배경, diffusion 완전 생략
BACKGROUND_MODE = "gradient"  # 2색 그라데이션, diffusion 완전 생략
BG_COLORS = ["#3A5A40"]           # solid=1개 / gradient=2개. None이면 카테고리 팔레트 사용
GRADIENT_DIRECTION = "vertical"   # gradient일 때만. None이면 "vertical" 기본
```

**확인 포인트**:
- ai → solid/gradient로 바꿔도 `smoke_api_endpoints.py` 등 기존 스크립트 동작(=background 필드를
  안 보내는 경우)은 전혀 안 바뀌는지 (하위 호환)
- solid/gradient에서 `run_log.json`의 `diffusion` 값이 `false`로 찍히는지
- refine 결과(1024)가 draft(768)를 확대한 게 아니라 원본+마스크로 새로 렌더링됐는지 —
  두 해상도 배경 색이 픽셀 단위로 다를 수 있는데(같은 색이라도 그라데이션 방향/보간이
  해상도별로 다시 계산됨) 이건 의도된 동작이다.
- 사용자가 색을 직접 지정했을 때 draft 3장의 `background.colors`가 실제로 어떻게
  변형됐는지(예: base/light/dark) — 정확히 지정한 색과 다를 수 있으니, 필요하면
  `config.BG_VARIANT_LIGHTNESS_DELTA` 값을 조정

**성능**: "20초 → 1초"는 아직 실측이 아니라 예상치다. `run_log.json`의 `elapsed_total`로
실제 시간을 측정해서 비교해달라.

**이번 범위에 포함 안 된 것**: `shadow_mode`(flatlay/grounded 분리)는 이번 변경에
포함하지 않았다. solid/gradient 결과를 먼저 확인한 뒤 다음 단계로 진행한다.

## 부록 — 누끼(세그멘테이션) 후속 실험 백로그 (동결)

현재 누끼 파이프라인(u2net, tight/dilated 마스크 분리, halo 개선)은 여기서 동결한다.
포스터 레이아웃(문구 크기/배치/z-order) 검증이 먼저이고, 아래 항목은 그 기본기가
안정화된 뒤에 별도로 진행할 후속 실험으로만 기록해둔다 — 지금 구현하지 않는다.

- soft alpha 정제: 현재 tight mask는 이진(0/255)에 가까워, 반투명/유리 재질 경계가
  살짝 딱딱해 보일 수 있음. 필요하면 alpha 경계를 부드럽게 다듬는 후처리 검토.
- 투명 제품 후처리: 유리병/투명 용기처럼 배경이 비치는 제품은 단순 마스킹만으로는
  경계에 옅은 회색 테두리가 남을 수 있음(halo 수정 때 "마스크를 더 줄이지 말라"는
  제약으로 남겨둔 부분). 별도 보정 로직 필요 여부 검토.
- 사용자 마스크 수정 기능: 자동 세그멘테이션이 틀렸을 때 사용자가 직접 마스크
  경계를 보정할 수 있는 UI/API 여부 (프론트 협의 필요, 범위 큼).

## 부록 — 포스터 레이아웃 검증 (auto_fit / 어절 줄바꿈 / z_order 실험)

`scripts/verification/poster/verify_poster_real.py` — plain + auto_fit + 톤별 프리셋(`config.TONE_PRESETS`)으로
실제 제품 사진에 문구를 배치하는 검증. 헤드라인이 제품 bbox를 가리지 않도록
`max_height_ratio`로 회피 영역을 계산한다. 한 번에 샘플 하나씩:
`PYTHONPATH="$PWD" python scripts/verification/poster/verify_poster_real.py cosmetic|snack|glass`

`scripts/verification/zorder/verify_zorder_behind.py` — z_order="behind"(제품이 헤드라인 일부를 가리는 연출)를
`generate.py`/`api.py` 수정 없이 pipeline의 기존 export 함수만 조합해 재현하는 A안 검증.
diffusion을 쓰지 않으므로(solid 배경 한정) API 서버 없이 바로 실행 가능:
`PYTHONPATH="$PWD" python scripts/verification/zorder/verify_zorder_behind.py`
front(기존 방식)/behind(제품이 헤드라인 일부를 가림) 결과를 나란히 비교하는
`snack_bold_promo_compare.png`를 만든다. 실제 결과로 통합감이 뚜렷이 개선된다고
확인되면, 그때 `generate.py`(refine 내부 렌더 순서)와 `api.py`(TextSpec에 z_order
필드 추가)에 정식 반영하는 범위를 제안한다 — 그 전까지 프로덕션 코드는 변경하지 않는다.

## 부록 — 문구 레이어 순서(z_order) 사용법

`POST /generate/refine`의 `text`에 다음 필드가 추가됐다. **둘 다 기본값이 `"front"`라
이 필드를 안 보내면 기존 동작과 완전히 동일하다.**

```python
headline_z_order: "front" | "behind" = "front"
sub_z_order:      "front" | "behind" = "front"
sub_x, sub_y: float | None            # 아래 "제약" 참고
```

렌더링 순서는 항상 이렇게 고정된다:

```text
배경 → 그림자 → behind 문구 → 제품 합성 → front 문구 → AI 생성물 표시
```

`behind`로 지정한 문구는 제품이 합성되기 **전에** 그려지므로, 제품이 그 문구의 일부를
자연스럽게 가린다(참고 포스터의 오클루전 연출). 검증에서 확인된 대표 조합:

```json
{"headline_z_order": "behind", "sub_z_order": "front",
 "x": 0.5, "y": 0.05, "sub_x": 0.5, "sub_y": 0.88,
 "align": "center", "style": "plain"}
```

### 제약 (validation에서 400으로 거부)

- **원본 필요**: `behind`는 제품을 원본에서 다시 합성하는 경로에서만 된다.
  `original_image` 없이 돌아가는 img2img 폴백 경로에는 "제품 뒤"라는 레이어 자체가
  없어서 명시적으로 거부한다.
- **`style="bar"` + 서로 다른 z_order 불가**: 두 z_order가 다르면 headline과 sub을
  각각 다른 레이어에 그려야 해서 `render_text`를 두 번 호출하게 되고, `bar`는 바가
  두 개 그려져 기존 결과와 달라진다. 이 경우 `style="plain"`만 허용한다.
  두 z_order가 **같으면** 기존처럼 한 번에 그리므로 `bar`도 그대로 쓸 수 있다.
- **`sub_x`/`sub_y` 필수 조건**: 두 z_order가 다르고 좌표 모드(`x`, `y`)를 쓰는 경우,
  sub가 headline과 같은 자리에 겹쳐 그려지지 않도록 `sub_x`/`sub_y`를 함께 보내야 한다.

### 알려진 제한 — 멀티라인 headline의 줄별 오클루전 제어 불가

`headline`은 문자열 하나이고 `y`는 **블록 전체의 시작점**이다. 따라서 `"MELON\nKICK"`처럼
여러 줄일 때 둘째 줄의 위치는 `y + headline_size * 1.35`로 자동 결정되며, **줄마다 위치를
따로 지정할 수 없다.**

실제 `snack.jpg`(`product_top ≈ 0.173`)에서 `y=0.02`로 고정하고 크기별 둘째 줄(KICK)
노출률을 실측한 결과:

| headline_size | MELON 하단 | KICK 노출률 |
|---|---|---|
| 0.16 | 0.1489 | 0% (완전히 가려짐) |
| 0.12 | 0.1167 | 0% |
| 0.10 | 0.1011 | 21% |
| 0.09 | 0.0932 | 42% |
| 0.08 | 0.0835 | 72% |
| 0.07 | 0.0766 | 100% (오클루전 효과 없음) |

즉 **"첫 줄 완전 노출 + 둘째 줄 부분 가림"을 만족하는 크기는 0.08 부근뿐이고, 이는
`bold_promo`가 의도한 큰 타이포(0.16~0.28)의 절반**이다. 큰 타이포와 부분 오클루전을
동시에 얻으려면 줄별로 `y`를 따로 주거나 제품 위치를 옮겨야 하는데, 둘 다 이번 최소
구현 범위 밖이다.

- **회피 방법(현재)**: headline을 한 줄로 쓰거나, 위 표를 참고해 크기를 조정한다.
- **후속 기능**: 줄별 오클루전 제어(줄마다 좌표 지정) 또는 확장 구현의 자동 배치
  (제품 이동 포함). 실험적 구현은 `scripts/verification/zorder/verify_zorder_behind.py`에 있다 — 거기서는
  큰 타이포(0.16)를 유지하기 위해 **제품을 아래로 이동**(`shift_ratio ≈ 0.10`)시켜
  해결했고, 이 제품 이동 로직은 프로덕션에 포함하지 않았다.

### 지원 범위

- **refine 단계에서만** 지원한다(draft는 원래 문구 합성이 없다).
- **자동 배치는 포함하지 않는다** — 제품 bbox 기준 headline 크기/위치 자동 조정,
  겹침 비율 자동 계산, 공간 부족 시 제품 자동 이동은 이번 범위에 없다. 클라이언트가
  draft 응답의 `meta.layout`(제품 bbox 비율)을 보고 좌표를 직접 계산해 넘기는 구조다.
  이 계산의 실험적 구현은 `scripts/verification/zorder/verify_zorder_behind.py`에 있다(프로덕션 코드 아님).

### 응답 meta

기존 `meta.text`(단일 dict)는 **구조를 그대로 유지**하고, 레이어 정보는 additive로
`meta.text_layers`에 따로 담긴다.

```json
{"text_layers": {
    "headline": {"z_order": "behind", "x": 0.5, "y": 0.05, "applied_size": 0.16},
    "sub":      {"z_order": "front",  "x": 0.5, "y": 0.88, "applied_size": 0.05}}}
```

### 검증

`tests/test_zorder_api.py` — GPU 없이 스키마/분기 배선만 확인하는 테스트
(4개 z_order 조합, validation 3종, 하위호환, AI 표시 1회, overlay.py 무변경).
`PYTHONPATH="$PWD" python tests/test_zorder_api.py`로 실행한다.


## 부록 — 제품 배치(product_placement) 실험 검증 결과

**상태: 실험 검증 완료 / 프로덕션 미반영.** `place_product()`는 아직
`scripts/verification/placement/verify_product_placement.py`에만 있고 `pipeline/masking.py`에는 없다.
프로덕션 반영 시 이 함수를 로직 수정 없이 그대로 옮기고, `api.py`·`generate.py`에
`product_placement` 필드를 추가하면 된다.

목적은 `minimal_product`의 비대칭 레이아웃(제품 우측·문구 좌측)이다.
`PYTHONPATH="$PWD" python scripts/verification/placement/verify_product_placement.py`로 실행한다(GPU 불필요, rembg 가중치는 필요).

### 확정된 설계 결정

- **순서**: `prepare_image()`(`add_blur_margin` 포함) → `place_product()`.
  `scale=1.0`은 원본 파일이 아니라 **전처리 완료 후 제품 bbox** 기준 배율이다.
  자동 margin 축소와 placement scale이 연속 적용될 수 있어 meta에 요청값/적용 중심/
  배치 전후 bbox를 모두 남긴다.
- **scale 범위**: `0 < scale <= 1.5`. 별도 업스케일링 없이 일반 리사이즈만 쓴다.
- **프레임 이탈**: 자동 clamp나 잘라내기 없이 `PlacementOutOfFrame`으로 거부하고,
  현재 scale 기준 허용 중심 좌표 범위를 오류에 함께 담는다.
- **`add_blur_margin` 자체는 변경하지 않는다.**

### 왜 `base` 전체 아핀 변환을 쓰지 않았나

`base` 전체를 옮기면 제품뿐 아니라 **원본 배경 픽셀까지 함께 이동**해, 원래 제품이
있던 자리에 배경 잔상이 남고 테두리에 원본 배경이 딸려온다. 그래서 다음 순서로 처리한다.

```text
base + tight mask -> 제품 RGBA 레이어만 추출
-> 레이어와 tight mask에 동일한 이동/크기 변환
-> 변환된 tight mask에서 inpaint mask를 기존 규칙(DILATE -> MASK_BLUR)으로 재생성
   (변환된 blur mask를 다시 블러하면 이중 블러가 되므로 반드시 "재생성")
-> 이후 그림자/합성 단계는 새 마스크를 그대로 쓴다
```

`add_ground_shadow()`는 손댈 필요가 없다. `generate.py`가 이미
`add_ground_shadow(배경, masks.product)` 순서로 부르므로, 그 전에 마스크를 교체하면
그림자가 자동으로 새 위치에서 계산된다.

### bleed(가장자리 색 번짐)가 필요한 이유

제품 레이어만 옮기면 마스크 바깥은 빈 캔버스가 된다. 그런데 `composite_product()`가
마스크를 `COMPOSITE_BLUR`(=2)로 블러해 합성하기 때문에, 경계 바깥 몇 px이 `base`에서
읽히면서 그 빈 캔버스 색이 얇게 배어난다. 그래서 제품 가장자리 색을 마스크 **바깥으로만**
`BLEED_PX`(=6)px 번지게 채운다(`cv2.inpaint`).

**마스크 자체는 넓히지 않는다** — halo 수정 때의 "마스크를 추가로 축소/확대하지 말 것"
제약과 충돌하지 않는다. 색만 번지게 할 뿐이다.

필요성은 대조군으로 실측했다(마젠타 배경 + 청록 제품 합성 케이스, 경계 밴드 5,744px):

| 항목 | 값 |
|---|---|
| `BLEED_PX=0` vs `6` 평균 색차 | 76.8 |
| 색차 30 이상(눈에 보이는 수준) 픽셀 | 5,149 |

### 검증 결과

합성 케이스(의도적으로 눈에 띄는 배경색 사용):

| 항목 | 결과 |
|---|---|
| 요청 중심 vs 실제 중심 | dx 0.0002 / dy 0.0001 |
| 요청 배율 0.85 vs 실제 | 0.845 |
| 제품 테두리 배경색 유출 | 0px |
| 그림자 중심 | 0.680 (제품 중심 0.68) |
| placement 미전달 시 | 원본 객체 그대로 반환(무변경) |
| "잔상"으로 검출된 1,032px | 전부 새 마스크로부터 2.9px 이내 = 의도한 bleed 밴드 |

실제 이미지(`cosmetic.jpg`, `snack.jpg`):

- 제품 이동(x, y) 및 scale 적용 정상
- before/after 비교에서 의도한 위치로 이동, 비대칭 포스터 구도 개선 확인
- 프레임 이탈 요청(`x=0.95`) 정상 거부
- 투명 용기(cosmetic) 경계에서 bleed가 유리 너머 배경색을 끌고 오는 현상 없음

### 프로덕션 반영 시 변경 범위 (아직 하지 않음)

| 파일 | 변경 |
|---|---|
| `masking.py` | `place_product()` **추가만**. 기존 함수 무변경 |
| `pipeline/__init__.py` | export 1줄 |
| `generate.py` | `prepare_image()` 호출 4곳 뒤에 조건부 호출, `product_placement` 파라미터, meta 기록 |
| `api.py` | `ProductPlacement` 모델 + `DraftRequest`/`RefineRequest`/`DraftItem` 3곳 |
| `overlay.py` | 변경 없음 |

`DraftItem`에도 넣어 **무상태 왕복**(draft에서 적용한 값을 refine에 되돌려 보냄)을
만드는 게 중요하다. `background`와 같은 패턴이며, 없으면 사용자가 고른 draft와
refine 결과의 제품 위치가 달라진다.

### z-order와의 역할 분리

두 기능은 다른 축을 다뤄 충돌하지 않는다.

- **배치**: 제품의 기하(위치·크기) → `generate.py` 내부, `prepare_image()` 직후
- **z-order**: 문구의 레이어 순서 → `api.py`, 이미 만들어진
  `pre_product`/`base`/`product_mask`를 소비

배치가 먼저 적용되므로 `generate.py`가 반환하는 `pre_product`/`base`/`product_mask`가
자동으로 이동된 제품을 반영한다. 따라서 배치를 반영해도 `api.py`의 z-order 코드는
고칠 필요가 없다.

### 후속 기능 (이번 범위 아님)

- 자동 clamp 또는 의도적인 일부 잘림 허용
- 제품 유형별 배치 프리셋 (`TONE_PRESETS`에 넣을지는 미정 — 배치 최적값이 사진마다
  달라서, 현재는 클라이언트가 명시적으로 넘기고 권장값은 문서로만 둔다)
- 확대 시 업스케일링 모델 적용

`minimal_product` 권장 시작값(실측 후 조정 필요):

```json
{"product_placement": {"x": 0.68, "y": 0.60, "scale": 0.85},
 "text": {"x": 0.08, "y": 0.18, "align": "left", "style": "plain"}}
```
