"""A3-1 — 비율 추론/검증과 placement 외부 좌표 변환 (GPU·rembg 불필요).

A3-1 범위는 api.py 배선 없이 순수 로직만이다. 확인 대상:
    1) 비율 추론이 exact가 아니라 tolerance 기반인지 (3:4가 정확히 0.75가 아님)
    2) 요청값과 추론값의 교차 검증 분기
    3) 외부 x/y가 제품 bbox '중심점' 정규화 좌표이고 배율에 흔들리지 않는지
    4) scale_factor가 CANVAS_MAX_UPSCALE을 넘지 못하는지
    5) 응답 placement가 부분 override에서도 채워진 최종 상태인지

실행 (프로젝트 루트에서):
    PYTHONPATH="$PWD" python tests/test_aspect_contract.py
"""
import sys
import types
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

sys.modules["torch"] = types.ModuleType("torch")
sys.modules["diffusers"] = types.ModuleType("diffusers")

from pipeline import config, layout                              # noqa: E402
from pipeline.masking import MaskResult                          # noqa: E402

PASS, FAIL = 0, 0

def _api_class_block(name):
    """api.py에서 특정 Pydantic 모델 정의 블록만 잘라낸다."""
    src = (ROOT / "api.py").read_text(encoding="utf-8").splitlines()
    i = next(k for k, l in enumerate(src) if l.startswith(f"class {name}("))
    out = [src[i]]
    for l in src[i + 1:]:
        if l.startswith("class ") or l.startswith("def "):
            break
        out.append(l)
    return "\n".join(out)




def check(name, ok, detail=""):
    global PASS, FAIL
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  {detail}" if detail else ""))
    if ok:
        PASS += 1
    else:
        FAIL += 1


def synth(size=1024):
    m = np.zeros((size, size), np.uint8)
    m[300:760, 330:520] = 255
    m[480:740, 560:680] = 255
    return MaskResult(Image.fromarray(m), Image.fromarray(255 - m),
                      float((m > 0).mean()))


def reject(fn, *a, **kw):
    try:
        fn(*a, **kw)
        return None
    except layout.LayoutRejection as e:
        return e.payload


print("\n[1] 비율 추론 — tolerance 기반")
# 실제 파이프라인에서 나오는 크기
for wh, want in (((1024, 1024), "1:1"), ((768, 768), "1:1"),
                 ((3072, 1024), "3:1"), ((2304, 768), "3:1"),
                 ((1024, 1368), "3:4"),      # refine 출력. 0.74854 (정확히 0.75 아님)
                 ((768, 1024), "3:4")):      # draft 출력. 0.75
    got = layout.infer_aspect_ratio(wh)
    check(f"{wh[0]}x{wh[1]} → {want}", got == want, f"got={got} ratio={wh[0]/wh[1]:.5f}")

check("3:4 최종 출력은 exact 0.75가 아님", abs(1024 / 1368 - 0.75) > 1e-4,
      f"{1024/1368:.5f}")
check("그래도 0.5% 안에 들어옴", abs(1024 / 1368 - 0.75) / 0.75 < 0.005,
      f"오차 {abs(1024/1368-0.75)/0.75*100:.3f}%")

print("\n[2] 비율 추론 — 재인코딩 오차 허용 / 경계")
# 기대값을 상수에서 직접 유도한다(허용치를 바꿔도 테스트가 따라간다).
for w in (1024, 1026, 1029, 1032, 1040, 1084):
    err = abs(w / 1368 - 0.75) / 0.75
    want = err <= config.ASPECT_INFER_TOLERANCE
    got = layout.infer_aspect_ratio((w, 1368))
    check(f"{w}x1368 (오차 {err*100:.2f}%) → {'3:4' if want else 'None'}",
          (got == "3:4") is want, f"got={got}")
for wh in ((1920, 1080), (1024, 768), (100, 300), (0, 100)):
    check(f"{wh[0]}x{wh[1]} → 미지원", layout.infer_aspect_ratio(wh) is None)

