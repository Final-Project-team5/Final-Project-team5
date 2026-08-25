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

# 가중치를 호스트 RAM에 두고 필요할 때만 GPU로 올릴지(True) 아니면 VRAM에 상주시킬지(False).
#
# True는 VRAM이 부족할 때 쓰는 설정이다. VRAM은 아끼지만 그만큼 호스트 RAM을 쓴다.
# 배포 VM은 반대 상황이라 False로 둔다.
#
#   VM  VRAM 24GB · RAM 16GB     넉넉한 쪽이 VRAM이다
#
# True였을 때 실측(2026-08-25, 배포 VM):
#
#   poster_model RSS   10.2GB / 15GB   시스템 RAM의 62%
#   VRAM 사용          280MiB / 23GB   ★ 1.2%
#
# 가중치 10GB가 전부 RAM에 올라가 있고 GPU는 비어 있었다. 이 상태에서 refine이
# 돌면 남은 4GB로 SDXL 추론 버퍼를 감당해야 해서 OOM Kill이 났다(진우님 실연동
# 7회 중 refine 단계에서 발생). 단색/그라데이션 배경에서 재현되지 않은 것은 그
# 경로가 diffusion을 타지 않기 때문이다.
#
# VRAM이 부족한 환경으로 옮기면 다시 True로 돌린다. 그때는 아래 _load()의
# slicing/tiling이 offload와 분리돼 있으므로 이 값만 바꾸면 된다.
USE_CPU_OFFLOAD = False

# warmup에서 SDXL까지 미리 올려둘지.
#
# False면 기동 시 SD1.5 계열만 적재하고, SDXL은 첫 refine에서 로드한다.
# 첫 refine 한 번이 모델 로딩만큼 느려지고 그 뒤로는 캐시된다.
#
# 왜 False인가 — 상주 총량이 이 장비에 안 맞는다.
#
#   sd15_inpaint         2.1GB
#   sd15_text2img        2.1GB
#   sd15_inpaint_notile  2.1GB   inpaint와 같은 가중치를 한 번 더 로드한다
#   sdxl_inpaint         7.0GB
#   sdxl_img2img         7.0GB
#   ─────────────────────────
#                      ≈ 20.4GB
#
# 20.4GB는 RAM(15GB)에도 VRAM(23GB에서 추론 여유를 빼면)에도 넉넉히 들어가지
# 않는다. 실제로 USE_CPU_OFFLOAD=False로 VRAM에 올렸더니 상주 20.4GB에 가용
# 413MiB만 남아 refine의 512MiB 할당에서 CUDA OOM이 났다(2026-08-25 VM 실측).
#
# True로 두려면 아래 두 가지 중복부터 없애야 한다. 둘 다 다음 스프린트 과제다.
#   - sd15_inpaint_notile이 inpaint와 컴포넌트를 공유하도록 (-2.1GB)
#   - SDXL 두 변형이 text encoder/VAE를 공유하도록 (-1.6GB)
KEEP_BOTH_LOADED = False

# ---------------------------------------------------------------- 마스킹

REMBG_MODEL = "u2net"       # 투명 포장에서 isnet보다 안전 (실험 결과)
DILATE = 6                  # 마스크 확장 px. 16은 halo 발생
MASK_BLUR = 8               # 마스크 경계 블러
COMPOSITE_BLUR = 2          # 원본 합성 시 경계 블러

# 제품 영역이 이 비율을 넘으면 배경 여백을 자동 확보
# --- 출력 비율 (A2-1) ---
# 아직 generate/api 어디에도 연결하지 않았다. 크기 계산만 담당한다.
# 값은 (가로비, 세로비). 짧은 변을 OUTPUT_SHORT_SIDE로 고정하고 긴 변을 계산한다.
ASPECT_RATIOS = {
    "1:1": (1, 1),      # SNS
    "3:1": (3, 1),      # 배너
    "3:4": (3, 4),      # 상세페이지
}
DEFAULT_ASPECT_RATIO = "1:1"
OUTPUT_SHORT_SIDE = 1024    # SDXL 기준. 8의 배수여야 한다.

