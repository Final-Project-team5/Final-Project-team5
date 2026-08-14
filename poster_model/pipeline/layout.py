"""출력 캔버스 크기 계산.

A2-1 범위: 비율 → W×H 계산만 한다. generate의 canvas_wh에 연결하지 않았고
API에도 노출하지 않는다. 3:1/3:4에서 제품을 어디에 얼마나 크게 둘지(scale,
x_px, y_px)는 이 모듈의 책임이 아니며 아직 정해지지 않았다(B 단계).

place_product_on_canvas()가 배치값을 받기만 하고 정하지 않으므로, 여기서
canvas_wh만 바꿔 연결하면 제품이 소스 위치에 그대로 남는다. 그래서 배선은
의도적으로 하지 않았다.
"""
from . import config
from .masking import _as_wh


def _round8(v: float) -> int:
    """8의 배수로 반올림한다.

    diffusion 계열이 8의 배수 해상도를 요구하고, 내림을 쓰면 목표 비율에서
    멀어진다(3:4에서 1365.3 → 내림 1360이 되어 0.7529, 반올림 1368은 0.7485).
    """
    return max(8, int(round(v / 8.0)) * 8)


def resolve_output_size(ratio: str = None, short_side: int = None) -> tuple[int, int]:
    """비율 문자열을 최종 캔버스 (W, H)로 바꾼다.

    짧은 변을 short_side로 고정하고 긴 변을 비율에서 계산한 뒤 8의 배수로
    반올림한다. 두 변 모두 8의 배수임이 보장된다.

        1:1 → 1024 x 1024
        3:1 → 3072 x 1024
        3:4 → 1024 x 1368     (1024 x 4/3 = 1365.3 → 1368)

    Args:
        ratio: config.ASPECT_RATIOS의 키. None이면 DEFAULT_ASPECT_RATIO.
        short_side: 짧은 변 픽셀. None이면 config.OUTPUT_SHORT_SIDE.

    Raises:
        ValueError: 지원하지 않는 비율이거나 short_side가 양수가 아닐 때.
    """
    key = config.DEFAULT_ASPECT_RATIO if ratio is None else str(ratio).strip()
    if key not in config.ASPECT_RATIOS:
        raise ValueError(
            f"지원하지 않는 비율입니다: {ratio!r} "
            f"(지원: {', '.join(sorted(config.ASPECT_RATIOS))})")

    short = config.OUTPUT_SHORT_SIDE if short_side is None else short_side
    if not isinstance(short, int) or isinstance(short, bool) or short <= 0:
        raise ValueError(f"short_side는 양의 정수여야 합니다: {short_side!r}")

    rw, rh = config.ASPECT_RATIOS[key]
    short = _round8(short)
    if rw >= rh:                       # 가로가 길다 → 세로가 짧은 변
        return _round8(short * rw / rh), short
    return short, _round8(short * rh / rw)


# =============================================================================
# 제품 배치 (A2-2, 내부 전용)
# =============================================================================
# 문구 내용에 의존하지 않는 최소 기본 배치만 계산한다. textfit/recommendation
# 같은 문구 기반 판단은 포함하지 않는다.
#
# 서버가 기본값을 계산하고 클라이언트 override를 허용하되, override여도 최종
# product+shadow footprint를 서버가 다시 검증한다. 클라이언트가 그림자 기하를
# 복제해서 계산하게 만들지 않기 위해서다.

import cv2                                          # noqa: E402
import numpy as np                                  # noqa: E402
from dataclasses import dataclass, field            # noqa: E402


class LayoutRejection(ValueError):
    """api.py가 400 detail로 그대로 쓸 수 있는 구조화된 거부."""

    def __init__(self, error: str, message: str, **detail):
        super().__init__(message)
        self.payload = {"error": error, "message": message, **detail}


