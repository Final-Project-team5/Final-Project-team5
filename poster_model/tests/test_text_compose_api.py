"""/compose/text — diffusion 없이 문구만 합성하는 경로 (GPU·rembg·모델 불필요).

이 엔드포인트는 diffusion을 타지 않으므로 파이프 스텁이 필요 없다. 실제 렌더링
코드를 그대로 돌린다.

확인 대상:
    1) 기본 동작 — 크기 보존, 문구가 실제로 그려짐, meta 형식이 refine과 호환
    2) 좌표 계약 — 1단계에서 확정한 "y=블록 중심, x=align 기준"
    3) ai_notice 순서 — 문구 뒤에 적용되어 가려지지 않음
    4) 오류 — 문구 없음 / behind / 잘못된 base64 / 스키마 위반
    5) 회귀 — /generate/refine과 TextSpec이 변하지 않음

실행 (프로젝트 루트에서):
    PYTHONPATH="$PWD" python tests/test_text_compose_api.py
"""
import base64
import contextlib
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

import api as api_module                                      # noqa: E402
from fastapi.testclient import TestClient                     # noqa: E402

client = TestClient(api_module.app)
PASS, FAIL = 0, 0
BG = (235, 232, 228)


@contextlib.contextmanager
def quiet():
    """폰트 fallback 경고로 출력이 묻히지 않게 한다."""
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


def b64(size=(1024, 1024), color=BG):
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


def decode(r):
    return Image.open(io.BytesIO(base64.b64decode(r.json()["image"])))


def compose(size=(1024, 1024), text=None, **extra):
    body = {"base_image": b64(size),
            "text": text or {"headline": "여름 한정 특가", "x": 0.5, "y": 0.5,
                             "align": "center", "style": "plain"},
            **extra}
    with quiet():
        return client.post("/compose/text", json=body)


def ink_box(img):
    a = np.array(img.convert("RGB"), np.int32)
    d = np.abs(a - np.array(BG, np.int32)).sum(2)
    ys, xs = np.where(d > 24)
    return (int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())) if len(xs) else None


print("\n[1] 기본 동작")
r = compose()
check("200 응답", r.status_code == 200, r.text[:200])
m = r.json()["meta"]
check("출력 크기 = base_image 크기", decode(r).size == (1024, 1024))
check("문구가 실제로 그려짐", ink_box(decode(r)) is not None)
check("meta.diffusion == false", m["diffusion"] is False)
check("meta.resolution = 짧은 변", m["resolution"] == 1024)
check("meta.canvas", m["canvas"] == {"width": 1024, "height": 1024})
check("meta.text / text_layers 존재", "text" in m and "text_layers" in m)
check("aspect_ratio·placement는 내리지 않음",
      "aspect_ratio" not in m and "placement" not in m, f"{sorted(m)}")

print("\n[1-1] 비율 무관하게 크기 보존")
for size in ((1024, 1024), (3072, 1024), (1024, 1368), (2304, 768)):
    r = compose(size)
    check(f"{size[0]}x{size[1]} 보존",
          r.status_code == 200 and decode(r).size == size,
          f"{decode(r).size if r.status_code == 200 else r.status_code}")
    check(f"{size[0]}x{size[1]} resolution = 짧은 변",
          r.json()["meta"]["resolution"] == min(size))

print("\n[1-2] meta.text 형식이 refine과 호환되는가")
r = compose(text={"headline": "여름 한정 특가", "sub": "지금 만나보세요",
                  "x": 0.5, "y": 0.5, "align": "center", "style": "plain"})
tm = r.json()["meta"]["text"]
for k in ("coord_mode", "y_anchor", "block_top_px", "block_height_px",
          "applied_headline_ratio", "applied_sub_ratio", "style"):
    check(f"meta.text.{k} 존재", k in tm)
tl = r.json()["meta"]["text_layers"]
check("text_layers에 headline·sub", set(tl) == {"headline", "sub"}, f"{sorted(tl)}")
for side in ("headline", "sub"):
    check(f"text_layers.{side} 키 구성",
          set(tl[side]) == {"z_order", "x", "y", "applied_size"}, f"{sorted(tl[side])}")
check("z_order는 front", tl["headline"]["z_order"] == "front")

print("\n[1-3] headline / sub 중 하나만 있어도 허용")
for text in ({"headline": "제목만", "x": 0.5, "y": 0.5, "align": "center"},
             {"sub": "보조만", "x": 0.5, "y": 0.5, "align": "center"}):
    r = compose(text={**text, "style": "plain"})
    only = "headline" if "headline" in text else "sub"
    check(f"{only}만 → 200", r.status_code == 200, r.text[:120])
    check(f"{only}만 → text_layers에 해당 항목만",
          set(r.json()["meta"]["text_layers"]) == {only})

