"""요청/응답 스키마.

응답의 headline/sub는 그대로 프론트 → 포스터 모델 /generate/refine 의
text 필드(headline, sub)로 전달되는 것을 전제로 함.
(position/align/style은 프론트에서 사용자가 선택 — 문구 모델 범위 아님)
"""
from typing import Literal, Optional
from pydantic import BaseModel, Field, model_validator

from . import config


# 서비스형(무형)은 챗봇에서 가게/서비스 이름을 묻지 않는다(8/18 확정).
# product가 비어 오면 서버가 업종 기반 기본 주어를 명시적으로 채운다.
_SERVICE_PRODUCT_CATEGORIES = ("academy", "sports")
_SERVICE_DEFAULT_PRODUCT = {
    "academy": "우리 학원",
    "sports": "우리 체육관",
}


class CopyRequest(BaseModel):
    category: Literal["food", "beauty", "goods", "academy", "sports"] = Field(
        description="업종 카테고리. 제품형(food/beauty/goods) + "
                    "서비스형(academy=학원, sports=체육관/도장)")
    product: Optional[str] = Field(
        default=None,
        description="제품/가게 이름. 제품형(food/beauty/goods)은 필수, "
                    "서비스형(academy/sports)은 선택 — 비우면 서버가 업종 "
                    "기반 기본값(우리 학원/우리 체육관)을 채운다.")
    keywords: Optional[list[str]] = Field(
        default=None, description="강조하고 싶은 키워드 목록")
    tone: Literal["warm", "energetic", "luxury", "simple"] = Field(
        default="warm", description="문구 톤")
    request: Optional[str] = Field(
        default=None, description="자유 요청사항 (예: '신메뉴 출시 강조')")
    num_candidates: int = Field(
        default=config.DEFAULT_NUM_CANDIDATES, ge=1, le=5,
        description="생성할 시안 개수")
    include_en: bool = Field(
        default=False,
        description="영어 현지화 문구 병행 생성 (글로벌 타깃 고도화 옵션)")

    @model_validator(mode="after")
    def _resolve_product(self):
        product = (self.product or "").strip()
        if product:
            self.product = product
            return self

        # 비어 있는 경우: 서비스형은 기본값, 제품형은 필수 오류(422).
        if self.category in _SERVICE_PRODUCT_CATEGORIES:
            self.product = _SERVICE_DEFAULT_PRODUCT[self.category]
            return self

        raise ValueError(
            "product는 제품형(food/beauty/goods)에서 필수입니다."
        )


class CopyCandidate(BaseModel):
    id: str
    headline: str
    sub: str
    headline_chars: int
    sub_chars: int
    over_limit: bool = Field(
        default=False,
        description="축약 재시도 후에도 제한 초과 시 True (포스터 쪽 자동 줄바꿈 참고용)")
    headline_en: Optional[str] = Field(
        default=None, description="영어 현지화 headline (include_en=true 시)")
    sub_en: Optional[str] = Field(
        default=None, description="영어 현지화 sub (include_en=true 시)")
    regulation_flags: list[dict] = Field(
        default_factory=list,
        description="룰 기반 규제 검사 결과 (비어있으면 통과). 상세 검증은 /validate/copy")
    safe: bool = Field(
        default=True,
        description="block 위반이 없으면 True. 프론트는 이 값만 보고 사용 가능 여부 판단 가능")


class CopyMeta(BaseModel):
    elapsed: float
    model: str
    mock: bool = False
    diversity_score: float = Field(
        default=1.0,
        description="시안 간 다양성 (1.0에 가까울수록 서로 다름)")
    max_pair_similarity: float = Field(
        default=0.0,
        description="가장 비슷한 시안 쌍의 유사도")
    diversity_retried: int = Field(
        default=0, description="다양성 확보를 위해 재생성한 횟수")
    diversity_ok: bool = Field(
        default=True,
        description="재생성 후에도 임계값을 넘는 중복이 남아있으면 False")


class CopyResponse(BaseModel):
    candidates: list[CopyCandidate]
    meta: CopyMeta