@dataclass
class Placement:
    """제품을 캔버스에 놓는 방법.

    scale / x_px / y_px는 **내부 좌표계**다. scale은 소스 누끼 bbox 대비 배율,
    x_px/y_px는 제품 bbox 좌상단의 캔버스 픽셀 좌표다.
    외부(API)에는 이 값을 그대로 노출하지 않고 as_public()으로 변환한다.
    """
    scale: float
    x_px: int = None            # None = 소스에서의 bbox 위치 유지
    y_px: int = None
    source: str = "auto"        # identity | auto | override
    region: tuple = None        # 제품 영역 (x0, y0, x1, y1). identity면 None
    auto_scale: float = 1.0     # 서버 기본 배율. scale_factor 역산용
    source_bbox: tuple = None   # 소스 제품 bbox (x0, y0, x1, y1)
    notes: list = field(default_factory=list)

    def as_kwargs(self) -> dict:
        return {"scale": self.scale, "x_px": self.x_px, "y_px": self.y_px}

    def as_public(self, canvas_wh, region_overflow: bool = False) -> dict:
        """외부 계약 형태. 부분 override여도 서버 계산값으로 채워진 최종 상태다.

        x, y는 **제품 bbox 중심점**의 캔버스 정규화 좌표(0~1)다. 내부의 좌상단
        좌표를 그대로 노출하면 배율이 바뀔 때 사용자 기준점이 흔들린다.
        """
        W, H = _as_wh(canvas_wh)
        bx0, by0, bx1, by1 = self.source_bbox
        bw, bh = (bx1 - bx0 + 1) * self.scale, (by1 - by0 + 1) * self.scale
        left = bx0 if self.x_px is None else self.x_px
        top = by0 if self.y_px is None else self.y_px
        return {
            "source": self.source,
            "scale_factor": round(self.scale / self.auto_scale, 4),
            "x": round((left + bw / 2) / W, 4),
            "y": round((top + bh / 2) / H, 4),
            "region_overflow": bool(region_overflow),
        }


def product_region(canvas_wh, ratio: str = None) -> tuple:
    """비율별 제품 영역 (x0, y0, x1, y1). 분할 규칙이 없으면 None."""
    W, H = canvas_wh
    key = config.DEFAULT_ASPECT_RATIO if ratio is None else str(ratio).strip()
    rule = config.CANVAS_REGIONS.get(key)
    if rule is None:
        return None                      # 1:1 — 영역 분할 없음
    m = int(round(min(W, H) * config.CANVAS_MARGIN_RATIO))
    if rule["axis"] == "x":
        start = int(round(W * rule["product_start"]))
        box = (start, m, W - m, H - m) if not rule["flip"] else \
              (m, m, int(round(W * rule["text_end"])), H - m)
    else:
        start = int(round(H * rule["product_start"]))
        box = (m, start, W - m, H - m) if not rule["flip"] else \
              (m, m, W - m, int(round(H * rule["text_end"])))
    return box


def _component_stats(product_mask):
    """연결요소 통계와 제품 bbox. add_ground_shadow()의 계산과 좌표계를 맞춘다.

    width는 add_ground_shadow와 동일하게 x_max - x_min (+1 아님)을 쓴다.
    면적 필터는 여기서 적용하지 않는다. 필터 기준(캔버스 면적 대비)이 배율에
    따라 달라지므로 배율마다 다시 판정해야 한다.

    ## 두 가지 폭 규약이 함께 있다 — 섞으면 안 된다

    width  = x_max - x_min          그림자 타원 폭 계산용. **기존 규약 그대로**
                                    add_ground_shadow와 1px까지 맞춰져 있다
    box    = (x, y, x + w, y + h)   Layout Validator용 bbox.
                                    right/bottom **exclusive**이며 cv2의
                                    WIDTH/HEIGHT가 이미 exclusive 폭이라 +1이 없다

    box는 **소스 좌표계**다. 캔버스 좌표로 옮긴 값은 validate_placement가
    component_boxes로 돌려준다.
    """
    binary = (np.array(product_mask.convert("L")) > 128).astype(np.uint8)
    ys, xs = np.where(binary > 0)
    if len(xs) == 0:
        raise ValueError("제품 마스크가 비어 있어 배치를 계산할 수 없습니다.")
    bx0, by0, bx1, by1 = int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())
    n, _labels, stats, _c = cv2.connectedComponentsWithStats(binary, connectivity=8)
    comps = []
    for i in range(1, n):
        x, y, w, h, area = (int(stats[i, cv2.CC_STAT_LEFT]),
                            int(stats[i, cv2.CC_STAT_TOP]),
                            int(stats[i, cv2.CC_STAT_WIDTH]),
                            int(stats[i, cv2.CC_STAT_HEIGHT]),
                            int(stats[i, cv2.CC_STAT_AREA]))
        comps.append({"area": area, "width": w - 1,
                      "rel_cx": (x + x + w - 1) / 2 - bx0,
                      "rel_y_max": (y + h - 1) - by0,
                      "box": (float(x), float(y),
                              float(x + w), float(y + h))})
    return comps, (bx0, by0, bx1, by1)


