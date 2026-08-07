"""배경 색상 validation 검증 (GPU·모델·서버 불필요).

pipeline을 스텁으로 대체해 모델을 전혀 실행하지 않고, api.py의 조건부 validation만
확인한다. 검증 대상은 `_validate_background_colors()`와 그 호출부다.

배경:
    BackgroundSpec.colors의 기본값이 []여서, refine 요청에 mode만 solid로 주고
    colors를 빠뜨리면 스키마 검증은 통과하지만 render_flat_background()의
    colors[0]에서 IndexError가 나 500으로 떨어졌다. 그 경로를 400으로 막았는지 본다.

실행 (poster_model 디렉터리에서):
    PYTHONPATH="$PWD" python tests/test_background_validation.py
"""
import base64
import io
import sys
import types
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]   # tests/ -> 프로젝트 루트

# --- pipeline 스텁: 모델을 로드하지 않는다 ---
sys.modules["torch"] = types.ModuleType("torch")
sys.modules["diffusers"] = types.ModuleType("diffusers")

CALLS = {"drafts": 0, "refine": 0}
SIZE = 64

pkg = types.ModuleType("pipeline")
pkg.__path__ = [str(ROOT / "pipeline")]
pkg.config = types.SimpleNamespace(DRAFT_MODEL="sd15", REFINE_MODEL="sdxl")


def _fake_drafts(**kwargs):
    CALLS["drafts"] += 1
    return {"images": [Image.new("RGB", (SIZE, SIZE), "white")],
            "seeds": [0], "backgrounds": [None], "meta": {}}


def _fake_refine(draft, original=None, prompt=None, category=None,
                 background=None, strength=None):
    CALLS["refine"] += 1
    return {"image": draft, "pre_product": None, "base": None,
            "product_mask": None, "meta": {}}


pkg.generate_drafts = _fake_drafts
pkg.refine = _fake_refine
pkg.render_text = lambda *a, **k: (a[0], {}) if k.get("return_meta") else a[0]
pkg.add_ai_notice = lambda img, text="AI 생성 이미지": img
pkg.composite_product = lambda *a, **k: a[0]
pkg.warmup = lambda: None
pkg.unload = lambda: None
sys.modules["pipeline"] = pkg

sys.path.insert(0, str(ROOT))
import api as api_module                                    # noqa: E402
from fastapi.testclient import TestClient                   # noqa: E402

client = TestClient(api_module.app)

buf = io.BytesIO()
Image.new("RGB", (SIZE, SIZE), "white").save(buf, format="PNG")
IMG = base64.b64encode(buf.getvalue()).decode()

fails = []


def check(name, cond, detail=""):
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"   {detail}" if not cond else ""))
    if not cond:
        fails.append(name)


def drafts(background_mode, bg_colors=..., **extra):
    body = {"mode": "inpaint", "image": IMG, "category": "beauty",
            "background_mode": background_mode, **extra}
    if bg_colors is not ...:
        body["bg_colors"] = bg_colors
    return client.post("/generate/drafts", json=body)


def refine(background=None):
    body = {"draft_image": IMG, "original_image": IMG,
            "category": "beauty", "ai_notice": False}
    if background is not None:
        body["background"] = background
    return client.post("/generate/refine", json=body)


print("\n[1] drafts + solid + 빈 bg_colors -> 400")
before = CALLS["drafts"]
r = drafts("solid", [])
check("400 반환", r.status_code == 400, f"{r.status_code} {r.text[:150]}")
check("메시지에 bg_colors 최소 1개 안내", "bg_colors가 최소 1개" in r.text, r.text[:150])
check("처리 함수 호출 전에 차단", CALLS["drafts"] == before, f"generate_drafts 호출됨")

print("\n[2] drafts + gradient + 빈 bg_colors -> 400")
before = CALLS["drafts"]
r = drafts("gradient", [])
check("400 반환", r.status_code == 400, f"{r.status_code} {r.text[:150]}")
check("처리 함수 호출 전에 차단", CALLS["drafts"] == before)

print("\n[3] refine + solid + 빈 background.colors -> 400")
before = CALLS["refine"]
r = refine({"mode": "solid", "colors": [], "direction": None})
check("400 반환", r.status_code == 400, f"{r.status_code} {r.text[:150]}")
check("메시지에 background.colors 안내", "background.colors가 최소 1개" in r.text, r.text[:150])
check("처리 함수 호출 전에 차단", CALLS["refine"] == before)

print("\n[4] refine + gradient + 빈 background.colors -> 400")
before = CALLS["refine"]
r = refine({"mode": "gradient", "colors": [], "direction": "vertical"})
check("400 반환", r.status_code == 400, f"{r.status_code} {r.text[:150]}")
check("처리 함수 호출 전에 차단", CALLS["refine"] == before)

print("\n[4-1] refine + solid + colors 필드 자체를 생략 -> 400 (기본값이 []라 같은 경로)")
r = refine({"mode": "solid"})
check("400 반환", r.status_code == 400, f"{r.status_code} {r.text[:150]}")

print("\n[5] ai 모드 + 빈 색상 배열 -> 색상 validation 통과")
r = drafts("ai", [])
check("drafts ai + [] : 200", r.status_code == 200, f"{r.status_code} {r.text[:150]}")
r = refine({"mode": "ai", "colors": [], "direction": None})
check("refine ai + [] : 200", r.status_code == 200, f"{r.status_code} {r.text[:150]}")

print("\n[6] 색상 1개 -> 기존 동작 유지")
r = drafts("solid", ["#AABBCC"])
check("drafts solid 1개 : 200", r.status_code == 200, f"{r.status_code} {r.text[:150]}")
r = refine({"mode": "solid", "colors": ["#AABBCC"], "direction": None})
check("refine solid 1개 : 200", r.status_code == 200, f"{r.status_code} {r.text[:150]}")
r = drafts("gradient", ["#AABBCC", "#112233"])
check("drafts gradient 2개 : 200", r.status_code == 200, f"{r.status_code} {r.text[:150]}")

print("\n[7] 잘못된 HEX -> 기존 오류 유지")
r = drafts("solid", ["not-a-color"])
check("400 반환", r.status_code == 400, f"{r.status_code} {r.text[:150]}")
check("형식 오류 메시지 유지", "#RRGGBB 형식" in r.text, r.text[:150])
r = refine({"mode": "solid", "colors": ["#GGGGGG"], "direction": None})
check("refine 형식 오류 400", r.status_code == 400 and "#RRGGBB 형식" in r.text,
      f"{r.status_code} {r.text[:150]}")

print("\n[8] bg_colors 미지정(None) -> 팔레트 폴백 경로 유지")
r = drafts("solid")
check("drafts solid 미지정 : 200", r.status_code == 200, f"{r.status_code} {r.text[:150]}")

print("\n" + "=" * 50)
if fails:
    print(f"실패 {len(fails)}건: {fails}")
    sys.exit(1)
print("ALL_TESTS_PASSED")
