"""text.tone — 타이포 프리셋을 API에 배선 (GPU·모델 불필요).

config.TONE_PRESETS는 이미 있었지만 API가 쓰지 않았다. 그래서 프리셋 5개 값 중
headline_size / sub_size 두 개만 전달되고, 두 톤을 실제로 가르는
stroke_width / fill_color / headline_font_role이 렌더러까지 가지 않았다.
verification 스크립트는 TONE_PRESETS를 직접 읽어 프리셋대로 그리는데,
실제 API 경로에서만 그 효과가 빠져 있었다.

확인 대상:
    1) tone 미지정 — render_text 현재 기본값이 그대로 쓰여 기존 렌더 동작 유지
    2) minimal_product / bold_promo — 5개 값이 정확히 전달
    3) 개별 필드가 프리셋을 이긴다 (프론트 미리보기와 어긋나면 안 된다)
    4) 알 수 없는 tone → 400 unknown_tone (silent fallback 없음)
    5) /generate/refine · /compose/text 두 경로 모두
    6) 검증이 diffusion **전에** 일어난다
    7) font_id 우선순위 유지
    8) 스키마 — TextSpec에 tone만 추가됨

실행 (프로젝트 루트에서):
    PYTHONPATH="$PWD" python tests/test_tone_preset.py
"""
import ast
import base64
import io
import sys
import types
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

sys.modules["torch"] = types.ModuleType("torch")
sys.modules["diffusers"] = types.ModuleType("diffusers")

import api as api_module                                      # noqa: E402
from pipeline import config, overlay                          # noqa: E402
from fastapi.testclient import TestClient                     # noqa: E402

client = TestClient(api_module.app)
PASS, FAIL = 0, 0