def _footprint_extent(comps, f, bw, bh, canvas_wh):
    """배율 f에서 제품 bbox 좌상단을 원점에 뒀을 때의 product+shadow 합집합.

    add_ground_shadow()의 실제 식을 그대로 따른다.
        ew = width * 0.95,  eh = max(width * SHADOW_SQUASH, 6)
        ey = y_max + H * SHADOW_Y_OFFSET_RATIO
    면적 필터는 배율을 반영해 area * f^2로 다시 판정한다.
    제품 bbox에는 blur 여유를 더하지 않는다(그림자에만 더한다).

    blur 여유는 3*SHADOW_BLUR을 쓴다. 2배로 두면 GaussianBlur의 꼬리를 다 덮지
    못해 추정 bbox가 실측 그림자보다 작아지는 것이 실측으로 확인됐다
    (3:1에서 좌우 3px, 아래 6px 초과). 여기서는 실측 보정 단계가 없으므로
    추정이 항상 실측을 감싸야 한다.
    """
    W, H = canvas_wh
    min_area = W * H * config.SHADOW_MIN_AREA_RATIO
    pad = 3 * config.SHADOW_BLUR
    x0, y0, x1, y1 = 0.0, 0.0, bw * f, bh * f
    for c in comps:
        if c["area"] * f * f < min_area:
            continue                                   # 이 배율에서는 걸러짐
        w = c["width"] * f
        ew, eh = w * 0.95, max(w * config.SHADOW_SQUASH, 6)
        cx = c["rel_cx"] * f
        ey = c["rel_y_max"] * f + H * config.SHADOW_Y_OFFSET_RATIO
        x0 = min(x0, cx - ew / 2 - pad)
        x1 = max(x1, cx + ew / 2 + pad)
        y0 = min(y0, ey - eh / 2 - pad)
        y1 = max(y1, ey + eh / 2 + pad)
    return x0, y0, x1, y1


def _solve_scale(comps, bw, bh, region, canvas_wh) -> float:
    """footprint가 영역에 들어가는 최대 배율. 이분 탐색.

    컴포넌트별 조건과 max(w*squash, 6) 바닥값 때문에 닫힌 식이 없다.
    footprint 크기는 f에 대해 단조 비감소라 이분 탐색이 성립한다.
    """
    rw, rh = region[2] - region[0], region[3] - region[1]

    def fits(f):
        x0, y0, x1, y1 = _footprint_extent(comps, f, bw, bh, canvas_wh)
        return (x1 - x0) <= rw and (y1 - y0) <= rh

    hi = config.CANVAS_MAX_UPSCALE
    if fits(hi):
        return hi * config.CANVAS_SAFETY_FACTOR
    lo = 0.0
    for _ in range(20):
        mid = (lo + hi) / 2
        if fits(mid):
            lo = mid
        else:
            hi = mid
    return lo * config.CANVAS_SAFETY_FACTOR


def _center_to_topleft(x, y, bw, bh, scale, canvas_wh):
    """외부 중심 정규화 좌표 → 내부 bbox 좌상단 픽셀 좌표."""
    W, H = canvas_wh
    return (int(round(x * W - bw * scale / 2)),
            int(round(y * H - bh * scale / 2)))


