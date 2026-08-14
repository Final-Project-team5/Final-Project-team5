"""Product Layout v2 — rotation_deg 기하·계약 검증 (rembg·GPU 불필요).

실제 제품 사진 대신 **합성 마스크**를 쓴다. 이 스위트의 목적은 화질이 아니라
계약이다 — 부호 규약, 중심 유지, bbox 재측정, 0° 회귀, 거부 조건, 그리고
layout/shadow가 회전된 마스크를 그대로 재사용하는지.

화질(aliasing, 디테일 손실)은 실제 사진이 필요하므로
tools/verification/rotation/probe_rotation.py 에서 따로 본다.

핵심 원칙 확인:
    회전된 마스크를 기존 layout 함수에 넣으면
    _component_stats / _footprint_extent / _solve_scale / validate_placement /
    add_ground_shadow 가 수정 없이 회전을 반영한다.

실행 (프로젝트 루트에서):
    PYTHONPATH="$PWD" python tests/test_rotation.py
"""
import contextlib
import inspect
import io
import math
import sys
import types
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

sys.modules.setdefault("torch", types.ModuleType("torch"))
sys.modules.setdefault("diffusers", types.ModuleType("diffusers"))

from pipeline import config, layout, masking                    # noqa: E402
from pipeline.masking import MaskResult, RotationRejection      # noqa: E402

PASS = FAIL = 0
ANGLES = [-15, -8, 0, 8, 15]


@contextlib.contextmanager
def quiet():
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        yield


def check(name, ok, detail=""):
    global PASS, FAIL
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  {detail}" if detail else ""))
    if ok:
        PASS += 1
    else:
        FAIL += 1
    return ok


