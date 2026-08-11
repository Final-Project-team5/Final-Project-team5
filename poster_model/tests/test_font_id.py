"""font_id — 사용자가 고른 폰트를 headline/sub에 공통 적용 (GPU·모델 불필요).

프론트 계약(PR #38): 폰트를 **하나만** 고르고, 그 하나를 headline과 sub에 같이 쓴다.
그래서 headline_font_id / sub_font_id로 나누지 않고 text.font_id 하나만 받는다.

확인 대상:
    1) whitelist — 5종 ID와 PR #27 기준 예상 경로 매핑
    2) resolve — 현재 있는 자산은 정상 해석 / 없는 자산은 font_asset_missing
    3) 400 — 미지원 ID, 자산 없는 ID, 빈 문자열. silent fallback 없음
    4) 렌더링 — font_id 지정 시 headline과 sub가 **같은 파일**로 그려짐
    5) 회귀 — font_id 미전달 결과가 변경 전 overlay와 **픽셀 동일**
    6) 스키마 — TextSpec에 font_id만 추가됨

주의: 지금 작업 브랜치에는 GmarketSans/Galmuri11/NanumPen 자산이 없다.
"5종 경로가 모두 실제 존재"는 **이 단계의 성공 조건이 아니다**. PR #27 자산이
병합된 뒤 아래 PENDING_AFTER_MERGE 항목을 성공 조건으로 올린다.

실행 (프로젝트 루트에서):
    PYTHONPATH="$PWD" python tests/test_font_id.py
"""
import base64
import contextlib
import ast
import importlib.util
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
from pipeline import config, overlay                          # noqa: E402
from fastapi.testclient import TestClient                     # noqa: E402

client = TestClient(api_module.app)
PASS, FAIL = 0, 0
BG = (235, 232, 228)

# 프론트가 실제로 보내는 5종. 문자열이 바뀌면 클라이언트 저장값이 깨진다.
FRONT_IDS = ["pretendard", "nanummyeongjo", "gmarketsans", "galmuri11", "nanumpen"]
EXPECTED_PATHS = {
    "pretendard": "assets/fonts/Pretendard/Pretendard-Regular.ttf",
    "nanummyeongjo": "assets/fonts/NanumMyeongjo/NanumMyeongjoBold.ttf",
    "gmarketsans": "assets/fonts/GmarketSans/GmarketSansTTFMedium.ttf",
    "galmuri11": "assets/fonts/Galmuri11/Galmuri11.ttf",
    "nanumpen": "assets/fonts/NanumPen/NanumPen.ttf",
}


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


def b64(size=(1024, 1024), color=BG):
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


def compose(text, size=(1024, 1024), **extra):
    with quiet():
        return client.post("/compose/text",
                           json={"base_image": b64(size), "text": text, **extra})


TEXT = {"headline": "여름 한정 특가", "sub": "오늘 하루만 20% 할인",
        "x": 0.5, "y": 0.5, "align": "center", "style": "plain"}

# 현재 브랜치에 자산이 있는 것 / 없는 것
HAVE = config.available_font_ids()
MISSING = [f for f in FRONT_IDS if f not in HAVE]


# ---------------------------------------------------------------------------
print("\n[1] whitelist 매핑")

check("5종 ID가 모두 등록됨", set(config.FONT_IDS) == set(FRONT_IDS),
      f"{sorted(config.FONT_IDS)}")
check("등록 순서가 프론트 목록과 같음", list(config.FONT_IDS) == FRONT_IDS)
for fid in FRONT_IDS:
    rel = Path(config.FONT_IDS[fid]).relative_to(ROOT).as_posix()
    check(f"{fid} 경로 = PR #27 기준", rel == EXPECTED_PATHS[fid], rel)
check("ID에 구분자/대문자 없음", all(f.islower() and f.isalnum() for f in config.FONT_IDS))
check("역할 기반 FONTS와 별개 테이블", "font_id" not in config.FONTS
      and set(config.FONTS) == {"headline", "body", "body_medium", "elegant", "accent"})

print(f"\n     현재 자산 있음: {HAVE}")
print(f"     현재 자산 없음: {MISSING}  ← PR #27 병합 대상")


# ---------------------------------------------------------------------------
print("\n[2] resolve — 있는 자산 / 없는 자산")