def compute_placement(masks, canvas_wh, ratio: str = None,
                      override: dict = None) -> Placement:
    """비율별 기본 배치를 계산한다. override가 있으면 그 값으로 덮는다.

    override는 **외부 계약 형태**다.
        scale_factor  서버 기본 배율 대비 배수 (1.0 = 기본값 그대로)
        x, y          제품 bbox 중심점의 캔버스 정규화 좌표 (0~1)
    셋 다 선택이며, 지정하지 않은 값은 서버 계산값으로 채워진다.

    scale_factor만 지정하고 x/y를 생략하면 자동 좌표를 재사용하지 않고
    **바뀐 배율로 영역 중앙 정렬을 다시 계산**한다. 배율이 바뀌면 footprint
    크기가 달라져 원래 좌표로는 영역에서 벗어나기 때문이다.

    1:1(영역 분할 규칙 없음)은 배율 1.0 + 위치 유지라 place_product_on_canvas의
    항등 경로를 타고, 기존 결과가 픽셀 단위로 보존된다.

    Raises:
        LayoutRejection: 최종 배율이 CANVAS_MAX_UPSCALE을 넘을 때.
    """
    W, H = _as_wh(canvas_wh)
    region = product_region((W, H), ratio)
    comps, sbox = _component_stats(masks.product)
    bx0, by0, bx1, by1 = sbox
    bw, bh = bx1 - bx0 + 1, by1 - by0 + 1

    def centered(f):
        """배율 f에서 footprint를 영역 중앙에 놓는 bbox 좌상단 좌표."""
        fx0, fy0, fx1, fy1 = _footprint_extent(comps, f, bw, bh, (W, H))
        tx = region[0] + ((region[2] - region[0]) - (fx1 - fx0)) / 2
        ty = region[1] + ((region[3] - region[1]) - (fy1 - fy0)) / 2
        return int(round(tx - fx0)), int(round(ty - fy0))

    if region is None:
        auto = Placement(1.0, None, None, "identity", None, 1.0, sbox)
    else:
        f = _solve_scale(comps, bw, bh, region, (W, H))
        ax, ay = centered(f)
        auto = Placement(round(f, 6), ax, ay, "auto", region, round(f, 6), sbox)

    if not override:
        return auto

    sf = override.get("scale_factor")
    sf = 1.0 if sf is None else float(sf)
    if sf <= 0:
        raise LayoutRejection("placement_invalid",
                              f"scale_factor는 양수여야 합니다: {sf}")
    scale = auto.scale * sf
    if scale > config.CANVAS_MAX_UPSCALE + 1e-9:
        raise LayoutRejection(
            "placement_over_max_upscale",
            f"확대 배율 상한을 초과합니다 (요청 {scale:.3f} > 상한 "
            f"{config.CANVAS_MAX_UPSCALE}). 확대할수록 제품 디테일이 뭉개집니다.",
            max_upscale=config.CANVAS_MAX_UPSCALE,
            requested_scale=round(scale, 4),
            max_scale_factor=round(config.CANVAS_MAX_UPSCALE / auto.scale, 4),
            suggested=auto.as_public((W, H)))

    x, y = override.get("x"), override.get("y")
    if x is None and y is None:
        # 좌표 미지정 — 바뀐 배율로 다시 중앙 정렬한다(원래 좌표 재사용 아님).
        nx, ny = centered(scale) if region is not None else (auto.x_px, auto.y_px)
    else:
        # 한쪽만 지정되면 나머지는 서버 계산값을 중심 좌표로 환산해 쓴다.
        cur = auto.as_public((W, H))
        cx = cur["x"] if x is None else float(x)
        cy = cur["y"] if y is None else float(y)
        nx, ny = _center_to_topleft(cx, cy, bw, bh, scale, (W, H))

    return Placement(round(scale, 6), nx, ny, "override", region,
                     auto.scale, sbox)


