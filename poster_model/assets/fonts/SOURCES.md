# 번들 폰트 출처

OS 설치에 의존하지 않고 로컬과 배포 환경에서 같은 폰트가 재현되도록 프로젝트에
직접 번들링한 폰트들입니다. 전부 원본 폰트의 공식 또는 공식에 준하는 배포처에서
받았으며, 각 폰트의 출처와 검증 방법은 아래와 같습니다.

## Pretendard (Pretendard-Regular.ttf, Pretendard-Medium.ttf)
- 출처: npm 공식 패키지 `pretendard@1.3.9` (제작자 orioncactus 본인이 직접 배포)
- 받은 경로: `https://registry.npmjs.org/pretendard/-/pretendard-1.3.9.tgz`
- 패키지 내 경로: `dist/public/static/alternative/Pretendard-Regular.ttf`, `...-Medium.ttf`
- 라이선스: SIL Open Font License 1.1 (`LICENSE.txt` 동봉)
- 검증: fontTools로 name table 확인 — "Pretendard Regular"/"Pretendard Medium", 각 14716 글리프

## Nanum Myeongjo Bold (NanumMyeongjoBold.ttf)
- 출처: npm 패키지 `@expo-google-fonts/nanum-myeongjo@0.4.1` — Expo가 Google Fonts 공식
  배포본(Naver/NHN 제작, Google Fonts에 등록된 원본)을 React Native용으로 그대로
  재패키징한 것. 폰트 데이터 자체를 변형하지 않음
- 받은 경로: `https://registry.npmjs.org/@expo-google-fonts/nanum-myeongjo/-/nanum-myeongjo-0.4.1.tgz`
- 패키지 내 경로: `700Bold/NanumMyeongjo_700Bold.ttf` → `NanumMyeongjoBold.ttf`로 이름만 변경
- 라이선스: SIL Open Font License 1.1, Copyright NHN Corporation (`LICENSE.txt` 동봉)
- 검증: name table "NanumMyeongjoBold", 14694 글리프. 로컬 apt(`fonts-nanum`)로 설치한 것과
  동일 원본이어야 하나, 로컬에서 실제 파일 하나를 받아 checksum 비교해보는 걸 권장

## Black Han Sans Regular (BlackHanSans-Regular.ttf) — accent 전용
- 출처: npm 패키지 `@expo-google-fonts/black-han-sans@0.4.1` — Google Fonts 공식 배포본
  (원저작자: zesstype, https://github.com/zesstype/Black-Han-Sans) 재패키징
- 받은 경로: `https://registry.npmjs.org/@expo-google-fonts/black-han-sans/-/black-han-sans-0.4.1.tgz`
- 패키지 내 경로: `400Regular/BlackHanSans_400Regular.ttf` → `BlackHanSans-Regular.ttf`로 이름만 변경
- 라이선스: SIL Open Font License 1.1 (`LICENSE.txt` 동봉)
- 검증 결과 (중요 — 팀 가정과 다름):
  - 글리프 수 2734개로 확실히 적음(Pretendard/나눔명조는 14000+)
  - 하지만 실측 결과 영문 대/소문자, 숫자는 전부 지원함 (cmap 전수 확인 + 실제 렌더링으로 확인)
    "영문을 지원하지 않는다"는 원래 가정과 다르니 참고 바람. 다만 한자·특수기호 등
    글리프 커버리지가 넓지 않은 건 맞아서, 여전히 accent(선택적 강조용)로 두는 게 안전함

## Gmarket Sans Bold — 미확보, 수동 확인 필요
이 세션에서는 공식 배포처(corp.gmarket.com/fonts)에 네트워크가 막혀 접근할 수 없었고,
npm에서 찾은 건 커뮤니티 미러(`@noonnu/gmarket-sans-medium`, MIT 재라이선스)뿐인데
그마저도 Medium 웨이트라 우리가 원하는 Bold가 아닙니다. **추정 파일로 대체하지 않고
비워뒀습니다.** 로컬에서 공식 페이지(https://corp.gmarket.com/fonts/)에서 Bold를
받아 `assets/fonts/GmarketSans/`에 넣고 실제 파일명을 알려주시면 config.py의
`FONTS["headline"]` 경로를 그 이름에 맞게 반영하겠습니다.


## 재배포 조건 (PR 포함 판단 근거)

번들된 3종은 모두 **SIL Open Font License 1.1 (OFL-1.1)** 입니다. OFL-1.1은 다음을
허용하므로 저장소에 폰트 파일을 함께 커밋해도 됩니다.

- 상업적 이용 허용 (제작물 판매·상업 서비스 사용 제한 없음)
- 번들·재배포 허용 (**단, 라이선스 원문을 반드시 동봉** — 각 폴더의 `LICENSE.txt`)
- 임베딩 허용

지켜야 할 제약은 두 가지입니다.

1. 폰트 파일 **단독 판매 금지** (다른 저작물과 함께 배포하는 것은 허용)
2. 수정본을 배포할 때 원래 폰트 이름(Reserved Font Name) 사용 금지 —
   이 프로젝트는 원본을 그대로 쓰므로 해당 없음

| 폰트 | 라이선스 | LICENSE.txt | 상업 이용 | 재배포 |
|---|---|---|---|---|
| Pretendard Regular/Medium | OFL-1.1 | 있음 | 가능 | 가능 |
| NanumMyeongjo Bold | OFL-1.1 (NHN) | 있음 | 가능 | 가능 |
| Black Han Sans Regular | OFL-1.1 | 있음 | 가능 | 가능 |
| Gmarket Sans Bold | — | **미확보** | — | `PENDING.md`만 유지 |

Gmarket Sans는 파일을 받지 못해 번들에 없습니다. 라이선스 조건도 확인 전이므로,
파일을 확보하면 **번들 전에 재배포 가능 여부를 먼저 확인**해야 합니다.
`config.resolve_font_path()`가 파일이 없을 때 `accent` 역할로 폴백하므로
현재 상태에서도 파이프라인은 정상 동작합니다.
