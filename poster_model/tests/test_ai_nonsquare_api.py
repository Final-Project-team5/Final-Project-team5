"""A4-2 — 3:1 AI production 경로 (GPU·rembg·diffusion 불필요).

rembg와 diffusion 파이프만 스텁으로 대체하고 layout/배치/업스케일/합성은 실제
코드를 그대로 돌린다. 스텁 파이프는 **호출 인자를 기록**하므로, GPU 픽셀 회귀를
돌릴 수 없는 AI 경로의 1:1 무변경을 인자 수준에서 검증할 수 있다.

실행 (프로젝트 루트에서):
    PYTHONPATH="$PWD" python tests/test_ai_nonsquare_api.py
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

# --- torch 스텁: 시드 생성만 쓰인다 ---
torch_stub = types.ModuleType("torch")


class _Gen:
    def __init__(self, device=None):
        self.device, self.seed = device, None

    def manual_seed(self, s):
        self.seed = s
        return self


class _Ints:
    def __init__(self, n):
        self.n = n

    def tolist(self):
        return [1000 + i for i in range(self.n)]


torch_stub.Generator = _Gen
torch_stub.randint = lambda lo, hi, shape: _Ints(shape[0])
sys.modules["torch"] = torch_stub
sys.modules["diffusers"] = types.ModuleType("diffusers")

import pipeline.masking as M                                   # noqa: E402


def _fake_remove(img, session=None):
    W, H = img.size
    a = np.zeros((H, W), np.uint8)
    a[int(H * .29):int(H * .74), int(W * .32):int(W * .51)] = 255
    a[int(H * .47):int(H * .72), int(W * .55):int(W * .66)] = 255
    return Image.fromarray(
        np.dstack([np.array(img.convert("RGB")), a]).astype(np.uint8), "RGBA")


M.remove = _fake_remove
M.get_session = lambda: None

import pipeline.generate as G                                  # noqa: E402

CALLS = []
LOADS = []          # _load(kind, task, tiling) 호출 기록 — 어느 인스턴스를 쓰는지


class _FakePipe:
    """호출 인자를 기록하고 요청한 크기의 이미지를 돌려준다."""

    def __call__(self, **kw):
        CALLS.append(kw)
        n = kw.get("num_images_per_prompt", 1)
        w, h = kw["width"], kw["height"]
        img = Image.fromarray(
            (np.random.RandomState(0).rand(h, w, 3) * 40 + 110).astype(np.uint8))
        return types.SimpleNamespace(images=[img.copy() for _ in range(n)])


def _fake_load(kind, task, tiling=True):
    LOADS.append({"kind": kind, "task": task, "tiling": tiling})
    return _FakePipe()


G._load = _fake_load

import api as api_module                                       # noqa: E402
from fastapi.testclient import TestClient                      # noqa: E402
from pipeline import config, layout                            # noqa: E402

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


IMG = b64((900, 700))
DRAFT_SIZE = config.MODELS[config.DRAFT_MODEL]["size"]
REFINE_SIZE = config.MODELS[config.REFINE_MODEL]["size"]


def drafts(**extra):
    CALLS.clear()
    LOADS.clear()
    return client.post("/generate/drafts", json={
        "mode": "inpaint", "image": IMG, "category": "beauty", "num_images": 1,
        "background_mode": "ai", **extra})


def refine(draft_size=(REFINE_SIZE, REFINE_SIZE), original=IMG, **extra):
    CALLS.clear()
    LOADS.clear()
    body = {"draft_image": b64(draft_size), "category": "beauty",
            "ai_notice": False, **extra}
    if original is not None:
        body["original_image"] = original
    return client.post("/generate/refine", json=body)


def out_size(r, key="image"):
    d = r.json()[key] if key == "image" else r.json()["drafts"][0]["image"]
    return Image.open(io.BytesIO(base64.b64decode(d))).size


print("\n[1] 1:1 AI 회귀 — 파이프 인자가 기존과 동일한가")
r = drafts()
check("200", r.status_code == 200, r.text[:200])
kw = CALLS[-1]
check(f"height == width == {DRAFT_SIZE}",
      kw["height"] == DRAFT_SIZE and kw["width"] == DRAFT_SIZE,
      f"{kw['width']}x{kw['height']}")
# 배치·업스케일이 개입하지 않았는지: prepare_image 결과와 픽셀 동일해야 한다
base, masks, _ = M.prepare_image(
    Image.open(io.BytesIO(base64.b64decode(IMG))), DRAFT_SIZE)
check("image가 prepare_image 결과와 픽셀 동일",
      np.array_equal(np.array(kw["image"]), np.array(base)))
check("mask가 masks.inpaint와 픽셀 동일",
      np.array_equal(np.array(kw["mask_image"]), np.array(masks.inpaint)))
check("출력이 정사각", out_size(r, "drafts") == (DRAFT_SIZE, DRAFT_SIZE))
check("1:1은 기존 인스턴스 사용 (tiling 유지)",
      LOADS == [{"kind": "sd15", "task": "inpaint", "tiling": True}], f"{LOADS}")
m = r.json()["meta"]
check("meta.aspect_ratio = 1:1", m["aspect_ratio"] == "1:1")
check("meta.canvas 정사각",
      m["canvas"] == {"width": DRAFT_SIZE, "height": DRAFT_SIZE})
check("meta.resolution 유지", m["resolution"] == DRAFT_SIZE)
check("내부 생성 해상도 미노출",
      not any(k in m for k in ("gen_size", "gen_wh", "diffusion_size")))

r = refine()
check("refine 1:1 200", r.status_code == 200, r.text[:200])
kw = CALLS[-1]
check(f"refine height == width == {REFINE_SIZE}",
      kw["height"] == REFINE_SIZE and kw["width"] == REFINE_SIZE)
check("refine image == draft.resize(정사각)",
      kw["image"].size == (REFINE_SIZE, REFINE_SIZE))
check("refine 출력 정사각", out_size(r) == (REFINE_SIZE, REFINE_SIZE))
check("1:1 refine도 기존 인스턴스",
      LOADS == [{"kind": "sdxl", "task": "inpaint", "tiling": True}], f"{LOADS}")
check("refine meta.aspect_ratio = 1:1", r.json()["meta"]["aspect_ratio"] == "1:1")

print("\n[2] 3:1 AI draft — 1536x512 생성 → 2304x768")
r = drafts(aspect_ratio="3:1")
check("200", r.status_code == 200, r.text[:200])
kw = CALLS[-1]
gen = layout.resolve_ai_gen_size("3:1", "draft", layout.resolve_output_size("3:1", DRAFT_SIZE))
check("생성 해상도 1536x512", (kw["width"], kw["height"]) == (1536, 512),
      f"{kw['width']}x{kw['height']}")
check("helper 값과 일치", (kw["width"], kw["height"]) == gen)
check("파이프에 넘긴 image/mask가 생성 해상도",
      kw["image"].size == gen and kw["mask_image"].size == gen)
check("최종 출력 2304x768", out_size(r, "drafts") == (2304, 768), f"{out_size(r, 'drafts')}")
check("3:1 draft는 no-tiling 인스턴스 사용",
      LOADS == [{"kind": "sd15", "task": "inpaint", "tiling": False}], f"{LOADS}")
m = r.json()["meta"]
check("meta.canvas = 2304x768", m["canvas"] == {"width": 2304, "height": 768})
check("meta.aspect_ratio = 3:1", m["aspect_ratio"] == "3:1")
check("meta.resolution은 짧은 변 유지", m["resolution"] == DRAFT_SIZE)
check("meta.placement 존재", m["placement"] and m["placement"]["source"] == "auto")
check("내부 생성 해상도 미노출",
      "1536" not in str(m) and "512" not in str(m.get("canvas", "")))

print("\n[3] 3:1 AI refine — 1728x576 생성 → 3072x1024")
r = refine(draft_size=(2304, 768))
check("200", r.status_code == 200, r.text[:200])
kw = CALLS[-1]
check("생성 해상도 1728x576", (kw["width"], kw["height"]) == (1728, 576),
      f"{kw['width']}x{kw['height']}")
check("draft가 생성 해상도로 리사이즈되어 전달", kw["image"].size == (1728, 576))
check("mask도 생성 해상도", kw["mask_image"].size == (1728, 576))
check("최종 출력 3072x1024", out_size(r) == (3072, 1024), f"{out_size(r)}")
check("3:1 refine은 SDXL 기존 인스턴스 (이번 변경 대상 아님)",
      LOADS == [{"kind": "sdxl", "task": "inpaint", "tiling": True}], f"{LOADS}")
m = r.json()["meta"]
check("meta.canvas = 3072x1024", m["canvas"] == {"width": 3072, "height": 1024})
check("meta.aspect_ratio = 3:1 (draft에서 추론)", m["aspect_ratio"] == "3:1")
check("meta.resolution 유지", m["resolution"] == REFINE_SIZE)

print("\n[4] 실제 draft → refine 연결 (폴백 미개입)")
d = drafts(aspect_ratio="3:1")
draft_img = d.json()["drafts"][0]["image"]
check("drafts 출력이 2304x768",
      Image.open(io.BytesIO(base64.b64decode(draft_img))).size == (2304, 768))
CALLS.clear()
r = client.post("/generate/refine", json={
    "draft_image": draft_img, "original_image": IMG,
    "category": "beauty", "ai_notice": False})     # aspect_ratio 미전송
check("aspect_ratio 미전송으로도 200", r.status_code == 200, r.text[:200])
check("draft 크기에서 3:1 추론", r.json()["meta"]["aspect_ratio"] == "3:1")
kw = CALLS[-1]
check("생성 해상도 1728x576", (kw["width"], kw["height"]) == (1728, 576))
# 폴백이 개입했다면 draft 픽셀이 아니라 다른 이미지가 들어갔을 것이다
sent = np.array(kw["image"].resize((2304, 768), Image.LANCZOS), np.int32)
orig = np.array(Image.open(io.BytesIO(base64.b64decode(draft_img))).convert("RGB"),
                np.int32)
check("파이프 입력이 실제 draft에서 유래 (stand-in 아님)",
      float(np.abs(sent - orig).mean()) < 12,
      f"평균 차이 {float(np.abs(sent - orig).mean()):.2f}")

print("\n[5] validation")
r = refine(draft_size=(2304, 768), original=None)
check("3:1 ai + original_image 없음 → 400", r.status_code == 400, f"{r.status_code}")
check("error=original_image_required_for_nonsquare_ai",
      r.json()["detail"].get("error") == "original_image_required_for_nonsquare_ai")
# 1:1 + original_image 없음은 기존 img2img 폴백으로 들어가야 한다(회귀 금지).
# 그 폴백은 실제 SDXL img2img 모델을 로드하므로 여기서는 완주할 수 없다.
# "validation에서 400으로 막히지 않고 폴백까지 도달했는가"만 확인한다.
lenient = TestClient(api_module.app, raise_server_exceptions=False)
CALLS.clear()
r = lenient.post("/generate/refine", json={
    "draft_image": b64((REFINE_SIZE, REFINE_SIZE)), "category": "beauty",
    "ai_notice": False})
check("1:1 ai + original_image 없음 → 400 아님 (폴백 유지)",
      r.status_code != 400, f"{r.status_code}")

r = drafts(aspect_ratio="3:4")
check("3:4 + ai draft → 400", r.status_code == 400, f"{r.status_code}")
check("error=aspect_ratio_not_supported_for_ai",
      r.json()["detail"].get("error") == "aspect_ratio_not_supported_for_ai")
check("supported 목록 안내",
      r.json()["detail"]["supported"] == list(config.AI_SUPPORTED_RATIOS))
r = refine(draft_size=(768, 1024), aspect_ratio="3:4")
check("3:4 + ai refine → 400", r.status_code == 400, f"{r.status_code}")
r = refine(draft_size=(1024, 1368))
check("3:4 draft 추론만으로도 400 (필드 미전송)", r.status_code == 400,
      f"{r.status_code}")
check("추론 경로도 같은 error",
      r.json()["detail"].get("error") == "aspect_ratio_not_supported_for_ai")

r = drafts(aspect_ratio="3:1", placement={"scale_factor": 0.9})
check("placement + ai → 400 (유지)", r.status_code == 400, f"{r.status_code}")
r = client.post("/generate/drafts", json={
    "mode": "text2img", "prompt": "p", "category": "food",
    "background_mode": "ai", "aspect_ratio": "3:1"})
check("비정사각 + text2img → 400 (유지)", r.status_code == 400, f"{r.status_code}")
r = drafts(aspect_ratio="16:9")
check("잘못된 enum → 422 (유지)", r.status_code == 422, f"{r.status_code}")

print("\n[6] resolve_ai_gen_size는 fail-closed")
for ratio, stage in (("3:4", "draft"), ("3:4", "refine"), ("3:1", "bogus")):
    try:
        layout.resolve_ai_gen_size(ratio, stage, (1024, 1024))
        check(f"{ratio}/{stage} → ValueError", False)
    except ValueError:
        check(f"{ratio}/{stage} → ValueError", True)
check("1:1은 최종 캔버스 그대로",
      layout.resolve_ai_gen_size("1:1", "draft", (768, 768)) == (768, 768))
check("None도 1:1로 취급",
      layout.resolve_ai_gen_size(None, "refine", (1024, 1024)) == (1024, 1024))

print("\n" + "=" * 60)
print(f"통과 {PASS} / 실패 {FAIL}")
sys.exit(1 if FAIL else 0)
