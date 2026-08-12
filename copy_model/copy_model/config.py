"""문구 모델 설정.

글자 수 제한은 팀 협의(headline 20자 / sub 30자)에 따른 기본값이며,
추후 조정 가능성이 있어 환경변수로 오버라이드할 수 있게 해 둠.
"""
import os

# ── OpenAI ──────────────────────────────────────────────
# 운영진이 전달해준 팀 API 키를 .env 또는 환경변수로 설정 (절대 커밋 금지!)
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

# 일반 생성은 mini, 필요 시 nano로 낮춰 비용 절약 (팀 한도 $30)
MODEL_NAME = os.getenv("COPY_MODEL_NAME", "gpt-5.4-mini")

# ── 글자 수 제한 (공백 포함 기준) ────────────────────────
HEADLINE_MAX = int(os.getenv("COPY_HEADLINE_MAX", "20"))
SUB_MAX = int(os.getenv("COPY_SUB_MAX", "30"))

# 영어 문구 제한 (한글 20자 ≈ 시각적으로 영문 약 2배 폭 기준, 팀 확정 전 임시값)
HEADLINE_MAX_EN = int(os.getenv("COPY_HEADLINE_MAX_EN", "40"))
SUB_MAX_EN = int(os.getenv("COPY_SUB_MAX_EN", "60"))

# ── 다국어 현지화 (조사_다국어확장.md 기반, 언어 파라미터화) ──
# 글자 수 제한은 전부 임시값 — 폰트 렌더 폭 실측(이미지 파트 연계) 후 확정.
# 규제 검증은 한국어 원문 기준(safe 시안만 번역 대상). 대상국 규제는 로드맵.
SUPPORTED_LANGS = ("en", "ja", "zh", "es", "fr")
LANG_LIMITS = {          # lang: (headline_max, sub_max)
    "en": (HEADLINE_MAX_EN, SUB_MAX_EN),
    "ja": (25, 40),      # 가나+한자 혼용, 한글보다 약간 넓음 (임시)
    "zh": (20, 35),      # 한자 밀도 높음, 한글과 유사 (임시)
    "es": (45, 70),      # 라틴계, 영어보다 단어가 긴 편 (임시)
    "fr": (45, 70),      # 라틴계, 영어보다 단어가 긴 편 (임시)
}
LANG_NAMES = {"en": "영어", "ja": "일본어", "zh": "중국어 간체",
              "es": "스페인어", "fr": "프랑스어"}

# ── 확장 기능 스위치 (팀 합의 전 기본 OFF 성격의 옵션) ──
# 영어 현지화 병행 생성: 요청 시 include_en=true 로 켬 (글로벌 소상공인 타깃 고도화용)

# 제한 초과 시 LLM에게 축약을 요청하는 최대 재시도 횟수
SHORTEN_RETRIES = int(os.getenv("COPY_SHORTEN_RETRIES", "1"))

# ── 실행 모드 ────────────────────────────────────────────
# COPY_MOCK=1 이면 API 호출 없이 고정 샘플 반환 (프론트 연동 테스트용, 비용 0)
MOCK_MODE = os.getenv("COPY_MOCK", "0") == "1"

# 기본 시안 개수
DEFAULT_NUM_CANDIDATES = int(os.getenv("COPY_NUM_CANDIDATES", "3"))

# ── 시안 다양성 ──────────────────────────────────────────
# 시안끼리 이 값 이상으로 비슷하면 중복으로 보고 재생성한다.
# 라벨링 샘플 21쌍 측정 결과에 근거한 값 (docs 참고):
#   서로 다른 시안 0.000~0.118 / 사실상 같은 시안 0.300~0.700
#   → 두 구간 사이인 0.25를 임계값으로 설정 (오탐·미탐 모두 0)
DIVERSITY_THRESHOLD = float(os.getenv("COPY_DIVERSITY_THRESHOLD", "0.25"))

# 재생성 시도 횟수. 응답 시간 보호를 위해 기본 1회.
# 재시도 후에도 비슷하면 그대로 내보내고 meta에 기록한다.
DIVERSITY_RETRIES = int(os.getenv("COPY_DIVERSITY_RETRIES", "1"))

# ── 카테고리 / 톤 옵션 ──────────────────────────────────
CATEGORIES = ("food", "beauty", "goods")

# ── CORS ────────────────────────────────────────────────
# 프론트(Vite 개발 서버 등)에서 브라우저로 직접 호출할 수 있도록 허용 출처 설정.
# 배포 시에는 실제 도메인을 COPY_CORS_ORIGINS에 콤마로 구분해 지정.
_DEFAULT_ORIGINS = ",".join([
    "http://localhost:5173", "http://127.0.0.1:5173",   # Vite 기본
    "http://localhost:3000", "http://127.0.0.1:3000",   # CRA / Next 기본
    "http://localhost:4173", "http://127.0.0.1:4173",   # Vite preview
])
CORS_ORIGINS = [
    o.strip() for o in os.getenv("COPY_CORS_ORIGINS", _DEFAULT_ORIGINS).split(",")
    if o.strip()
]

TONES = ("warm", "energetic", "luxury", "simple")
