# 포스터 이미지 생성 모델

소상공인 광고 콘텐츠 생성 서비스의 **이미지 파트**입니다.
제품 사진을 받아 배경을 교체하고, 접지 그림자와 광고 문구를 합성해 포스터를 만듭니다.

```text
제품 사진 → 누끼(rembg) → 배경 생성 → 접지 그림자 → 원본 제품 복원 → 문구 합성 → AI 표시
```

핵심은 **제품 픽셀 보존**입니다. diffusion만으로는 포장지의 로고와 한글이 뭉개지기 때문에,
생성 결과 위에 원본 제품을 마스크로 다시 덮어씌웁니다.

학원·체육관처럼 보여줄 제품이 없는 업종은 **서비스형** 경로로 처리합니다. 사진 없이
`mode="text2img"`로 배경을 통째로 생성하며, 제품 전제 프롬프트를 붙이지 않습니다.
요청에 `subject_kind="service"`를 보내면 됩니다.

---

## 현재 구현 범위

필드 단위 명세는 `docs/api.md`에 있습니다. 여기서는 **무엇까지 되는지**만 정리합니다.

### 되는 것

| | 범위 |
|---|---|
| 생성 흐름 | 시안 3장 생성 → 사용자 선택 → 고품질 렌더링. 2단계 모두 API로 노출 |
| 배경 | AI 생성(SD1.5 inpaint / SDXL refine), 단색, 그라데이션 |
| 제품 보존 | 누끼 마스크로 원본 제품을 최종 해상도에서 다시 합성. 로고·한글이 뭉개지지 않음 |
| 출력 비율 | 단색·그라데이션 **1:1 · 3:1 · 3:4** / AI 배경 **1:1 · 3:1** |
| 제품 배치 | 크기·위치를 클라이언트가 지정 가능(`placement`). 서버가 안전성을 재검증하고 벗어나면 400 |
| 문구 | 좌표 지정, 정렬, 크기, 자동 맞춤, 제목·본문 분리 배치, 제품 앞뒤 레이어 순서 |
| 서체 | 5종 선택(`font_id`). 자산 전부 확보 |
| 타이포 프리셋 | 2종(`tone`) — 크기·서체 역할·외곽선·색을 묶음으로 적용 |
| 문구만 재합성 | `POST /compose/text` — diffusion 없이 문구만 다시 얹음 |
| 서비스형 | 제품 없는 업종용 경로. 해상도·재해석 강도를 제품형과 분리 |
| AI 생성 표시 | 결과물 우측 하단에 자동 합성 |

### 안 되는 것

| | 상태 |
|---|---|
| AI 배경의 3:4 | **막아둠(400).** 투명 제품에서 제품 영역 밖으로 구조가 생성되는 현상이 확인됐고, 위험 제품을 자동으로 가릴 방법이 없어 열지 않음 |
| 제품 회전 | 내부 구현은 있으나 **API로 노출하지 않음** |
| 문구 자동 배치 | 서버는 문구 좌표를 계산하지 않음. `meta.layout`을 보고 클라이언트가 정함 |
| 여러 비율 일괄 반환 | 응답은 이미지 1장 고정. 비율마다 따로 요청 |
| 챗봇 문구 자동 전달 | 문구는 클라이언트가 직접 넣음 |
| Design Planner (`dynamic/`) | **production 미연결.** `docs/design_planner.md` 참고 |

서버에는 있지만 **화면이 없어 사용자가 쓸 수 없는 것**이 몇 가지 있습니다 —
`tone`, `placement`, 문구 앞뒤 레이어, 제목·본문 분리 배치, `/compose/text`.
계약은 완성돼 있어 프론트가 붙이기만 하면 됩니다.

---

## 설치

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