# --- 비율별 기본 제품 배치 (A2-2, 내부 상수) ---
# 아직 API 계약이 아니다. 방향을 뒤집거나 값을 조정할 수 있어야 하므로 여기 둔다.
#
#   axis          영역을 나누는 축. "x"=좌우, "y"=상하
#   text_end      문구 영역이 끝나는 지점 (축 길이 대비 비율)
#   product_start 제품 영역이 시작하는 지점 (축 길이 대비 비율)
#   flip          True면 제품이 앞쪽(왼쪽/위쪽), 문구가 뒤쪽에 온다
#
# 1:1은 항목이 없다 = 영역 분할 없이 소스 위치를 그대로 유지한다(기존 동작 보존).
CANVAS_REGIONS = {
    "3:1": {"axis": "x", "text_end": 0.50, "product_start": 0.55, "flip": False},
    # 제품 영역이 하단 65%가 되도록 product_start = 1 - 0.65 = 0.35.
    "3:4": {"axis": "y", "text_end": 0.35, "product_start": 0.35, "flip": False},
}
CANVAS_MARGIN_RATIO = 0.04   # 캔버스 가장자리 여백 (짧은 변 대비)

# 제품 회전(Product Layout v2) 허용 각도. 외부 계약은 **양수 = 시계 방향**이다.
# Product Layout v2에서 검증한 허용 범위. 범위 밖은 조용히 clamp하지 않고 거부한다.
ROTATION_MAX_ABS_DEG = 20.0

# 회전 시 접지 그림자 계산에 쓰는 값들. rotation_deg == 0이면 이 값들은 쓰이지
# 않고 기존 legacy 경로가 그대로 돈다(하위 호환).
#   기울어진 제품은 bbox 중심과 실제 접지점이 어긋나므로, 하단 band의 x 분포로
#   접지 중심/폭을 다시 잡는다. 실험(B1)에서 검증한 값이며 이번 범위에서
#   추가 튜닝하지 않는다.
SHADOW_CONTACT_BAND_RATIO = 0.12   # 성분 높이 대비 하단 band 두께
SHADOW_CONTACT_PCT = (5, 95)       # band 내 x 백분위수 (min/max 대신)
SHADOW_CONTACT_MIN_WIDTH_RATIO = 0.45  # 접지 폭 하한 (성분 bbox 폭 대비)
SHADOW_CONTACT_MAX_SHIFT_RATIO = 0.30  # 중심 이동 상한 (성분 bbox 폭 대비)

# 배치 배율 상수. 실험값을 초기 내부값으로 재사용한다.
# production 정책 확정값이 아니며 A3 전에 재검증 대상이다.
CANVAS_MAX_UPSCALE = 1.6     # 소스 누끼 대비 확대 상한. provisional 내부값이다
                             # (실제 샘플에서 상한에 걸린 사례가 아직 없어
                             #  '검증된 최적값'으로 보지 않는다).
                             # 클라이언트 override의 최종 배율도 이 값을 넘을 수 없다.
CANVAS_SAFETY_FACTOR = 0.97  # 계산된 배율에 곱하는 여유 계수

# draft/refine 이미지 크기에서 비율을 추론할 때의 상대 오차 허용치.
# 3:4 최종 출력이 1024x1368(=0.7485)이라 정확히 0.75가 아니고, 프론트 재인코딩으로
# 몇 px이 달라질 수 있어 exact 비교를 쓰지 않는다.
ASPECT_INFER_TOLERANCE = 0.005

# --- AI 배경의 비정사각 지원 (A4-2, 내부 상수) ---
# 3:4는 glass 계열에서 제품 외부에 neck/cap/bottom 구조를 만드는 continuation이
# 확인됐고, 투명/위험 제품을 구분하는 정책이 아직 없어 제외한다.
AI_SUPPORTED_RATIOS = ("1:1", "3:1")

# AI diffusion을 실제로 돌릴 짧은 변. 최종 캔버스와 분리한다.
# 제품은 최종 해상도 원본으로 다시 합성하므로 저해상도 생성의 손실은 배경에만 남는다.
#   3:1 refine 3072x1024 직접 생성: 1430s / peak reserved 16.664GB (제외)
#   3:1 refine 2304x768  생성:      12.67~131.56s, 지연 변동 큼    (제외)
#   3:1 refine 1728x576  생성:      3.7~3.8s / peak reserved 9.961GB (채택)
# 한계: 복잡한 미세 질감 배경에서 디테일 감소 가능 (outputs/verification/aspect/ai_nonsquare 참고).
# 미실행 후보로 1920x640(R2.5)을 남겨두었다.
AI_GEN_SHORT_SIDE = {"3:1": {"draft": 512, "refine": 576}}

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