def validate_placement(masks, canvas_wh, placement: Placement,
                       strict: bool = True) -> dict:
    """배치 결과의 product+shadow footprint를 캔버스 기준으로 검증한다.

    클라이언트 override든 서버 계산이든 동일하게 통과시킨다. 클라이언트가
    그림자 기하를 알 수 없으므로 이 검증은 서버에만 있을 수 있다.

    Args:
        strict: True면 캔버스를 벗어날 때 ValueError. False면 결과만 돌려준다.

    Returns:
        {"ok", "product_box", "footprint", "canvas_clipped",
         "region_overflow", "reasons", "component_boxes"}

        component_boxes는 연결요소별 bbox를 **product_box와 같은 캔버스 좌표계**로
        옮긴 값이다((left, top, right, bottom), right/bottom exclusive).
        면적 필터를 적용하지 않으므로 작은 덩어리도 그대로 들어 있다 — 그림자를
        그릴지 정하는 기준(SHADOW_MIN_AREA_RATIO)과는 목적이 다르기 때문이다.
        합집합의 bbox는 product_box와 일치한다.
    """
    W, H = _as_wh(canvas_wh)
    comps, (bx0, by0, bx1, by1) = _component_stats(masks.product)
    bw, bh = bx1 - bx0 + 1, by1 - by0 + 1
    f = placement.scale
    dx = bx0 if placement.x_px is None else placement.x_px
    dy = by0 if placement.y_px is None else placement.y_px

    fx0, fy0, fx1, fy1 = _footprint_extent(comps, f, bw, bh, (W, H))
    fp = (dx + fx0, dy + fy0, dx + fx1, dy + fy1)
    pb = (dx, dy, dx + bw * f, dy + bh * f)

    # 소스 좌표 → 캔버스 좌표. product_box와 **같은 변환**을 써야 기준이 맞는다
    #   (px, py) -> (dx + (px - bx0) * f,  dy + (py - by0) * f)
    cbs = [(dx + (c["box"][0] - bx0) * f, dy + (c["box"][1] - by0) * f,
            dx + (c["box"][2] - bx0) * f, dy + (c["box"][3] - by0) * f)
           for c in comps]

    reasons = []
    if pb[0] < 0 or pb[1] < 0 or pb[2] > W or pb[3] > H:
        reasons.append("product_clipped")
    if fp[0] < 0 or fp[1] < 0 or fp[2] > W or fp[3] > H:
        reasons.append("shadow_clipped")
    clipped = bool(reasons)

    overflow = False
    if placement.region is not None:
        r = placement.region
        overflow = fp[0] < r[0] or fp[1] < r[1] or fp[2] > r[2] or fp[3] > r[3]
        if overflow:
            reasons.append("region_overflow")   # 경고. 캔버스 이탈과는 별개다.

    result = {"ok": not clipped, "product_box": pb, "footprint": fp,
              "canvas_clipped": clipped, "region_overflow": overflow,
              "reasons": reasons, "component_boxes": cbs}
    if strict and clipped:
        raise LayoutRejection(
            "placement_unsafe",
            f"배치가 캔버스를 벗어납니다({', '.join(reasons)}).",
            reasons=reasons,
            canvas={"width": W, "height": H},
            footprint=[round(v, 1) for v in fp])
    return result


def resolve_ai_gen_size(ratio: str, stage: str, final_wh) -> tuple:
    """AI diffusion을 실제로 돌릴 (W, H). 최종 캔버스와 분리된 값이다.

    **fail-closed다.** 등록되지 않은 조합은 최종 크기로 조용히 떨어지지 않고
    ValueError를 낸다. 3:4처럼 아직 차단된 비율이 실수로 여기까지 들어왔을 때
    full-resolution 직접 생성으로 진행되는 것이 가장 위험한 실패이기 때문이다.

    1:1은 최종 캔버스를 그대로 돌려준다(= 업스케일 단계가 실행되지 않음).
    """
    key = config.DEFAULT_ASPECT_RATIO if ratio is None else str(ratio).strip()
    if key == "1:1":
        return _as_wh(final_wh)
    table = config.AI_GEN_SHORT_SIDE.get(key)
    if table is None or stage not in table:
        raise ValueError(
            f"AI 생성 해상도가 정의되지 않은 조합입니다: ratio={key!r}, stage={stage!r} "
            f"(지원: {', '.join(sorted(config.AI_GEN_SHORT_SIDE)) or '없음'})")
    return resolve_output_size(key, short_side=table[stage])


def plan_canvas(ratio: str, short_side: int) -> tuple:
    """비율 → (canvas_wh, blur_margin 적용 여부).

    ratio가 None이면 정사각 short_side 캔버스라 기존 동작과 같다.
    비정사각에서만 blur margin을 생략한다(캔버스 배치가 제품 크기를 단독 책임).
    """
    canvas = resolve_output_size(ratio, short_side=short_side)
    return canvas, canvas == (short_side, short_side)