print("\n[2] 좌표 계약 (1단계와 동일 기준)")
for size in ((1024, 1024), (3072, 1024)):
    for yv in (0.3, 0.5, 0.7):
        r = compose(size, text={"headline": "여름 한정 특가", "x": 0.5, "y": yv,
                                "align": "center", "style": "plain"})
        tm = r.json()["meta"]["text"]
        want = yv * size[1]
        got = tm["block_top_px"] + tm["block_height_px"] / 2
        check(f"{size[0]}x{size[1]} y={yv}: 블록 중심 = y*H",
              abs(got - want) < 2, f"{got:.0f} vs {want:.0f}")
        check(f"{size[0]}x{size[1]} y={yv}: y_anchor=center", tm["y_anchor"] == "center")

# 잉크 bbox로 재므로 AI 표시(우하단)를 꺼야 한다. 켜두면 표시까지 bbox에 들어간다.
r = compose(text={"headline": "테스트 문구", "x": 0.5, "y": 0.5,
                  "align": "center", "style": "plain"}, ai_notice=False)
b = ink_box(decode(r))
check("align=center: 잉크 가로 중심 ≈ x*W", abs((b[0] + b[2]) / 2 - 512) < 14,
      f"{(b[0]+b[2])/2:.0f}")
for align, want, idx in (("left", 512, 0), ("right", 512, 2)):
    rr = compose(text={"headline": "테스트 문구", "x": 0.5, "y": 0.5,
                       "align": align, "style": "plain"}, ai_notice=False)
    bb = ink_box(decode(rr))
    check(f"align={align}: x*W가 {'좌변' if align == 'left' else '우변'}",
          abs(bb[idx] - want) < 14, f"{bb[idx]}")

r = compose(text={"headline": "테스트", "x": 0.5, "position": "top", "style": "plain"})
check("x만 주면 프리셋 폴백", r.json()["meta"]["text"]["coord_mode"] is False)
check("폴백 시 y_anchor=position", r.json()["meta"]["text"]["y_anchor"] == "top")

print("\n[3] ai_notice")
r_on = compose(ai_notice=True)
r_off = compose(ai_notice=False)
check("기본값은 true", compose().json()["meta"]["ai_notice"] is True)
check("meta.ai_notice가 요청과 일치",
      r_on.json()["meta"]["ai_notice"] is True
      and r_off.json()["meta"]["ai_notice"] is False)
a_on = np.array(decode(r_on).convert("RGB"), np.int32)
a_off = np.array(decode(r_off).convert("RGB"), np.int32)
check("true일 때 이미지가 달라짐 (표시 추가)",
      int(np.abs(a_on - a_off).max()) > 0)
# 표시는 우하단. false 쪽에는 없어야 한다
H, W, _ = a_on.shape
corner_on = np.abs(a_on[int(H * 0.9):, int(W * 0.6):] - np.array(BG, np.int32)).sum(2)
corner_off = np.abs(a_off[int(H * 0.9):, int(W * 0.6):] - np.array(BG, np.int32)).sum(2)
check("표시가 우하단에 그려짐", (corner_on > 24).sum() > 0 and (corner_off > 24).sum() == 0,
      f"on {(corner_on>24).sum()}px / off {(corner_off>24).sum()}px")

# 문구를 우하단에 겹치게 두고 표시가 위에 오는지
r_overlap = compose(text={"headline": "겹침테스트", "x": 0.85, "y": 0.93,
                          "align": "center", "style": "plain"}, ai_notice=True)
r_plain = compose(text={"headline": "겹침테스트", "x": 0.85, "y": 0.93,
                        "align": "center", "style": "plain"}, ai_notice=False)
check("문구와 겹쳐도 표시가 마지막에 적용됨",
      int(np.abs(np.array(decode(r_overlap).convert("RGB"), np.int32)
                 - np.array(decode(r_plain).convert("RGB"), np.int32)).max()) > 0)

print("\n[4] 오류")
r = compose(text={"headline": "", "sub": "", "x": 0.5, "y": 0.5})
check("headline·sub 모두 빈 문자열 → 400", r.status_code == 400, f"{r.status_code}")
r = compose(text={"x": 0.5, "y": 0.5})
check("둘 다 생략(기본 빈 문자열) → 400", r.status_code == 400, f"{r.status_code}")

for field in ("headline_z_order", "sub_z_order"):
    r = compose(text={"headline": "제목", "sub": "보조", "x": 0.5, "y": 0.5,
                      "align": "center", "style": "plain", field: "behind"})
    check(f"{field}=behind → 400", r.status_code == 400, f"{r.status_code}")
    check(f"{field}=behind → error 코드",
          r.json()["detail"].get("error") == "text_behind_not_supported")
    check(f"{field}=behind → supported 안내",
          r.json()["detail"].get("supported") == ["front"])

with quiet():
    r = client.post("/compose/text", json={"base_image": "not-a-base64!!",
                                           "text": {"headline": "x"}})
check("깨진 base64 → 400", r.status_code == 400, f"{r.status_code}")
with quiet():
    r = client.post("/compose/text", json={"text": {"headline": "x"}})
