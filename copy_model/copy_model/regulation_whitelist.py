"""허용 표현 화이트리스트 (오탐 방지 + 대체표현 근거).

배경:
    규제 룰은 위반 '표현'을 잡지만, 같은 소재라도 **법이 허용하는 표현 형식**이 있다.
    화장품은 화장품법 시행규칙 §2에 정한 '기능성화장품' 범위에서
    "OO에 도움을 주는" 형식이 허용된다. 이 형식을 화이트리스트로 명시해:
      1) 룰을 넓힐 때 합법 표현이 실수로 차단되는 오탐을 막고(guard),
      2) 위반 표현이 걸렸을 때 **법적으로 승인된 대체 표현**으로 유도한다(suggestion).

주의:
    "OO에 도움을 주는"은 해당 제품이 **기능성화장품으로 심사·인정**된 경우에만 실제로
    합법이다. 본 도구는 표현 '형식'의 합법성만 판단하며, 인증 보유 여부는 확인하지 못한다.
    → 대체 표현 제안 시 "기능성 인정 제품에 한함"을 함께 안내한다. (면책 참조)

근거:
    화장품법 시행규칙 제2조(기능성화장품의 범위) / 식약처 화장품 표시·광고 관리 지침
"""
import re

# 화장품법 시행규칙 §2 — 법정 기능성 종류별 '허용되는 표현 형식'
# stem(룰이 잡는 위반 소재) → approved(승인된 표현 형식)
COSMETIC_FUNCTIONAL = {
    "미백":   "피부 미백에 도움을 주는",
    "주름":   "피부 주름 개선에 도움을 주는",
    "자외선": "자외선으로부터 피부를 보호하는 데 도움을 주는",
    "여드름": "여드름성 피부를 완화하는 데 도움을 주는",
    "탈모":   "탈모 증상 완화에 도움을 주는",
    "튼살":   "튼살로 인한 붉은 선을 엷게 하는 데 도움을 주는",
    "장벽":   "피부장벽 기능을 회복하는 데 도움을 주는",
    "각질":   "피부 각질 관리에 도움을 주는",
}

# 승인된 표현으로 인정하는 '완곡 형식' — 위반 단정어가 아니라 이 형식이면 통과
_APPROVED_FORM = re.compile(
    r"(개선|완화|관리|보호|진정)(에|하는)\s*도움을?\s*주(는|어)")

# 일반식품/건기식에서 '기능성 단정'이 아니라 허용되는 완곡 표현
FOOD_SOFT_ALLOWED = re.compile(
    r"(든든하게|가볍게|산뜻하게|깔끔하게|편안하게)\s*(채우|즐기|시작|마무리)")


def has_approved_form(text: str) -> bool:
    """'OO에 도움을 주는' 등 법이 허용하는 완곡 표현 형식이 있는지."""
    return bool(_APPROVED_FORM.search(text))


def approved_expression(matched: str) -> str:
    """위반으로 걸린 표현(matched)에 대응하는 법적 승인 표현을 돌려준다.

    대체표현 제안(suggestion) 강화에 사용. 매핑 없으면 빈 문자열.
    """
    for stem, approved in COSMETIC_FUNCTIONAL.items():
        if stem in matched:
            return approved
    return ""


def is_whitelisted(matched: str, text: str) -> bool:
    """걸린 표현이 '승인된 완곡 형식' 안에 있으면 True (오탐으로 보고 통과).

    예: 룰이 '주름'을 넓게 잡더라도, 문구가 '주름 개선에 도움을 주는'이면 합법 → 통과.
    단정어(제거/박멸/없애/보장/완치)가 함께 있으면 화이트리스트 적용 안 함.
    """
    HARD = re.compile(r"(제거|박멸|없애|없앤|보장|완치|100\s*%|완전)")
    if HARD.search(text):
        return False
    # 걸린 소재가 기능성 stem이고, 문구가 승인된 완곡 형식이면 통과
    for stem in COSMETIC_FUNCTIONAL:
        if stem in matched and has_approved_form(text):
            return True
    return False