# =============================================================================
# 비율 추론/교차 검증 (A3-1, 내부 전용)
# =============================================================================

def infer_aspect_ratio(size_wh, tolerance: float = None):
    """이미지 크기에서 지원 비율을 추론한다. 없으면 None.

    exact 비교를 쓰지 않는다. 3:4의 최종 출력이 1024x1368(=0.7485)이라 정확히
    0.75가 아니고, draft(짧은 변 768)와 refine(1024)의 8배수 반올림 결과가 다르며,
    프론트가 draft를 재인코딩하면 몇 px이 달라질 수 있다.

        1024x1368 → 0.74854  목표 0.75  상대오차 0.195%  → "3:4"
        768x1024  → 0.75000  목표 0.75  상대오차 0%      → "3:4"
        2304x768  → 3.0                                 → "3:1"
    """
    W, H = _as_wh(size_wh)
    if W <= 0 or H <= 0:
        return None
    tol = config.ASPECT_INFER_TOLERANCE if tolerance is None else tolerance
    ratio = W / H
    best, best_err = None, None
    for key, (rw, rh) in config.ASPECT_RATIOS.items():
        target = rw / rh
        err = abs(ratio - target) / target
        if err <= tol and (best_err is None or err < best_err):
            best, best_err = key, err
    return best


def resolve_aspect_ratio(requested: str = None, image_size=None) -> tuple:
    """요청값과 이미지 크기 추론을 합쳐 최종 비율을 정한다.

    조용한 실패를 막는 것이 목적이다. 사용자가 3:1 시안을 고른 뒤 refine이
    1:1로 떨어지면 미리보기와 전혀 다른 포스터가 나오는데 에러도 경고도 없다.

    Returns:
        (ratio, warnings)

    Raises:
        LayoutRejection: 미지원 비율, 추론 실패, 요청값과 추론값 불일치.
    """
    inferred = infer_aspect_ratio(image_size) if image_size else None
    supported = sorted(config.ASPECT_RATIOS)

    if requested is None:
        if image_size is None:
            return config.DEFAULT_ASPECT_RATIO, []
        if inferred is None:
            W, H = _as_wh(image_size)
            raise LayoutRejection(
                "aspect_ratio_unsupported",
                f"이미지 비율을 지원 목록에서 찾지 못했습니다 ({W}x{H}). "
                f"aspect_ratio를 직접 지정해주세요.",
                image_size=[W, H], supported=supported)
        return inferred, []

    req = str(requested).strip()
    if req not in config.ASPECT_RATIOS:
        raise LayoutRejection(
            "aspect_ratio_unsupported",
            f"지원하지 않는 비율입니다: {requested!r}",
            requested=req, supported=supported)

    if image_size is None:
        return req, []
    if inferred is None:
        W, H = _as_wh(image_size)
        # 추론이 안 되면 명시값을 쓰되, 조용히 넘어가지 않고 알린다.
        return req, [f"draft 비율({W}x{H})을 판정하지 못해 요청값 {req}를 사용했습니다."]
    if inferred != req:
        W, H = _as_wh(image_size)
        raise LayoutRejection(
            "aspect_ratio_mismatch",
            f"요청한 비율({req})과 draft 이미지의 비율({inferred})이 다릅니다.",
            requested=req, inferred_from_draft=inferred, draft_size=[W, H])
    return req, []


def resolve_placement(masks, canvas_wh, ratio: str = None, override: dict = None):
    """배치 계산 + 안전성 검증을 한 번에. api.py가 쓸 단일 진입점.

    거부될 때는 서버 기본 배치를 suggested로 함께 담아, 클라이언트가 한 번의
    왕복으로 복구할 수 있게 한다.

    Returns:
        (Placement, public_dict)
    """
    auto = compute_placement(masks, canvas_wh, ratio, None)
    place = compute_placement(masks, canvas_wh, ratio, override)
    try:
        v = validate_placement(masks, canvas_wh, place, strict=True)
    except LayoutRejection as e:
        e.payload.setdefault("suggested", auto.as_public(canvas_wh))
        raise
    return place, place.as_public(canvas_wh, v["region_overflow"])
