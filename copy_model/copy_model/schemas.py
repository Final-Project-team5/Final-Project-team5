"""요청/응답 스키마.

응답의 headline/sub는 그대로 프론트 → 포스터 모델 /generate/refine 의
text 필드(headline, sub)로 전달되는 것을 전제로 함.
(position/align/style은 프론트에서 사용자가 선택 — 문구 모델 범위 아님)
"""
from typing import Literal, Optional
from pydantic import BaseModel, Field

from . import config


class CopyRequest(BaseModel):
    category: Literal["food", "beauty", "goods"] = Field(
        description="업종 카테고리 (푸드/뷰티/굿즈)")
    product: str = Field(min_length=1, description="제품/가게 이름")
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


class CopyMeta(BaseModel):
    elapsed: float
    model: str
    mock: bool = False


class CopyResponse(BaseModel):
    candidates: list[CopyCandidate]
    meta: CopyMeta
