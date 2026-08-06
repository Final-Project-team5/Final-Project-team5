"""그림자 후처리 형태 확인 (diffusion 없이 rembg만 사용, GPU 불필요).

목적: add_ground_shadow()의 타원 계산이 실제 제품 실루엣 폭과 잘 맞는지
     6장 샘플 이미지로 몇 초 안에 빠르게 확인한다.
     특히 몸통보다 위/아래가 넓은 제품(글라스, 몬스터 피규어 등)에서
     그림자가 과하게 넓어지지 않는지 보는 용도.

v2: 실제 제품 실루엣(마스크)을 반투명 흰색으로 같이 그려서, 그림자 타원 폭이
    bbox(빨간 사각형)가 아니라 진짜 제품 모양과 맞는지 눈으로 비교할 수 있게 함.
    (v1은 bbox만 그려서 항상 사각형으로 보이는 문제가 있었음)

v3: 실행 코드를 main()으로 옮기고 `if __name__ == "__main__"` 가드를 적용했다.
    이전에는 모듈을 import하는 것만으로 prepare_image()가 돌아 rembg 모델
    다운로드/초기화가 시작됐다. rembg 세션 자체는 pipeline.masking.get_session()이
    최초 호출 때 만들므로, 실행 함수 밖에서는 모델이 로드되지 않는다.

실행:
    cd poster_model
    source .venv/bin/activate
    PYTHONPATH="$PWD" python scripts/verification/shadow/check_shadow_shapes.py

결과: outputs/verification/shadow/shadow_shape_check.png
    - 반투명 흰색 = 실제 제품 실루엣(마스크)
    - 빨간 사각형 = 그림자 폭 계산에 쓰인 마스크 bbox (참고용, 항상 사각형임)
    - 회색 바닥의 어두운 타원 = 후처리로 그려진 그림자
"""
import glob
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

SIZE = 768
ROOT = Path(__file__).resolve().parents[3]   # scripts/verification/shadow/ -> 프로젝트 루트
OUT_DIR = ROOT / "outputs" / "verification" / "shadow"


def main():
    # rembg를 쓰는 모듈은 실행 시점에 import한다 (import 부작용 방지).
    from pipeline.masking import add_ground_shadow, prepare_image

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    paths = sorted(glob.glob(str(ROOT / "image" / "*.jpg")))
    if not paths:
        raise SystemExit(f"{ROOT / 'image'} 에서 jpg를 찾지 못했습니다. "
                         "image/README.md의 필요 파일 목록을 확인하세요.")

    cells = []
    for path in paths:
        img, masks, mode = prepare_image(path, SIZE)

        gray = Image.new("RGB", (SIZE, SIZE), (200, 200, 200))
        shadow_only = add_ground_shadow(gray, masks.product).convert("RGBA")

        # 실제 제품 실루엣을 반투명 흰색으로 오버레이 (검증용. 실제 파이프라인엔 없는 단계)
        mask_l = masks.product.convert("L")
        white_layer = Image.new("RGBA", (SIZE, SIZE), (255, 255, 255, 170))
        empty = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
        silhouette = Image.composite(white_layer, empty, mask_l)

        overlay = Image.alpha_composite(shadow_only, silhouette).convert("RGB")
        draw = ImageDraw.Draw(overlay)

        m = np.array(mask_l) > 128
        ys, xs = np.where(m)
        if len(xs):
            draw.rectangle([int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())],
                           outline=(255, 0, 0), width=3)

        label = Path(path).name
        print(f"{label}: area_ratio={masks.area_ratio:.3f}, mode={mode}")
        cells.append((label, overlay))

    cols = 3
    rows = (len(cells) + cols - 1) // cols
    thumb = 384
    grid = Image.new("RGB", (thumb * cols, thumb * rows), (255, 255, 255))
    draw = ImageDraw.Draw(grid)
    for i, (label, im) in enumerate(cells):
        t = im.resize((thumb, thumb))
        x, y = thumb * (i % cols), thumb * (i // cols)
        grid.paste(t, (x, y))
        draw.rectangle([x, y, x + 90, y + 20], fill=(255, 255, 255))
        draw.text((x + 4, y + 4), label, fill=(200, 0, 0))

    out = OUT_DIR / "shadow_shape_check.png"
    grid.save(out)
    print(f"완료: {out} 확인하세요.")


if __name__ == "__main__":
    main()
