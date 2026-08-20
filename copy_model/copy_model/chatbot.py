"""챗봇 슬롯필링 모듈 (LLM 로직만 — UI/화면 흐름은 프론트 파트 담당).

팀 논의 반영:
- (8/5) PM진우님: 고정 질문 흐름, 각 단계마다 선택지 여러 개 + 기타 직접입력
- (8/19) 챗봇을 광고 정보 입력 메인 플로우로 사용. 각 단계는 자기 슬롯만 수정하며
  별도 키워드 UI를 자동 변경했다는 안내는 하지 않는다.
- (8/11) 소원·지우님 확정: 이미지 비율은 챗봇 '용도' 질문에서 받는다.
    용도 → 비율 매핑: SNS 카드뉴스=1:1 / 배너=3:1 / 상세페이지=3:4
    (비정사각 생성 구조상 draft 생성 전에 비율이 정해져야 하므로 챗봇에서 수집)

두 가지 모드 지원:
  1) 고정 플로우 (mode="fixed", 기본값) — PM진우님 안.
     단계가 정해져 있어 프론트가 진행률(1/6) 표시 가능.
  2) 자유 진행 (mode="auto") — LLM이 미수집 슬롯 중 다음 질문을 판단.

target_slots (서비스개발소원님 요청):
  물어볼 항목을 지정하면 그것만 채우고 done=true로 끝남.
  - 메인 흐름: target_slots 없이 호출 → 1단계부터 순서대로 6단계
  - 서브 패널 도우미: target_slots=["tone"] → 톤만 물어보고 종료

어느 모드든 done=true 시 spec을 그대로 /generate/copy 바디로 사용 가능
(purpose/aspect_ratio는 이미지 파이프라인용 필드로, CopyRequest는 이를 무시함.
 프론트가 aspect_ratio를 drafts 요청에 실어 넘긴다).
"""
import json
import re
import time
from typing import Literal, Optional

from pydantic import BaseModel, Field

from . import config
from .errors import CopyInputError

# ── 용도 → 이미지 비율 매핑 (8/11 소원·지우님 확정) ──────
#   SNS 카드뉴스 = 1:1 / 배너 = 3:1 / 상세페이지 = 3:4
#   서버가 결정적으로 매핑한다(LLM 판단에 맡기지 않음 — 항상 고정값).
PURPOSE_ASPECT = {"sns": "1:1", "banner": "3:1", "detail": "3:4"}
PURPOSE_LABEL = {"sns": "SNS 카드뉴스", "banner": "배너", "detail": "상세페이지"}
DEFAULT_PURPOSE = "sns"  # 알 수 없는 용도가 들어왔을 때의 안전 기본값(가장 흔한 정사각 1:1)

# ── business_type 분기 (방식 B — 무형 서비스업 확장) ─────────
#   제품형(product): 기존 흐름(food/beauty/goods + 사진 업로드).
#   서비스형(service): 무형 서비스업(학원/체육관·도장), 사진 스킵 + 1:1 고정.
#   0단계 질문(제품/서비스)은 프론트가 하드코딩해서 물어보고 그 값만 spec에
#   실어준다(소원님 협의). 서버는 business_type을 보고 흐름을 분기만 한다.
DEFAULT_BUSINESS_TYPE = "product"  # 하위호환: 없으면 제품형(기존 프론트 불변)
BUSINESS_TYPES = ("product", "service")
PRODUCT_CATEGORIES = ("food", "beauty", "goods")
SERVICE_CATEGORIES = ("academy", "sports")  # 확정 무형 서비스업(학원/체육관·도장)


def _business_type(spec: dict) -> str:
    """spec에서 business_type을 정규화해 반환. 미지정/이상값은 제품형."""
    bt = (spec or {}).get("business_type")
    return bt if bt in BUSINESS_TYPES else DEFAULT_BUSINESS_TYPE


