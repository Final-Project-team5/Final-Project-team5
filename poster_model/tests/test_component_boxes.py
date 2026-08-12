"""A1 — 연결요소 bbox 반환 검증 (GPU·rembg 불필요).

`layout._component_stats`가 요소별 `box`를, `validate_placement`가
`component_boxes`를 함께 돌려주는지 확인한다. **기존 키·규약은 불변**이어야 한다.

두 폭 규약을 섞지 않았는지가 핵심이다.
    width = x_max - x_min        그림자 계산용 (기존)
    box   = (x, y, x+w, y+h)     Validator용, right/bottom exclusive (신규)

합성 마스크만 쓰므로 rembg가 필요 없다. 실제 제품 마스크가 필요한 항목
(multi-object)은 두 덩어리 합성 마스크로 같은 구조를 만든다.
"""
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

try:
    import torch  # noqa: F401
except ModuleNotFoundError:
    import types
    sys.modules.setdefault("torch", types.ModuleType("torch"))
    sys.modules.setdefault("diffusers", types.ModuleType("diffusers"))

from pipeline import layout, masking, config          # noqa: E402

PASS = FAIL = 0


def check(label, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {label}  {extra}")
    else:
        FAIL += 1
        print(f"  [FAIL] {label}  {extra}")
    return bool(cond)


def mask_result(img_l):
    a = np.array(img_l)
    return masking.MaskResult(product=img_l, inpaint=img_l,
                              area_ratio=float((a > 128).mean()))


def one_blob(W=512, H=512, box=(120, 140, 340, 420)):
    m = Image.new("L", (W, H), 0)
    ImageDraw.Draw(m).rounded_rectangle(list(box), radius=18, fill=255)
    return m


def two_blobs(W=512, H=512):
    m = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(m)
    d.rounded_rectangle([80, 150, 200, 420], radius=14, fill=255)
    d.rounded_rectangle([300, 130, 430, 420], radius=14, fill=255)
    return m


def with_speck(W=512, H=512):
    """큰 덩어리 + 아주 작은 점. 필터가 걸리지 않는지 본다."""
    m = one_blob(W, H)
    ImageDraw.Draw(m).rectangle([470, 470, 473, 473], fill=255)
    return m


def placement_of(mask, scale=1.0, x_px=None, y_px=None):
    a = np.array(mask.convert("L"))
    ys, xs = np.where(a > 128)
    sbox = (int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max()))
    return layout.Placement(scale=scale, x_px=x_px, y_px=y_px, source="auto",
                            region=None, auto_scale=1.0, source_bbox=sbox)


print("=" * 60)
print("A1 — 연결요소 bbox 반환")
print("=" * 60)

# --------------------------------------------------------------- 기존 규약
print("\n[1] 기존 반환 구조·규약 불변")
m1 = one_blob()
comps, sbox = layout._component_stats(m1)
check("반환은 (comps, bbox) 튜플 그대로", isinstance(comps, list) and len(sbox) == 4)
bx0, by0, bx1, by1 = sbox
check("기존 키 4개 유지",
      all(k in comps[0] for k in ("area", "width", "rel_cx", "rel_y_max")),
      str(sorted(comps[0].keys())))

a = np.array(m1) > 128
ys, xs = np.where(a)
check("bbox는 inclusive 인덱스 그대로",
      (bx0, by0, bx1, by1) == (int(xs.min()), int(ys.min()),
                               int(xs.max()), int(ys.max())))
check("width = x_max - x_min 규약 유지 (+1 아님)",
      comps[0]["width"] == int(xs.max()) - int(xs.min()),
      f"width={comps[0]['width']}")

# --------------------------------------------------------------- 신규 box
print("\n[2] 신규 box 계약")
check("comps 각 항목에 box 키 존재", all("box" in c for c in comps))
b = comps[0]["box"]
check("box는 길이 4 float 튜플",
      len(b) == 4 and all(isinstance(v, float) for v in b), str(b))
check("box는 right/bottom exclusive",
      b[0] == float(xs.min()) and b[1] == float(ys.min())
      and b[2] == float(xs.max()) + 1 and b[3] == float(ys.max()) + 1, str(b))
check("box 폭 = width + 1 (두 규약이 1px 차이로 구분됨)",
      (b[2] - b[0]) == comps[0]["width"] + 1)

print("\n[3] box와 마스크의 관계")
def area(x):
    return max(0.0, x[2] - x[0]) * max(0.0, x[3] - x[1])