`torch`는 CUDA 버전에 맞는 빌드가 필요합니다. [pytorch.org](https://pytorch.org/get-started/locally/)에서
환경에 맞는 설치 명령을 확인하세요.

최초 실행 시 다음이 자동으로 내려받아집니다.

| 대상 | 크기 | 위치 |
|---|---|---|
| rembg u2net 가중치 | 약 170MB | `~/.u2net/` |
| SD1.5 inpaint (시안 생성) | 약 4GB | HuggingFace 캐시 |
| SDXL inpaint (고품질 렌더링) | 약 7GB | HuggingFace 캐시 |

## 실행

```bash
uvicorn api:app --host 0.0.0.0 --port 8000
```

서버가 뜨면 `http://localhost:8000/docs`에서 스키마를 확인할 수 있습니다.

### 기본 흐름

```text
POST /generate/drafts   시안 여러 장 (가벼운 모델, 문구 없음)
        ↓ 사용자가 하나 선택
POST /generate/refine   고품질 렌더링 + 문구 합성 + AI 생성물 표시
```

서버는 상태를 저장하지 않습니다. draft 응답에 담겨 내려온 `background` 값을
클라이언트가 refine 요청에 그대로 되돌려 보내야 같은 배경이 재현됩니다.

refine에는 **`original_image`(원본 제품 사진)를 항상 함께 보내주세요.** 스키마상
선택이지만, 없으면 원본 제품을 다시 덮어씌우는 보존 단계가 적용되지 않아 로고·제품명·
포장지 문구가 훼손됩니다. 배경 모드와 무관합니다.

응답 이미지는 `data:` prefix가 없는 순수 PNG base64입니다.

자세한 요청/응답 스펙은 **[`docs/api.md`](docs/api.md)** 를 참고하세요.

---

## 디렉터리 구조

```text
├── api.py                      FastAPI 엔드포인트
├── pipeline/                   생성 파이프라인 (서비스 코드)
│   ├── config.py               모델·파라미터 설정 (튜닝은 여기만 수정)
│   ├── masking.py              누끼, 마스크, 그림자, 단색·그라데이션 배경
│   ├── generate.py             시안 생성(draft) / 고품질 렌더링(refine)
│   ├── layout.py               출력 캔버스 크기, 제품 배치, 비율 추론
│   └── overlay.py              문구 합성, AI 생성물 표시
├── dynamic/                    Design Planner — 레이아웃을 데이터로 표현하는 계층
│                               **production 미연결.** api·pipeline 어느 쪽과도
│                               import 관계가 없다 (docs/design_planner.md 참고)
├── tests/                      자동으로 PASS/FAIL을 판정하는 테스트
│   └── _baseline/              변경 전 모듈 스냅샷 (픽셀 회귀 비교용, 직접 실행 안 함)
├── scripts/verification/       수동 실행·육안 검증 스크립트 (카테고리별)
├── docs/                       API·검증 문서
├── assets/fonts/               번들 폰트 + 라이선스
└── outputs/                    검증 스크립트 실행 결과물 (git 제외, 자동 생성)
```

`tests/`와 `scripts/verification/`의 차이는 **자동 판정 여부**입니다.
`tests/`는 실행하면 스스로 PASS/FAIL을 내고, `scripts/verification/`는 이미지를 만들어
사람이 눈으로 확인해야 합니다.

---

## 테스트

**전부 GPU도 서버도 없이** 실행됩니다. 26개 스위트가 각각 스스로 PASS/FAIL을 냅니다.

```bash
for f in tests/test_*.py; do PYTHONPATH="$PWD" python "$f"; done
```

**`pytest tests`로는 돌지 않습니다.** 각 파일이 스크립트 형태라 모듈 수준에서
`sys.exit`을 부르고, pytest는 수집 단계에서 그것을 오류로 봅니다. 위 for-loop가
유일한 실행 방법이며 CI도 없습니다. 그래서 "통과"는 항상 **누군가 로컬에서 돌린
결과**입니다. 결과를 인용할 때 그 조건을 함께 적어주세요.

### API 계약

| 스위트 | 내용 |
|---|---|
| `test_drafts_canvas_api.py` | drafts의 비율·배치 요청/응답 계약, 1:1 회귀 |
| `test_refine_canvas_api.py` | refine의 비율 추론·교차검증·placement round-trip |
| `test_text_compose_api.py` | `/compose/text` 동작·좌표·ai_notice 순서·오류 |
| `test_ai_nonsquare_api.py` | 3:1 AI 경로, 1:1 AI 회귀, 3:4 AI 400 유지 |
| `test_zorder_api.py` | z_order 4개 조합, validation, 하위 호환, AI 표시 1회 적용 |
| `test_background_validation.py` | 배경 색상 validation (빈 배열·형식·모드별 차이) |

### 레이아웃 · 렌더링

| 스위트 | 내용 |
|---|---|
| `test_output_size.py` | 비율별 출력 캔버스 크기 계산 |
| `test_canvas_bridge.py` | W×H 캔버스 변환, 1:1 항등 경로(픽셀 동일) |
| `test_placement.py` | 비율별 기본 배치, 제품·그림자 clipping |
| `test_aspect_contract.py` | 비율 추론 tolerance, 배치 좌표 변환 |
| `test_rotation.py` | 제품 회전, 접지 그림자 재계산 |
| `test_component_boxes.py` | 구성 요소 박스 계산 |

### 문구 · 폰트

| 스위트 | 내용 |
|---|---|
| `test_text_coords.py` | 문구 좌표 계약(y=블록 중심), 프리셋 경로 픽셀 회귀 |
| `test_font_id.py` | `font_id` whitelist·400 두 종류·headline/sub 공통 적용·픽셀 회귀, config 상수 스냅샷 |
| `test_tone_preset.py` | `tone` 프리셋 적용과 거부 |
| `test_letter_spacing.py` | 자간 |
| `test_render_text_regression.py` | 문구 합성 픽셀 회귀 |

`test_text_coords.py`의 "프리셋 경로 회귀" 절은 변경 전 코드 사본을 `/tmp/oldpkg`에서
찾습니다. 없으면 **그 절만 건너뛰고** 나머지는 정상 판정합니다.

`test_tone_preset.py`는 통과하면서 "tone × 3:1/3:4 시각 회귀 미수행"을 함께 출력합니다.
비정사각 비율에서 프리셋의 시각 회귀는 아직 확인되지 않았습니다.

### Design Planner (`dynamic/`)

나머지 9개 스위트가 `dynamic/` 계층을 단독으로 검증합니다 — 스키마, 해석, 렌더,
안전성, Planner 입출력. `dynamic`을 단독으로 import했을 때 `pipeline`이 함께
올라오지 않는지도 확인합니다.

**production 경로에는 연결되어 있지 않습니다.** 이 계층의 범위와 현재 상태는
`docs/design_planner.md`를 참고하세요.

## 검증 스크립트

모든 명령은 **프로젝트 루트 기준**입니다. 결과물은 `outputs/verification/<카테고리>/`에
저장되며 폴더는 자동 생성됩니다.

| 명령 | 필요 조건 |
|---|---|
| `PYTHONPATH="$PWD" python scripts/verification/typography/verify_autofit.py` | 없음 |
| `PYTHONPATH="$PWD" python scripts/verification/shadow/check_shadow_shapes.py` | rembg + 제품 사진 |
| `PYTHONPATH="$PWD" python scripts/verification/placement/verify_product_placement.py` | rembg + 제품 사진 |
| `PYTHONPATH="$PWD" python scripts/verification/zorder/verify_zorder_behind.py` | rembg + 제품 사진 |
| `PYTHONPATH="$PWD" python scripts/verification/aspect/verify_canvas_placement.py` | rembg + 제품 사진 |
| `PYTHONPATH="$PWD" python scripts/verification/aspect/verify_aspect_ratio.py` | rembg + 제품 사진 |
| `PYTHONPATH="$PWD" python scripts/verification/aspect/make_contact_sheet.py` | 없음 (기존 결과 이미지 필요) |
| `PYTHONPATH="$PWD" python scripts/verification/aspect/probe_ai_nonsquare.py` | GPU |
| `PYTHONPATH="$PWD" python scripts/verification/api/smoke_ai_nonsquare.py` | 서버 + GPU |
| `PYTHONPATH="$PWD" python scripts/verification/api/smoke_api_endpoints.py` | 서버 + GPU |
| `PYTHONPATH="$PWD" python scripts/verification/api/smoke_zorder_api.py` | 서버 + GPU |
| `PYTHONPATH="$PWD" python scripts/verification/poster/verify_poster_real.py <name>` | 서버 + GPU |
| `PYTHONPATH="$PWD" python scripts/verification/shadow/batch_verify_shadow.py` | 서버 + GPU |

`scripts/verification/placement/verify_product_placement.py`와
`scripts/verification/zorder/verify_zorder_behind.py`에는 **아직 프로덕션에 반영되지 않은
실험 로직**이 들어 있습니다. 각 파일 상단에 명시되어 있습니다.

---

## 테스트 입력 이미지

검증 스크립트가 쓰는 제품 사진은 **저장소에 포함되어 있지 않습니다**(`.gitignore`).
직접 준비해 `image/` 폴더에 아래 파일명으로 넣어야 합니다.

| 파일명 | 필요한 성질 | 이 파일을 쓰는 스크립트 |
|---|---|---|
| `image/snack.jpg` | 불투명 포장, 로고·한글 포함 | `smoke_zorder_api`, `verify_product_placement`, `verify_poster_real`, `verify_zorder_behind`, `batch_verify_shadow` |
| `image/cosmetic.jpg` | **제품 2개**, 반투명 용기 | `verify_product_placement`, `verify_poster_real`, `batch_verify_shadow` |
| `image/glass.jpg` | **투명** 재질, 정면형 단일 제품 | `verify_poster_real`, `batch_verify_shadow` |
| `image/cake.jpg` | 푸드 카테고리 | `smoke_api_endpoints`, `batch_verify_shadow` |
| `image/monster_side.jpg` | 캔 음료 측면 | `batch_verify_shadow` (glob) |
| `image/monster_top.jpg` | 캔 음료 상단 | `batch_verify_shadow` (glob) |

**아무 사진으로나 대체하면 검증 의미가 달라집니다.** `cosmetic.jpg`는 제품이 2개여야
연결요소별 그림자 분리가 검증되고, `glass.jpg`는 투명해야 마스크 경계(halo) 처리가
검증됩니다. 사진은 단일 제품만 담겨야 하며, 배경에 다른 사물이 있으면 누끼가 오염됩니다.

정사각형일 필요는 없습니다. `prepare_image()`가 중앙 크롭합니다.

사진 없이 돌릴 수 있는 검증은 `tests/test_zorder_api.py`와
`scripts/verification/typography/verify_autofit.py` 두 가지입니다.

---

## 폰트

`assets/fonts/`에 번들되어 있습니다. OS 설치에 의존하지 않고 로컬과 배포 환경에서
같은 폰트가 재현되게 하기 위함입니다.

폰트를 고르는 경로가 **두 가지**입니다. 목적이 달라 테이블도 분리되어 있습니다.

**1) 역할 기반 (`config.FONTS`) — 서버가 용도에 맞게 고름**