def _apply_aspect_ratio(spec: dict) -> dict:
    """purpose 슬롯이 채워지면 비율(aspect_ratio)을 서버가 결정적으로 매핑.

    방어 가드(지우님 리뷰 반영):
      - 미선택(None/""): 매핑하지 않음. 비율은 용도 확정 후 결정.
      - 범위 밖(잘못된) purpose: 기본값(sns/1:1)으로 보정하고 원본을
        purpose_invalid에 남겨 추적 가능하게 한다. 잘못된 값이 그대로
        이미지 파이프라인으로 흘러가 aspect_ratio가 비는 것을 막는다.
      - 서비스형(business_type=service): 비정사각(3:1/3:4)은 서버가 막아둔
        상태(지우님 확인 — 사진 없는 text2img 비정사각은 400)라 purpose를
        sns(1:1)로 강제 보정하고 원본을 purpose_locked에 남긴다. 프론트가
        옵션을 잠그지만 서버도 방어한다.
    """
    purpose = spec.get("purpose")
    if _business_type(spec) == "service" and purpose and purpose != "sns":
        spec["purpose_locked"] = purpose   # 원본 보존(서비스형 비정사각 차단)
        purpose = "sns"
        spec["purpose"] = purpose
    if not purpose:                       # None 또는 "" — 아직 미선택
        return spec
    if purpose not in PURPOSE_ASPECT:     # 범위 밖 값 — 기본값으로 보정
        spec["purpose_invalid"] = purpose  # 원본 보존(로깅/디버깅용)
        purpose = DEFAULT_PURPOSE
        spec["purpose"] = purpose
    spec["aspect_ratio"] = PURPOSE_ASPECT[purpose]
    return spec


# ── 고정 플로우 정의 (PM진우님 제안 기반) ────────────────
# slot: 채우는 슬롯 / multi: 복수 선택 허용 / free_text: 기타 입력칸 노출
FLOW_STEPS = [
    {"step": 1, "slot": "category", "multi": False,
     "question": "현재 운영하시는 업종은 어떤 것인가요?",
     "hint": "food/beauty/goods 중 하나로 매핑. 선택지는 업종 예시를 구체적으로."},
    {"step": 2, "slot": "purpose", "multi": False,
     "question": "만드신 이미지를 주로 어디에 쓰실 건가요?",
     "hint": "SNS 카드뉴스→'sns' / 배너→'banner' / 상세페이지→'detail' 로 매핑. "
             "비율(1:1/3:1/3:4)은 서버가 자동 결정하므로 sns/banner/detail 값만 확정할 것."},
    {"step": 3, "slot": "product", "multi": False,
     "question": "어떤 제품이나 가게를 홍보하시나요?",
     "hint": "제품/가게 이름. 선택지는 해당 업종의 대표 품목 예시로."},
    {"step": 4, "slot": "tone", "multi": False,
     "question": "원하시는 포스터의 느낌은 어떤 것인가요?",
     "hint": "warm/energetic/luxury/simple 중 하나로 매핑. 선택지는 감성 표현으로."},
    {"step": 5, "slot": "keywords", "multi": True,
     "question": "강조하고 싶은 점을 골라주세요.",
     "hint": "복수 선택 가능. 제품 특징·강점 키워드."},
    {"step": 6, "slot": "request", "multi": False,
     "question": "추가로 반영했으면 하는 내용이 있으신가요?",
     "hint": "신메뉴 출시, 할인 행사 등. 없으면 건너뛰기 가능."},
]
TOTAL_STEPS = len(FLOW_STEPS)

# business_type=service일 때 덮어쓸 단계별 질문/힌트 (방식 B).
# 공통 단계(purpose 비율·tone·request)는 그대로 두고, 업종·강조점만 교체.
# 참고: service는 제품/가게 이름(product) 단계를 챗봇에서 묻지 않는다.
#       product는 선택값이며, 비면 /generate/copy(CopyRequest)가 업종 기반
#       기본값(우리 학원/우리 체육관)을 채운다. 프론트가 이름을 갖고 있으면
#       spec.product로 실어 보낼 수 있다(_SERVICE_EXCLUDED_SLOTS).
_SERVICE_STEP_OVERRIDES = {
    "category": {
        "question": "어떤 서비스 업종이신가요?",
        "hint": "academy/sports 중 하나로 매핑. 학원→academy, 체육관/도장/헬스장/피트니스→sports. "
                "선택지는 서비스 업종 예시로 구체적으로.",
    },
    "purpose": {
        "hint": "서비스형은 정사각(1:1)만 지원하므로 purpose는 'sns'로 확정한다"
                "(배너 3:1·상세페이지 3:4는 미지원). 비율은 서버가 자동으로 1:1.",
    },
    "keywords": {
        "hint": "복수 선택 가능. 서비스형 강조점 세트: 전문성·경력 / 후기·평판 / "
                "접근성(위치·시간) / 상담·가격 안내 등.",
    },
}