# ---------------------------------------------------------------------------
# font_id — 사용자가 직접 고르는 폰트
#
# 위의 FONTS(역할 기반)와는 목적이 다르다. FONTS는 "서버가 용도에 맞게 고르는"
# 것이고, 여기 FONT_IDS는 "프론트에서 사용자가 고른" 것이다. 그래서 폴백 규칙도
# 정반대다 — 역할 기반은 파일이 없으면 대체 폰트로 넘어가지만, font_id는
# **절대 다른 폰트로 조용히 바꾸지 않는다**. 사용자가 고른 폰트가 아닌 결과가
# 나가면 무엇이 잘못됐는지 알 방법이 없기 때문이다.
#
# ID 문자열은 프론트 계약(PR #38)에서 확정된 값 그대로다. 구분자 없는 소문자이고,
# 이 값은 클라이언트가 저장해두는 식별자라 임의로 바꾸면 안 된다.
#
# weight는 이번 범위에서 API 파라미터로 두지 않는다. ID 하나가 프론트 UI에
# 표시되는 그 폰트 파일 하나를 직접 가리킨다(Gmarket Sans는 Bold/Medium/Light
# 중 Medium으로 고정 — 팀 결정).
#
# 선택된 폰트 하나가 headline과 sub에 **공통** 적용된다.
FONT_IDS = {
    "pretendard": FONT_DIR / "Pretendard" / "Pretendard-Regular.ttf",
    "nanummyeongjo": FONT_DIR / "NanumMyeongjo" / "NanumMyeongjoBold.ttf",
    "gmarketsans": FONT_DIR / "GmarketSans" / "GmarketSansTTFMedium.ttf",
    "galmuri11": FONT_DIR / "Galmuri11" / "Galmuri11.ttf",
    "nanumpen": FONT_DIR / "NanumPen" / "NanumPen.ttf",
}


class FontRejection(ValueError):
    """font_id를 처리할 수 없을 때. payload를 그대로 400 응답 본문에 쓴다.

    layout.LayoutRejection과 같은 구조다 — 파이프라인 계층은 HTTP를 모르고,
    API 계층이 payload를 그대로 내려보낸다.
    """

    def __init__(self, error: str, message: str, **detail):
        super().__init__(message)
        self.payload = {"error": error, "message": message, **detail}


def available_font_ids() -> list:
    """등록된 ID 중 **실제 TTF 파일이 있는 것**만. 순서를 고정해 응답을 안정시킨다."""
    return [k for k in FONT_IDS if Path(FONT_IDS[k]).is_file()]


def resolve_font_id_path(font_id: str) -> str:
    """사용자가 고른 font_id를 실제 폰트 파일 경로로 바꾼다.

    resolve_font_path(역할 기반)와 달리 **폴백이 없다**. 두 가지 실패를 구분한다.

        font_not_supported — whitelist에 없는 ID. 프론트가 계약에 없는 값을 보냄
        font_asset_missing — 계약에는 있지만 이 브랜치에 TTF가 아직 없음
                             (PR #27 자산 병합 전 상태)

    프론트가 받아야 할 신호가 다르다. 앞은 클라이언트를 고쳐야 하고, 뒤는
    서버 자산을 채우면 해결된다. 그래서 같은 400이라도 error 코드를 나눈다.

    Raises: FontRejection
    """
    path = FONT_IDS.get(font_id)
    if path is None:
        raise FontRejection(
            "font_not_supported",
            f"지원하지 않는 font_id입니다: {font_id!r}",
            supported=sorted(FONT_IDS), available=available_font_ids())
    if not Path(path).is_file():
        # 서버 내부 절대 경로는 응답에 넣지 않는다. 어떤 폰트가 비어 있는지만 알린다.
        raise FontRejection(
            "font_asset_missing",
            f"font_id {font_id!r}는 지원 목록에 있지만 서버에 폰트 파일이 "
            f"아직 없습니다. 다른 폰트로 대체하지 않고 요청을 거부합니다.",
            font_id=font_id, available=available_font_ids())
    return str(path)

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

# 서비스형(학원·체육관 등) 기본 품질 baseline.
#
# 업종별 템플릿을 만들지 않는다. academy/sports를 나누면 업종이 늘 때마다
# 템플릿이 늘어난다. 업종별 차이는 사용자 prompt가 담당한다.
# 제품 전제 어휘(product / product shot / shadow under product)를 쓰지 않는다.
SERVICE_QUALITY_BASELINE = (
    "professional commercial photography of an interior space, "
    "natural lighting, clean composition, inviting atmosphere"
)