print("\n[3] resolve_aspect_ratio — 교차 검증 분기")
r, w = layout.resolve_aspect_ratio(None, None)
check("요청·이미지 모두 없음 → 기본 1:1", r == config.DEFAULT_ASPECT_RATIO and not w)
r, w = layout.resolve_aspect_ratio(None, (768, 768))
check("요청 없음 + 정사각 draft → 1:1 (기존 클라이언트)", r == "1:1" and not w)
r, w = layout.resolve_aspect_ratio(None, (2304, 768))
check("요청 없음 + 3:1 draft → 추론값", r == "3:1" and not w)
r, w = layout.resolve_aspect_ratio("3:1", (2304, 768))
check("요청·추론 일치", r == "3:1" and not w)
r, w = layout.resolve_aspect_ratio("3:4", None)
check("이미지 없이 요청값만", r == "3:4" and not w)

p = reject(layout.resolve_aspect_ratio, None, (1920, 1080))
check("요청 없음 + 추론 실패 → 거부",
      p and p["error"] == "aspect_ratio_unsupported" and p["image_size"] == [1920, 1080])
p = reject(layout.resolve_aspect_ratio, "16:9", None)
check("미지원 요청값 → 거부",
      p and p["error"] == "aspect_ratio_unsupported" and "16:9" in str(p["requested"]))
p = reject(layout.resolve_aspect_ratio, "1:1", (2304, 768))
check("요청·추론 불일치 → 거부", p and p["error"] == "aspect_ratio_mismatch")
check("불일치 payload에 진단 정보",
      p["requested"] == "1:1" and p["inferred_from_draft"] == "3:1"
      and p["draft_size"] == [2304, 768], f"{p}")
r, w = layout.resolve_aspect_ratio("3:1", (1920, 1080))
check("요청 있음 + 추론 실패 → 요청값 + 경고", r == "3:1" and len(w) == 1, f"{w}")

print("\n[4] 외부 x/y = 제품 bbox 중심점, 배율에 안 흔들림")
masks = synth()
W, H = layout.resolve_output_size("3:1", 1024)
auto = layout.compute_placement(masks, (W, H), "3:1")
pub = auto.as_public((W, H))
check("public 키 구성",
      set(pub) == {"source", "scale_factor", "x", "y", "region_overflow"}, f"{pub}")
check("x/y가 0~1", 0 <= pub["x"] <= 1 and 0 <= pub["y"] <= 1)
check("내부 좌상단 좌표는 노출 안 됨",
      "x_px" not in pub and "y_px" not in pub and "scale" not in pub
      and "region" not in pub and "footprint" not in pub)

# 중심 좌표를 고정한 채 배율만 바꿔도 중심이 그대로여야 한다.
# 상한을 넘지 않는 범위에서만 (상한 초과는 [5]에서 따로 본다)
for sf in (0.6, 0.8, 1.0, min(1.02, config.CANVAS_MAX_UPSCALE / auto.scale * 0.98)):
    pl = layout.compute_placement(masks, (W, H), "3:1",
                                  {"scale_factor": sf, "x": 0.70, "y": 0.45})
    got = pl.as_public((W, H))
    check(f"scale_factor={sf:.3f}에도 중심 고정",
          abs(got["x"] - 0.70) < 0.002 and abs(got["y"] - 0.45) < 0.002,
          f"x={got['x']} y={got['y']}")

# public → override 왕복
back = layout.compute_placement(masks, (W, H), "3:1",
                                {k: pub[k] for k in ("scale_factor", "x", "y")})
check("public 값을 그대로 되보내면 같은 배치",
      abs(back.scale - auto.scale) < 1e-6
      and abs(back.x_px - auto.x_px) <= 1 and abs(back.y_px - auto.y_px) <= 1,
      f"auto=({auto.x_px},{auto.y_px}) back=({back.x_px},{back.y_px})")

print("\n[5] scale_factor와 CANVAS_MAX_UPSCALE")
check("자동 배율은 상한 이하", auto.scale <= config.CANVAS_MAX_UPSCALE + 1e-9,
      f"{auto.scale:.4f}")
limit = config.CANVAS_MAX_UPSCALE / auto.scale
ok = layout.compute_placement(masks, (W, H), "3:1", {"scale_factor": limit * 0.99})
check("상한 바로 아래는 허용", ok.scale <= config.CANVAS_MAX_UPSCALE)
p = reject(layout.compute_placement, masks, (W, H), "3:1",
           {"scale_factor": limit * 1.01})