# service 흐름에서 제외하는 슬롯.
# product(가게/서비스 이름)는 챗봇 단계로 묻지 않는다(선택값, 기본값은 CopyRequest).
# 8/18 확정: service 진행은 category/purpose/tone/keywords/request 5단계.
_SERVICE_EXCLUDED_SLOTS = ("product",)


def _prompt_bits(business_type: str) -> dict:
    """business_type별 프롬프트 조각(category/purpose 매핑 규칙 + JSON enum)."""
    if business_type == "service":
        return {
            "category_rule": 'category는 반드시 "academy" | "sports" 중 하나로 매핑'
                             ' (학원→academy, 체육관/도장/헬스장/피트니스→sports)',
            "purpose_rule": 'purpose는 "sns"로 확정 (서비스형은 정사각 1:1만 지원, '
                            '배너·상세페이지 미지원)',
            "category_enum": 'null|"academy"|"sports"',
            "purpose_enum": 'null|"sns"',
        }
    return {
        "category_rule": 'category는 반드시 "food" | "beauty" | "goods" 중 하나로 매핑',
        "purpose_rule": 'purpose는 반드시 "sns" | "banner" | "detail" 중 하나로 매핑 '
                        '(SNS/카드뉴스/인스타→sns, 배너/광고배너→banner, 상세페이지/상세/제품페이지→detail)',
        "category_enum": 'null|"food"|"beauty"|"goods"',
        "purpose_enum": 'null|"sns"|"banner"|"detail"',
    }

_FIXED_SYSTEM_PROMPT = """당신은 소상공인 광고 콘텐츠 제작 서비스의 도우미 챗봇입니다.
정해진 순서대로 질문하며 광고 문구 제작에 필요한 정보를 수집합니다.

[이번 단계]
- 단계: {step}/{total}
- 질문: {question}
- 채울 슬롯: {slot}
- 복수 선택 허용: {multi}
- 참고: {hint}
- 다음 단계 질문: {next_question}

[지금까지 수집된 정보]
{current_spec}

[규칙]
1. 사용자의 이번 답변에서 이번 단계 슬롯 값을 확정한다.
   - {category_rule}
   - {purpose_rule}
   - tone은 반드시 "warm" | "energetic" | "luxury" | "simple" 중 하나로 매핑
   - keywords는 문자열 배열
2. next_question에는 위 "다음 단계 질문"을 그대로 넣고, 그 질문에 쓸 선택지
   4개를 생성한다. 지금까지 파악된 맥락(업종·제품)에 맞게 구체적으로 만든다.
3. confirm_message에는 이번에 확정된 값의 확인 멘트를 담는다.
   슬롯 종류에 맞는 표현을 쓸 것 (사용자가 고른 표현 그대로 인용):
   - category → "'푸드'로 업종을 설정했어요."
   - purpose  → "'SNS 카드뉴스'용으로 정했어요. 정사각(1:1) 비율로 만들어드릴게요."
     (배너→"가로로 긴 배너(3:1)", 상세페이지→"세로로 긴 상세페이지(3:4)")
   - product  → "'떡볶이'로 정했어요."
   - tone     → "'모던한 K-푸드 스타일'로 분위기를 잡았어요."
   - keywords → "'수제', '당일 생산'을 강조 포인트로 확인했어요."
   - request  → "'신메뉴 출시'를 반영할게요."
   별도 화면이나 키워드 영역을 수정했다는 표현은 사용하지 않는다.
4. 마지막 단계까지 끝나면 done=true, next_question은 마무리 멘트, options는 빈 배열.
5. 반드시 JSON으로만 응답:
{{"spec": {{"category": {category_enum},
  "purpose": {purpose_enum},
  "product": null|"...", "tone": null|"warm"|"energetic"|"luxury"|"simple",
  "keywords": null|["..."], "request": null|"..."}},
 "next_question": "...", "options": ["...", "...", "...", "..."],
 "confirm_message": "..."}}"""

