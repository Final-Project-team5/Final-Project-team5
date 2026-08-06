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

# ── 확장 기능 스위치 (팀 합의 전 기본 OFF 성격의 옵션) ──
# 영어 현지화 병행 생성: 요청 시 include_en=true 로 켬 (글로벌 소상공인 타깃 고도화용)

# 제한 초과 시 LLM에게 축약을 요청하는 최대 재시도 횟수
SHORTEN_RETRIES = int(os.getenv("COPY_SHORTEN_RETRIES", "1"))

# ── 실행 모드 ────────────────────────────────────────────
# COPY_MOCK=1 이면 API 호출 없이 고정 샘플 반환 (프론트 연동 테스트용, 비용 0)
MOCK_MODE = os.getenv("COPY_MOCK", "0") == "1"

# 기본 시안 개수
DEFAULT_NUM_CANDIDATES = int(os.getenv("COPY_NUM_CANDIDATES", "3"))

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