# --------------------------------------------------------------- 합성 소재
def make_case(kind, size=1024):
    """제품 형태별 합성 (base RGB, MaskResult).

    RGB에는 격자 무늬를 넣는다. 단색이면 회전이 실제로 일어났는지,
    RGB와 마스크가 같이 돌았는지 픽셀로 확인할 수 없다.
    """
    W = H = size
    m = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(m)
    cx, cy = W // 2, H // 2
    if kind == "wide":          # 과자봉지: 가로로 넓음
        w, h = int(W * 0.42), int(H * 0.26)
        d.rounded_rectangle([cx - w, cy - h, cx + w, cy + h], radius=40, fill=255)
    elif kind == "tall":        # 화장품: 세로로 김 (폭 증가율 최불리)
        w, h = int(W * 0.11), int(H * 0.30)
        d.rounded_rectangle([cx - w, cy - h, cx + w, cy + h], radius=24, fill=255)
        d.rectangle([cx - w // 3, cy - h - int(H * 0.05), cx + w // 3, cy - h], fill=255)
    elif kind == "thin":        # 유리잔 손잡이: 얇은 구조
        w, h = int(W * 0.13), int(H * 0.20)
        d.ellipse([cx - w, cy - h, cx + w, cy + h], fill=255)
        d.arc([cx + w - 10, cy - h // 2, cx + w + 70, cy + h // 2], -90, 90,
              fill=255, width=9)          # 9px 얇은 손잡이
    elif kind == "two":         # 연결요소 2개 (그림자 분리 확인용)
        w, h = int(W * 0.09), int(H * 0.16)
        for off in (-int(W * 0.16), int(W * 0.16)):
            d.rounded_rectangle([cx + off - w, cy - h, cx + off + w, cy + h],
                                radius=18, fill=255)
    elif kind == "huge":        # 프레임을 거의 채움 (거부 조건 확인용)
        w, h = int(W * 0.47), int(H * 0.47)
        d.rectangle([cx - w, cy - h, cx + w, cy + h], fill=255)
    else:
        raise ValueError(kind)

    arr = np.array(m)
    base = np.zeros((H, W, 3), np.uint8)
    yy, xx = np.mgrid[0:H, 0:W]
    base[..., 0] = ((xx // 16 + yy // 16) % 2) * 120 + 60      # 체크 무늬
    base[..., 1] = (xx % 64) * 3
    base[..., 2] = (yy % 64) * 3
    base = Image.fromarray(base)

    tight = Image.fromarray((arr > 128).astype(np.uint8) * 255)
    import cv2
    k = np.ones((config.DILATE, config.DILATE), np.uint8)
    dil = cv2.dilate(np.array(tight), k, iterations=1) if config.DILATE > 0 else np.array(tight)
    from PIL import ImageFilter
    inp = Image.fromarray(255 - dil).filter(ImageFilter.GaussianBlur(config.MASK_BLUR))
    return base, MaskResult(tight, inp, float((arr > 128).mean()))


def bbox_of(mask):
    a = (np.array(mask.convert("L")) > 128)
    ys, xs = np.where(a)
    return int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())


def center_of(mask):
    x0, y0, x1, y1 = bbox_of(mask)
    return (x0 + x1) / 2, (y0 + y1) / 2


def area_of(mask):
    return int((np.array(mask.convert("L")) > 128).sum())


# =============================================================== [1] 부호 규약
print("\n[1] 부호 규약 — 양수 = 시계 방향")

base, masks = make_case("tall")
# 상단에 표식을 하나 더 붙여 방향을 판별한다(마스크 자체는 좌우 대칭이라 부족).
mk = masks.product.copy()
d = ImageDraw.Draw(mk)
d.rectangle([512 - 8, 200, 512 + 8, 240], fill=255)   # 위쪽 중앙 돌기
marked = MaskResult(mk, masks.inpaint, masks.area_ratio)

cx0, cy0 = center_of(marked.product)
with quiet():
    rot_cw, _ = masking.rotate_product(base, marked, 15)
    rot_ccw, _ = masking.rotate_product(base, marked, -15)


def topmost_x(mask):
    a = (np.array(mask.convert("L")) > 128)
    ys, xs = np.where(a)
    top = ys.min()
    return xs[ys <= top + 2].mean()


_, mcw = masking.rotate_product(base, marked, 15)
_, mccw = masking.rotate_product(base, marked, -15)
x_cw, x_ccw, x0_ = topmost_x(mcw.product), topmost_x(mccw.product), topmost_x(marked.product)
check("양수(+15°)는 상단 돌기를 오른쪽으로 → 시계 방향",
      x_cw > x0_ + 5, f"{x0_:.0f} → {x_cw:.0f}")
check("음수(-15°)는 상단 돌기를 왼쪽으로 → 반시계 방향",
      x_ccw < x0_ - 5, f"{x0_:.0f} → {x_ccw:.0f}")
check("+15°와 -15°는 서로 다른 결과",
      not np.array_equal(np.array(mcw.product), np.array(mccw.product)))
src = (ROOT / "pipeline" / "masking.py").read_text(encoding="utf-8")
check("부호 변환이 한 곳에서만 일어남 (pil_deg = -d)",
      src.count("pil_deg = -d") == 1 and src.count("pil_deg") == 3,
      f"pil_deg {src.count('pil_deg')}회")
check("docstring에 부호 규약 명시", "양수 = 시계 방향" in src)


# =============================================================== [2] 0° 회귀
print("\n[2] rotation_deg = 0 회귀")

for kind in ("wide", "tall", "thin", "two"):
    b, m = make_case(kind)
    rb, rm = masking.rotate_product(b, m, 0)
    same = (np.array_equal(np.array(b), np.array(rb))
            and np.array_equal(np.array(m.product), np.array(rm.product))
            and np.array_equal(np.array(m.inpaint), np.array(rm.inpaint)))
    check(f"{kind}: base·product·inpaint 픽셀 동일", same)
    check(f"{kind}: area_ratio 동일", m.area_ratio == rm.area_ratio)
    check(f"{kind}: 반환 객체는 별개 (mutation 격리)",
          rb is not b and rm.product is not m.product)

# 0.0 / 0 / None / -0.0 모두 bypass
b, m = make_case("wide")
for v in (0, 0.0, -0.0, None):
    rb, _ = masking.rotate_product(b, m, v)
    check(f"deg={v!r} 도 bypass", np.array_equal(np.array(b), np.array(rb)))

# 파이프라인 끝단까지 동일한가 (배치 + 그림자 + 합성)
def flat_pipeline(b, m, canvas, ratio):
    place, _pub = layout.resolve_placement(m, canvas, ratio, None)
    bc, mc = masking.place_product_on_canvas(b, m, canvas, **place.as_kwargs())
    bg = masking.render_flat_background(canvas, ["#F0EAE2"])
    sh = masking.add_ground_shadow(bg, mc.product)
    return masking.composite_product(bc, sh, mc.product), place, mc


for ratio, canvas in [("1:1", (1024, 1024)), ("3:1", (3072, 1024)), ("3:4", (1024, 1368))]:
    b, m = make_case("wide")
    with quiet():
        out_a, pa, _ = flat_pipeline(b, m, canvas, ratio)
        rb, rm = masking.rotate_product(b, m, 0)
        out_b, pb, _ = flat_pipeline(rb, rm, canvas, ratio)
    check(f"{ratio}: 최종 합성 픽셀 diff = 0",
          np.array_equal(np.array(out_a), np.array(out_b)),
          f"max {np.abs(np.array(out_a, int) - np.array(out_b, int)).max()}")
    check(f"{ratio}: placement 동일",
          (pa.scale, pa.x_px, pa.y_px) == (pb.scale, pb.x_px, pb.y_px))


# =============================================================== [3] 회전 기하
print("\n[3] 회전 기하 — 중심 유지 · bbox 재측정")

for kind in ("wide", "tall", "thin"):
    b, m = make_case(kind)
    x0, y0, x1, y1 = bbox_of(m.product)
    bw, bh = x1 - x0, y1 - y0
    c0 = center_of(m.product)
    for deg in ANGLES:
        if deg == 0:
            continue
        try:
            with quiet():
                rb, rm = masking.rotate_product(b, m, deg)
        except RotationRejection as e:
            check(f"{kind} {deg:+d}° 회전", False, e.payload["error"])
            continue
        c1 = center_of(rm.product)
        err = math.hypot(c1[0] - c0[0], c1[1] - c0[1])
        check(f"{kind} {deg:+3d}° 중심 유지 (≤1px)", err <= 1.0, f"{err:.2f}px")

        # 이론값 bw·cos+bh·sin 은 **bbox를 통째로 돌린 상한**이다. 실루엣이
        # 채워진 사각형이 아니면(둥근 모서리·타원·손잡이) 항상 그보다 작다.
        # 따라서 등식이 아니라 "상한 이하 + 원본보다는 큼"으로 검사한다.
        r = math.radians(abs(deg))
        exp_w = bw * math.cos(r) + bh * math.sin(r)
        exp_h = bw * math.sin(r) + bh * math.cos(r)
        rx0, ry0, rx1, ry1 = bbox_of(rm.product)
        gw, gh = rx1 - rx0, ry1 - ry0
        check(f"{kind} {deg:+3d}° bbox ≤ 이론 상한",
              gw <= exp_w + 2 and gh <= exp_h + 2,
              f"실측 {gw}x{gh} / 상한 {exp_w:.0f}x{exp_h:.0f}")
        # 축별로는 줄어들 수 있다. 얇은 손잡이처럼 극점이 대각으로 놓인 실루엣은
        # 회전하면서 한 축이 오히려 짧아진다(실측: thin -15°에서 높이 408→401).
        # 그래서 축별 증가가 아니라 **bbox 면적이 무너지지 않는지**만 본다.
        check(f"{kind} {deg:+3d}° bbox 면적 유지",
              gw * gh >= bw * bh * 0.9, f"{bw*bh} → {gw*gh}")

    # 대칭성: +θ와 -θ의 bbox 크기는 같아야 한다
    with quiet():
        _, mp = masking.rotate_product(b, m, 8)
        _, mn = masking.rotate_product(b, m, -8)
    bp, bn = bbox_of(mp.product), bbox_of(mn.product)
    check(f"{kind}: +8°/-8° bbox 크기 대칭 (±2px)",
          abs((bp[2] - bp[0]) - (bn[2] - bn[0])) <= 2
          and abs((bp[3] - bp[1]) - (bn[3] - bn[1])) <= 2,
          f"{bp[2]-bp[0]}x{bp[3]-bp[1]} vs {bn[2]-bn[0]}x{bn[3]-bn[1]}")


# =============================================================== [4] RGB·마스크 일치
print("\n[4] RGB와 마스크가 동일 변환")

b, m = make_case("wide")
with quiet():
    rb, rm = masking.rotate_product(b, m, 15)
arr_rgb = np.array(rb)
arr_msk = (np.array(rm.product) > 128)
inside = arr_rgb[arr_msk]
check("마스크 영역에 미채움(검정) 픽셀 없음",
      (inside.sum(axis=1) > 0).all(),
      f"검정 {int((inside.sum(axis=1) == 0).sum())}px")

# bleed가 회전된 마스크 바깥까지 덮는지 (테두리 어두워짐 방지)
import cv2 as _cv2
band = _cv2.dilate(arr_msk.astype(np.uint8), np.ones((3, 3), np.uint8), iterations=3)
ring = (band > 0) & (~arr_msk)
check("회전된 마스크 바깥 3px도 채워져 있음",
      (arr_rgb[ring].sum(axis=1) > 0).mean() > 0.99,
      f"{(arr_rgb[ring].sum(axis=1) > 0).mean():.4f}")

# 무늬가 실제로 회전했는지 (RGB가 그대로면 마스크만 돈 것)
check("RGB가 실제로 회전됨", not np.array_equal(np.array(b), arr_rgb))


# =============================================================== [5] 거부 조건
print("\n[5] 거부 — 조용히 자르지 않음")

b, m = make_case("huge")
try:
    with quiet():
        masking.rotate_product(b, m, 15)
    check("프레임 초과 → 거부", False, "예외 없음")
except RotationRejection as e:
    check("프레임 초과 → rotation_clipped",
          e.payload["error"] == "rotation_clipped", e.payload["error"])
    check("  거부 payload에 회전 후 크기 포함", "bbox_after_size" in e.payload)
    check("  거부 payload에 목표 위치 포함", "target_topleft" in e.payload)
    check("  거부 payload에 bbox_before 포함", "bbox_before" in e.payload)

b, m = make_case("wide")
for bad in (25, -25, 90):
    try:
        with quiet():
            masking.rotate_product(b, m, bad)
        check(f"{bad}° → 거부", False, "예외 없음")
    except RotationRejection as e:
        check(f"{bad}° → rotation_out_of_range",
              e.payload["error"] == "rotation_out_of_range", e.payload["error"])
for ok_deg in (20, -20):
    try:
        with quiet():
            masking.rotate_product(b, m, ok_deg)
        check(f"{ok_deg}° (경계값) 허용", True)
    except RotationRejection as e:
        check(f"{ok_deg}° (경계값) 허용", False, e.payload["error"])

check("허용 상한이 config에 있음", config.ROTATION_MAX_ABS_DEG == 20.0)
empty = MaskResult(Image.new("L", (1024, 1024), 0), Image.new("L", (1024, 1024), 255), 0.0)
try:
    masking.rotate_product(b, empty, 8)
    check("빈 마스크 → 거부", False, "예외 없음")
except RotationRejection as e:
    check("빈 마스크 → rotation_empty_mask", e.payload["error"] == "rotation_empty_mask")


# =============================================================== [6] layout 재사용
print("\n[6] 회전된 마스크를 기존 layout이 그대로 처리")

layout_src = (ROOT / "pipeline" / "layout.py").read_text(encoding="utf-8")
check("layout.py에 rotation 관련 코드 없음 (수정 안 함)",
      "rotation" not in layout_src.lower())

for ratio, canvas in [("3:1", (3072, 1024)), ("3:4", (1024, 1368))]:
    b, m = make_case("tall")
    with quiet():
        p0 = layout.compute_placement(m, canvas, ratio, None)
        _, m15 = masking.rotate_product(b, m, 15)
        p15 = layout.compute_placement(m15, canvas, ratio, None)
    check(f"{ratio}: 회전 시 auto_scale 감소",
          p15.scale < p0.scale, f"{p0.scale:.4f} → {p15.scale:.4f}")
    with quiet():
        v = layout.validate_placement(m15, canvas, p15, strict=False)
    check(f"{ratio}: 회전 배치가 canvas 안에 들어감", v["ok"], str(v["reasons"]))
    check(f"{ratio}: footprint가 제품 bbox보다 큼(그림자 포함)",
          v["footprint"][3] > v["product_box"][3])

# 1:1은 자동 축소가 없다 — 결정 1(A안)대로 거부되는지
b, m = make_case("huge")
try:
    with quiet():
        masking.rotate_product(b, m, 8)
    check("1:1 큰 제품: 자동 축소 없이 거부", False, "통과해버림")
except RotationRejection as e:
    check("1:1 큰 제품: 자동 축소 없이 거부",
          e.payload["error"] == "rotation_clipped")


# =============================================================== [7] 그림자
print("\n[7] 회전된 마스크 기준 그림자 재생성")

b, m = make_case("tall")
canvas = (3072, 1024)
with quiet():
    _, m15 = masking.rotate_product(b, m, 15)
    p = layout.compute_placement(m15, canvas, "3:1", None)
    _bc, mc = masking.place_product_on_canvas(b, m15, canvas, **p.as_kwargs())
    bg = masking.render_flat_background(canvas, ["#FFFFFF"])
    sh = masking.add_ground_shadow(bg, mc.product)
diff = np.abs(np.array(sh, int) - np.array(bg, int)).sum(axis=2) > 8
ys, xs = np.where(diff)
check("그림자가 실제로 생성됨", len(xs) > 0, f"{len(xs)}px")
if len(xs):
    sb = (xs.min(), ys.min(), xs.max(), ys.max())
    pb = bbox_of(mc.product)
    check("그림자가 제품 하단 근처", sb[3] >= pb[3] - 5, f"shadow y1={sb[3]} product y1={pb[3]}")
    with quiet():
        v = layout.validate_placement(m15, canvas, p, strict=False)
    fp = v["footprint"]
    check("footprint 추정이 실측 그림자를 감쌈",
          fp[0] <= sb[0] + 1 and fp[1] <= sb[1] + 1
          and fp[2] >= sb[2] - 1 and fp[3] >= sb[3] - 1,
          f"추정 {[round(x) for x in fp]} / 실측 {list(sb)}")

# 연결요소 2개 — 회전 후에도 그림자가 2개로 분리되는지
b, m = make_case("two")
with quiet():
    _, m8 = masking.rotate_product(b, m, 8)
    bg = masking.render_flat_background((1024, 1024), ["#FFFFFF"])
    sh = masking.add_ground_shadow(bg, m8.product)
d2 = (np.abs(np.array(sh, int) - np.array(bg, int)).sum(axis=2) > 8).astype(np.uint8)
n, _l, _st, _c = _cv2.connectedComponentsWithStats(d2, connectivity=8)
check("연결요소 2개 → 그림자도 분리 유지", n - 1 >= 2, f"{n-1}개")


# =============================================================== [8] 보간 A/B
print("\n[8] BICUBIC vs NEAREST 수치 회귀 (production 기본: BICUBIC)")

for kind in ("wide", "tall", "thin"):
    b, m = make_case(kind)
    a0 = area_of(m.product)
    row = []
    for mode in ("bicubic", "nearest"):
        with quiet():
            _, rm = masking.rotate_product(b, m, 15, mask_resample=mode)
        a1 = area_of(rm.product)
        cnt, _h = _cv2.findContours((np.array(rm.product) > 128).astype(np.uint8),
                                    _cv2.RETR_EXTERNAL, _cv2.CHAIN_APPROX_NONE)
        per = sum(_cv2.arcLength(c, True) for c in cnt)
        row.append((mode, (a1 - a0) / a0, per))
    print(f"     {kind:5s}  " + "  ".join(
        f"{mo}: 면적 {dr*100:+.2f}%  둘레 {pe:.0f}" for mo, dr, pe in row))
    check(f"{kind}: 두 모드 모두 면적 변화 5% 이내",
          all(abs(dr) < 0.05 for _mo, dr, _pe in row))
    check(f"{kind}: 두 모드 결과가 실제로 다름",
          abs(row[0][2] - row[1][2]) > 1e-6)
check("기본값은 bicubic",
      'mask_resample: str = "bicubic"' in src)
try:
    masking.rotate_product(*make_case("wide"), 8, mask_resample="lanczos")
    check("알 수 없는 보간 모드 → 거부", False, "예외 없음")
except ValueError:
    check("알 수 없는 보간 모드 → 거부", True)


# =============================================================== [8-1] fit=expand
print("\n[8-1] fit='expand' — 소스 프레임 여백 의존 제거")

b, m = make_case("huge")            # 프레임을 거의 채워 source에서는 거부되는 케이스
try:
    with quiet():
        masking.rotate_product(b, m, 15, fit="source")
    check("huge: fit=source는 여전히 거부", False, "통과해버림")
except RotationRejection as e:
    check("huge: fit=source는 여전히 거부", e.payload["error"] == "rotation_clipped")

with quiet():
    rb, rm = masking.rotate_product(b, m, 15, fit="expand")
check("huge: fit=expand는 거부하지 않음", True)
check("  프레임이 실제로 넓어짐", rb.size[0] > 1024 and rb.size[1] > 1024, str(rb.size))
check("  base와 mask 크기 일치", rb.size == rm.product.size == rm.inpaint.size)
check("  넓힌 프레임이 대칭", (rb.size[0] - 1024) % 2 == 0 and (rb.size[1] - 1024) % 2 == 0,
      str(rb.size))
rx0, ry0, rx1, ry1 = bbox_of(rm.product)
check("  회전 제품이 프레임 경계에 닿지 않음",
      rx0 > 0 and ry0 > 0 and rx1 < rb.size[0] - 1 and ry1 < rb.size[1] - 1,
      f"bbox {rx0},{ry0}~{rx1},{ry1} / 프레임 {rb.size}")
check("  마스크 면적 손실 없음 (잘려나간 픽셀 없음)",
      abs(area_of(rm.product) - area_of(m.product)) / area_of(m.product) < 0.01,
      f"{area_of(m.product)} → {area_of(rm.product)}")

# 여유가 충분하면 expand여도 프레임이 그대로여야 한다(불필요한 확장 금지)
b2, m2 = make_case("tall")
with quiet():
    rb2, _ = masking.rotate_product(b2, m2, 15, fit="expand")
check("여유가 있으면 확장하지 않음", rb2.size == b2.size, str(rb2.size))

# 0°는 fit과 무관하게 bypass
for f_ in ("source", "expand"):
    rb3, rm3 = masking.rotate_product(b2, m2, 0, fit=f_)
    check(f"fit={f_} 0° bypass 픽셀 동일",
          np.array_equal(np.array(b2), np.array(rb3))
          and np.array_equal(np.array(m2.product), np.array(rm3.product)))

try:
    masking.rotate_product(b2, m2, 8, fit="bogus")
    check("알 수 없는 fit → 거부", False, "예외 없음")
except ValueError:
    check("알 수 없는 fit → 거부", True)

# 넓힌 프레임에서도 layout이 그대로 동작하는가
with quiet():
    rb4, rm4 = masking.rotate_product(b, m, 15, fit="expand")
    p4 = layout.compute_placement(rm4, (3072, 1024), "3:1", None)
    v4 = layout.validate_placement(rm4, (3072, 1024), p4, strict=False)
check("expand 결과로 3:1 배치 성립", v4["ok"], str(v4["reasons"]))


# =============================================================== [9] 회귀 가드
print("\n[9] 0° legacy shadow baseline 준비")

import ast

def defs(path):
    tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    out = {}
    src_t = Path(path).read_text(encoding="utf-8")
    for n in tree.body:
        if isinstance(n, (ast.FunctionDef, ast.ClassDef)):
            out[n.name] = ast.get_source_segment(src_t, n)
    return out

before = defs(ROOT / "tests" / "_baseline" / "masking_before_rotation.py")

check(
    "legacy add_ground_shadow baseline 존재",
    "add_ground_shadow" in before,
)

# ------------------------------------------------------------------ [10]
print("\n[10] A2 production 배선 — 0°는 기존과 픽셀 동일")

import cv2                                                     # noqa: E402
from PIL import ImageFilter                                    # noqa: E402

# A2 이전 add_ground_shadow를 baseline 소스에서 그대로 실행해 비교한다.
_ns = {"config": config, "np": np, "cv2": cv2, "Image": Image,
       "ImageDraw": ImageDraw, "ImageFilter": ImageFilter}
exec(before["add_ground_shadow"], _ns)
legacy_shadow = _ns["add_ground_shadow"]


def _bg(W=512, H=512):
    img = Image.new("RGB", (W, H), (235, 230, 222))
    d = ImageDraw.Draw(img)
    for i in range(0, W, 37):          # 평평하지 않은 배경 (블렌딩 차이를 드러냄)
        d.line([(i, 0), (i, H)], fill=(210, 205, 198), width=3)
    return img


def _pixdiff(a, b):
    x = np.array(a.convert("RGB"), np.int16)
    y = np.array(b.convert("RGB"), np.int16)
    return int((np.abs(x - y).sum(2) > 0).sum())


shadow_cases = [(k, make_case(k, 512)[1].product)
                for k in ("tall", "two", "wide", "thin")]
for label, mk in shadow_cases:
    img = _bg()
    old = legacy_shadow(img, mk)
    new0 = masking.add_ground_shadow(img, mk)                    # 기본값 0.0
    new_kw = masking.add_ground_shadow(img, mk, rotation_deg=0.0)
    check(f"{label}: rotation_deg 기본값에서 legacy와 픽셀 동일",
          _pixdiff(old, new0) == 0, f"diff {_pixdiff(old, new0)}px")
    check(f"{label}: rotation_deg=0.0 명시에서도 픽셀 동일",
          _pixdiff(old, new_kw) == 0, f"diff {_pixdiff(old, new_kw)}px")

# 회전 시에만 contact 경로가 켜진다
_rb_in, _rm_in = make_case("tall", 512)
rb, rm = masking.rotate_product(_rb_in, _rm_in, 12.0, fit="expand")
img_r = _bg(*rb.size)
s_legacy = masking.add_ground_shadow(img_r, rm.product)
s_contact = masking.add_ground_shadow(img_r, rm.product, rotation_deg=12.0)
check("회전 마스크에서 contact 경로가 legacy와 다른 결과를 낸다",
      _pixdiff(s_legacy, s_contact) > 0,
      f"diff {_pixdiff(s_legacy, s_contact)}px")

# _contact_center_width 자체 계약
m = np.array(make_case("tall", 512)[1].product.convert("L")) > 128
ys, xs = np.where(m)
cx, w = masking._contact_center_width(m.astype(np.uint8), int(ys.min()),
                                      int(ys.max()), int(xs.min()), int(xs.max()))
bbox_w = int(xs.max()) - int(xs.min())
bbox_cx = (int(xs.min()) + int(xs.max())) / 2
check("접지 폭 하한이 지켜진다",
      w >= bbox_w * config.SHADOW_CONTACT_MIN_WIDTH_RATIO - 1e-6,
      f"w={w:.1f} >= {bbox_w * config.SHADOW_CONTACT_MIN_WIDTH_RATIO:.1f}")
check("중심 이동 상한이 지켜진다",
      abs(cx - bbox_cx) <= bbox_w * config.SHADOW_CONTACT_MAX_SHIFT_RATIO + 1e-6,
      f"shift={abs(cx - bbox_cx):.1f}")

# generate._prepare 배선 — rembg 없이 stub으로 확인
print("\n[11] generate._prepare 배선 (rembg 없이 stub)")
from pipeline import generate                                   # noqa: E402

_stub_base, _stub_masks = make_case("tall", 256)
_orig_prepare_image = generate.prepare_image
_orig_rotate = generate.rotate_product
_calls = []
generate.prepare_image = lambda src, size, apply_blur_margin=True: (
    _stub_base, _stub_masks, "stub")
generate.rotate_product = lambda b, m, d, **kw: (
    _calls.append({"deg": d, **kw}) or (b, m))
try:
    b0, m0, _ = generate._prepare("x", 256, rotation_deg=0.0)
    check("rotation_deg=0 이면 rotate_product를 호출하지 않는다", not _calls)
    check("rotation_deg=0 이면 prepare_image 결과 객체 그대로",
          b0 is _stub_base and m0 is _stub_masks)
    generate._prepare("x", 256, rotation_deg=7.5)
    check("rotation_deg != 0 이면 rotate_product 호출", len(_calls) == 1)
    check("호출부가 fit='expand'를 명시한다",
          _calls and _calls[0].get("fit") == "expand", str(_calls[:1]))
    check("각도가 그대로 전달된다", _calls and _calls[0]["deg"] == 7.5)
finally:
    generate.prepare_image = _orig_prepare_image
    generate.rotate_product = _orig_rotate

check("rotate_product 기본 fit은 여전히 source (전역 기본값 불변)",
      inspect.signature(masking.rotate_product)
      .parameters["fit"].default == "source")


# ------------------------------------------------------------------ [12]
print("\n[12] 1:1 회전 — expand 후에도 중심 유지 · 캔버스 크기 유지")
print("     (1:1 AI 경로는 뒤에 placement가 없어 _prepare가 직접 되돌린다)")

SIZE = 512
for kind in ("wide", "tall"):
    for deg in (+15, -15):
        b0, m0 = make_case(kind, SIZE)
        cx_n, cy_n = generate._bbox_center_norm(m0.product, b0.size)

        rb, rm = masking.rotate_product(b0, m0, deg, fit="expand")
        grew = rb.size != (SIZE, SIZE)
        pb, pm = generate._place_rotated(rb, rm, (SIZE, SIZE), cx_n, cy_n)

        # 1) 최종 캔버스 크기 유지
        check(f"{kind} {deg:+d}°: 출력 크기 {SIZE}x{SIZE} 유지",
              pb.size == (SIZE, SIZE) and pm.product.size == (SIZE, SIZE),
              f"expand 후 {rb.size} → {pb.size}")

        # 2) 목표 중심 오차 <= 1px
        gx, gy = generate._bbox_center_norm(pm.product, pm.product.size)
        ex, ey = abs(gx - cx_n) * SIZE, abs(gy - cy_n) * SIZE
        check(f"{kind} {deg:+d}°: 중심 오차 ≤ 1px",
              ex <= 1.0 and ey <= 1.0, f"dx={ex:.2f}px dy={ey:.2f}px")

        # 3) 제품 bbox가 캔버스 안
        x0, y0, x1, y1 = bbox_of(pm.product)
        check(f"{kind} {deg:+d}°: 제품 bbox가 캔버스 안",
              x0 >= 0 and y0 >= 0 and x1 <= SIZE - 1 and y1 <= SIZE - 1,
              f"bbox=({x0},{y0},{x1},{y1})")

        # 4) 실제로 회전이 일어났다
        check(f"{kind} {deg:+d}°: 회전 결과가 원본과 다르다",
              not np.array_equal(np.array(m0.product), np.array(pm.product)),
              f"expand로 프레임이 커졌는가: {grew}")

# --- 프레임이 실제로 커지는 케이스 (expand가 필요한 상황) -----------------
# 위 wide/tall은 여백이 있어 expand가 프레임을 안 키운다. 축소 경로를 실제로
# 태우려면 제품이 프레임을 거의 채운 상태여야 한다.
print("\n     프레임이 커지는 케이스 — 축소 경로 검증")
for deg in (+15, -15):
    b0, m0 = make_case("huge", SIZE)
    cx_n, cy_n = generate._bbox_center_norm(m0.product, b0.size)

    # fit="source"였다면 거부됐을 상황인지 먼저 확인한다
    rejected = False
    try:
        masking.rotate_product(b0, m0, deg, fit="source")
    except RotationRejection as e:
        rejected = e.payload["error"] == "rotation_clipped"
    check(f"huge {deg:+d}°: fit='source'였다면 거부됨 (expand가 필요한 상황)",
          rejected)

    rb, rm = masking.rotate_product(b0, m0, deg, fit="expand")
    check(f"huge {deg:+d}°: expand가 프레임을 실제로 키웠다",
          rb.size != (SIZE, SIZE), f"{(SIZE, SIZE)} → {rb.size}")

    pb, pm = generate._place_rotated(rb, rm, (SIZE, SIZE), cx_n, cy_n)
    check(f"huge {deg:+d}°: 출력 크기 {SIZE}x{SIZE}로 복원",
          pb.size == (SIZE, SIZE) and pm.product.size == (SIZE, SIZE),
          f"{rb.size} → {pb.size}")
    gx, gy = generate._bbox_center_norm(pm.product, pm.product.size)
    ex, ey = abs(gx - cx_n) * SIZE, abs(gy - cy_n) * SIZE
    check(f"huge {deg:+d}°: 중심 오차 ≤ 1px",
          ex <= 1.0 and ey <= 1.0, f"dx={ex:.2f}px dy={ey:.2f}px")
    x0, y0, x1, y1 = bbox_of(pm.product)
    check(f"huge {deg:+d}°: 제품 bbox가 캔버스 안",
          x0 >= 0 and y0 >= 0 and x1 <= SIZE - 1 and y1 <= SIZE - 1,
          f"bbox=({x0},{y0},{x1},{y1})")
    # 캔버스에 넣으려면 축소가 일어나야 한다
    a0 = area_of(m0.product)
    a1 = area_of(pm.product)
    check(f"huge {deg:+d}°: 캔버스에 맞추려 축소됨", a1 < a0,
          f"면적 {a0} → {a1} ({a1 / a0:.2f}배)")


# 회전 없이 같은 경로를 태우면 안 된다 — 0°는 _place_rotated를 거치지 않는다
_calls2 = []
_o_pi, _o_rot, _o_place = (generate.prepare_image, generate.rotate_product,
                           generate._place_rotated)
_sb, _sm = make_case("wide", SIZE)
generate.prepare_image = lambda src, size, apply_blur_margin=True: (_sb, _sm, "stub")
generate._place_rotated = lambda *a, **k: _calls2.append(1) or (_sb, _sm)
try:
    generate._prepare("x", SIZE, rotation_deg=0.0, fit_canvas=(SIZE, SIZE))
    check("0°는 fit_canvas를 줘도 _place_rotated를 거치지 않는다", not _calls2)
    generate._prepare("x", SIZE, rotation_deg=10.0, fit_canvas=(SIZE, SIZE))
    check("회전 시에만 _place_rotated를 탄다", len(_calls2) == 1)
    _calls2.clear()
    generate._prepare("x", SIZE, rotation_deg=10.0)      # fit_canvas 미지정
    check("fit_canvas 미지정이면 되돌리지 않는다 (3:1/3:4·flat 경로)",
          not _calls2)
finally:
    (generate.prepare_image, generate.rotate_product,
     generate._place_rotated) = _o_pi, _o_rot, _o_place

# 1:1 AI 경로가 fit_canvas를 실제로 넘기는가 (소스 확인)
gsrc = (ROOT / "pipeline" / "generate.py").read_text(encoding="utf-8")
check("1:1 AI 경로 2곳이 fit_canvas=(size, size)를 넘긴다",
      gsrc.count("fit_canvas=(size, size)") == 2,
      f"{gsrc.count('fit_canvas=(size, size)')}곳")
for fn in ("generate_drafts", "refine"):
    check(f"{fn}의 rotation_deg 기본값 0.0",
          inspect.signature(getattr(generate, fn))
          .parameters["rotation_deg"].default == 0.0)

print("\n" + "=" * 62)
print(f"통과 {PASS} / 실패 {FAIL}")
sys.exit(1 if FAIL else 0)