_AUTO_SYSTEM_PROMPT = """당신은 소상공인 광고 콘텐츠 제작 서비스의 도우미 챗봇입니다.
사용자와 대화하며 광고 문구 제작에 필요한 정보를 수집합니다.

[수집할 슬롯]
- category: "food" | "beauty" | "goods" 중 하나
- purpose: "sns" | "banner" | "detail" 중 하나 (이미지 용도. SNS/카드뉴스→sns,
  배너→banner, 상세페이지→detail. 비율은 서버가 자동 결정)
- product: 제품/가게 이름 (구체적으로)
- tone: "warm" | "energetic" | "luxury" | "simple" 중 하나
- keywords: 강조할 키워드 1~3개
- request: 추가 요청사항 (선택, 없어도 됨)

[진행 규칙]
1. 대화 이력과 새 메시지에서 파악 가능한 슬롯을 모두 채운다.
2. category, purpose, product, tone, keywords가 모두 채워지면 done=true.
3. 부족하면 done=false로 하고, 가장 중요한 미수집 슬롯 1개에 대해
   질문 1개 + 사용자가 고르기 쉬운 선택지 4개를 제시한다.
4. 한 번에 질문은 반드시 1개만.
5. 이번 입력으로 새로 확정된 항목이 있으면 confirm_message에 짧은 확인 멘트를 담는다.
   별도 화면이나 키워드 영역을 수정했다는 표현은 사용하지 않는다. (없으면 빈 문자열)
6. 반드시 JSON으로만 응답:
{"spec": {"category": null|"food"|"beauty"|"goods",
  "purpose": null|"sns"|"banner"|"detail", "product": null|"...",
  "tone": null|"warm"|"energetic"|"luxury"|"simple",
  "keywords": null|["..."], "request": null|"..."},
 "done": true|false,
 "next_question": "...", "options": ["...", "...", "...", "..."],
 "confirm_message": "..."}"""


class ChatTurn(BaseModel):
    role: str  # "user" | "assistant"
    content: str


class SuggestRequest(BaseModel):
    message: str = Field(min_length=1, description="사용자 입력 (선택지 선택값 또는 자유 텍스트)")
    history: Optional[list[ChatTurn]] = Field(default=None, description="이전 대화 이력")
    mode: Literal["fixed", "auto"] = Field(
        default="fixed",
        description="fixed=고정 6단계 흐름(PM 제안안) / auto=LLM이 다음 질문 판단")
    step: int = Field(
        default=1, ge=1,
        description="fixed 모드에서 현재 진행 중인 단계 (1부터)")
    spec: Optional[dict] = Field(
        default=None,
        description="이전까지 채워진 슬롯 (fixed 모드에서 프론트가 상태로 들고 있다가 전달). "
                    "business_type(\"product\"|\"service\")을 0단계에서 프론트가 담아 보내면 "
                    "서버가 흐름을 분기한다. 없으면 제품형(product)으로 간주(하위호환).")
    target_slots: Optional[list[str]] = Field(
        default=None,
        description="물어볼 항목만 지정 (예: [\"tone\"]). 지정하면 해당 항목만 채우고 "
                    "done=true로 종료 — 서브 패널 도우미 용도. "
                    "생략하면 전체 6단계 흐름 (메인 흐름 용도)")


