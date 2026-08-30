# 최종보고서 제출
## 📑 프로젝트 통합 보고서
[📄 PDF 다운로드(docs/5team_report.pdf)](docs/5team_report.pdf?raw=true)

# 협업일지
>[협업일지(김도혁)](https://github.com/Final-Project-team5/Final-Project-team5/discussions?discussions_q=%EA%B9%80%EB%8F%84%ED%98%81)  
>[협업일지(김소원)](https://github.com/Final-Project-team5/Final-Project-team5/discussions?discussions_q=%EA%B9%80%EC%86%8C%EC%9B%90)  
>[협업일지(정진우)](https://github.com/Final-Project-team5/Final-Project-team5/discussions?discussions_q=%EC%A0%95%EC%A7%84%EC%9A%B0)  
>[협업일지(황지우)](https://github.com/Final-Project-team5/Final-Project-team5/discussions?discussions_q=%ED%99%A9%EC%A7%80%EC%9A%B0)

# 애드지니 (AdGenie) — 광고 콘텐츠 생성 서비스

> 소상공인을 위한 **법적으로 안전한** 광고 문구 · 포스터 자동 생성 서비스

생성형 AI로 광고 문구와 포스터 이미지를 만들어 주되, **표시광고법 · 식품표시광고법 · 화장품법 · 방문판매법 등 업종별로 문제가 될 표현을 자동으로 걸러냅니다.** 예쁜 결과물을 만드는 서비스는 많지만, 소상공인이 실제로 겪는 위험은 "몰라서 쓴 한 문장"입니다.

제품 사진이 있는 업종(푸드·뷰티·굿즈)뿐 아니라 학원·체육관 같은 서비스형 업종도 지원합니다.

```
"아토피 치료되는 크림"  →  🚫 화장품법: 질환명 언급은 의약품 오인 광고
"부작용 전혀 없음"      →  🚫 화장품법: 부작용 부재 단정 금지
```

---

## 서비스 흐름

업종 유형(product / service)에 따라 챗봇 단계 수와 사진 업로드 여부가 갈립니다.

```
0. 업종 유형 선택 — product(사진 필수) / service(사진 없이 진행)

[product: food·beauty·goods, 6단계]           [service: academy·sports, 5단계]
업종 → 용도(비율) → 제품 사진 → 느낌 → 강조점 → 추가요청     업종 → 용도(1:1 고정) → 느낌 → 강조점 → 추가요청
  · 제품 사진 업로드 시 Vision 인식 → 사용자 확인
    ← 문구 모델 /vision/product(/confirm)
  · 배경 참고 이미지 업로드 시 Vision 분석(선택)
    ← 문구 모델 /vision/background
  · 강조점에서 가격·할인/위치·시간 같은 사실값을 고르면 후속질문 1개로 구체값을 확인
  · 후속질문·추가요청 자유 입력은 제출 즉시 규제 룰 검사(block 재입력 / warn 경고)
        ↓
문구 생성 + 규제 검증        ← 문구 모델 /generate/copy
(동시에) 시각 프롬프트 구체화 ← 문구 모델 /generate/visual-prompt (전체 흐름에서 1회, drafts/refine이 재사용)
        ↓
배경 방식 선택 (AI / 단색 / 그라데이션 — 업종·비율에 따라 선택지 조건부 노출)
        ↓
포스터 초안 3장 생성          ← 포스터 모델 /generate/drafts
        ↓
시안 선택 + 문구 위치·크기·폰트 조정 (프론트 실시간 미리보기)
        ↓
고품질 렌더링 + 문구 합성     ← 포스터 모델 /generate/refine
        ↓
문구만 다시 조정 (diffusion 재실행 없이) ← 포스터 모델 /compose/text
        ↓
용도별 사이즈(1:1 SNS / 3:1 배너 / 3:4 상세페이지) 선택 → 다운로드
```

이미지 생성은 **2단계 파이프라인**입니다. 가벼운 모델로 시안 3장을 빠르게 뽑아 사용자가 방향을 고르게 한 뒤, 선택한 한 장만 큰 모델로 고품질화합니다. 문구 위치·크기만 다시 바꿀 때는 `/compose/text`로 diffusion 없이 CPU에서 재합성해 반복 편집을 빠르게 합니다.

---

## 주요 기능

| 기능 | 설명 |
|---|---|
| 업종 유형 분기 | 제품형(food/beauty/goods, 사진 필수·6단계) / 서비스형(academy/sports, 사진 없이·5단계)으로 챗봇 흐름 자체가 분기 |
| 챗봇 슬롯필링 | 순차 질문으로 필요한 정보를 자연스럽게 수집 |
| 규제 필터링 | 프롬프트 차단 + 룰 기반 검사 + LLM 재검증의 3중 방어. 제품형(식품표시광고법·화장품법) + 서비스형(방문판매법·국민체육진흥법 등) 룰 포함 |
| 문구 생성 | headline 20자 / sub 30자 보장, 초과 시 자동 축약 |
| 제품 사진 인식 | 업로드 시 Vision으로 제품을 인식하고 사용자 확인([맞아요]/[수정할게요]) 후 확정 |
| 배경 레퍼런스 분석 | 배경 참고 이미지를 Vision으로 분석해 문구·포스터 생성에 반영(선택 입력) |
| 포스터 2단계 생성 | 초안 3장 → 선택 → 고품질화 |
| 출력 비율 선택 | SNS(1:1) / 배너(3:1) / 상세페이지(3:4) — 용도에 맞는 비율로 시안부터 생성 |
| 배경 방식 선택 | AI 생성 / 단색 / 그라데이션 3방식 지원, 업종·비율별로 가능한 조합만 노출 |
| 문구 위치·크기 조정 | 드래그로 자유 배치, 서버 호출 없이 실시간 미리보기. 확정 후 `/compose/text`로 diffusion 없이 재합성 |
| 폰트 선택 | Pretendard / 나눔명조 / Gmarket Sans / Galmuri11 / 나눔손글씨펜 5종 중 선택, headline·sub 공통 적용 |
| 타이포그래피 프리셋 | `tone`(`minimal_product` / `bold_promo`) 하나로 문구 크기·서체 역할·외곽선·색을 한 번에 적용. 챗봇 스펙의 `tone`(문구 느낌)과는 다른 축 |
| 제품 배치 조정 | 단색/그라데이션 배경에서 제품 위치·크기(scale)를 직접 지정, 캔버스 이탈 시 서버가 거부 |
| 제품 사진 반영 | 업로드 시 inpaint 모드, 없으면 text2img 모드로 자동 분기 |
| AI 생성물 표시 | AI기본법 제31조 대응 — 이미지 워터마크 + 화면 고지 |

---

## 제한 사항

- **AI 배경의 3:4 비율** — 투명 제품에서 제품 영역 밖으로 구조가 생성되는 현상이 확인되어 막아뒀습니다(400 오류).
- **서버에는 있지만 화면과 연결되지 않은 기능** — `tone`(타이포그래피 프리셋), `placement`(제품 배치 직접 지정), 문구 앞뒤 레이어 순서, 제목·본문 분리 배치, `/compose/text`는 API 계약은 완성돼 있으나 프론트 미연동 상태입니다.

상세는 [`poster_model/README.md`](poster_model/README.md)의 "현재 구현 범위" 절 참고.

---

## 팀 구성

| 파트 | 담당 |
|---|---|
| PM | 정진우 |
| 문구 모델 · 규제 검증 · 챗봇 로직 | 김도혁 |
| 포스터 모델 · 후처리 파이프라인 | 황지우 |
| 프론트엔드 · 백엔드 | 김소원 |
| 서빙 인프라 | 하태진 |

---

## 폴더 구조

```
Final-Project-team5/
├── copy_model/       문구 생성 + 규제 검증 API (FastAPI, :8001)
├── poster_model/     포스터 생성 파이프라인 API
├── frontend/         React + Vite 웹 클라이언트 (:5173)
├── serving/          배포 설정, 컨테이너
├── docs/             스펙 문서, 회의록, 일정
└── README.md
```

각 폴더의 상세 실행 방법은 해당 폴더의 README를 참고하세요.

---

## 실행 방법

### 사전 요구사항

- Python 3.11 이상
- Node.js LTS
- NVIDIA GPU — 포스터 모델 구동 시 필요

### 1. 문구 모델 서버

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\Activate.ps1

pip install -r copy_model/requirements.txt
cp copy_model/.env.example copy_model/.env   # API 키 입력

uvicorn copy_model.api:app --reload --port 8001
```

API 키 없이 프론트 연동만 테스트하려면 mock 모드를 사용하세요.

```bash
COPY_MOCK=1 uvicorn copy_model.api:app --port 8001
# Windows PowerShell: $env:COPY_MOCK=1 후 실행
```

`http://127.0.0.1:8001/docs` 에서 API 문서와 테스트 화면을 확인할 수 있습니다.

### 2. 프론트엔드

```bash
cd frontend
npm install
npm run dev
```

`http://localhost:5173` 으로 접속합니다.

### 3. 포스터 모델 서버

`poster_model/README.md` 참고.

---

## API 개요

서버는 모두 **stateless** 구조입니다. 세션을 저장하지 않으므로 프론트가 상태(`spec`, 선택한 시안 이미지)를 들고 다니며 다음 요청에 함께 전달합니다.

### 문구 모델

| 엔드포인트 | 역할 |
|---|---|
| `POST /suggest/options` | 챗봇 순차 질문 — 다음 질문과 선택지 반환. 강조점에서 사실값을 고르면 후속질문으로, 자유 입력 단계에서는 `input_type`/`max_length`/`regulation` 필드로 응답 |
| `POST /vision/product` | 제품 사진 인식 (자동 확정 없음, confirmation pending) |
| `POST /vision/product/confirm` | 사용자 확인 후 제품 정보 확정 + 다음 단계 진행 |
| `POST /vision/background` | 배경 참고 이미지 분석 → `spec.background_context` 반영 (선택) |
| `POST /generate/copy` | 광고 문구 생성 (headline / sub) |
| `POST /generate/visual-prompt` | 사용자의 짧은 시각 요구를 이미지 생성용 영어 시각 프롬프트로 구체화(SD1.5 텍스트 인코더가 영어 기준). LLM이 실패해도 규칙 fallback으로 200 반환. 전체 제작 흐름에서 1회만 호출하며 drafts/refine이 같은 값을 재사용 |
| `POST /validate/copy` | 사용자가 수정한 문구 재검증 |

### 포스터 모델

| 엔드포인트 | 역할 |
|---|---|
| `POST /generate/drafts` | 초안 시안 3장 생성 (AI 배경 또는 단색/그라데이션 배경, 문구 없음). `aspect_ratio`·`placement`·`subject_kind`(product/service)로 비율·제품 배치·업종 경로 지정 가능 |
| `POST /generate/refine` | 선택 시안 고품질화 + 문구 합성. `text.font_id`·`text.tone`·`headline_z_order`·좌표(`x`/`y`)로 문구를 세밀하게 제어. `subject_kind`는 drafts와 같은 값을 그대로 전달해야 함 |
| `POST /compose/text` | diffusion 없이 문구만 재합성. 위치·크기·폰트·`tone`을 반복 편집할 때 사용 (CPU, 수백 ms) |

이미지는 모두 **base64**로 주고받습니다. 문구 위치는 0~1 비율 좌표로 전달하여 출력 해상도가 달라져도 동일한 위치에 배치됩니다. 지원 출력 비율은 `1:1`(SNS) / `3:1`(배너) / `3:4`(상세페이지)이며, AI 배경은 현재 `1:1`·`3:1`만 지원합니다. 개발 서버 CORS는 `http://localhost:5173` 단일 origin만 허용하므로 다른 포트·`127.0.0.1`로 접속하면 요청이 막힙니다.

상세 스펙은 [`docs/UIUX_스펙정리.md`](docs/UIUX_스펙정리.md) 와 [`poster_model/docs/api.md`](poster_model/docs/api.md) 를 참고하세요.

---

## 규제 필터링 구조

핵심 차별점이자 서비스의 존재 이유입니다.

1. **생성 단계 차단** — 프롬프트에 금지 규칙을 명시하여 애초에 위험한 표현이 나오지 않게 함
2. **룰 기반 자동 검사** — 생성 결과마다 `regulation_flags` 자동 첨부 (비용 0)
3. **LLM 재검증** — 사용자가 직접 수정한 문구를 맥락까지 판단하여 검사
4. **챗봇 자유 입력 즉시 검사** — 강조점 후속질문·추가요청에 사용자가 직접 입력한 문구도 제출 즉시 룰 기반 검사(비용 0)를 거침. `block`이면 대체 표현 안내 후 재입력, `warn`이면 경고를 동봉한 채 진행

플래그는 `block`(사용 불가)과 `warn`(맥락 확인 필요)으로 구분되며, 프론트에서 각각 빨간 배지 / 노란 배지로 표시합니다.

룰 사전은 제품형(food/beauty/goods)뿐 아니라 서비스형(academy/sports)까지 업종별로 분리되어 있습니다 — 예: 체육관은 환불·중도해지 불가 문구, 학원은 합격·점수 보장 문구를 block 처리합니다. 상세 커버리지는 [`copy_model/docs/규제_커버리지_매트릭스.md`](copy_model/docs/규제_커버리지_매트릭스.md) 참고. **이 룰은 데모용 1차 사전이며 법률 자문이 아닙니다** — 면책 고지와 공식 사전심의 경로는 [`docs/규제필터_면책_및_심의경로.md`](docs/규제필터_면책_및_심의경로.md) 참고.

---

## AI 생성물 표시

「인공지능 발전과 신뢰 기반 조성 등에 관한 기본법」 제31조에 따라 세 지점에서 대응합니다.

| 조항 | 대응 | 담당 |
|---|---|---|
| ①항 사전 고지 | 서비스 진입 화면 하단 상시 노출 | 프론트 |
| ②항 결과물 표시 | 결과 화면 캡션 + 다운로드 안내 | 프론트 |
| ③항 이미지 표시 | 이미지 하단 모서리 반투명 워터마크 | 포스터 모델 후처리 |

상세는 [`docs/AI_생성물_고지_표준안.md`](docs/AI_생성물_고지_표준안.md) 참고.

---

## 개발 규칙

**브랜치 · 병합**
- PR은 다른 팀원의 Approve 후 병합 (Files changed → Review changes → Approve)

**커밋 금지 항목**
- `.env`, API 키 — 한 번 올라가면 히스토리에서 제거하기 어렵습니다
- `node_modules/`, `.venv/`, 모델 가중치 파일

**프론트엔드 PR 체크**
- `npm run build` 통과
- `npm run lint` 통과

---

## 일정

| 날짜 | 마일스톤 |
|---|---|
| 8/10 | mock API 배포, 인터페이스 합의 완료 |
| 8/17 | 중간 점검 — 전원 시연 |
| 8/20 | 모델 코드 동결 |
| 8/24 | 전체 통합 시연 |
| 8/31 | 최종 제출 |

위 마일스톤은 8/10 기준 계획이며, 최신 진행 상황은 팀 채널에서 확인하세요.

---

## 문서

**서비스 전반**

- [UI/UX 스펙 정리](docs/UIUX_스펙정리.md) — 화면별 상세, 데이터 흐름, 엣지 케이스
- [AI 생성물 고지 표준안](docs/AI_생성물_고지_표준안.md) — 법적 요건과 표기 방식

**규제 필터 (문구 모델)**

- [광고 규제 법규 정리](docs/광고규제_법규정리.md) — 룰 구현의 근거 법령
- [규제 룰 근거·출처 매핑](docs/규제근거_출처.md) — 룰별 공식 근거 대응표
- [규제 필터 면책 고지 & 사전심의 경로](docs/규제필터_면책_및_심의경로.md) — 필터 한계 명시, 공식 확인 경로 안내
- [규제 검증 LLM 레이어 설계](docs/설계_LLM검증레이어.md) — 룰 → LLM 하이브리드 검증 구조
- [규제 필터 실험 결과](docs/실험결과_규제필터.md) — A/B 실험·골드셋 회귀 결과
- [다국어 확장 조사](docs/조사_다국어확장.md) — 영어 현지화 확장 범위 조사
- [규제 커버리지 매트릭스](copy_model/docs/규제_커버리지_매트릭스.md) — 업종별 룰 개수·근거 실측

**포스터 모델**

- [포스터 API 현황](poster_model/docs/api.md) — 요청/응답 필드, validation, 오류 코드 상세
- [Design Planner 설계](poster_model/docs/design_planner.md) — 레이아웃을 데이터로 표현하는 실험적 레이어(아직 API 미연동)
- [로컬 검증 가이드](poster_model/docs/local_validation.md) — 그림자·배경·문구 실측 기록, 알려진 제한
