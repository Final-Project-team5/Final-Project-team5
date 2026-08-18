"""문구 모델 FastAPI 엔드포인트.

실행:
    uvicorn copy_model.api:app --reload --port 8001

포스터 모델(/generate/drafts, /generate/refine)과 포트를 분리해
초기에는 프론트가 각 모델 API를 직접 호출하는 구조 (팀 합의사항).
"""
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from . import config
from .chatbot import SuggestRequest, SuggestResponse, suggest_options
from .generator import generate_copy
from .regulation import ValidateRequest, ValidateResponse, validate_copy
from .schemas import CopyRequest, CopyResponse
from .background import (
    BackgroundAdvanceRequest,
    BackgroundVisionResponse,
    advance_background_image,
)
from .vision_flow import (
    ProductVisionAdvanceRequest,
    ProductVisionAdvanceResponse,
    ProductVisionConfirmRequest,
    ProductVisionConfirmResponse,
    advance_product_image,
    confirm_product,
)

app = FastAPI(title="광고 문구 생성 API", version="0.2.0")

# 프론트에서 브라우저로 직접 호출할 수 있도록 CORS 허용
# (허용 출처는 config.CORS_ORIGINS — 환경변수 COPY_CORS_ORIGINS로 변경 가능)
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    """서버 상태 확인 — 프론트 연동 시 첫 호출로 사용하면 편합니다."""
    return {
        "status": "ok",
        "mock": config.MOCK_MODE,
        "model": config.MODEL_NAME,
        "limits": {"headline": config.HEADLINE_MAX, "sub": config.SUB_MAX},
        "cors_origins": config.CORS_ORIGINS,
    }


@app.post("/generate/copy", response_model=CopyResponse)
def post_generate_copy(req: CopyRequest) -> CopyResponse:
    if not config.MOCK_MODE and not config.OPENAI_API_KEY:
        raise HTTPException(
            status_code=500,
            detail="OPENAI_API_KEY가 설정되지 않았습니다. "
                   ".env 설정 또는 COPY_MOCK=1로 실행하세요.")
    try:
        return generate_copy(req)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"문구 생성 실패: {e}") from e


@app.post("/suggest/options", response_model=SuggestResponse)
def post_suggest_options(req: SuggestRequest) -> SuggestResponse:
    """챗봇 슬롯필링: 자유 입력 → 선택지 제시 → 니즈 좁히기.

    done=true가 되면 spec을 그대로 /generate/copy 바디로 사용 가능.
    """
    if not config.MOCK_MODE and not config.OPENAI_API_KEY:
        raise HTTPException(
            status_code=500,
            detail="OPENAI_API_KEY가 설정되지 않았습니다. "
                   ".env 설정 또는 COPY_MOCK=1로 실행하세요.")
    try:
        return suggest_options(req)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"선택지 생성 실패: {e}") from e


@app.post(
    "/vision/product",
    response_model=ProductVisionAdvanceResponse,
)
def post_vision_product(
    req: ProductVisionAdvanceRequest,
) -> ProductVisionAdvanceResponse:
    """제품 사진 인식만 수행한다 — 자동 진행 없음(confirmation pending).

    최종 spec.product 확정은 사용자 확인 후 /vision/product/confirm에서.
    """
    if not config.MOCK_MODE and not config.OPENAI_API_KEY:
        raise HTTPException(
            status_code=500,
            detail="OPENAI_API_KEY is not configured.",
        )

    try:
        return advance_product_image(req)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(
            status_code=502,
            detail=f"Product Vision flow failed: {e}",
        ) from e


@app.post(
    "/vision/product/confirm",
    response_model=ProductVisionConfirmResponse,
)
def post_vision_product_confirm(
    req: ProductVisionConfirmRequest,
) -> ProductVisionConfirmResponse:
    """사용자 확인([맞아요]/[수정할게요])으로 spec.product 확정 + tone 단계 진행."""
    if not config.MOCK_MODE and not config.OPENAI_API_KEY:
        raise HTTPException(
            status_code=500,
            detail="OPENAI_API_KEY is not configured.",
        )

    try:
        return confirm_product(req)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(
            status_code=502,
            detail=f"Product Vision confirm failed: {e}",
        ) from e


@app.post(
    "/vision/background",
    response_model=BackgroundVisionResponse,
)
def post_vision_background(
    req: BackgroundAdvanceRequest,
) -> BackgroundVisionResponse:
    """배경 레퍼런스(선택)를 분석해 spec.background_context에 반영한다.

    재확인 단계 없음. 결과는 meta.spec에 갱신된 spec으로 함께 반환.
    product/product_context는 건드리지 않는다.
    """
    if not config.MOCK_MODE and not config.OPENAI_API_KEY:
        raise HTTPException(
            status_code=500,
            detail="OPENAI_API_KEY is not configured.",
        )

    try:
        return advance_background_image(req)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(
            status_code=502,
            detail=f"Background Vision flow failed: {e}",
        ) from e


@app.post("/validate/copy", response_model=ValidateResponse)
def post_validate_copy(req: ValidateRequest) -> ValidateResponse:
    """광고 규제 검증: 룰 기반(즉시·무료) + LLM 맥락 검증(use_llm=true).

    /generate/copy 결과에도 룰 검사(regulation_flags)는 자동 첨부됨.
    이 엔드포인트는 사용자가 직접 수정한 문구 재검증, LLM 상세 검증용.
    """
    if req.use_llm and not config.MOCK_MODE and not config.OPENAI_API_KEY:
        raise HTTPException(
            status_code=500,
            detail="use_llm=true는 OPENAI_API_KEY 필요 (룰 검사만은 use_llm=false)")
    try:
        return validate_copy(req)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"규제 검증 실패: {e}") from e