check("상한 초과 → 거부", p and p["error"] == "placement_over_max_upscale")
check("거부 payload에 상한·최대 배수·기본 배치",
      p["max_upscale"] == config.CANVAS_MAX_UPSCALE
      and abs(p["max_scale_factor"] - limit) < 1e-3
      and p["suggested"]["source"] == "auto", f"{p}")
check("le=3 스키마 상한과 별개로 막힘", limit < 3.0,
      f"이 제품의 실제 상한 배수 = {limit:.3f}")

print("\n[6] 응답 placement = 최종 resolved 상태")
for label, ov in (("scale_factor만", {"scale_factor": 0.8}),
                  ("x만", {"x": 0.72}),
                  ("y만", {"y": 0.40}),
                  ("전체", {"scale_factor": 0.9, "x": 0.72, "y": 0.40})):
    pl, public = layout.resolve_placement(masks, (W, H), "3:1", ov)
    check(f"{label}: 모든 값이 채워짐",
          all(public.get(k) is not None
              for k in ("source", "scale_factor", "x", "y", "region_overflow")),
          f"{public}")
    check(f"{label}: source=override", public["source"] == "override")
    if "x" in ov:
        check(f"{label}: 지정 x 반영", abs(public["x"] - ov["x"]) < 0.002)
    if "y" in ov:
        check(f"{label}: 지정 y 반영", abs(public["y"] - ov["y"]) < 0.002)
    if "scale_factor" in ov:
        check(f"{label}: 지정 scale_factor 반영",
              abs(public["scale_factor"] - ov["scale_factor"]) < 0.002)

pl, public = layout.resolve_placement(masks, (W, H), "3:1", None)
check("override 없음 → source=auto, scale_factor=1.0",
      public["source"] == "auto" and public["scale_factor"] == 1.0)

# 1:1 항등도 resolved 좌표를 낼 수 있어야 한다
pl, public = layout.resolve_placement(synth(), (1024, 1024), "1:1", None)
check("1:1 identity도 resolved 중심 좌표 반환",
      public["source"] == "identity" and public["scale_factor"] == 1.0
      and 0 < public["x"] < 1 and 0 < public["y"] < 1, f"{public}")

print("\n[7] 거부 시 suggested 첨부")
p = None
try:
    layout.resolve_placement(masks, (W, H), "3:1", {"x": 0.99})
except layout.LayoutRejection as e:
    p = e.payload
check("unsafe override → placement_unsafe", p and p["error"] == "placement_unsafe")
check("suggested에 서버 기본 배치",
      p["suggested"]["source"] == "auto" and p["suggested"]["scale_factor"] == 1.0)
check("진단용 canvas/footprint 포함",
      p["canvas"] == {"width": W, "height": H} and len(p["footprint"]) == 4)

print("\n[8] 배선 상태 — A3-2 / A3-3 완료")
draft_req = _api_class_block("DraftRequest")
refine_req = _api_class_block("RefineRequest")
check("A3-2: DraftRequest에 aspect_ratio 있음", "aspect_ratio" in draft_req)
check("A3-2: DraftRequest에 placement 있음", "placement" in draft_req)
check("A3-3: RefineRequest에 aspect_ratio 있음", "aspect_ratio" in refine_req)
check("A3-3: RefineRequest에 placement 있음", "placement" in refine_req)
check("DraftItem에는 추가하지 않음 (요청 단위 값이라 meta가 맞음)",
      "aspect_ratio" not in _api_class_block("DraftItem")
      and "placement" not in _api_class_block("DraftItem"))
check("PlacementSpec은 extra 금지 (응답 객체 통째 전달 방지)",
      'extra="forbid"' in _api_class_block("PlacementSpec"))
# docstring에서 "response-only"라고 설명하는 것은 계약 문서화이므로 허용한다.
# 금지하는 것은 **필드로 선언**하는 것이다.
_ps_fields = [l.strip().split(":")[0] for l in _api_class_block("PlacementSpec").splitlines()
              if l.startswith("    ") and ": " in l and not l.strip().startswith("#")
              and "=" in l]
check("PlacementSpec 필드는 scale_factor/x/y 뿐",
      set(_ps_fields) == {"scale_factor", "x", "y"}, f"{_ps_fields}")

print("\n" + "=" * 60)
print(f"통과 {PASS} / 실패 {FAIL}")
sys.exit(1 if FAIL else 0)
