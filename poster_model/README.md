# 포스터 이미지 생성 모델

소상공인 광고 콘텐츠 생성 서비스의 **이미지 파트**입니다.
제품 사진을 받아 배경을 교체하고, 접지 그림자와 광고 문구를 합성해 포스터를 만듭니다.

```text
제품 사진 → 누끼(rembg) → 배경 생성 → 접지 그림자 → 원본 제품 복원 → 문구 합성 → AI 표시
```

핵심은 **제품 픽셀 보존**입니다. diffusion만으로는 포장지의 로고와 한글이 뭉개지기 때문에,
생성 결과 위에 원본 제품을 마스크로 다시 덮어씌웁니다.

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
│   └── overlay.py              문구 합성, AI 생성물 표시
├── tests/                      자동으로 PASS/FAIL을 판정하는 테스트
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

GPU도 서버도 없이 바로 실행할 수 있습니다.

```bash
PYTHONPATH="$PWD" python tests/test_zorder_api.py
```

z_order 4개 조합, validation 3종, 하위 호환, AI 표시 1회 적용 등을 자동 판정합니다.

## 검증 스크립트

모든 명령은 **프로젝트 루트 기준**입니다. 결과물은 `outputs/verification/<카테고리>/`에
저장되며 폴더는 자동 생성됩니다.

| 명령 | 필요 조건 |
|---|---|
| `PYTHONPATH="$PWD" python scripts/verification/typography/verify_autofit.py` | 없음 |
| `PYTHONPATH="$PWD" python scripts/verification/shadow/check_shadow_shapes.py` | rembg + 제품 사진 |
| `PYTHONPATH="$PWD" python scripts/verification/placement/verify_product_placement.py` | rembg + 제품 사진 |
| `PYTHONPATH="$PWD" python scripts/verification/zorder/verify_zorder_behind.py` | rembg + 제품 사진 |
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

| 역할 | 폰트 | 라이선스 |
|---|---|---|
| `headline` | Gmarket Sans Bold | **미확보** — `assets/fonts/GmarketSans/PENDING.md` 참고 |
| `body` / `body_medium` | Pretendard Regular / Medium | OFL-1.1 |
| `elegant` | 나눔명조 Bold | OFL-1.1 |
| `accent` | 검은고딕 (Black Han Sans) | OFL-1.1 |

Gmarket Sans는 아직 없어서 `config.resolve_font_path()`가 `accent`로 자동 폴백합니다.
경고만 출력되고 파이프라인은 정상 동작합니다. 출처와 재배포 조건은
`assets/fonts/SOURCES.md`에 정리되어 있습니다.

---

## 문서

| 문서 | 내용 |
|---|---|
| [`docs/api.md`](docs/api.md) | 구현된 API 필드, 요청 예시, validation, 미구현 항목 |
| [`docs/local_validation.md`](docs/local_validation.md) | 로컬 검증 절차, 그림자·배경·문구 실측 기록, 알려진 제한 |