def ck(cond, label, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS  {label}")
    else:
        FAIL += 1
        print(f"  ★FAIL {label}   {detail}")


def section(t):
    print(f"\n{'─' * 70}\n{t}\n{'─' * 70}")


def b64_png(size=(512, 512), color=(240, 240, 240)):
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


BASE_IMG = b64_png()
TEXT = {"headline": "진하고 부드러운", "sub": "오늘만 20%"}


def spec_of(**kw):
    """TextSpec 인스턴스. _tone_kwargs를 직접 부르기 위한 것."""
    return api_module.TextSpec(**{**TEXT, **kw})


# ══════════════════════════════════════════════════════════════════════
section("§1  tone 미지정 — render_text 현재 기본값이 그대로 쓰인다")
# ══════════════════════════════════════════════════════════════════════
# render_text의 실제 기본값을 서명에서 읽어 온다. 손으로 적어 두면 기본값이
# 바뀌었을 때 이 테스트가 거짓으로 통과한다.
import inspect                                                # noqa: E402

sig = inspect.signature(overlay.render_text)
defaults = {n: p.default for n, p in sig.parameters.items()}

kw = api_module._tone_kwargs(spec_of())
ck(kw["headline_font_role"] == defaults["headline_font_role"],
   f"headline_font_role == render_text 기본값({defaults['headline_font_role']!r})",
   repr(kw["headline_font_role"]))
ck(kw["stroke_width"] == defaults["stroke_width"],
   "stroke_width == render_text 기본값(None)", repr(kw["stroke_width"]))
ck(kw["fill_color"] == defaults["fill_color"],
   "fill_color == render_text 기본값(None)", repr(kw["fill_color"]))
ck(kw["headline_size"] is None and kw["sub_size"] is None,
   "size는 요청값 그대로(None)", str((kw["headline_size"], kw["sub_size"])))

# 요청이 size를 줬고 tone은 없을 때 — 종전과 같이 그 값이 그대로 간다
kw2 = api_module._tone_kwargs(spec_of(headline_size=0.09, sub_size=0.03))
ck(kw2["headline_size"] == 0.09 and kw2["sub_size"] == 0.03,
   "tone 없이 size만 주면 그 값이 그대로", str(kw2))
ck(kw2["stroke_width"] is None and kw2["fill_color"] is None,
   "그때도 나머지는 기본값")


# ══════════════════════════════════════════════════════════════════════
section("§2  프리셋 2종 — 5개 값이 정확히 전달")
# ══════════════════════════════════════════════════════════════════════
for name in ("minimal_product", "bold_promo"):
    preset = config.TONE_PRESETS[name]
    kw = api_module._tone_kwargs(spec_of(tone=name))
    for key in ("headline_size", "sub_size", "headline_font_role",
                "stroke_width", "fill_color"):
        ck(kw[key] == preset[key], f"{name}.{key} == {preset[key]!r}",
           repr(kw[key]))

# 두 톤이 실제로 갈리는 3개 값이 서로 다른지 — 이게 이번 배선의 목적이다
a = api_module._tone_kwargs(spec_of(tone="minimal_product"))
b = api_module._tone_kwargs(spec_of(tone="bold_promo"))
for key in ("headline_font_role", "stroke_width", "fill_color"):
    ck(a[key] != b[key], f"★ 두 톤의 {key}가 서로 다르다",
       f"{a[key]!r} vs {b[key]!r}")


# ══════════════════════════════════════════════════════════════════════
section("§3  개별 필드가 프리셋을 이긴다")
# ══════════════════════════════════════════════════════════════════════
kw = api_module._tone_kwargs(spec_of(tone="bold_promo", headline_size=0.07))
ck(kw["headline_size"] == 0.07,
   "명시 headline_size가 프리셋(0.22)을 이긴다", str(kw["headline_size"]))
ck(kw["sub_size"] == config.TONE_PRESETS["bold_promo"]["sub_size"],
   "안 준 sub_size는 프리셋 값", str(kw["sub_size"]))
ck(kw["stroke_width"] == config.TONE_PRESETS["bold_promo"]["stroke_width"],
   "size를 덮어도 나머지 프리셋 값은 유지")

kw = api_module._tone_kwargs(spec_of(tone="minimal_product",
                                     headline_size=0.2, sub_size=0.05))
ck(kw["headline_size"] == 0.2 and kw["sub_size"] == 0.05,
   "두 size 모두 명시하면 둘 다 이긴다", str(kw))


# ══════════════════════════════════════════════════════════════════════
section("§4  알 수 없는 tone → 400 unknown_tone")
# ══════════════════════════════════════════════════════════════════════
r = client.post("/compose/text", json={
    "base_image": BASE_IMG, "text": {**TEXT, "tone": "no_such_tone"}})
ck(r.status_code == 400, "400", str(r.status_code))
d = r.json().get("detail", {})
ck(d.get("code") == "unknown_tone", "code == unknown_tone", str(d))
ck(sorted(d.get("supported", [])) == sorted(config.TONE_PRESETS),
   "supported에 실제 프리셋 목록", str(d.get("supported")))
ck("no_such_tone" in d.get("message", ""), "message에 받은 값이 들어간다", str(d))

# 빈 문자열은 미지정과 같게 본다(falsy) — 400이 아니다
r = client.post("/compose/text", json={
    "base_image": BASE_IMG, "text": {**TEXT, "tone": ""}})
ck(r.status_code == 200, "빈 문자열 tone은 미지정 취급 → 200", str(r.status_code))


# ══════════════════════════════════════════════════════════════════════
section("§5  /compose/text 실제 렌더 — 두 톤이 다른 결과를 낸다")
# ══════════════════════════════════════════════════════════════════════
imgs = {}
for name in (None, "minimal_product", "bold_promo"):
    body = {"base_image": BASE_IMG, "text": dict(TEXT), "ai_notice": False}
    if name:
        body["text"]["tone"] = name
    r = client.post("/compose/text", json=body)
    ck(r.status_code == 200, f"tone={name} → 200", str(r.status_code))
    if r.status_code == 200:
        imgs[name] = r.json()["image"]

if len(imgs) == 3:
    ck(imgs["minimal_product"] != imgs["bold_promo"],
       "★ 두 프리셋의 렌더 결과가 실제로 다르다")
    ck(imgs[None] != imgs["minimal_product"],
       "★ tone 지정과 미지정이 다르다 (프리셋이 실제로 먹는다)")


# ══════════════════════════════════════════════════════════════════════
section("§6  검증이 diffusion 전에 일어난다 (/generate/refine)")
# ══════════════════════════════════════════════════════════════════════
called = []
orig_refine = api_module.pipeline.refine


def spy(*a, **k):
    called.append(1)
    raise AssertionError("diffusion이 호출됐다 — 검증이 늦었다")


api_module.pipeline.refine = spy
try:
    r = client.post("/generate/refine", json={
        "draft_image": BASE_IMG,
        "text": {**TEXT, "tone": "no_such_tone"}})
    ck(r.status_code == 400, "/generate/refine 잘못된 tone → 400",
       str(r.status_code))
    ck(r.json().get("detail", {}).get("code") == "unknown_tone",
       "code == unknown_tone", str(r.json())[:200])
    ck(not called, "★ pipeline.refine이 호출되지 않았다 (GPU 시간 낭비 없음)",
       f"called={len(called)}")
finally:
    api_module.pipeline.refine = orig_refine


# ══════════════════════════════════════════════════════════════════════
section("§7  font_id 우선순위 유지")
# ══════════════════════════════════════════════════════════════════════
# _tone_kwargs는 headline_font_role만 정하고 font_id는 건드리지 않는다.
# 실제 우선순위(font_id > role)는 render_text 안에 있고, 이 PR은 그 규칙을
# 바꾸지 않는다. 여기서는 배선이 font_id를 가리지 않는지만 본다.
kw = api_module._tone_kwargs(spec_of(tone="minimal_product", font_id="pretendard"))
ck("font_id" not in kw, "_tone_kwargs가 font_id를 만들지 않는다", str(kw.keys()))
ck(kw["headline_font_role"] == "body_medium",
   "role은 프리셋대로", str(kw["headline_font_role"]))

src = (ROOT / "api.py").read_text(encoding="utf-8")
tree = ast.parse(src)
calls = [n for n in ast.walk(tree)
         if isinstance(n, ast.Call)
         and getattr(n.func, "attr", "") == "render_text"]
ck(len(calls) == 2, f"render_text 호출 2곳", str(len(calls)))
for c in calls:
    names = {k.arg for k in c.keywords}
    ck("font_id" in names, "호출부가 font_id를 그대로 넘긴다", str(names))
    ck(None in names or any(k.arg is None for k in c.keywords),
       "호출부가 **_tone_kwargs(...)를 넘긴다", str(names))
    ck("headline_size" not in names and "sub_size" not in names,
       "size는 _tone_kwargs로 흡수됐다 (중복 인자 없음)", str(names))


# ══════════════════════════════════════════════════════════════════════
section("§8  스키마 — TextSpec에 tone만 추가됐다")
# ══════════════════════════════════════════════════════════════════════
fields = api_module.TextSpec.model_fields
ck("tone" in fields, "TextSpec.tone 존재")
ck(fields["tone"].default is None, "기본값 None", str(fields["tone"].default))
expected = {"headline", "sub", "x", "y", "position", "align", "style",
            "headline_size", "sub_size", "headline_z_order", "sub_z_order",
            "sub_x", "sub_y", "font_id", "tone"}
ck(set(fields) == expected, "다른 필드가 늘거나 줄지 않았다",
   str(set(fields) ^ expected))

# 응답 계약은 넓히지 않았다
r = client.post("/compose/text", json={"base_image": BASE_IMG,
                                       "text": {**TEXT, "tone": "bold_promo"}})
if r.status_code == 200:
    meta = r.json()["meta"]
    ck("warnings" not in meta,
       "meta에 warnings를 새로 만들지 않았다 (_tone_warnings는 이번 범위 밖)",
       str(list(meta)))


# ══════════════════════════════════════════════════════════════════════
print(f"\n{'═' * 70}")
print(f"PASS {PASS} · FAIL {FAIL} · 판정 {'PASS' if not FAIL else '★ FAIL'}")
print("═" * 70)
print("""
★ 이번 범위 밖 (알려진 검증 공백)
   text.tone × 3:1 / 3:4 조합의 시각 회귀는 수행하지 않았다.
   _tone_warnings(미검증 조합 경고)도 이번 배선에 포함하지 않았다.
""")
sys.exit(1 if FAIL else 0)
