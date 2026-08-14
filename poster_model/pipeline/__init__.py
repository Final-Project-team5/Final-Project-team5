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
from .config import (FontRejection, available_font_ids,
                     resolve_font_id_path)
from .layout import (LayoutRejection, compute_placement, infer_aspect_ratio,
                     resolve_ai_gen_size,
                     resolve_aspect_ratio, resolve_output_size, resolve_placement,
                     validate_placement)
from .generate import generate_drafts, refine, unload, warmup
from .masking import (RotationRejection, add_ground_shadow, composite_product,
                      describe_product_bbox, make_masks,
                      place_product_on_canvas, prepare_image,
                      render_flat_background, resolve_background,
                      rotate_product)
from .overlay import add_ai_notice, render_text

__all__ = [
    "config",
    "generate_drafts", "refine", "warmup", "unload",
    "make_masks", "prepare_image", "composite_product", "add_ground_shadow",
    "describe_product_bbox", "render_flat_background", "resolve_background",
    "place_product_on_canvas", "resolve_output_size",
    "rotate_product", "RotationRejection",
    "compute_placement", "validate_placement", "resolve_placement",
    "infer_aspect_ratio", "resolve_aspect_ratio", "LayoutRejection",
    "resolve_font_id_path", "available_font_ids", "FontRejection",
    "render_text", "add_ai_notice",
]
