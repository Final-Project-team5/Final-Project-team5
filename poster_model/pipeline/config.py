"""파이프라인 전역 설정.

모델 교체나 파라미터 튜닝은 이 파일만 수정하면 됩니다.
"""

# ---------------------------------------------------------------- 모델

MODELS = {
    "sd15": {
        "inpaint": "runwayml/stable-diffusion-inpainting",
        "text2img": "runwayml/stable-diffusion-v1-5",
        "size": 768,
        "variant": None,
    },
    "sdxl": {
        "inpaint": "diffusers/stable-diffusion-xl-1.0-inpainting-0.1",
        "text2img": "stabilityai/stable-diffusion-xl-base-1.0",
        "size": 1024,
        "variant": "fp16",
    },
}

DRAFT_MODEL = "sd15"    # 1단계: 시안 생성 (가벼움)
REFINE_MODEL = "sdxl"   # 2단계: 고품질 렌더링

# VRAM이 넉넉하면 False (속도 우선), 부족하면 True
USE_CPU_OFFLOAD = True

# 두 모델을 동시에 메모리에 올려둘지
KEEP_BOTH_LOADED = True

# ---------------------------------------------------------------- 마스킹

REMBG_MODEL = "u2net"       # 투명 포장에서 isnet보다 안전 (실험 결과)
DILATE = 6                  # 마스크 확장 px. 16은 halo 발생
MASK_BLUR = 8               # 마스크 경계 블러
COMPOSITE_BLUR = 2          # 원본 합성 시 경계 블러

# 제품 영역이 이 비율을 넘으면 배경 여백을 자동 확보
AREA_THRESHOLD = 0.45
MARGIN_SCALE = 0.7          # 여백 확보 시 제품 축소 비율
BG_BLUR = 40                # 여백 배경 블러 강도

# ---------------------------------------------------------------- 그림자
# 배경을 교체하면 원본 그림자가 마스크 밖(배경 영역)에 있어 사라지고
# 제품이 공중에 뜬 것처럼 보이는 문제 보정용 (접지 그림자 후처리, masking.add_ground_shadow)

SHADOW_OPACITY = 90           # 그림자 최대 진하기 (0~255). 110 -> 90 (실측 비교 1차)
SHADOW_BLUR = 14              # 그림자 블러 강도(px). 18 -> 14 (실측 비교 1차)
SHADOW_SQUASH = 0.28          # 타원 높이/너비 비율 (눌린 정도) — 우선 유지
SHADOW_Y_OFFSET_RATIO = 0.005 # 제품 하단 대비 그림자 중심 하향 오프셋 (이미지 크기 비례). 0.015 -> 0.005 (하단에 더 붙임)
SHADOW_MIN_AREA_RATIO = 0.005 # 이 비율보다 작은 연결요소는 노이즈로 보고 그림자 생략

# ---------------------------------------------------------------- 생성

DRAFT_STEPS = 30
REFINE_STEPS = 30
REFINE_STRENGTH = 0.35  # 실사용(inpaint) 경로 기준. 0.75는 장면을 거의 새로 그려 재해석이
                        # 심해짐 — 구도 유지·디테일 개선의 균형점으로 실험에서 확인된 값
NUM_DRAFTS = 3

# ---------------------------------------------------------------- 문구
#
# 폰트는 OS 설치에 의존하지 않고 프로젝트에 직접 번들링한다(assets/fonts/).
# 로컬 WSL과 GCP/Docker에서 항상 같은 폰트 파일이 재현되게 하기 위함.
# 출처·라이선스는 assets/fonts/SOURCES.md 참고.
#
# 역할:
#   headline — 굵은 광고 제목용
#   body / body_medium — 일반 설명문용 (강조 시 medium)
#   elegant — 감성/고급 스타일용
#   accent — 강한 포인트용. 글리프 범위가 좁으니(검은고딕 실측 2734자,
#            Pretendard/나눔명조는 14000+) 넣을 문구에 실제로 필요한 글자가
#            들어있는지 확인하고 선택적으로만 쓸 것

from pathlib import Path

FONT_DIR = Path(__file__).resolve().parent.parent / "assets" / "fonts"

FONTS = {
    # Gmarket Sans Bold: 이 파일은 아직 이 프로젝트에 없다. 공식 배포처
    # (corp.gmarket.com/fonts)에 받아 assets/fonts/GmarketSans/에 넣어야 한다.
    # 경로/파일명은 공식 배포본의 관례적인 이름을 따른 것이라 실제로 받은
    # 파일명과 다르면 이 값을 맞게 고쳐야 한다 (assets/fonts/GmarketSans/PENDING.md 참고).
    "headline": FONT_DIR / "GmarketSans" / "GmarketSansTTFBold.ttf",
    "body": FONT_DIR / "Pretendard" / "Pretendard-Regular.ttf",
    "body_medium": FONT_DIR / "Pretendard" / "Pretendard-Medium.ttf",
    "elegant": FONT_DIR / "NanumMyeongjo" / "NanumMyeongjoBold.ttf",
    "accent": FONT_DIR / "BlackHanSans" / "BlackHanSans-Regular.ttf",
}

# headline 파일(Gmarket Sans Bold)이 아직 없을 때 대신 쓸 역할.
# 파일이 생기기 전까지 코드가 죽지 않도록 하는 임시 안전장치일 뿐, 최종 모습이 아님.
FONT_FALLBACK_ROLE = "accent"

# 하위 호환용 별칭. overlay.py 등 기존 코드가 FONT_BOLD/FONT_REGULAR를
# 참조하던 부분을 점진적으로 FONTS[...] 참조로 옮기는 동안 유지한다.
FONT_BOLD = FONTS["headline"]
FONT_REGULAR = FONTS["body"]


