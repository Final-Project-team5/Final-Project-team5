"""A3-3 — /generate/refine flat 경로의 비율 추론/배치 배선 (GPU·rembg 불필요).

rembg만 합성 마스크로 대체하고 layout/배치/렌더는 실제 코드를 그대로 돌린다.
AI 경로는 diffusion을 타므로 이 테스트에서는 호출하지 않는다(400 분기만 확인).

실행 (프로젝트 루트에서):
    PYTHONPATH="$PWD" python tests/test_refine_canvas_api.py
"""
import base64
import io
import sys
import types
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

sys.modules["torch"] = types.ModuleType("torch")
sys.modules["diffusers"] = types.ModuleType("diffusers")

import pipeline.masking as M                                  # noqa: E402


def _fake_remove(img, session=None):
    W, H = img.size
    a = np.zeros((H, W), np.uint8)
    a[int(H * .29):int(H * .74), int(W * .32):int(W * .51)] = 255
    a[int(H * .47):int(H * .72), int(W * .55):int(W * .66)] = 255
    return Image.fromarray(
        np.dstack([np.array(img.convert("RGB")), a]).astype(np.uint8), "RGBA")


M.remove = _fake_remove
M.get_session = lambda: None

import api as api_module                                      # noqa: E402
from fastapi.testclient import TestClient                     # noqa: E402
from pipeline import config                                   # noqa: E402
from pipeline.layout import resolve_output_size               # noqa: E402

client = TestClient(api_module.app)
PASS, FAIL = 0, 0


def check(name, ok, detail=""):
    global PASS, FAIL
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  {detail}" if detail else ""))
    if ok:
        PASS += 1
    else:
        FAIL += 1


def b64(size, color=(180, 170, 160)):
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


ORIGINAL = b64((900, 700))
SOLID = {"mode": "solid", "colors": ["#F2E9DC"], "direction": None}


def refine(draft_size=(768, 768), background=SOLID, **extra):
    body = {"draft_image": b64(draft_size), "original_image": ORIGINAL,
            "category": "beauty", "ai_notice": False, **extra}
    if background is not None:
        body["background"] = background
    return client.post("/generate/refine", json=body)


def decode(r):
    return Image.open(io.BytesIO(base64.b64decode(r.json()["image"])))


def drafts(**extra):
    return client.post("/generate/drafts", json={
        "mode": "inpaint", "image": ORIGINAL, "category": "beauty",
        "num_images": 1, "background_mode": "solid",
        "bg_colors": ["#F2E9DC"], **extra})


REFINE_SIZE = config.MODELS[config.REFINE_MODEL]["size"]

print("\n[1] 기존 refine 하위 호환")
r0 = refine()
check("200 응답", r0.status_code == 200, r0.text[:200])
m0 = r0.json()["meta"]
img0 = decode(r0)
check(f"출력 정사각 {REFINE_SIZE}", img0.size == (REFINE_SIZE, REFINE_SIZE), f"{img0.size}")
for k in ("elapsed", "model", "strength", "mode", "area_ratio", "layout",
          "diffusion", "background_mode", "resolution"):
    check(f"기존 meta 키 유지: {k}", k in m0)
check("resolution 타입·값 유지",
      m0["resolution"] == REFINE_SIZE and isinstance(m0["resolution"], int))
check("신규 키는 추가만",
      set(m0) - {"elapsed", "model", "strength", "mode", "area_ratio", "layout",
                 "diffusion", "background_mode", "resolution"}
      == {"aspect_ratio", "canvas", "placement"}, f"{sorted(m0)}")
check("768x768 draft → resolved 1:1", m0["aspect_ratio"] == "1:1")
check("placement source = identity", m0["placement"]["source"] == "identity")
check("canvas 정사각", m0["canvas"] == {"width": REFINE_SIZE, "height": REFINE_SIZE})

r1 = refine(aspect_ratio="1:1")
check("explicit 1:1도 pixel diff = 0",
      int(np.abs(np.array(decode(r1), np.int32)
                 - np.array(img0, np.int32)).max()) == 0)

