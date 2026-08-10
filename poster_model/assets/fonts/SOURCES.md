# 번들 폰트 출처

OS 설치에 의존하지 않고 로컬과 배포 환경에서 같은 폰트가 재현되도록 프로젝트에
직접 번들링한 폰트들입니다. 전부 원본 폰트의 공식 또는 공식에 준하는 배포처에서
받았으며, 각 폰트의 출처와 검증 방법은 아래와 같습니다.

검증은 `verify_fonts.py`(fontTools 기반)로 일괄 수행했습니다. name table로 폰트 신원을
확인하고, cmap과 실제 글리프 외곽선을 함께 확인해 **"대응표에는 있는데 실제 글자가
비어 있는"** 경우까지 걸러냈습니다. sha256(앞 16자리)은 파일이 교체·변조되지 않았는지
나중에 대조하기 위한 값입니다.

## 검증 재현

```bash
pip install fonttools
python poster_model/assets/fonts/verify_fonts.py poster_model/assets/fonts --out FONT_REPORT.md
```
---

# 폰트별 상세

## Pretendard Regular

- 출처: npm 공식 패키지 `pretendard@1.3.9` (제작자 orioncactus 본인이 직접 배포)
- 받은 경로: `https://registry.npmjs.org/pretendard/-/pretendard-1.3.9.tgz`
- 패키지 내 경로: `dist/public/static/alternative/Pretendard-Regular.ttf`
- 경로: `Pretendard/Pretendard-Regular.ttf`
- 패밀리 / 굵기: Pretendard / Regular
- 버전: Version 1.309
- 글리프 수: 14,716개
- 파일 크기: 2,661 KB
- sha256(앞 16자리): `6d0af5258997aec7`
- 라이선스: SIL Open Font License 1.1 (`LICENSE.txt` 동봉)
- 라이선스 URL: http://scripts.sil.org/OFL

| 문자 집합 | 지원 | 빠진 문자 |
|---|---|---|
| 영문 대문자 | OK | - |
| 영문 소문자 | OK | - |
| 숫자 | OK | - |
| 기본 문장부호 | OK | - |
| 통화·기호 | OK | - |
| 한글 음절(전체 11172) | OK | - |
| 한글 자모 | OK | - |
| 한자(샘플) | 없음 | 韓 國 語 文 字 漢 字 書 體 美 風 水 火 山 川 |

## Pretendard Medium

- 출처: npm 공식 패키지 `pretendard@1.3.9`
- 받은 경로: `https://registry.npmjs.org/pretendard/-/pretendard-1.3.9.tgz`
- 패키지 내 경로: `dist/public/static/alternative/Pretendard-Medium.ttf`
- 경로: `Pretendard/Pretendard-Medium.ttf`
- 패밀리 / 굵기: Pretendard Medium / Regular
- 버전: Version 1.309
- 글리프 수: 14,716개
- 파일 크기: 2,637 KB
- sha256(앞 16자리): `3bae579377eb8e9a`
- 라이선스: SIL Open Font License 1.1 (`LICENSE.txt` 동봉)
- 라이선스 URL: http://scripts.sil.org/OFL

| 문자 집합 | 지원 | 빠진 문자 |
|---|---|---|
| 영문 대문자 | OK | - |
| 영문 소문자 | OK | - |
| 숫자 | OK | - |
| 기본 문장부호 | OK | - |
| 통화·기호 | OK | - |
| 한글 음절(전체 11172) | OK | - |
| 한글 자모 | OK | - |
| 한자(샘플) | 없음 | 韓 國 語 文 字 漢 字 書 體 美 風 水 火 山 川 |

## NanumMyeongjo Bold

- 출처: npm 패키지 `@expo-google-fonts/nanum-myeongjo@0.4.1` — Expo가 Google Fonts 공식
  배포본(Naver/NHN 제작, Google Fonts에 등록된 원본)을 React Native용으로 그대로
  재패키징한 것. 폰트 데이터 자체를 변형하지 않음