def resolve_font_path(role: str) -> str:
    """역할 이름으로 실제 폰트 파일 경로를 반환한다.

    파일이 아직 없으면(예: Gmarket Sans Bold 미확보) 경고를 출력하고
    FONT_FALLBACK_ROLE로 대체한다. 그 대체 폰트마저 없으면 에러를 낸다 —
    조용히 넘어가면 나중에 왜 폰트가 이상하게 나오는지 추적하기 어렵다.
    """
    path = FONTS.get(role)
    if path and Path(path).is_file():
        return str(path)

    print(f"[config] 경고: '{role}' 역할 폰트 파일을 찾을 수 없습니다 ({path}). "
         f"'{FONT_FALLBACK_ROLE}'로 대체합니다.")
    fallback = FONTS.get(FONT_FALLBACK_ROLE)
    if fallback and Path(fallback).is_file():
        return str(fallback)

    raise FileNotFoundError(
        f"'{role}' 폰트({path})도, 폴백 폰트({fallback})도 찾을 수 없습니다. "
        f"assets/fonts/ 구성을 확인하세요.")

TEXT_MARGIN_RATIO = 0.06    # 이미지 크기 대비 여백
HEADLINE_RATIO = 0.07       # headline_size 미지정 시 기본값. 호출 시 0.07~0.30 범위로
                            # 자유롭게 키울 수 있다(overlay.render_text의 auto_fit이
                            # 배치 영역을 벗어날 때만 자동으로 축소해 안전하게 처리한다).
SUB_RATIO = 0.043           # sub_size 미지정 시 기본값. headline과 동일하게 자유롭게 조정 가능.
LINE_GAP_RATIO = 0.026

BAR_ALPHA = 140
BAR_RADIUS = 12
STROKE_WIDTH = 3

# 스타일(tone)별 headline/sub 권장 값. 하나의 headline_size 범위를 모든 톤에 그대로
# 쓰면(예: 0.18을 minimal_product에도 적용) 톤에 안 맞게 과하게 커질 수 있어 분리한다.
# render_text()의 headline_font_role/stroke_width 인자와 함께 쓰는 것을 전제로 한다.
TONE_PRESETS = {
    "minimal_product": {
        "headline_size": 0.11,        # 권장 범위 0.09~0.13
        "sub_size": 0.04,
        "headline_font_role": "body_medium",  # Gmarket Sans 확보 전까지 Pretendard Medium 사용
        "stroke_width": 0,             # 흰색+굵은 외곽선은 이벤트 전단처럼 보여 제거
        "fill_color": (45, 40, 38, 255),  # 밝은 solid/gradient 배경(BG_PALETTES) 대비용 짙은 단색
    },
    "bold_promo": {
        "headline_size": 0.22,        # 권장 범위 0.18~0.28
        "sub_size": 0.06,
        "headline_font_role": "headline",
        "stroke_width": STROKE_WIDTH,   # 강한 인상이 목적이므로 기존 굵은 stroke 유지
        "fill_color": (255, 255, 255, 255),  # 기존처럼 흰색 + 외곽선
    },
}

# ---------------------------------------------------------------- 프롬프트

PROMPT_TEMPLATES = {
    "food": (
        "marble table, cozy cafe interior, soft natural window light, "
        "professional food photography, bokeh"
    ),
    "beauty": (
        "clean minimal background, soft gradient, studio lighting, "
        "elegant, professional cosmetic photography"
    ),
    "goods": (
        "clean white studio background, soft shadow, "
        "professional product photography, minimal, commercial"
    ),
}

DEFAULT_CATEGORY = "goods"

# ---------------------------------------------------------------- 배경 모드 (solid/gradient)
# background_mode="ai"가 기본값이며 기존 diffusion 경로는 변경하지 않는다.
# solid/gradient는 diffusion을 완전히 생략하고 PIL로만 배경을 채운다 (masking.render_flat_background).
# 카테고리별 기본 팔레트는 우선 3색으로 시작 (과도하게 늘리지 않음)
BG_PALETTES = {
    "food": ["#F5EDE0", "#F0DCC8", "#E8C9A8"],      # 크림 -> 테라코타 계열 (따뜻한 톤)
    "beauty": ["#F5F1EC", "#E8E4DD", "#E6EAEE"],    # 베이지 / 크림 / 소프트 그레이
    "goods": ["#FFFFFF", "#F2F2F2", "#E5E5E5"],     # 뉴트럴 스튜디오 화이트/그레이
}

# 사용자가 색상을 정확히 1개(solid)/2개(gradient) 지정했을 때 draft 여러 장을 만들기 위한
# base/light/dark 변형 폭 (HSL lightness 기준 ±). 지정 색이 draft마다 그대로 유지되진 않으니
# 응답의 background.colors에 실제 적용된 색을 그대로 내려서 프론트가 확인할 수 있게 한다.
BG_VARIANT_LIGHTNESS_DELTA = 0.12

# 배경 생성 시 제외할 요소
NEGATIVE_PROMPT = (
    "text, watermark, logo, letters, blurry, distorted, low quality, "
    "additional objects, extra props, multiple products, duplicate item, clutter"
)

# 모든 카테고리 프롬프트에 공통으로 덧붙이는 그림자 유도 문구 (비용 0, generate.resolve_prompt에서 사용)
SHADOW_PROMPT_SUFFIX = "soft contact shadow under product, grounded, sitting on surface"

# 참고 포스터들은 대부분 제품 하나만 단독으로 다룸(다른 사물 없음). SDXL이 "commercial
# product photography" 같은 문구에서 소품을 임의로 만들어 넣는 환각이 있어 방지 문구 추가
ISOLATION_PROMPT_SUFFIX = "single product only, isolated product shot, no other objects"