for fid in HAVE:
    with quiet():
        p = config.resolve_font_id_path(fid)
    check(f"{fid} 정상 resolve", Path(p).is_file() and Path(p).suffix == ".ttf",
          Path(p).name)

for fid in MISSING:
    try:
        with quiet():
            config.resolve_font_id_path(fid)
        check(f"{fid} → font_asset_missing", False, "예외가 나지 않음")
    except config.FontRejection as e:
        check(f"{fid} → font_asset_missing",
              e.payload["error"] == "font_asset_missing", e.payload["error"])

try:
    config.resolve_font_id_path("nosuchfont")
    check("미등록 ID → font_not_supported", False, "예외가 나지 않음")
except config.FontRejection as e:
    check("미등록 ID → font_not_supported", e.payload["error"] == "font_not_supported")
    check("supported 목록 동봉", e.payload.get("supported") == sorted(FRONT_IDS))

check("available_font_ids는 실제 파일 있는 것만",
      all(Path(config.FONT_IDS[f]).is_file() for f in HAVE))
check("FontRejection은 ValueError", issubclass(config.FontRejection, ValueError))


# ---------------------------------------------------------------------------
print("\n[3] API 400 — silent fallback 없음")

r = compose({**TEXT, "font_id": "nosuchfont"})
check("미등록 ID → 400", r.status_code == 400, str(r.status_code))
check("error=font_not_supported", r.json()["detail"]["error"] == "font_not_supported")
check("응답에 supported 목록", set(r.json()["detail"]["supported"]) == set(FRONT_IDS))

if MISSING:
    r = compose({**TEXT, "font_id": MISSING[0]})
    check(f"자산 없는 ID({MISSING[0]}) → 400", r.status_code == 400, str(r.status_code))
    d = r.json()["detail"]
    check("error=font_asset_missing", d["error"] == "font_asset_missing", d.get("error"))
    check("두 오류 코드가 구분됨", d["error"] != "font_not_supported")
    check("응답에 서버 절대경로 미노출", "/sessions" not in str(d) and "assets/fonts" not in str(d),
          str(d)[:80])
    check("available 목록 동봉", d.get("available") == HAVE)

r = compose({**TEXT, "font_id": ""})
check('빈 문자열은 미전달과 동일(200)', r.status_code == 200, str(r.status_code))

r = compose({**TEXT, "font_id": 123})
check("타입 위반은 422", r.status_code == 422, str(r.status_code))

check("잘못된 font_id가 200으로 통과하지 않음",
      compose({**TEXT, "font_id": "Pretendard"}).status_code == 400)   # 대문자 = 미등록


# ---------------------------------------------------------------------------
print("\n[4] 렌더링 — headline·sub에 같은 폰트")

calls = []
orig_id, orig_role = config.resolve_font_id_path, config.resolve_font_path


def spy_id(fid):
    p = orig_id(fid)
    calls.append(("id", fid, p))
    return p


def spy_role(role):
    p = orig_role(role)
    calls.append(("role", role, p))
    return p