- 받은 경로: `https://registry.npmjs.org/@expo-google-fonts/nanum-myeongjo/-/nanum-myeongjo-0.4.1.tgz`
- 패키지 내 경로: `700Bold/NanumMyeongjo_700Bold.ttf` → `NanumMyeongjoBold.ttf`로 이름만 변경
- 경로: `NanumMyeongjo/NanumMyeongjoBold.ttf`
- 패밀리 / 굵기: NanumMyeongjo / Bold
- 버전: Version 2.032
- 글리프 수: 14,694개
- 파일 크기: 3,001 KB
- sha256(앞 16자리): `fe22a50c17d820f4`
- 라이선스: SIL Open Font License 1.1, Copyright NHN Corporation (`LICENSE.txt` 동봉)
- 라이선스 URL: http://www.nhncorp.com

| 문자 집합 | 지원 | 빠진 문자 |
|---|---|---|
| 영문 대문자 | OK | - |
| 영문 소문자 | OK | - |
| 숫자 | OK | - |
| 기본 문장부호 | OK | - |
| 통화·기호 | OK | - |
| 한글 음절(전체 11172) | OK | - |
| 한글 자모 | OK | - |
| 한자(샘플) | 없음 | 韓 國 語 文 字 漢 字 書 體 美 風 水 火 山 川 |

## Gmarket Sans Bold

