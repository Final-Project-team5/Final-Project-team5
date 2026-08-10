"""auto_fit 텍스트 크기 조정 검증 (torch 없이 config/masking/overlay만 standalone 로드).

자동으로 PASS/FAIL을 판정하지 않는다. 4가지 조건의 비교 이미지를 만들어
눈으로 확인하는 용도다(그래서 tests/가 아니라 scripts/verification/에 있다).

실행 (GPU·서버 불필요):
    cd poster_model
    source .venv/bin/activate
    PYTHONPATH="$PWD" python scripts/verification/typography/verify_autofit.py

결과: outputs/verification/typography/autofit_compare.png
"""
import importlib.util
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

# scripts/verification/typography/ -> 프로젝트 루트
PROJECT = Path(__file__).resolve().parents[3]
OUT_DIR = PROJECT / "outputs" / "verification" / "typography"
OUT_DIR.mkdir(parents=True, exist_ok=True)


def load(name, relpath):
    spec = importlib.util.spec_from_file_location(f"pipeline.{name}", PROJECT / relpath)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod

# masking.py는 `from . import config` 를 쓰므로 pipeline 패키지 자체를 최소 스텁으로 등록
pkg_spec = importlib.util.spec_from_file_location("pipeline", PROJECT / "pipeline" / "__init__.py",
                                                   submodule_search_locations=[str(PROJECT / "pipeline")])
pkg = importlib.util.module_from_spec(pkg_spec)
sys.modules["pipeline"] = pkg  # exec_module은 하지 않음 (torch import 트리거 방지)

config = load("config", "pipeline/config.py")
masking = load("masking", "pipeline/masking.py")
overlay = load("overlay", "pipeline/overlay.py")

SIZE = 1024

def make_placeholder_mask(size, w_ratio=0.34, h_ratio=0.55, cx_ratio=0.5, cy_ratio=0.62):
    """병 모양 placeholder 마스크 (실제 제품 대신 사용)."""
    m = Image.new("L", (size, size), 0)
    d = ImageDraw.Draw(m)
    w, h = int(size * w_ratio), int(size * h_ratio)
    cx, cy = int(size * cx_ratio), int(size * cy_ratio)
    body_top = cy - h // 2
    body_bot = cy + h // 2
    d.rounded_rectangle([cx - w // 2, body_top, cx + w // 2, body_bot], radius=int(w * 0.18), fill=255)
    neck_w = int(w * 0.36)
    d.rectangle([cx - neck_w // 2, body_top - int(h * 0.14), cx + neck_w // 2, body_top + 4], fill=255)
    return m


def scene():
    """배경+그림자+제품 합성이 끝난 상태의 베이스 이미지 (bar_vs_plain 테스트와 동일 스캐폴드)."""
    bg = masking.render_flat_background(SIZE, ["#F5F1EC", "#E6EAEE"], "vertical")
    mask = make_placeholder_mask(SIZE)
    shadowed = masking.add_ground_shadow(bg, mask)
    arr_bg = np.array(shadowed.convert("RGB"))
    arr_mask = np.array(mask) > 128
    product_color = np.array([210, 140, 150], dtype=np.uint8)  # 임의의 제품 색
    arr_bg[arr_mask] = product_color
    return Image.fromarray(arr_bg)


HEADLINE = "오늘만 20% 할인"
SUB = "매장 방문 시 즉시 적용됩니다"

# 1) 기존 기본값 수준 (참고용 baseline)
img1 = overlay.render_text(scene(), HEADLINE, SUB, x=0.08, y=0.08, align="left",
                           style="plain", headline_size=0.075, sub_size=0.04)

# 2) 확대된 headline_size — 위쪽에 배치해 공간이 충분 → 요청 크기 그대로 사용되어야 함
img2 = overlay.render_text(scene(), HEADLINE, SUB, x=0.08, y=0.06, align="left",
                           style="plain", headline_size=0.20, sub_size=0.06)

# 3) 동일하게 크게 요청했지만 하단(y=0.78)에 배치 → 영역이 좁아 auto_fit 없이는 화면 밖으로 잘림
img3 = overlay.render_text(scene(), HEADLINE, SUB, x=0.08, y=0.78, align="left",
                           style="plain", headline_size=0.22, sub_size=0.07, auto_fit=False)

# 4) 동일 조건, auto_fit=True(기본값) → 영역을 벗어나는 만큼만 자동 축소되어 온전히 들어옴
img4 = overlay.render_text(scene(), HEADLINE, SUB, x=0.08, y=0.78, align="left",
                           style="plain", headline_size=0.22, sub_size=0.07, auto_fit=True)

labels = [
    "1) 기존 baseline (headline_size=0.075)",
    "2) 확대 요청, 공간 충분 -> 요청 크기 그대로(0.20)",
    "3) 확대 요청, 하단 배치, auto_fit=False -> 하단 잘림",
    "4) 확대 요청, 하단 배치, auto_fit=True -> 자동 축소로 온전히 표시",
]
imgs = [img1, img2, img3, img4]

pad = 16
label_h = 40
cell_w, cell_h = SIZE // 2, SIZE // 2
grid = Image.new("RGB", (cell_w * 2 + pad * 3, (cell_h + label_h) * 2 + pad * 3), "white")
d = ImageDraw.Draw(grid)
positions = [(0, 0), (1, 0), (0, 1), (1, 1)]
for (col, row), im, label in zip(positions, imgs, labels):
    thumb = im.resize((cell_w, cell_h))
    x0 = pad + col * (cell_w + pad)
    y0 = pad + row * (cell_h + label_h + pad)
    d.text((x0, y0), label, fill="black")
    grid.paste(thumb, (x0, y0 + label_h))

out_path = OUT_DIR / "autofit_compare.png"
grid.save(out_path)
print("saved:", out_path)