class SuggestResponse(BaseModel):
    spec: dict = Field(
        description="현재까지 채워진 슬롯 (done=true면 /generate/copy 바디로 사용). "
                    "purpose 확정 시 aspect_ratio(1:1/3:1/3:4)가 함께 채워짐 — 이미지 파이프라인용")
    done: bool
    step: int = Field(description="방금 처리한 단계")
    next_step: Optional[int] = Field(default=None, description="다음 단계 (done이면 null)")
    total_steps: int = Field(default=TOTAL_STEPS, description="전체 단계 수 (진행률 표시용)")
    question: str = Field(description="다음에 물을 질문 (done이면 마무리 멘트)")
    options: list[str] = Field(
        description="선택지 (프론트에서 '기타(직접 입력)' 항목을 항상 추가로 노출)")
    allow_multiple: bool = Field(
        default=False, description="다음 질문이 복수 선택 가능한지")
    confirm_message: str = Field(
        default="",
        description="이번 턴에 현재 단계 값을 확정한 확인 멘트 (빈 문자열이면 표시 안 함)")
    meta: dict


# mock 샘플 (슬롯별) — options는 '그 슬롯을 물을 때' 보여줄 선택지
_MOCK_SLOT = {
    "category": {
        "options": ["음식점·카페", "화장품·뷰티", "소품·잡화", "기타"],
        "patch": {"category": "food"},
        "confirm": "'푸드'로 업종을 설정했어요."},
    "purpose": {
        "options": ["SNS 카드뉴스 (정사각 1:1)", "배너 (가로로 긴 3:1)",
                    "상세페이지 (세로로 긴 3:4)"],
        "patch": {"purpose": "sns"},
        "confirm": "'SNS 카드뉴스'용으로 정했어요. 정사각(1:1) 비율로 만들어드릴게요!"},
    "product": {
        "options": ["떡볶이", "김밥", "분식 세트", "음료"],
        "patch": {"product": "떡볶이"},
        "confirm": "'떡볶이'로 정했어요."},
    "tone": {
        "options": ["활기찬 분식집 느낌", "모던한 K-푸드 스타일", "정겹고 따뜻한 느낌",
                    "깔끔한 정보 전달형"],
        "patch": {"tone": "energetic"},
        "confirm": "'활기찬 분식집 느낌'으로 분위기를 잡았어요."},
    "keywords": {
        "options": ["수제", "당일 생산", "매운맛 단계 선택", "포장 가능"],
        "patch": {"keywords": ["수제", "당일 생산"]},
        "confirm": "'수제', '당일 생산'을 강조 포인트로 확인했어요."},
    "request": {
        "options": ["신메뉴 출시", "할인 행사", "배달 시작", "없음"],
        "patch": {"request": "신메뉴 출시"},
        "confirm": "'신메뉴 출시'를 반영할게요."},
}

# 서비스형(business_type=service) mock 샘플 — 학원/체육관 예시.
# category/product/keywords/purpose만 서비스형으로 교체, tone/request는 공통.
_MOCK_SLOT_SERVICE = {
    "category": {
        "options": ["학원 (입시·보습)", "체육관·도장 (헬스·복싱·태권도)", "기타"],
        "patch": {"category": "academy"},
        "confirm": "'학원'으로 업종을 설정했어요."},
    "purpose": {
        "options": ["SNS 카드뉴스 (정사각 1:1)"],
        "patch": {"purpose": "sns"},
        "confirm": "'SNS 카드뉴스'용으로 정했어요. 서비스형은 정사각(1:1)으로 만들어드릴게요!"},
    "product": {
        "options": ["수학 전문 학원", "영어 회화 학원", "입시 종합반", "코딩 학원"],
        "patch": {"product": "수학 전문 학원"},
        "confirm": "'수학 전문 학원'으로 정했어요."},
    "tone": {
        "options": ["신뢰감 있는 전문가 느낌", "활기찬 분위기", "차분하고 깔끔한 느낌",
                    "따뜻하고 친근한 느낌"],
        "patch": {"tone": "simple"},
        "confirm": "'차분하고 깔끔한 느낌'으로 분위기를 잡았어요."},
    "keywords": {
        "options": ["전문성·경력", "후기·평판", "접근성(위치·시간)", "상담·가격 안내"],
        "patch": {"keywords": ["전문성·경력", "후기·평판"]},
        "confirm": "'전문성·경력', '후기·평판'을 강조 포인트로 확인했어요."},
    "request": {
        "options": ["신규 개강", "무료 상담 이벤트", "수강료 할인", "없음"],
        "patch": {"request": "신규 개강"},
        "confirm": "'신규 개강'을 반영할게요."},
}


