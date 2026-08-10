"""소상공인 광고 포스터 생성 파이프라인.

사용 예:
    from pipeline import generate_drafts, refine, render_text

    result = generate_drafts(image="cake.jpg", category="food")
    chosen = result["images"][0]

    out = refine(chosen, original="cake.jpg", category="food")
    final = render_text(out["image"], "진하고 부드러운 티라미수",
                        "오늘 하루만 20% 할인", position="top", style="bar")
"""

from . import config
from .generate import generate_drafts, refine, unload, warmup
from .masking import (add_ground_shadow, composite_product, describe_product_bbox,
                      make_masks, prepare_image, render_flat_background, resolve_background)
from .overlay import add_ai_notice, render_text

__all__ = [
    "config",
    "generate_drafts", "refine", "warmup", "unload",
    "make_masks", "prepare_image", "composite_product", "add_ground_shadow",
    "describe_product_bbox", "render_flat_background", "resolve_background",
    "render_text", "add_ai_notice",
]
