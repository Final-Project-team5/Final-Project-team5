"""A3-2 — /generate/drafts flat 경로의 비율/배치 API 배선 (GPU·rembg 불필요).

rembg만 합성 마스크로 대체하고 **layout/배치/렌더는 실제 코드를 그대로** 돌린다.
스텁으로 덮으면 캔버스 크기나 배치 좌표가 검증되지 않기 때문이다.
AI 경로는 400에서 막히므로 diffusion을 호출하지 않는다.

실행 (프로젝트 루트에서):
    PYTHONPATH="$PWD" python tests/test_drafts_canvas_api.py
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
    """rembg 대체. 제품 2덩어리(연결요소 2개)를 결정적으로 만든다."""
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

client = TestClient(api_module.app)

buf = io.BytesIO()
Image.new("RGB", (900, 700), (180, 170, 160)).save(buf, format="PNG")
IMG = base64.b64encode(buf.getvalue()).decode()

PASS, FAIL = 0, 0


def check(name, ok, detail=""):
    global PASS, FAIL
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  {detail}" if detail else ""))
    if ok:
        PASS += 1
    else:
        FAIL += 1


def drafts(**extra):
    body = {"mode": "inpaint", "image": IMG, "category": "beauty",
            "num_images": 1, "background_mode": "solid",
            "bg_colors": ["#F2E9DC"], **extra}
    return client.post("/generate/drafts", json=body)


def decode(r):
    d = r.json()["drafts"][0]["image"]
    return Image.open(io.BytesIO(base64.b64decode(d)))


DRAFT_SIZE = config.MODELS[config.DRAFT_MODEL]["size"]

print("\n[1] 기존 요청 — aspect_ratio 미전송")
r0 = drafts()
check("200 응답", r0.status_code == 200, r0.text[:200])
m0 = r0.json()["meta"]
img0 = decode(r0)
check(f"출력이 정사각 {DRAFT_SIZE}", img0.size == (DRAFT_SIZE, DRAFT_SIZE), f"{img0.size}")
check("resolution 키 타입·값 유지", m0["resolution"] == DRAFT_SIZE
      and isinstance(m0["resolution"], int))
for k in ("elapsed", "model", "mode", "area_ratio", "layout",
          "diffusion", "background_mode", "resolution"):
    check(f"기존 meta 키 유지: {k}", k in m0)
check("신규 키는 추가만", set(m0) - {"elapsed", "model", "mode", "area_ratio",
      "layout", "diffusion", "background_mode", "resolution"}
      == {"aspect_ratio", "canvas", "placement"}, f"{sorted(m0)}")
check("resolved aspect_ratio = 1:1", m0["aspect_ratio"] == "1:1")
check("canvas = 정사각", m0["canvas"] == {"width": DRAFT_SIZE, "height": DRAFT_SIZE})
check("placement source = identity", m0["placement"]["source"] == "identity")

print("\n[2] explicit 1:1 — 생략한 요청과 동일 출력")
r1 = drafts(aspect_ratio="1:1")
check("200 응답", r1.status_code == 200)
img1 = decode(r1)
diff = int(np.abs(np.array(img0, np.int32) - np.array(img1, np.int32)).max())
check("생략 요청과 pixel diff = 0", diff == 0, f"max diff={diff}")
m1 = r1.json()["meta"]
check("resolved aspect_ratio = 1:1", m1["aspect_ratio"] == "1:1")
check("placement도 동일", m1["placement"] == m0["placement"])

print("\n[3] flat 3:1 / 3:4")
EXPECT = {"3:1": (DRAFT_SIZE * 3, DRAFT_SIZE),
          "3:4": (DRAFT_SIZE, round(DRAFT_SIZE * 4 / 3 / 8) * 8)}
for ratio, want in EXPECT.items():
    r = drafts(aspect_ratio=ratio)
    check(f"{ratio}: 200 응답", r.status_code == 200, r.text[:200])
    m = r.json()["meta"]
    im = decode(r)
    check(f"{ratio}: 출력 크기 {want}", im.size == want, f"{im.size}")
    check(f"{ratio}: canvas 일치",
          m["canvas"] == {"width": want[0], "height": want[1]})
    check(f"{ratio}: resolved aspect_ratio", m["aspect_ratio"] == ratio)
    check(f"{ratio}: resolution은 짧은 변 그대로", m["resolution"] == DRAFT_SIZE)
    p = m["placement"]
    check(f"{ratio}: placement source=auto", p["source"] == "auto")
    check(f"{ratio}: x/y가 0~1 정규화", 0 < p["x"] < 1 and 0 < p["y"] < 1, f"{p}")
    check(f"{ratio}: 내부값 미노출",
          set(p) == {"source", "scale_factor", "x", "y", "region_overflow"}, f"{sorted(p)}")
    check(f"{ratio}: meta에 내부 키 없음",
          not any(k in m for k in ("region", "footprint", "scale", "x_px", "y_px",
                                   "CANVAS_MAX_UPSCALE", "components")))

# 1024 기준(최종 출력)도 계약 문서 값과 맞는지
from pipeline.layout import resolve_output_size                # noqa: E402
check("1:1 최종 1024x1024", resolve_output_size("1:1") == (1024, 1024))
check("3:1 최종 3072x1024", resolve_output_size("3:1") == (3072, 1024))
check("3:4 최종 1024x1368", resolve_output_size("3:4") == (1024, 1368))

print("\n[4] public x/y가 제품 bbox 중심인지 (실제 픽셀로 확인)")
r = drafts(aspect_ratio="3:1")
m = r.json()["meta"]
im = decode(r)
W, H = im.size
flat = np.array(Image.new("RGB", (W, H), (242, 233, 220)), np.int32)
d = np.abs(np.array(im, np.int32) - flat).sum(2)
ys, xs = np.where(d > 40)          # 제품+그림자 잉크
# 제품 마스크만 정확히 재현하긴 어려우므로 중심 좌표의 대략적 일치만 본다
cx = (xs.min() + xs.max()) / 2 / W
check("응답 x가 실제 잉크 중심과 근사", abs(m["placement"]["x"] - cx) < 0.06,
      f"응답={m['placement']['x']:.4f} 실측={cx:.4f}")

print("\n[5] validation")
r = drafts(aspect_ratio="16:9")
check("잘못된 enum → 422", r.status_code == 422, f"{r.status_code}")
# A4-2에서 3:1 + ai는 허용됐다. 여기서는 여전히 막히는 3:4로 확인한다.
# (3:1 AI 경로는 tests/test_ai_nonsquare_api.py에서 다룬다)
r = drafts(aspect_ratio="3:4", background_mode="ai", bg_colors=None)
check("3:4 + ai → 400 (유지)", r.status_code == 400, f"{r.status_code} {r.text[:120]}")
check("error=aspect_ratio_not_supported_for_ai",
      r.json()["detail"].get("error") == "aspect_ratio_not_supported_for_ai",
      f"{r.json()['detail']}")
r = client.post("/generate/drafts", json={
    "mode": "text2img", "prompt": "p", "category": "food",
    "background_mode": "solid", "bg_colors": ["#F2E9DC"], "aspect_ratio": "3:1"})
check("non-square + text2img → 400", r.status_code == 400, f"{r.status_code}")
r = drafts(background_mode="ai", bg_colors=None, placement={"scale_factor": 0.9})
check("placement + ai → 400", r.status_code == 400, f"{r.status_code}")
r = drafts()
check("정사각 + placement 없음은 영향 없음", r.status_code == 200)

print("\n[6] unsafe override → 400 + suggested")
r = drafts(aspect_ratio="3:1", placement={"x": 0.995})
check("캔버스 이탈 → 400", r.status_code == 400, f"{r.status_code}")
det = r.json()["detail"]
check("error=placement_unsafe", det.get("error") == "placement_unsafe", f"{det}")
check("suggested에 기본 배치",
      det["suggested"]["source"] == "auto" and det["suggested"]["scale_factor"] == 1.0)
check("suggested가 public 형태만",
      set(det["suggested"]) == {"source", "scale_factor", "x", "y", "region_overflow"})

print("\n[7] partial override")
base = drafts(aspect_ratio="3:1").json()["meta"]["placement"]
for label, ov in (("scale_factor만", {"scale_factor": 0.8}),
                  ("x만", {"x": 0.72}),
                  ("y만", {"y": 0.40}),
                  ("전체", {"scale_factor": 0.85, "x": 0.72, "y": 0.40})):
    r = drafts(aspect_ratio="3:1", placement=ov)
    check(f"{label}: 200", r.status_code == 200, r.text[:160])
    p = r.json()["meta"]["placement"]
    check(f"{label}: 모든 값이 채워짐",
          all(p.get(k) is not None for k in
              ("source", "scale_factor", "x", "y", "region_overflow")), f"{p}")
    check(f"{label}: source=override", p["source"] == "override")
    for k, v in ov.items():
        check(f"{label}: 지정 {k} 반영", abs(p[k] - v) < 0.003, f"{p[k]}")
    missing = [k for k in ("scale_factor", "x", "y") if k not in ov]
    check(f"{label}: 누락값은 서버 계산 (echo 아님)",
          all(p[k] is not None for k in missing))

r = drafts(aspect_ratio="3:1", placement={"scale_factor": 0.8})
p = r.json()["meta"]["placement"]
check("scale_factor만 줘도 좌표가 재계산됨",
      p["x"] is not None and p["y"] is not None, f"{p}")

print("\n[8] max upscale 상한")
r = drafts(aspect_ratio="3:1", placement={"scale_factor": 3.0})
check("le=3 스키마는 통과하지만 400", r.status_code == 400, f"{r.status_code}")
det = r.json()["detail"]
check("error=placement_over_max_upscale",
      det.get("error") == "placement_over_max_upscale", f"{det}")
check("max_upscale과 max_scale_factor 안내",
      det["max_upscale"] == config.CANVAS_MAX_UPSCALE and det["max_scale_factor"] > 0,
      f"max_scale_factor={det.get('max_scale_factor')}")
check("suggested 포함", det["suggested"]["source"] == "auto")
r = drafts(aspect_ratio="3:1", placement={"scale_factor": 3.5})
check("le=3 초과는 422", r.status_code == 422, f"{r.status_code}")
r = drafts(aspect_ratio="3:1", placement={"scale_factor": det["max_scale_factor"] * 0.98})
check("상한 바로 아래는 200", r.status_code == 200, f"{r.status_code}")

print("\n[9] 잘못된 placement 값")
for bad, want in (({"scale_factor": 0}, 422), ({"scale_factor": -1}, 422),
                  ({"x": 1.5}, 422), ({"y": -0.1}, 422)):
    r = drafts(aspect_ratio="3:1", placement=bad)
    check(f"{bad} → {want}", r.status_code == want, f"{r.status_code}")

print("\n" + "=" * 60)
print(f"통과 {PASS} / 실패 {FAIL}")
sys.exit(1 if FAIL else 0)