print("\n[2] 비율 추론 (tolerance)")
for size, want in (((768, 768), "1:1"), ((1024, 1024), "1:1"),
                   ((2304, 768), "3:1"), ((3072, 1024), "3:1"),
                   ((768, 1024), "3:4"), ((1024, 1368), "3:4")):
    r = refine(draft_size=size)
    check(f"{size[0]}x{size[1]} → {want}",
          r.status_code == 200 and r.json()["meta"]["aspect_ratio"] == want,
          f"{r.status_code} {r.json().get('meta', {}).get('aspect_ratio')}")
check("1024x1368은 exact 0.75가 아님 (tolerance로 통과)",
      abs(1024 / 1368 - 0.75) > 1e-4)

for size in ((1920, 1080), (1024, 768), (1032, 1368)):
    r = refine(draft_size=size)
    check(f"{size[0]}x{size[1]} 미지원 → 400", r.status_code == 400, f"{r.status_code}")
    check(f"{size[0]}x{size[1]}: error=aspect_ratio_unsupported",
          r.json()["detail"].get("error") == "aspect_ratio_unsupported")

r = refine(draft_size=(2304, 768), aspect_ratio="1:1")
check("명시값과 추론값 불일치 → 400", r.status_code == 400, f"{r.status_code}")
d = r.json()["detail"]
check("error=aspect_ratio_mismatch", d.get("error") == "aspect_ratio_mismatch")
check("불일치 진단 정보",
      d["requested"] == "1:1" and d["inferred_from_draft"] == "3:1"
      and d["draft_size"] == [2304, 768], f"{d}")
r = refine(draft_size=(2304, 768), aspect_ratio="3:1")
check("명시값과 추론값 일치 → 200", r.status_code == 200)

print("\n[3] flat refine 3:1 / 3:4")
for ratio, draft_size in (("3:1", (2304, 768)), ("3:4", (768, 1024))):
    want = resolve_output_size(ratio)
    r = refine(draft_size=draft_size)
    check(f"{ratio}: 200", r.status_code == 200, r.text[:160])
    m = r.json()["meta"]
    im = decode(r)
    check(f"{ratio}: 최종 출력 {want}", im.size == want, f"{im.size}")
    check(f"{ratio}: canvas 일치", m["canvas"] == {"width": want[0], "height": want[1]})
    check(f"{ratio}: resolved aspect_ratio", m["aspect_ratio"] == ratio)
    check(f"{ratio}: resolution은 짧은 변", m["resolution"] == REFINE_SIZE)
    p = m["placement"]
    check(f"{ratio}: placement 미전송 → auto", p["source"] == "auto"
          and p["scale_factor"] == 1.0, f"{p}")
    check(f"{ratio}: public 키만", set(p) ==
          {"source", "scale_factor", "x", "y", "region_overflow"})
    check(f"{ratio}: 내부 키 미노출",
          not any(k in m for k in ("region", "footprint", "x_px", "y_px")))
check("3:1 최종 3072x1024", resolve_output_size("3:1") == (3072, 1024))
check("3:4 최종 1024x1368", resolve_output_size("3:4") == (1024, 1368))

print("\n[4] drafts → refine placement round-trip")
for ratio in ("3:1", "3:4"):
    dr = drafts(aspect_ratio=ratio)
    check(f"{ratio}: drafts 200", dr.status_code == 200)
    dp = dr.json()["meta"]["placement"]
    draft_img = Image.open(io.BytesIO(base64.b64decode(
        dr.json()["drafts"][0]["image"])))
    # response-only 필드는 요청에 담지 않는다. 세 필드만 명시 전달.
    echo = {k: dp[k] for k in ("scale_factor", "x", "y")}
    rr = refine(draft_size=draft_img.size, placement=echo)
    check(f"{ratio}: refine 200", rr.status_code == 200, rr.text[:200])
    rp = rr.json()["meta"]["placement"]
    check(f"{ratio}: 정규화 중심 재현 (draft 768 → refine 1024)",
          abs(rp["x"] - dp["x"]) < 0.005 and abs(rp["y"] - dp["y"]) < 0.005,
          f"draft=({dp['x']},{dp['y']}) refine=({rp['x']},{rp['y']})")
    check(f"{ratio}: 상대 배율 재현",
          abs(rp["scale_factor"] - dp["scale_factor"]) < 0.005,
          f"{dp['scale_factor']} → {rp['scale_factor']}")
    check(f"{ratio}: source=override", rp["source"] == "override")

    # partial override도 같은 규칙
    rr = refine(draft_size=draft_img.size, placement={"scale_factor": 0.85})
    rp = rr.json()["meta"]["placement"]
    check(f"{ratio}: partial(scale_factor만) 200", rr.status_code == 200)
    check(f"{ratio}: partial 누락값이 서버 계산으로 채워짐",
          rp["x"] is not None and rp["y"] is not None
          and abs(rp["scale_factor"] - 0.85) < 0.003, f"{rp}")

