"""GPU 없이 api.py의 z_order 분기/스키마 배선만 검증 (pipeline은 스텁).

실행 (프로젝트 루트에서):
    PYTHONPATH="$PWD" python tests/test_zorder_api.py
"""
import base64, io, sys, types
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]   # tests/ -> 프로젝트 루트

# --- pipeline 스텁: 실제 overlay.render_text와 composite_product는 진짜를 쓴다 ---
sys.modules["torch"] = types.ModuleType("torch")
sys.modules["diffusers"] = types.ModuleType("diffusers")

import importlib.util
def load_real(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod

pkg = types.ModuleType("pipeline")
pkg.__path__ = [str(ROOT / "pipeline")]
sys.modules["pipeline"] = pkg
real_config = load_real("pipeline.config", ROOT / "pipeline" / "config.py")
pkg.config = real_config
real_masking = load_real("pipeline.masking", ROOT / "pipeline" / "masking.py")
real_overlay = load_real("pipeline.overlay", ROOT / "pipeline" / "overlay.py")

SIZE = 256
CALLS = {"render_text": 0, "composite_product": 0, "ai_notice": 0}

def spy_render_text(*a, **kw):
    CALLS["render_text"] += 1
    return real_overlay.render_text(*a, **kw)

def spy_composite_product(*a, **kw):
    CALLS["composite_product"] += 1
    return real_masking.composite_product(*a, **kw)

def spy_ai_notice(img, text="AI 생성 이미지"):
    CALLS["ai_notice"] += 1
    return real_overlay.add_ai_notice(img, text)

pkg.render_text = spy_render_text
pkg.composite_product = spy_composite_product
pkg.add_ai_notice = spy_ai_notice
pkg.warmup = lambda: None
pkg.unload = lambda: None
pkg.generate_drafts = lambda **kw: {"images": [], "seeds": [], "backgrounds": [], "meta": {}}

_mask = Image.new("L", (SIZE, SIZE), 0)
from PIL import ImageDraw
ImageDraw.Draw(_mask).rectangle([60, 100, 200, 230], fill=255)

REFINE_RESULT = {}
def fake_refine(draft, original=None, prompt=None, category=None, background=None, strength=None):
    return dict(REFINE_RESULT)
pkg.refine = fake_refine

sys.path.insert(0, str(ROOT))
import api as api_module
from fastapi.testclient import TestClient
client = TestClient(api_module.app)

def b64(img):
    buf = io.BytesIO(); img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()

IMG = b64(Image.new("RGB", (SIZE, SIZE), "white"))

def set_result(with_behind_support=True):
    REFINE_RESULT.clear()
    REFINE_RESULT.update({
        "image": Image.new("RGB", (SIZE, SIZE), (240, 235, 220)),
        "pre_product": Image.new("RGB", (SIZE, SIZE), (240, 235, 220)) if with_behind_support else None,
        "base": Image.new("RGB", (SIZE, SIZE), (150, 200, 120)) if with_behind_support else None,
        "product_mask": _mask if with_behind_support else None,
        "meta": {"model": None, "resolution": SIZE, "layout": {"bbox_h_ratio": 0.5}},
    })

def post(text=None, ai_notice=False, original=True):
    body = {"draft_image": IMG, "ai_notice": ai_notice}
    if original:
        body["original_image"] = IMG
    if text is not None:
        body["text"] = text
    return client.post("/generate/refine", json=body)

BASE_TEXT = {"headline": "MELON KICK", "sub": "달콤하고 바삭한 한입",
             "x": 0.5, "y": 0.05, "align": "center", "style": "plain",
             "headline_size": 0.16, "sub_size": 0.05}

fails = []
def check(name, cond, detail=""):
    if cond:
        print(f"  PASS  {name}")
    else:
        print(f"  FAIL  {name}  {detail}")
        fails.append(name)

print("\n[1] 하위호환: z_order 필드 미전송 (기존 클라이언트)")
set_result(); CALLS.update({k: 0 for k in CALLS})
r = post({"headline": "제목", "sub": "부제", "position": "top", "style": "bar"})
check("200 응답", r.status_code == 200, r.text[:200])
m = r.json()["meta"]
check("render_text 1회만 호출(단일 경로)", CALLS["render_text"] == 1, CALLS)
check("composite_product 미호출", CALLS["composite_product"] == 0, CALLS)
check("meta.text 는 기존 단일 dict", isinstance(m.get("text"), dict) and "applied_headline_px" in m["text"])
check("meta.text_layers 추가됨", "headline" in m.get("text_layers", {}) and "sub" in m["text_layers"])
check("layers z_order 기본 front",
      m["text_layers"]["headline"]["z_order"] == "front" and m["text_layers"]["sub"]["z_order"] == "front")

print("\n[2] front/front 명시")
set_result(); CALLS.update({k: 0 for k in CALLS})
r = post({**BASE_TEXT, "headline_z_order": "front", "sub_z_order": "front"})
check("200", r.status_code == 200, r.text[:200])
check("render_text 1회(기존 경로 유지)", CALLS["render_text"] == 1, CALLS)
check("composite_product 미호출", CALLS["composite_product"] == 0, CALLS)

print("\n[3] behind/front (이번 핵심 요구사항)")
set_result(); CALLS.update({k: 0 for k in CALLS})
r = post({**BASE_TEXT, "headline_z_order": "behind", "sub_z_order": "front",
          "sub_x": 0.5, "sub_y": 0.88})
check("200", r.status_code == 200, r.text[:300])
check("render_text 2회(레이어 분리)", CALLS["render_text"] == 2, CALLS)
check("composite_product 1회(제품이 headline 가림)", CALLS["composite_product"] == 1, CALLS)
m = r.json()["meta"]
check("meta.text 여전히 단일 dict", isinstance(m["text"], dict) and "applied_headline_px" in m["text"])
check("headline z_order=behind 기록", m["text_layers"]["headline"]["z_order"] == "behind")
check("sub z_order=front 기록", m["text_layers"]["sub"]["z_order"] == "front")
check("sub 좌표는 sub_x/sub_y 반영", m["text_layers"]["sub"]["y"] == 0.88, m["text_layers"]["sub"])
check("applied_sub_ratio 채워짐", m["text"].get("applied_sub_ratio") is not None, m["text"])

print("\n[4] front/behind (반대 조합)")
set_result(); CALLS.update({k: 0 for k in CALLS})
r = post({**BASE_TEXT, "headline_z_order": "front", "sub_z_order": "behind",
          "sub_x": 0.5, "sub_y": 0.6})
check("200", r.status_code == 200, r.text[:300])
check("render_text 2회", CALLS["render_text"] == 2, CALLS)
check("composite_product 1회", CALLS["composite_product"] == 1, CALLS)
m = r.json()["meta"]
check("headline front / sub behind 기록",
      m["text_layers"]["headline"]["z_order"] == "front" and m["text_layers"]["sub"]["z_order"] == "behind")

print("\n[5] behind/behind (둘 다 뒤 — 단일 호출이라 bar 허용)")
set_result(); CALLS.update({k: 0 for k in CALLS})
r = post({**BASE_TEXT, "headline_z_order": "behind", "sub_z_order": "behind", "style": "bar"})
check("200 (bar 허용)", r.status_code == 200, r.text[:300])
check("render_text 1회(단일 호출)", CALLS["render_text"] == 1, CALLS)
check("composite_product 1회", CALLS["composite_product"] == 1, CALLS)

print("\n[6] validation: 원본/마스크 없는 경로에서 behind 요청")
set_result(with_behind_support=False)
r = post({**BASE_TEXT, "headline_z_order": "behind", "sub_z_order": "behind"})
check("400 반환", r.status_code == 400, f"{r.status_code} {r.text[:200]}")
check("에러 메시지에 original_image 언급", "original_image" in r.text)

print("\n[7] validation: z_order 다른데 style=bar")
set_result()
r = post({**BASE_TEXT, "headline_z_order": "behind", "sub_z_order": "front",
          "style": "bar", "sub_x": 0.5, "sub_y": 0.88})
check("400 반환", r.status_code == 400, f"{r.status_code} {r.text[:200]}")
check("에러 메시지에 plain 안내", "plain" in r.text)

print("\n[8] validation: z_order 다른데 sub 좌표 누락")
set_result()
r = post({**BASE_TEXT, "headline_z_order": "behind", "sub_z_order": "front"})
check("400 반환", r.status_code == 400, f"{r.status_code} {r.text[:200]}")
check("에러 메시지에 sub_x/sub_y 안내", "sub_x" in r.text)

print("\n[9] AI 표시는 마지막에 한 번만")
set_result(); CALLS.update({k: 0 for k in CALLS})
r = post({**BASE_TEXT, "headline_z_order": "behind", "sub_z_order": "front",
          "sub_x": 0.5, "sub_y": 0.88}, ai_notice=True)
check("200", r.status_code == 200, r.text[:200])
check("add_ai_notice 정확히 1회", CALLS["ai_notice"] == 1, CALLS)

print("\n[10] headline만 / sub만 있는 경우")
set_result(); CALLS.update({k: 0 for k in CALLS})
r = post({"headline": "제목만", "x": 0.5, "y": 0.1, "align": "center",
          "style": "plain", "headline_z_order": "behind"})
check("headline만 behind: 200", r.status_code == 200, r.text[:300])
check("render_text 1회", CALLS["render_text"] == 1, CALLS)
check("sub 레이어 없음", "sub" not in r.json()["meta"]["text_layers"])

set_result(); CALLS.update({k: 0 for k in CALLS})
r = post({"sub": "부제만", "x": 0.5, "y": 0.8, "align": "center",
          "style": "plain", "sub_z_order": "behind"})
check("sub만 behind: 200", r.status_code == 200, r.text[:300])
check("headline 레이어 없음", "headline" not in r.json()["meta"]["text_layers"])

print("\n[11] render_text 인터페이스 유지 확인 (시그니처에 z_order 인자 없음)")
import inspect
sig = inspect.signature(real_overlay.render_text)
check("render_text에 z_order 관련 인자 없음",
      not any("z_order" in p for p in sig.parameters), list(sig.parameters))

print("\n" + "=" * 50)
if fails:
    print(f"실패 {len(fails)}건: {fails}")
    sys.exit(1)
print("ALL_TESTS_PASSED")
