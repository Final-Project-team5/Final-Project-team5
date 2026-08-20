# 애드지니 — Frontend

광고 콘텐츠 생성 서비스 **애드지니**의 프론트엔드입니다.

- React 19
- Vite
- 문구/챗봇 API + 포스터 생성 API 연동
- mock / real API 전환 지원

---

## 1. 실행 방법

```bash
cd frontend
npm install
npm run dev
```

`npm run dev` 실행 후 일반적으로 아래 주소에서 확인할 수 있습니다.

```text
http://localhost:5173
```

5173 포트가 이미 사용 중이면 Vite가 자동으로 다음 빈 포트를 사용합니다.  
터미널에 출력되는 실제 접속 주소를 확인해 주세요.

---

## 2. 실서버 연동 설정

프론트는 mock API와 실제 API를 모두 지원합니다.

실서버로 테스트하려면 `frontend` 폴더에 `.env.local` 또는 `.env` 파일을 생성하고 아래 값을 설정합니다.

```env
VITE_USE_REAL_COPY_API=true
VITE_COPY_API_BASE=http://136.64.72.66:8001

VITE_USE_REAL_POSTER_API=true
VITE_POSTER_API_BASE=http://136.64.72.66:8000
```

환경변수 파일은 Git에 포함되지 않을 수 있으므로 로컬에서 직접 생성해야 합니다.

### 중요

`.env` 또는 `.env.local`을 수정한 뒤에는 실행 중인 Vite 서버를 종료하고 다시 실행해야 합니다.

```bash
npm run dev
```

환경변수는 Vite 시작 시점에 읽습니다.

---

## 3. Mock / Real API 전환

### 문구·챗봇 API

```env
VITE_USE_REAL_COPY_API=true
```

- `true`: 실제 copy API 사용
- `false` 또는 미설정: mock 사용

### 포스터 API

```env
VITE_USE_REAL_POSTER_API=true
```

- `true`: 실제 poster API 사용
- `false` 또는 미설정: mock 사용

발표/개발 중 서버가 불안정한 경우 mock으로 전환해 화면 흐름만 확인할 수 있습니다.

---

## 4. 현재 서버 주소

### Copy / Chatbot / Vision

```text
http://136.64.72.66:8001
```

Swagger:

```text
http://136.64.72.66:8001/docs
```

주요 기능:

- 챗봇 질문/옵션
- 광고 문구 생성
- 광고 규제 검증
- 제품 Vision 인식
- 제품 confirm
- 배경 레퍼런스 Vision 분석

### Poster

```text
http://136.64.72.66:8000
```

Swagger:

```text
http://136.64.72.66:8000/docs
```

주요 기능:

- 시안 3장 생성
- AI 배경
- 단색/그라데이션 배경
- 최종 고품질화
- 제품 합성
- 문구 배치

실서버 E2E 테스트 시 VM 및 각 서버가 실행 중이어야 합니다.

---

## 5. 현재 사용자 흐름

### Product

```text
광고 유형 선택
→ 업종 선택 (푸드 / 뷰티 / 굿즈)
→ 용도 선택
→ 제품 이미지 업로드
→ Vision 제품 인식
→ 맞아요 / 수정할게요
→ 제품 confirm
→ 배경 레퍼런스 업로드 / 배경 없이 진행
→ tone
→ keywords
→ 추가 요청
→ 문구 생성 및 규제 검증
→ 배경 방식 선택
→ 시안 3장 생성
→ 시안 선택
→ 문구 위치/크기 조정
→ 최종 고품질화
→ 결과 다운로드
```

Product 총 진행 단계는 **7단계**입니다.

### Service

```text
광고 유형 선택
→ 업종 선택 (학원 / 체육관)
→ SNS 1:1
→ tone
→ keywords
→ 추가 요청
→ 문구 생성 및 규제 검증
→ AI 시안 생성
→ 시안 선택
→ 문구 위치/크기 조정
→ 최종 고품질화
→ 결과 다운로드
```

Service 총 진행 단계는 **6단계**입니다.

서비스형은 현재 제품 사진 없이 진행하며 **SNS 1:1 + AI 배경만 지원**합니다.

---

## 6. 배경 방식 지원 범위

| 유형 | 비율 | AI 배경 | 심플 배경 |
| --- | --- | --- | --- |
| product | 1:1 | O | O |
| product | 3:1 | O | O |
| product | 3:4 | X | O |
| service | 1:1 | O | X |

화면 진입 규칙:

- product 1:1 / 3:1  
  → `AI 배경 / 심플 배경` 선택

- product 3:4  
  → 선택 화면 생략 후 바로 심플 배경 설정

- service 1:1  
  → 선택 화면 생략 후 바로 AI 시안 생성

심플 배경은:

```text
단색 / 그라데이션
→ 알아서 추천 / 직접 선택
```

으로 설정합니다.

`직접 선택`에서는 추천 색상 또는 컬러피커를 통해 HEX 색상을 지정할 수 있습니다.

---

## 7. 주요 API

Copy API:

```text
POST /suggest/options
POST /generate/copy
POST /validate/copy
POST /vision/product
POST /vision/product/confirm
POST /vision/background
```

Poster API:

```text
POST /generate/drafts
POST /generate/refine
```

프론트에서 실제 API 계약을 임의로 변경하지 말고, 서버 스키마와 `docs/` 문서를 우선 확인합니다.

---

## 8. 그 외 명령어

```bash
npm run build    # 프로덕션 빌드 (dist/ 생성)
npm run preview  # 빌드 결과 로컬 미리보기
npm run lint     # oxlint 실행
```

작업 완료 전 기본 확인:

```bash
npm run lint
npm run build
git diff --check
```

디버깅용 `console.log`, `console.debug`, `debugger`가 남아 있지 않은지 확인합니다.

---

## 9. 참고 문서

작업 전 반드시 아래 문서를 확인합니다.

```text
CLAUDE.md
../docs/UIUX_스펙정리.md
../docs/API_SPEC.md
../docs/ARCHITECTURE.md
../docs/DEVELOPMENT_GUIDE.md
```

특히 UI/UX 및 사용자 플로우는 **`UIUX_스펙정리.md`의 가장 최근 날짜 기록을 최우선 기준**으로 사용합니다.

실제 구현 상태는 문서보다 **현재 최신 코드**를 우선합니다.

기획과 구현이 다를 경우:

```text
기획상 A / 현재 구현 B
```

형태로 구분해 확인합니다.