print("\n[5] response-only 필드는 요청에서 거부")
dr = drafts(aspect_ratio="3:1")
dp = dr.json()["meta"]["placement"]
draft_img = Image.open(io.BytesIO(base64.b64decode(dr.json()["drafts"][0]["image"])))
for bad in ("source", "region_overflow"):
    r = refine(draft_size=draft_img.size,
               placement={k: dp[k] for k in ("scale_factor", "x", "y")} | {bad: dp[bad]})
    check(f"placement에 {bad} 포함 → 422 (extra 무시 아님)",
          r.status_code == 422, f"{r.status_code}")
r = refine(draft_size=draft_img.size, placement=dp)
check("응답 객체 통째로 전달 → 422", r.status_code == 422, f"{r.status_code}")

print("\n[6] validation")
# A4-2에서 3:1 + ai는 허용됐다. 여전히 막히는 3:4로 확인한다.
r = refine(draft_size=(768, 1024), background=None, aspect_ratio="3:4")
check("3:4 + ai → 400 (유지)", r.status_code == 400, f"{r.status_code}")
check("error=aspect_ratio_not_supported_for_ai",
      r.json()["detail"].get("error") == "aspect_ratio_not_supported_for_ai")
# 비정사각 AI refine은 original_image 필수
r = client.post("/generate/refine", json={
    "draft_image": b64((2304, 768)), "category": "beauty", "ai_notice": False})
check("3:1 ai + original_image 없음 → 400", r.status_code == 400, f"{r.status_code}")
check("error=original_image_required_for_nonsquare_ai",
      r.json()["detail"].get("error") == "original_image_required_for_nonsquare_ai",
      f"{r.json()['detail']}")
r = refine(background=None, placement={"scale_factor": 0.9})
check("placement + ai → 400", r.status_code == 400, f"{r.status_code}")
r = refine(draft_size=(2304, 768), placement={"x": 0.995})
check("unsafe override → 400", r.status_code == 400, f"{r.status_code}")
d = r.json()["detail"]
check("error=placement_unsafe", d.get("error") == "placement_unsafe", f"{d}")
check("suggested에 기본 배치",
      d["suggested"]["source"] == "auto" and set(d["suggested"]) ==
      {"source", "scale_factor", "x", "y", "region_overflow"})
r = refine(draft_size=(2304, 768), placement={"scale_factor": 3.0})
check("max upscale 초과 → 400", r.status_code == 400, f"{r.status_code}")
check("error=placement_over_max_upscale",
      r.json()["detail"].get("error") == "placement_over_max_upscale")
r = refine(draft_size=(2304, 768), placement={"scale_factor": 3.5})
check("le=3 초과는 422", r.status_code == 422, f"{r.status_code}")
r = refine(aspect_ratio="16:9")
check("잘못된 enum → 422", r.status_code == 422, f"{r.status_code}")

print("\n[7] 1:1 placement")
r = refine()
check("placement 미전송 → identity 유지",
      r.json()["meta"]["placement"]["source"] == "identity")
r = refine(placement={"scale_factor": 0.8})
check("1:1 + placement 명시 → 200", r.status_code == 200, r.text[:160])
p = r.json()["meta"]["placement"]
check("1:1 + placement → source=override", p["source"] == "override")
check("1:1 + placement → 배율 반영", abs(p["scale_factor"] - 0.8) < 0.003, f"{p}")
im = decode(r)
check("1:1 + placement도 캔버스는 정사각", im.size == (REFINE_SIZE, REFINE_SIZE))

print("\n[8] drafts의 placement + text2img")
r = client.post("/generate/drafts", json={
    "mode": "text2img", "prompt": "p", "category": "food",
    "background_mode": "ai", "placement": {"scale_factor": 0.9}})
check("placement + text2img → 400", r.status_code == 400, f"{r.status_code}")

print("\n" + "=" * 60)
print(f"통과 {PASS} / 실패 {FAIL}")
sys.exit(1 if FAIL else 0)