def _mock_slots_for(business_type: str) -> dict:
    return _MOCK_SLOT_SERVICE if business_type == "service" else _MOCK_SLOT


def _effective_flow(target_slots: Optional[list[str]],
                    business_type: str = DEFAULT_BUSINESS_TYPE) -> list[dict]:
    """business_type 분기 + target_slots 필터를 적용한 흐름을 반환.

    - business_type=service면 category/keywords 단계의 질문·힌트를 서비스형으로
      덮어쓰고, product(가게/서비스 이름) 단계는 제외한다.
      → service는 category/purpose/tone/keywords/request 5단계.
      제외 후 step 번호를 1..N으로 다시 매겨 진행률(total_steps)을 맞춘다.
    - product 흐름은 6단계 그대로 유지(하위호환).
    - target_slots가 있으면 해당 슬롯만 원래 순서대로 추린다(서브 패널 도우미).
    """
    base = FLOW_STEPS
    if business_type == "service":
        base = [
            {**s, **_SERVICE_STEP_OVERRIDES.get(s["slot"], {})}
            for s in FLOW_STEPS
            if s["slot"] not in _SERVICE_EXCLUDED_SLOTS
        ]
        # product 제외로 비는 번호를 없애기 위해 1..N으로 재번호.
        base = [{**s, "step": i + 1} for i, s in enumerate(base)]
    if not target_slots:
        return base
    picked = [s for s in base if s["slot"] in target_slots]
    return picked or base


def _merge_fixed_slot(
    base_spec: dict,
    llm_spec: dict,
    slot: str,
) -> dict:
    """Merge only the slot that the current fixed step is allowed to write.

    The LLM is never allowed to mutate category/product/tone/etc. from a
    different step. Server-owned provenance such as product_context is
    preserved from base_spec.
    """
    merged = dict(base_spec or {})
    incoming = llm_spec or {}

    if slot in incoming and incoming[slot] is not None:
        merged[slot] = incoming[slot]

    return merged


def _sanitize_confirm_message(value: object) -> str:
    """Remove obsolete references to a separate/left-side keyword UI."""
    message = str(value or "")
    cleaned = re.sub(
        r"[^.!?\n]*(?:왼쪽|키워드\s*(?:창|영역))[^.!?\n]*[.!?]?",
        "",
        message,
    ).strip()
    return re.sub(r"^확인해보세요[.!?]?$", "", cleaned).strip()

def _mock_fixed(req: SuggestRequest, t0: float) -> SuggestResponse:
    business_type = _business_type(req.spec)
    flow = _effective_flow(req.target_slots, business_type)
    mock_slots = _mock_slots_for(business_type)
    total = len(flow)
    step = min(req.step, total)
    cfg = flow[step - 1]
    m = mock_slots[cfg["slot"]]

    spec = dict(req.spec or {})
    spec.update(m["patch"])
    _apply_aspect_ratio(spec)

    done = step >= total
    next_step = None if done else step + 1
    if done:
        question, options, allow_multiple = (
            "제공해주신 정보를 바탕으로 문구를 만들어드릴게요!", [], False)
    else:
        next_cfg = flow[next_step - 1]
        question = next_cfg["question"]
        options = mock_slots[next_cfg["slot"]]["options"]
        allow_multiple = next_cfg["multi"]

    return SuggestResponse(
        spec=spec, done=done, step=step, next_step=next_step, total_steps=total,
        question=question, options=options, allow_multiple=allow_multiple,
        confirm_message=m["confirm"],
        meta={"elapsed": round(time.time() - t0, 3), "model": "mock", "mock": True},
    )


