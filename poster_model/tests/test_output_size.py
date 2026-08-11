"""출력 캔버스 크기 계산 검증 (A2-1, GPU·모델 불필요).

resolve_output_size()는 크기 계산만 담당한다. 실제 생성 경로에 연결되지
않았음(A2-2 보류)도 함께 확인한다.

실행 (프로젝트 루트에서):
    PYTHONPATH="$PWD" python tests/test_output_size.py
"""
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

sys.modules["torch"] = types.ModuleType("torch")
sys.modules["diffusers"] = types.ModuleType("diffusers")

from pipeline import config                        # noqa: E402
from pipeline.layout import _round8, resolve_output_size   # noqa: E402

PASS, FAIL = 0, 0


def check(name, ok, detail=""):
    global PASS, FAIL
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  {detail}" if detail else ""))
    if ok:
        PASS += 1
    else:
        FAIL += 1


print("\n[1] 지원 비율 정확도")
EXPECT = {"1:1": (1024, 1024), "3:1": (3072, 1024), "3:4": (1024, 1368)}
for ratio, want in EXPECT.items():
    got = resolve_output_size(ratio)
    check(f"{ratio} → {want[0]}x{want[1]}", got == want, f"got={got[0]}x{got[1]}")

check("None → 기본 비율(1:1)", resolve_output_size() == EXPECT[config.DEFAULT_ASPECT_RATIO])
check("공백 허용", resolve_output_size(" 3:1 ") == (3072, 1024))

print("\n[2] 짧은 변 1024 고정 / 비율 근사")
for ratio, (w, h) in EXPECT.items():
    rw, rh = config.ASPECT_RATIOS[ratio]
    check(f"{ratio}: 짧은 변 = {config.OUTPUT_SHORT_SIDE}",
          min(w, h) == config.OUTPUT_SHORT_SIDE)
    err = abs((w / h) - (rw / rh)) / (rw / rh)
    check(f"{ratio}: 목표 비율 오차 < 0.5%", err < 0.005, f"{w/h:.4f} vs {rw/rh:.4f}")

print("\n[3] W/H 모두 8의 배수")
for ratio in EXPECT:
    w, h = resolve_output_size(ratio)
    check(f"{ratio}: 8의 배수", w % 8 == 0 and h % 8 == 0, f"{w}x{h}")
for short in (512, 768, 1024, 1000, 1365):
    for ratio in EXPECT:
        w, h = resolve_output_size(ratio, short)
        check(f"{ratio} @short={short}: 8의 배수", w % 8 == 0 and h % 8 == 0, f"{w}x{h}")

print("\n[4] 8의 배수 반올림 규칙 (내림이 아님)")
# 3:4의 긴 변은 1365.33 → 반올림 1368. 내림이면 1360이 되어 비율 오차가 커진다.
check("3:4 긴 변 = 1368 (내림 1360 아님)", resolve_output_size("3:4")[1] == 1368)
check("_round8(1365.33) == 1368", _round8(1024 * 4 / 3) == 1368)
check("_round8은 최소 8 보장", _round8(1) == 8 and _round8(0) == 8)

print("\n[5] 미지원 비율 거부")
for bad in ("16:9", "4:3", "1:2", "", "square", None if False else "3:2", "3;1", 31, 3.1, [3, 1]):
    try:
        resolve_output_size(bad)
        check(f"{bad!r} 거부", False)
    except ValueError:
        check(f"{bad!r} 거부", True)
for bad in (0, -1024, 3.5, "1024", True):
    try:
        resolve_output_size("1:1", bad)
        check(f"short_side={bad!r} 거부", False)
    except ValueError:
        check(f"short_side={bad!r} 거부", True)

print("\n[6] 기존 1:1 동작 영향 없음")
api = (ROOT / "api.py").read_text(encoding="utf-8")
# resolver는 pipeline 안에서만 호출된다. api.py는 비율 문자열만 넘긴다.
check("api.py가 resolver를 직접 호출하지 않음", "resolve_output_size" not in api)
check("aspect_ratio 기본값은 None (미전송 = 1:1)",
      "aspect_ratio: Optional[Literal" in api and "= None" in api)
check("draft size 768 유지", config.MODELS["sd15"]["size"] == 768)
check("refine size 1024 유지", config.MODELS["sdxl"]["size"] == 1024)
check("1:1 resolver 결과 == refine size",
      resolve_output_size("1:1") == (config.MODELS["sdxl"]["size"],) * 2)

print("\n" + "=" * 60)
print(f"통과 {PASS} / 실패 {FAIL}")
sys.exit(1 if FAIL else 0)