config.resolve_font_id_path = spy_id
config.resolve_font_path = spy_role
try:
    picked = HAVE[0]
    calls.clear()
    r = compose({**TEXT, "font_id": picked})
    check(f"font_id={picked} 200", r.status_code == 200, str(r.status_code))
    id_calls = [c for c in calls if c[0] == "id"]
    role_calls = [c for c in calls if c[0] == "role" and c[1] != "body"]
    check("font_id 경로로 해석됨", len(id_calls) >= 1, f"{len(id_calls)}회")
    check("headline_font_role 해석은 일어나지 않음", not role_calls, f"{role_calls}")
    check("해석된 경로가 하나뿐(headline·sub 공통)",
          len({c[2] for c in id_calls}) == 1, f"{ {c[2].split('/')[-1] for c in id_calls} }")

    # 두 번째 폰트가 있으면 실제로 다른 결과가 나오는지까지 확인
    if len(HAVE) >= 2:
        a = compose({**TEXT, "font_id": HAVE[0], "ai_notice": False})
        b = compose({**TEXT, "font_id": HAVE[1], "ai_notice": False})
        ia = np.array(Image.open(io.BytesIO(base64.b64decode(a.json()["image"]))))
        ib = np.array(Image.open(io.BytesIO(base64.b64decode(b.json()["image"]))))
        check(f"{HAVE[0]} != {HAVE[1]} 결과가 실제로 다름", not np.array_equal(ia, ib))

    # sub만 있는 경우에도 선택 폰트가 쓰이는지 (기본 경로는 sub를 "body"로 고정)
    # ai_notice는 의도적으로 "body" 역할을 계속 쓰므로 끄고 본다.
    # 켜두면 그 호출이 섞여 "sub가 body를 썼다"와 구분되지 않는다.
    calls.clear()
    r = compose({"sub": "오늘 하루만 20% 할인", "x": 0.5, "y": 0.5,
                 "align": "center", "style": "plain", "font_id": picked},
                ai_notice=False)
    check("sub만 있어도 선택 폰트 적용",
          r.status_code == 200 and any(c[0] == "id" for c in calls))
    check("sub 경로에서 body 역할이 안 쓰임",
          not [c for c in calls if c[0] == "role"],
          f"{[c[1] for c in calls if c[0] == 'role']}")

    calls.clear()
    compose({**TEXT, "font_id": picked}, ai_notice=True)
    check("ai_notice는 body 역할을 계속 사용",
          [c[1] for c in calls if c[0] == "role"] == ["body"],
          f"{[c[1] for c in calls if c[0] == 'role']}")

    # font_id 미전달이면 기존 역할 경로를 그대로 탄다
    calls.clear()
    compose(TEXT)
    check("미전달 시 역할 기반 경로 유지",
          {c[1] for c in calls if c[0] == "role"} == {"headline", "body"},
          f"{sorted({c[1] for c in calls if c[0] == 'role'})}")
    check("미전달 시 font_id 해석 없음", not [c for c in calls if c[0] == "id"])
finally:
    config.resolve_font_id_path = orig_id
    config.resolve_font_path = orig_role


# ---------------------------------------------------------------------------
print("\n[5] meta")

r = compose({**TEXT, "font_id": HAVE[0]})
tm = r.json()["meta"]["text"]
check("meta.text.font_id = 요청값", tm.get("font_id") == HAVE[0], str(tm.get("font_id")))
check("font_id 사용 시 headline_font_role=null", tm.get("headline_font_role") is None)

tm0 = compose(TEXT).json()["meta"]["text"]
check("미전달 시 font_id=null", tm0.get("font_id") is None)
check("미전달 시 headline_font_role 유지", tm0.get("headline_font_role") == "headline")


# ---------------------------------------------------------------------------
print("\n[6] 회귀 — 미전달 시 변경 전과 픽셀 동일")

# 변경 전 overlay 사본을 그대로 로드해 같은 입력으로 렌더링하고 픽셀 비교한다.
# "기존 동작 유지"를 말이 아니라 수치로 확인하려는 것이다.
BASE = ROOT / "tests" / "_baseline" / "overlay_before_font_id.py"
src = BASE.read_text(encoding="utf-8").replace(
    "from . import config", "from pipeline import config")
mod = types.ModuleType("overlay_before")
mod.__file__ = str(BASE)
with quiet():
    exec(compile(src, str(BASE), "exec"), mod.__dict__)

CASES = [
    dict(headline="여름 한정 특가", sub="오늘 하루만 20% 할인", x=0.5, y=0.5,
         align="center", style="plain"),
    dict(headline="아주 긴 문구를 넣어서 자동 줄바꿈과 auto_fit 축소가 함께 도는 경우",
         sub="두 줄 이상 내려가는 서브 문구도 같이 확인한다", x=0.5, y=0.4,
         align="center", style="bar"),
    dict(headline="프리셋 모드", sub="좌표 없이 position으로", position="bottom",
         align="left", style="bar"),
    dict(headline="서브 없음", x=0.3, y=0.2, align="left", style="plain"),
]
for i, kw in enumerate(CASES, 1):
    img = Image.new("RGB", (1024, 1024), BG)
    with quiet():
        before = mod.render_text(img.copy(), **kw)
        after = overlay.render_text(img.copy(), **kw)
    diff = int(np.abs(np.array(before, np.int32) - np.array(after, np.int32)).max())
    check(f"case {i} 픽셀 동일 (max diff 0)", diff == 0, f"diff={diff}")

for size in [(3072, 1024), (1024, 1368)]:
    img = Image.new("RGB", size, BG)
    kw = dict(headline="비정사각 캔버스", sub="3:1 / 3:4", x=0.5, y=0.5,
              align="center", style="bar")
    with quiet():
        before, after = mod.render_text(img.copy(), **kw), overlay.render_text(img.copy(), **kw)
    d = int(np.abs(np.array(before, np.int32) - np.array(after, np.int32)).max())
    check(f"{size[0]}x{size[1]} 픽셀 동일", d == 0, f"diff={d}")