def _client_chat(messages: list[dict], temperature: float = 0.5) -> dict:
    from openai import OpenAI
    client = OpenAI(api_key=config.OPENAI_API_KEY)
    resp = client.chat.completions.create(
        model=config.MODEL_NAME,
        messages=messages,
        response_format={"type": "json_object"},
        temperature=temperature,
    )
    return json.loads(resp.choices[0].message.content)


def suggest_options(req: SuggestRequest) -> SuggestResponse:
    t0 = time.time()

    # service는 fixed 모드만 지원한다(8/18 확정). auto는 product 슬롯 처리가
    # fixed와 달라 계약이 어긋나므로 service+auto를 명시적으로 미지원 처리한다.
    if req.mode == "auto" and _business_type(req.spec) == "service":
        # 클라이언트가 미지원 조합을 요청한 입력 오류 → api에서 400으로 매핑.
        raise CopyInputError(
            "service(business_type=service)는 fixed 모드만 지원합니다. "
            "auto 모드는 제품형에서만 사용하세요."
        )

    if config.MOCK_MODE:
        if req.mode == "fixed":
            return _mock_fixed(req, t0)
        return _mock_fixed(
            SuggestRequest(message=req.message, step=1, spec=req.spec), t0)

    business_type = _business_type(req.spec)

    if req.mode == "fixed":
        flow = _effective_flow(req.target_slots, business_type)
        total = len(flow)
        step = min(req.step, total)
        cfg = flow[step - 1]
        done = step >= total
        next_cfg = None if done else flow[step]

        system = _FIXED_SYSTEM_PROMPT.format(
            step=step, total=total, question=cfg["question"],
            slot=cfg["slot"], multi=cfg["multi"], hint=cfg["hint"],
            next_question=("(없음 — 마지막 단계이므로 마무리 멘트를 넣을 것)"
                           if done else next_cfg["question"]),
            current_spec=json.dumps(req.spec or {}, ensure_ascii=False),
            **_prompt_bits(business_type),
        )
        messages = [{"role": "system", "content": system},
                    {"role": "user", "content": req.message}]
        data = _client_chat(messages)

        spec = _merge_fixed_slot(
            req.spec or {},
            data.get("spec") or {},
            cfg["slot"],
        )
        _apply_aspect_ratio(spec)

        return SuggestResponse(
            spec=spec, done=done, step=step,
            next_step=None if done else step + 1, total_steps=total,
            question=str(data.get("next_question", "")),
            options=[] if done else [str(o) for o in data.get("options", [])][:4],
            allow_multiple=False if done else next_cfg["multi"],
            confirm_message=_sanitize_confirm_message(data.get("confirm_message", "")),
            meta={"elapsed": round(time.time() - t0, 3),
                  "model": config.MODEL_NAME, "mock": False},
        )

    # auto 모드
    system_auto = _AUTO_SYSTEM_PROMPT
    if business_type == "service":
        system_auto += (
            "\n\n[business_type=service 오버라이드 — 아래를 기본 규칙보다 우선]\n"
            '- category는 "academy" | "sports" 중 하나로 매핑'
            "(학원→academy, 체육관/도장/헬스장/피트니스→sports).\n"
            '- purpose는 "sns"로 확정(서비스형은 정사각 1:1만 지원, 배너·상세 미지원).')
    messages = [{"role": "system", "content": system_auto}]
    for turn in req.history or []:
        messages.append({"role": turn.role, "content": turn.content})
    messages.append({"role": "user", "content": req.message})
    data = _client_chat(messages)

    spec = data.get("spec", {}) or {}
    if business_type == "service":
        spec["business_type"] = "service"   # LLM 출력이 흘려도 분기값 보존
    _apply_aspect_ratio(spec)
    return SuggestResponse(
        spec=spec,
        done=bool(data.get("done", False)),
        step=req.step, next_step=None,
        question=str(data.get("next_question", "")),
        options=[str(o) for o in data.get("options", [])][:4],
        confirm_message=_sanitize_confirm_message(data.get("confirm_message", "")),
        meta={"elapsed": round(time.time() - t0, 3),
              "model": config.MODEL_NAME, "mock": False},
    )