| 역할 | 폰트 |
|---|---|
| `headline` | Gmarket Sans Bold |
| `body` / `body_medium` | Pretendard Regular / Medium |
| `elegant` | 나눔명조 Bold |
| `accent` | 검은고딕 (Black Han Sans) |

파일이 없으면 경고를 출력하고 `accent`로 폴백합니다.

**2) `font_id` (`config.FONT_IDS`) — 사용자가 직접 고름**

| `font_id` | 폰트 파일 |
|---|---|
| `pretendard` | `Pretendard/Pretendard-Regular.ttf` |
| `nanummyeongjo` | `NanumMyeongjo/NanumMyeongjoBold.ttf` |
| `gmarketsans` | `GmarketSans/GmarketSansTTFMedium.ttf` |
| `galmuri11` | `Galmuri11/Galmuri11.ttf` |
| `nanumpen` | `NanumPen/NanumPen.ttf` |

고른 폰트 하나가 headline과 sub에 **공통 적용**됩니다. 역할 기반과 달리
**폴백이 없습니다** — 쓸 수 없는 폰트는 400으로 거부합니다. 사용자가 고른 폰트가
아닌 결과가 나가면 원인을 추적할 수 없기 때문입니다. 자세한 계약은
[`docs/api.md`](docs/api.md)를 참고하세요.

출처와 재배포 조건은 `assets/fonts/SOURCES.md`에, 자산 검증은
`assets/fonts/verify_fonts.py`에 있습니다.

---

## 문서

| 문서 | 내용 |
|---|---|
| [`docs/api.md`](docs/api.md) | 구현된 API 필드, 요청 예시, validation, 미구현 항목 |
| [`docs/local_validation.md`](docs/local_validation.md) | 로컬 검증 절차, 그림자·배경·문구 실측 기록, 알려진 제한 |