# 역할 기반 매핑 자체가 안 바뀌었는지 (font_id 작업이 기존 테이블을 건드리지 않았는지)
# 문자열 슬라이싱은 주변 빈 줄 수에 따라 경계가 달라져 신뢰할 수 없다.
# ast로 정의 노드를 집어 그 소스 조각만 비교한다.
def _defs(src):
    tree = ast.parse(src)
    out = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            out[node.name] = ast.get_source_segment(src, node)
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    out[t.id] = ast.get_source_segment(src, node)
    return out


bdefs = _defs((ROOT / "tests" / "_baseline" / "config_before_font_id.py")
              .read_text(encoding="utf-8"))
cdefs = _defs((ROOT / "pipeline" / "config.py").read_text(encoding="utf-8"))
for name in ["FONTS", "FONT_FALLBACK_ROLE", "resolve_font_path",
             "FONT_BOLD", "FONT_REGULAR", "TONE_PRESETS"]:
    check(f"{name} 무변경", name in bdefs and bdefs[name] == cdefs.get(name))
check("기존 정의가 사라지지 않음", set(bdefs) <= set(cdefs),
      f"{sorted(set(bdefs) - set(cdefs))}")
check("추가된 것은 font_id 관련뿐",
      set(cdefs) - set(bdefs) == {"FONT_IDS", "FontRejection",
                                  "available_font_ids", "resolve_font_id_path"},
      f"{sorted(set(cdefs) - set(bdefs))}")


# ---------------------------------------------------------------------------
print("\n[7] 스키마 / 양쪽 엔드포인트")

asrc = (ROOT / "api.py").read_text(encoding="utf-8")
i = asrc.index("class TextSpec(")
block = asrc[i:asrc.index("class ", i + 10)]
fields = {l.strip().split(":")[0] for l in block.splitlines()
          if l.startswith("    ") and ": " in l and "=" in l
          and not l.strip().startswith("#")}
check("TextSpec = 기존 13개 + font_id",
      fields == {"headline", "sub", "x", "y", "position", "align", "style",
                 "headline_size", "sub_size", "headline_z_order", "sub_z_order",
                 "sub_x", "sub_y", "font_id"}, f"{sorted(fields)}")
check("font_id는 Optional[str]", "font_id: Optional[str] = None" in block)
check("Literal로 막지 않음(400을 내려야 하므로)", "font_id: Literal" not in block)
check("refine이 diffusion 전에 검증",
      asrc.index("_validate_font_id(req.text)") < asrc.index("result = pipeline.refine("))
check("compose/text도 같은 검증", "_validate_font_id(spec)" in asrc)
check("render_text 두 호출부 모두 font_id 전달", asrc.count("font_id=spec.font_id") == 2)
check("add_ai_notice는 body 유지",
      'resolve_font_path("body")' in (ROOT / "pipeline" / "overlay.py").read_text(encoding="utf-8"))

# refine도 같은 TextSpec을 쓰므로 스키마 레벨에서 동일하게 받는지
schema = client.get("/openapi.json").json()["components"]["schemas"]["TextSpec"]
check("OpenAPI에 font_id 노출", "font_id" in schema["properties"])
check("font_id는 필수 아님", "font_id" not in schema.get("required", []))
check("OpenAPI에 내부 경로 미노출",
      "assets/fonts" not in str(schema) and "FONT_IDS" not in str(schema))


# ---------------------------------------------------------------------------
print("\n[PENDING] PR #27 자산 병합 후 성공 조건으로 올릴 항목")
for fid in MISSING:
    print(f"  [TODO] {fid}: 실제 파일 존재 + 렌더링 결과 확인 "
          f"({EXPECTED_PATHS[fid]})")
if not MISSING:
    print("  자산이 모두 병합됨 — 아래를 성공 조건으로 검사한다")
    for fid in FRONT_IDS:
        r = compose({**TEXT, "font_id": fid})
        check(f"{fid} 렌더링 200", r.status_code == 200, str(r.status_code))

print("\n" + "=" * 60)
print(f"통과 {PASS} / 실패 {FAIL}")
sys.exit(1 if FAIL else 0)