- 출처: G마켓 공식 배포 페이지 (https://corp.gmarket.com/fonts/)
- 경로: `GmarketSans/GmarketSansTTFBold.ttf`
- 패밀리 / 굵기: Gmarket Sans TTF Bold / Regular
- 버전: Version 1.000
- 글리프 수: 12,262개
- 파일 크기: 2,453 KB
- sha256(앞 16자리): `ff7c354dd1a324e4`
- 라이선스: SIL Open Font License 1.1 — 수정·재배포 명시 허용
  (`GmarketSans-LICENSE.txt` 동봉)
- 라이선스 URL: www.gmarket.co.kr/corp/gmarketsans

| 문자 집합 | 지원 | 빠진 문자 |
|---|---|---|
| 영문 대문자 | OK | - |
| 영문 소문자 | OK | - |
| 숫자 | OK | - |
| 기본 문장부호 | OK | - |
| 통화·기호 | OK | - |
| 한글 음절(전체 11172) | OK | - |
| 한글 자모 | OK | - |
| 한자(샘플) | 없음 | 韓 國 語 文 字 漢 字 書 體 美 風 水 火 山 川 |

이전 세션에서 미확보 상태로 비워뒀던 폰트입니다. 확보 완료로
`FONTS["headline"]`의 Black Han Sans 자동 폴백은 더 이상 필요하지 않습니다.

## Gmarket Sans Medium

- 출처: G마켓 공식 배포 페이지 (https://corp.gmarket.com/fonts/)
- 경로: `GmarketSans/GmarketSansTTFMedium.ttf`
- 패밀리 / 굵기: Gmarket Sans TTF Medium / Regular
- 버전: Version 1.000
- 글리프 수: 12,262개
- 파일 크기: 2,360 KB
- sha256(앞 16자리): `c6b9a2c10bfdb559`
- 라이선스: SIL Open Font License 1.1 (`GmarketSans-LICENSE.txt` 동봉)
- 라이선스 URL: www.gmarket.co.kr/corp/gmarketsans

| 문자 집합 | 지원 | 빠진 문자 |
|---|---|---|
| 영문 대문자 | OK | - |
| 영문 소문자 | OK | - |
| 숫자 | OK | - |
| 기본 문장부호 | OK | - |
| 통화·기호 | OK | - |
| 한글 음절(전체 11172) | OK | - |
| 한글 자모 | OK | - |
| 한자(샘플) | 없음 | 韓 國 語 文 字 漢 字 書 體 美 風 水 火 山 川 |

## Gmarket Sans Light

- 출처: G마켓 공식 배포 페이지 (https://corp.gmarket.com/fonts/)
- 경로: `GmarketSans/GmarketSansTTFLight.ttf`
- 패밀리 / 굵기: Gmarket Sans TTF Light / Regular
- 버전: Version 1.000
- 글리프 수: 12,262개
- 파일 크기: 2,357 KB
- sha256(앞 16자리): `7e8e8c70349ed94a`
- 라이선스: SIL Open Font License 1.1 (`GmarketSans-LICENSE.txt` 동봉)
- 라이선스 URL: www.gmarket.co.kr/corp/gmarketsans

| 문자 집합 | 지원 | 빠진 문자 |
|---|---|---|
| 영문 대문자 | OK | - |
| 영문 소문자 | OK | - |
| 숫자 | OK | - |
| 기본 문장부호 | OK | - |
| 통화·기호 | OK | - |
| 한글 음절(전체 11172) | OK | - |
| 한글 자모 | OK | - |
| 한자(샘플) | 없음 | 韓 國 語 文 字 漢 字 書 體 美 風 水 火 山 川 |

## 카페24 써라운드 에어

- 출처: Cafe24 폰트 공식 페이지 (https://fonts.cafe24.com)
- 경로: `Cafe24SsurroundAir/Cafe24SsurroundAir-v1.1.ttf`
- 패밀리 / 굵기: Cafe24 Ssurround air Light / Regular
- 버전: Version 1.002
- 글리프 수: 11,438개
- 파일 크기: 4,027 KB
- sha256(앞 16자리): `16861fe2aa270218`
- 라이선스: SIL Open Font License 1.1 (`Cafe24SsurroundAir-LICENSE.txt` 동봉)
- 라이선스 URL: https://fonts.cafe24.com

| 문자 집합 | 지원 | 빠진 문자 |
|---|---|---|
| 영문 대문자 | OK | - |
| 영문 소문자 | OK | - |
| 숫자 | OK | - |
| 기본 문장부호 | 12/15 | – — · |
| 통화·기호 | 9/10 | ₩ |
| 한글 음절(전체 11172) | OK | - |
| 한글 자모 | OK | - |
| 한자(샘플) | 없음 | 韓 國 語 文 字 漢 字 書 體 美 風 水 火 山 川 |

## Galmuri11

- 출처: 제작자 공식 배포처
- 경로: `Galmuri11/Galmuri11.ttf`
- 패밀리 / 굵기: Galmuri11 Regular / Regular
- 버전: Version 2.403
- 글리프 수: 20,968개
- 파일 크기: 5,250 KB
- sha256(앞 16자리): `2c709890595668f7`
- 라이선스: SIL Open Font License 1.1 (`LICENSE.txt` 동봉)
- 라이선스 URL: https://openfontlicense.org

| 문자 집합 | 지원 | 빠진 문자 |
|---|---|---|
| 영문 대문자 | OK | - |
| 영문 소문자 | OK | - |
| 숫자 | OK | - |
| 기본 문장부호 | OK | - |
| 통화·기호 | OK | - |
| 한글 음절(전체 11172) | OK | - |
| 한글 자모 | OK | - |
| 한자(샘플) | OK | - |

한자(샘플, "韓國語文字漢字書體美風水火山川")를 지원합니다. 다만 픽셀(비트맵 스타일) 폰트라 용도가 제한적입니다.

## 우아한 세리프 Bold (GraceSerif)

- 출처: Pear Type Foundry
- 경로: `GraceSerif/GraceSerif-Bold.ttf`
- 패밀리 / 굵기: 우아한 세리프 Bold / Regular
- 버전: Version 1.001
- 글리프 수: 11,567개
- 파일 크기: 582 KB
- sha256(앞 16자리): `bbdc46f95144d470`
- 라이선스: SIL Open Font License 1.1 (`LICENSE.txt` 동봉)

| 문자 집합 | 지원 | 빠진 문자 |
|---|---|---|
| 영문 대문자 | 없음 | A B C D E F G H I J K L M N O P Q R S T ... (외 6자) |
| 영문 소문자 | 없음 | a b c d e f g h i j k l m n o p q r s t ... (외 6자) |
| 숫자 | OK | - |
| 기본 문장부호 | 12/15 | – — … |
| 통화·기호 | OK | - |
| 한글 음절(전체 11172) | OK | - |
| 한글 자모 | OK | - |
| 한자(샘플) | 없음 | 韓 國 語 文 字 漢 字 書 體 美 風 水 火 山 川 |

**영문 대/소문자 52자를 전부 미지원하므로 순한글 문구 전용입니다.**
또한 Bold의 name table 패밀리명이 "우아한 세리프 Bold", Regular은 "우아한 세리프"로
다릅니다. 굵기 구분이 subfamily가 아니라 패밀리명에 들어 있으니 로딩 코드에서 주의.

## 우아한 세리프 Regular (GraceSerif)

- 출처: Pear Type Foundry
- 경로: `GraceSerif/GraceSerif-Regular.ttf`
- 패밀리 / 굵기: 우아한 세리프 / Regular
- 버전: Version 1.001
- 글리프 수: 11,567개
- 파일 크기: 637 KB
- sha256(앞 16자리): `33eb8227c4ecd0cf`
- 라이선스: SIL Open Font License 1.1 (`LICENSE.txt` 동봉)

| 문자 집합 | 지원 | 빠진 문자 |
|---|---|---|
| 영문 대문자 | 없음 | A B C D E F G H I J K L M N O P Q R S T ... (외 6자) |
| 영문 소문자 | 없음 | a b c d e f g h i j k l m n o p q r s t ... (외 6자) |
| 숫자 | OK | - |
| 기본 문장부호 | 12/15 | – — … |
| 통화·기호 | OK | - |
| 한글 음절(전체 11172) | OK | - |
| 한글 자모 | OK | - |
| 한자(샘플) | 없음 | 韓 國 語 文 字 漢 字 書 體 美 風 水 火 山 川 |

## 나눔손글씨펜 (Nanum Pen Script)

- 출처: 네이버 한글한글 아름답게 (https://hangeul.naver.com)
- 경로: `NanumPen/NanumPen.ttf`
- 패밀리 / 굵기: Nanum Pen Script / Regular
- 버전: Version 1.100
- 글리프 수: 20,770개
- 파일 크기: 3,465 KB
- sha256(앞 16자리): `0e1e2cc07fd5c5d1`
- 라이선스: SIL Open Font License 1.1, Copyright NHN Corporation (`LICENSE.txt` 동봉)
- 라이선스 URL: http://www.nhncorp.com

| 문자 집합 | 지원 | 빠진 문자 |
|---|---|---|
| 영문 대문자 | OK | - |
| 영문 소문자 | OK | - |
| 숫자 | OK | - |
| 기본 문장부호 | OK | - |
| 통화·기호 | OK | - |
| 한글 음절(전체 11172) | OK | - |
| 한글 자모 | OK | - |
| 한자(샘플) | 없음 | 韓 國 語 文 字 漢 字 書 體 美 風 水 火 山 川 |

## Black Han Sans Regular

- 출처: npm 패키지 `@expo-google-fonts/black-han-sans@0.4.1` — Google Fonts 공식 배포본
  (원저작자: zesstype, https://github.com/zesstype/Black-Han-Sans) 재패키징
- 받은 경로: `https://registry.npmjs.org/@expo-google-fonts/black-han-sans/-/black-han-sans-0.4.1.tgz`
- 패키지 내 경로: `400Regular/BlackHanSans_400Regular.ttf` → `BlackHanSans-Regular.ttf`로 이름만 변경
- 경로: `BlackHanSans/BlackHanSans-Regular.ttf`
- 패밀리 / 굵기: Black Han Sans / Regular
- 버전: Version 1.001
- 글리프 수: 2,734개
- 파일 크기: 956 KB
- sha256(앞 16자리): `24b7f51ab85c9175`
- 라이선스: SIL Open Font License 1.1 (`LICENSE.txt` 동봉)
- 라이선스 URL: https://openfontlicense.org

| 문자 집합 | 지원 | 빠진 문자 |
|---|---|---|
| 영문 대문자 | OK | - |
| 영문 소문자 | OK | - |
| 숫자 | OK | - |
| 기본 문장부호 | 11/15 | – — … · |
| 통화·기호 | OK | - |
| 한글 음절(전체 11172) | 2581/11172 | 갂 갃 갅 갆 갌 갍 갎 갏 갘 갞 갟 갡 갢 갥 갦 갧 갨 갩 갪 갫 ... (외 8,571자) |
| 한글 자모 | OK | - |
| 한자(샘플) | 없음 | 韓 國 語 文 字 漢 字 書 體 美 風 水 火 山 川 |

검증 결과가 팀 초기 가정과 다릅니다. **영문 대/소문자와 숫자는 전부 지원합니다**
(cmap 전수 확인 + 실제 외곽선 확인). "영문을 지원하지 않는다"는 원래 가정은
사실과 다르니 참고 바랍니다. 다만 한글이 부분 지원 수준이라 accent 등급으로 둡니다.

## 나눔휴먼 ExtraLight

- 출처: 네이버 한글한글 아름답게 (https://hangeul.naver.com/2017/nanum)
- 경로: `NanumHuman/NanumHumanEL.ttf`
- 패밀리 / 굵기: NanumHuman TTF ExtraLight / Regular
- 버전: Version 1.000
- 글리프 수: 12,488개
- 파일 크기: 993 KB
- sha256(앞 16자리): `805948bec1d8706b`
- 라이선스: SIL Open Font License 1.1 (`NanumHuman-LICENSE.txt` 동봉)
- 라이선스 URL: http://www.navercorp.com & https://hangeul.naver.com/2017/nanum

| 문자 집합 | 지원 | 빠진 문자 |
|---|---|---|
| 영문 대문자 | OK | - |
| 영문 소문자 | OK | - |
| 숫자 | OK | - |
| 기본 문장부호 | OK | - |
| 통화·기호 | OK | - |
| 한글 음절(전체 11172) | 2479/11172 | 갂 갃 갅 갆 갋 갌 갍 갎 갏 갘 갞 갟 갡 갢 갣 갥 갦 갧 갨 갩 ... (외 8,673자) |
| 한글 자모 | OK | - |
| 한자(샘플) | 없음 | 韓 國 語 文 字 漢 字 書 體 美 風 水 火 山 川 |

## 나눔휴먼 Regular

- 출처: 네이버 한글한글 아름답게 (https://hangeul.naver.com/2017/nanum)
- 경로: `NanumHuman/NanumHumanRegular.ttf`
- 패밀리 / 굵기: NanumHuman TTF Regular / Regular
- 버전: Version 1.000
- 글리프 수: 12,488개
- 파일 크기: 1,038 KB
- sha256(앞 16자리): `ef009fbb959413ea`
- 라이선스: SIL Open Font License 1.1 (`NanumHuman-LICENSE.txt` 동봉)
- 라이선스 URL: http://www.navercorp.com & https://hangeul.naver.com/2017/nanum

| 문자 집합 | 지원 | 빠진 문자 |
|---|---|---|
| 영문 대문자 | OK | - |
| 영문 소문자 | OK | - |
| 숫자 | OK | - |
| 기본 문장부호 | OK | - |
| 통화·기호 | OK | - |
| 한글 음절(전체 11172) | 2479/11172 | 갂 갃 갅 갆 갋 갌 갍 갎 갏 갘 갞 갟 갡 갢 갣 갥 갦 갧 갨 갩 ... (외 8,673자) |
| 한글 자모 | OK | - |
| 한자(샘플) | 없음 | 韓 國 語 文 字 漢 字 書 體 美 風 水 火 山 川 |

## KERIS 케듀체 Line

- 출처: 한국교육학술정보원(KERIS) (https://www.keris.or.kr/)
- 경로: `KerisKeduLine/KERISKEDU_Line.ttf`
- 패밀리 / 굵기: KERIS KEDU Line / Line
- 버전: Version 1.000
- 글리프 수: 12,265개
- 파일 크기: 1,812 KB
- sha256(앞 16자리): `eb0743251a555bb4`
- 라이선스: 재배포·상업 이용 허용 확인 (`KerisKedu-LICENSE.txt` 동봉)
- 라이선스 URL: https://www.keris.or.kr/

| 문자 집합 | 지원 | 빠진 문자 |
|---|---|---|
| 영문 대문자 | OK | - |
| 영문 소문자 | OK | - |
| 숫자 | OK | - |
| 기본 문장부호 | 14/15 | – |
| 통화·기호 | OK | - |
| 한글 음절(전체 11172) | 2780/11172 | 갂 갃 갅 갆 갌 갍 갎 갏 갘 갞 갟 갡 갢 갥 갦 갧 갨 갩 갪 갫 ... (외 8,372자) |
| 한글 자모 | OK | - |
| 한자(샘플) | 없음 | 韓 國 語 文 字 漢 字 書 體 美 風 水 火 山 川 |

## 재민체 3.0 (Jaemin3.0)

- 출처: 토끼네 활자공장
- 경로: `Jaemin/Jaemin3-Regular.ttf`
- 패밀리 / 굵기: Jaemin3.0 / Regular
- 버전: Version 1.000; Build 20220519
- 글리프 수: 20,172개
- 파일 크기: 10,545 KB
- sha256(앞 16자리): `1f7a34b31d81f6ad`
- 라이선스: 재배포·상업 이용 허용 확인 (`Jaemin3-LICENSE.txt` 동봉)

| 문자 집합 | 지원 | 빠진 문자 |
|---|---|---|
| 영문 대문자 | OK | - |
| 영문 소문자 | OK | - |
| 숫자 | OK | - |
| 기본 문장부호 | OK | - |
| 통화·기호 | OK | - |
| 한글 음절(전체 11172) | 2350/11172 | 갂 갃 갅 갆 갋 갌 갍 갎 갏 갘 갞 갟 갡 갢 갣 갥 갦 갧 갨 갩 ... (외 8,802자) |
| 한글 자모 | OK | - |
| 한자(샘플) | OK | - |

글리프 수는 20,172개로 많지만 대부분 한자입니다. 한글은 2,350자 부분 지원.

## HS활공명조

- 출처: 제작자(hp0) 공식 배포처 (http://hp0.blog.me)
- 경로: `HSHwalkongSerif/HSHwalkongSerif.ttf`
- 패밀리 / 굵기: HS활공명조 / Regular
- 버전: Version 1.001
- 글리프 수: 3,829개
- 파일 크기: 629 KB
- sha256(앞 16자리): `4081869278909373`
- 라이선스: 재배포·상업 이용 허용 확인 (`HSHwalgongSerif-LICENSE.txt` 동봉)

| 문자 집합 | 지원 | 빠진 문자 |
|---|---|---|
| 영문 대문자 | OK | - |
| 영문 소문자 | OK | - |
| 숫자 | OK | - |
| 기본 문장부호 | 13/15 | – — |
| 통화·기호 | OK | - |
| 한글 음절(전체 11172) | 2781/11172 | 갂 갃 갅 갆 갌 갍 갎 갏 갘 갞 갟 갡 갢 갥 갦 갧 갨 갩 갪 갫 ... (외 8,371자) |
| 한글 자모 | OK | - |
| 한자(샘플) | 없음 | 韓 國 語 文 字 漢 字 書 體 美 風 水 火 山 川 |

## HS유지체

- 출처: 제작자(hp0) 공식 배포처 (http://hp0.blog.me)
- 경로: `HSYuji/HSYuji.ttf`
- 패밀리 / 굵기: HSYuji / Regular
- 버전: Version 2.0
- 글리프 수: 3,436개
- 파일 크기: 1,800 KB
- sha256(앞 16자리): `bf18a6408a0de44e`
- 라이선스: 재배포·상업 이용 허용 확인 (`HSYuji-LICENSE.txt` 동봉)
- 라이선스 URL: http://hp0.blog.me

| 문자 집합 | 지원 | 빠진 문자 |
|---|---|---|
| 영문 대문자 | OK | - |
| 영문 소문자 | OK | - |
| 숫자 | OK | - |
| 기본 문장부호 | OK | - |
| 통화·기호 | OK | - |
| 한글 음절(전체 11172) | 2350/11172 | 갂 갃 갅 갆 갋 갌 갍 갎 갏 갘 갞 갟 갡 갢 갣 갥 갦 갧 갨 갩 ... (외 8,802자) |
| 한글 자모 | OK | - |
| 한자(샘플) | 없음 | 韓 國 語 文 字 漢 字 書 體 美 風 水 火 山 川 |

---

## 한글 커버리지 등급

검증 리포트의 "판정" 열은 한글 음절 지원 범위로 나눈 것입니다.

- **전체 지원 (11,172자 전수)** — 현대 한글로 표현 가능한 모든 음절 지원. 제한 없이 사용
- **부분 지원 (2,350~2,781자)** — 1987년 KS X 1001 표준이 담은 "실무에서 쓰이는
  한글"만 지원. 일상 문장의 99.9%는 커버되지만, `쉐`(쉐이크·쉐프·쉐딩),
  `똠`(똠얌) 같은 외래어 표기가 빠짐

**부분 지원 폰트는 탈락시키지 않고 accent 등급으로 사용합니다.** 짧은 헤드라인에는
충분하고 디자인 가치가 있기 때문입니다. 다만 미지원 글자는 **에러가 아니라 빈
네모(두부)로 조용히 렌더링되므로**, 런타임에 미리 검사해 폴백하는 안전장치가
반드시 함께 있어야 합니다.

```python
from functools import lru_cache
from fontTools.ttLib import TTFont

@lru_cache(maxsize=32)
def _cmap_of(font_path: str) -> frozenset:
    return frozenset(TTFont(font_path, lazy=True).getBestCmap().keys())

def missing_chars(text: str, font_path: str) -> list[str]:
    """이 폰트로 렌더링 못 하는 글자 목록. 비어 있으면 안전."""
    cmap = _cmap_of(font_path)
    return [c for c in set(text) if not c.isspace() and ord(c) not in cmap]

def pick_font(text: str, preferred: str, fallback: str) -> str:
    """선호 폰트로 안 되면 폴백."""
    return preferred if not missing_chars(text, preferred) else fallback
```

`lru_cache` 덕분에 폰트당 한 번만 파싱하므로 요청마다 부담은 없습니다.

폴백 대상은 **모든 글자가 되는 폰트**여야 의미가 있습니다. 현재 `resolve_font_path()`가
폴백하는 Black Han Sans는 한글 2,581자만 지원하므로, 전수 통과인 **Pretendard로
교체**해야 합니다.

## 기호 정규화

여러 폰트가 대시류(`–` `—`)·말줄임표(`…`)·가운뎃점(`·`)·원화(`₩`)를 지원하지 않습니다.
제작자 입장에서 한글 11,172자를 그리는 게 주 작업이라 유니코드 구두점 영역이 후순위로
밀리기 때문입니다. 폰트별 폴백보다 **렌더링 직전 일괄 치환**이 관리하기 편합니다.

| 원본 | 치환 | 비고 |
|---|---|---|
| `–` `—` | `-` | 여러 폰트 공통 미지원 |
| `…` | `...` | |
| `·` | `,` 또는 `/` | 문맥에 따라 |
| `₩` | `원` | 카페24 미지원 |
| `“ ” ‘ ’` | `"` `'` | LLM이 둥근 따옴표를 생성하는 경향이 있어 예방 차원 |

## 역할 배정

| 역할 | 폰트 | 근거 |
|---|---|---|
| headline | Gmarket Sans Bold | 전수 통과, 결함 없음 |
| body | Pretendard Regular/Medium | 전수 통과, 최종 폴백 겸용 |
| serif | NanumMyeongjo Bold, 우아한 세리프 Bold/Regular | 전수 통과 (우아한 세리프는 순한글 전용) |
| display | 카페24 써라운드 에어, Gmarket Sans Medium/Light | 전수 통과, 기호 정규화 필요 |
| handwriting | 나눔손글씨펜 | 전수 통과 |
| accent | Black Han Sans, Galmuri11, HS활공명조, HS유지체, 재민체 3.0, KERIS 케듀 Line, 나눔휴먼 EL/Regular | 한글 부분 지원 또는 용도 제한 — 폴백 필수 |

---

## 재배포 조건 (PR 포함 판단 근거)

번들된 폰트는 전부 **재배포·상업 이용이 허용된 것만** 선별했습니다. 대부분
**SIL Open Font License 1.1 (OFL-1.1)** 이며, OFL-1.1은 다음을 허용하므로 저장소에
폰트 파일을 함께 커밋해도 됩니다.

- 상업적 이용 허용 (제작물 판매·상업 서비스 사용 제한 없음)
- 번들·재배포 허용 (**단, 라이선스 원문을 반드시 동봉** — 각 폴더의 LICENSE 파일)
- 임베딩 허용

지켜야 할 제약은 두 가지입니다.

1. 폰트 파일 **단독 판매 금지** (다른 저작물과 함께 배포하는 것은 허용)
2. 수정본을 배포할 때 원래 폰트 이름(Reserved Font Name) 사용 금지 —
   이 프로젝트는 원본을 그대로 쓰므로 해당 없음

| 폰트 | 라이선스 | LICENSE 파일 | 상업 이용 | 재배포 |
|---|---|---|---|---|
| Pretendard Regular/Medium | OFL-1.1 | 있음 | 가능 | 가능 |
| NanumMyeongjo Bold | OFL-1.1 (NHN) | 있음 | 가능 | 가능 |
| Gmarket Sans Bold/Medium/Light | OFL-1.1 | 있음 | 가능 | 가능 |
| 카페24 써라운드 에어 | OFL-1.1 | 있음 | 가능 | 가능 |
| Galmuri11 | OFL-1.1 | 있음 | 가능 | 가능 |
| 우아한 세리프 Bold/Regular | OFL-1.1 | 있음 | 가능 | 가능 |
| 나눔손글씨펜 | OFL-1.1 (NHN) | 있음 | 가능 | 가능 |
| Black Han Sans Regular | OFL-1.1 | 있음 | 가능 | 가능 |
| 나눔휴먼 EL/Regular | OFL-1.1 | 있음 | 가능 | 가능 |
| KERIS 케듀체 Line | 제작자 자체 | 있음 | 가능 | 가능 |
| 재민체 3.0 | 제작자 자체 | 있음 | 가능 | 가능 |
| HS활공명조 | 제작자 자체 | 있음 | 가능 | 가능 |
| HS유지체 | 제작자 자체 | 있음 | 가능 | 가능 |