check("base_image 누락 → 422", r.status_code == 422, f"{r.status_code}")
with quiet():
    r = client.post("/compose/text", json={"base_image": b64()})
check("text 누락 → 422", r.status_code == 422, f"{r.status_code}")

for bad, why in (({"headline": "x", "x": 1.5, "y": 0.5}, "x > 1"),
                 ({"headline": "x", "x": 0.5, "y": -0.1}, "y < 0"),
                 ({"headline": "x", "headline_size": 0}, "headline_size = 0"),
                 ({"headline": "x", "align": "middle"}, "align 오타"),
                 ({"headline": "x", "style": "box"}, "style 오타")):
    r = compose(text=bad)
    check(f"{why} → 422", r.status_code == 422, f"{r.status_code}")

print("\n[5] style=\"bar\"는 막지 않는다 (기본값이라 생략 시 적용됨)")
r_bar = compose(text={"headline": "여름 한정 특가", "x": 0.5, "y": 0.5,
                      "align": "center", "style": "bar"})
r_omit = compose(text={"headline": "여름 한정 특가", "x": 0.5, "y": 0.5,
                       "align": "center"})
check("style=bar → 200", r_bar.status_code == 200)
check("style 생략 시 bar가 적용됨",
      r_omit.json()["meta"]["text"]["style"] == "bar")
check("bar와 plain 결과가 다름",
      int(np.abs(np.array(decode(r_bar).convert("RGB"), np.int32)
                 - np.array(decode(compose()).convert("RGB"), np.int32)).max()) > 0)

print("\n[5-1] sub_x/sub_y — 실제 적용값이 meta에 기록되는가")
r = compose(text={"headline": "제목", "sub": "보조", "x": 0.3, "y": 0.4,
                  "sub_x": 0.8, "sub_y": 0.9, "align": "center", "style": "plain"})
check("200 (조합 자체는 허용)", r.status_code == 200, r.text[:160])
sub = r.json()["meta"]["text_layers"]["sub"]
check("sub 좌표가 실제 사용값 x/y로 기록",
      sub["x"] == 0.3 and sub["y"] == 0.4, f"{sub}")
check("sub_x/sub_y가 그대로 새어나오지 않음",
      sub["x"] != 0.8 and sub["y"] != 0.9)
check("meta.ignored_fields에 두 필드 기록",
      r.json()["meta"].get("ignored_fields") == ["sub_x", "sub_y"],
      r.json()["meta"].get("ignored_fields"))

for extra_kw, want in (({"sub_x": 0.8}, ["sub_x"]),
                       ({"sub_y": 0.9}, ["sub_y"]),
                       ({}, None)):
    rr = compose(text={"headline": "제목", "sub": "보조", "x": 0.3, "y": 0.4,
                       "align": "center", "style": "plain", **extra_kw})
    got = rr.json()["meta"].get("ignored_fields")
    check(f"{extra_kw or '없음'} → ignored_fields={want}", got == want, f"{got}")

rr = compose(text={"headline": "제목만", "x": 0.3, "y": 0.4, "align": "center",
                   "style": "plain", "sub_x": 0.8})
check("sub가 없어도 sub_x는 무시로 기록",
      rr.json()["meta"].get("ignored_fields") == ["sub_x"],
      rr.json()["meta"].get("ignored_fields"))
check("refine과 같은 기준인지 (helper 공유)",
      "_ignored_fields(spec)" in (ROOT / "api.py").read_text(encoding="utf-8")
      and "_ignored_fields(req.text)" in (ROOT / "api.py").read_text(encoding="utf-8"))

print("\n[6] 회귀 — 기존 계약 무변경")
src = (ROOT / "api.py").read_text(encoding="utf-8")
i = src.index("class TextSpec(")
block = src[i:src.index("class ", i + 10)]
fields = {l.strip().split(":")[0] for l in block.splitlines()
          if l.startswith("    ") and ": " in l and "=" in l
          and not l.strip().startswith("#")}
# font_id는 A6에서 의도적으로 추가한 필드다(프론트가 폰트를 하나 골라 headline·sub에
# 공통 적용). 가드 자체는 유지한다 — 이후 무단 필드 추가를 계속 막기 위해서다.
check("TextSpec 필드 목록 = 기존 13개 + font_id",
      fields == {"headline", "sub", "x", "y", "position", "align", "style",
                 "headline_size", "sub_size", "headline_z_order", "sub_z_order",
                 "sub_x", "sub_y", "font_id"}, f"{sorted(fields)}")
check("refine 핸들러가 _render_text_layers를 계속 사용",
      "_render_text_layers(req.text, result)" in src)
check("compose는 _render_text_layers를 쓰지 않음",
      "_render_text_layers" not in src[src.index("def compose_text("):])
check("/generate/refine 엔드포인트 유지", '@app.post("/generate/refine"' in src)
check("/compose/text 엔드포인트 추가", '@app.post("/compose/text"' in src)

print("\n" + "=" * 60)
print(f"통과 {PASS} / 실패 {FAIL}")
sys.exit(1 if FAIL else 0)