for name, mk in (("단일", one_blob()), ("2덩어리", two_blobs()),
                 ("작은점 포함", with_speck())):
    cs, sb = layout._component_stats(mk)
    arr = np.array(mk) > 128
    total_box = sum(area(c["box"]) for c in cs)
    check(f"{name}: sum(box 면적) >= 마스크 픽셀 수",
          total_box >= int(arr.sum()),
          f"box합 {total_box:.0f} >= 픽셀 {int(arr.sum())}")
    ob = (float(sb[0]), float(sb[1]), float(sb[2]) + 1, float(sb[3]) + 1)
    check(f"{name}: 모든 box가 전체 bbox 안",
          all(c["box"][0] >= ob[0] and c["box"][1] >= ob[1]
              and c["box"][2] <= ob[2] and c["box"][3] <= ob[3] for c in cs))
    check(f"{name}: box 합집합의 bbox == 전체 bbox",
          (min(c["box"][0] for c in cs), min(c["box"][1] for c in cs),
           max(c["box"][2] for c in cs), max(c["box"][3] for c in cs)) == ob)

print("\n[4] multi-object / 필터 미적용")
cs2, _ = layout._component_stats(two_blobs())
check("두 덩어리가 각각 요소로 나온다", len(cs2) == 2, f"요소 {len(cs2)}개")
check("두 요소의 box가 겹치지 않는다",
      cs2[0]["box"][2] <= cs2[1]["box"][0]
      or cs2[1]["box"][2] <= cs2[0]["box"][0])

cs3, _ = layout._component_stats(with_speck())
check("아주 작은 요소도 필터 없이 포함된다", len(cs3) == 2, f"요소 {len(cs3)}개")
small = min(cs3, key=lambda c: c["area"])
canvas_area = 512 * 512
check("그 요소는 기존 그림자 필터 기준(0.005)에는 못 미친다",
      small["area"] < canvas_area * config.SHADOW_MIN_AREA_RATIO,
      f"area={small['area']} < {canvas_area * config.SHADOW_MIN_AREA_RATIO:.0f}")

# ------------------------------------------------- validate_placement
print("\n[5] validate_placement.component_boxes")
for name, mk, scale, xy in (("항등", one_blob(), 1.0, (None, None)),
                            ("이동", one_blob(), 1.0, (40, 30)),
                            ("축소+이동", one_blob(), 0.6, (60, 50)),
                            ("2덩어리 축소", two_blobs(), 0.75, (20, 25))):
    pl = placement_of(mk, scale, *xy)
    v = layout.validate_placement(mask_result(mk), (512, 512), pl, strict=False)
    check(f"{name}: 기존 키 6개 유지",
          all(k in v for k in ("ok", "product_box", "footprint",
                               "canvas_clipped", "region_overflow", "reasons")))
    cb = v["component_boxes"]
    cs, _ = layout._component_stats(mk)
    check(f"{name}: component_boxes 개수 == 요소 수", len(cb) == len(cs))
    pb = v["product_box"]
    union = (min(c[0] for c in cb), min(c[1] for c in cb),
             max(c[2] for c in cb), max(c[3] for c in cb))
    check(f"{name}: 합집합 bbox == product_box",
          all(abs(u - p) < 1e-6 for u, p in zip(union, pb)),
          f"union={tuple(round(x,2) for x in union)} pb={tuple(round(x,2) for x in pb)}")
    check(f"{name}: 모든 요소가 product_box 안",
          all(c[0] >= pb[0] - 1e-6 and c[1] >= pb[1] - 1e-6
              and c[2] <= pb[2] + 1e-6 and c[3] <= pb[3] + 1e-6 for c in cb))
    check(f"{name}: footprint가 component_boxes를 감싼다",
          all(c[0] >= v["footprint"][0] - 1e-6
              and c[2] <= v["footprint"][2] + 1e-6 for c in cb))

print("\n[6] 실제 마스크 좌표와의 대조 (배치 변환 후)")
mk = two_blobs()
pl = placement_of(mk, 1.0, None, None)   # 항등 배치 = 소스 좌표 그대로
v = layout.validate_placement(mask_result(mk), (512, 512), pl, strict=False)
arr = np.array(mk) > 128
import cv2                                                  # noqa: E402
n, lab, st, _ = cv2.connectedComponentsWithStats(arr.astype(np.uint8), 8)
truth = sorted([(float(st[i, 0]), float(st[i, 1]),
                 float(st[i, 0] + st[i, 2]), float(st[i, 1] + st[i, 3]))
                for i in range(1, n)])
check("항등 배치에서 component_boxes == 실제 요소 bbox",
      sorted(v["component_boxes"]) == truth,
      f"{sorted(v['component_boxes'])} vs {truth}")

print("\n" + "=" * 60)
print(f"통과 {PASS} / 실패 {FAIL}")
sys.exit(1 if FAIL else 0)
