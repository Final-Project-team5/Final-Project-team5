"""시안 생성(1단계) 및 고품질 렌더링(2단계)."""

import time

import torch
from PIL import Image

from . import config
from . import layout
from .masking import (add_ground_shadow, composite_product, describe_product_bbox,
                      make_masks, place_product_on_canvas, prepare_image,
                      render_flat_background, resolve_background)

_pipes = {}


def _load(kind: str, task: str, tiling: bool = True):
    """kind: 'sd15' | 'sdxl', task: 'inpaint' | 'text2img'.

    tiling=False면 VAE tiling을 끈 **별도 인스턴스**를 따로 캐시한다.
    같은 객체의 tiling을 요청마다 켰다 껐다 하면 동시 요청이 서로 간섭하므로
    상태를 토글하지 않고 인스턴스를 나눈다. 기본값이 True라 기존 호출부는
    동작이 그대로다.
    """
    key = f"{kind}_{task}" if tiling else f"{kind}_{task}_notile"
    if key in _pipes:
        return _pipes[key]

    from diffusers import (StableDiffusionInpaintPipeline,
                           StableDiffusionPipeline,
                           StableDiffusionXLInpaintPipeline,
                           StableDiffusionXLPipeline)

    spec = config.MODELS[kind]
    cls = {
        ("sd15", "inpaint"): StableDiffusionInpaintPipeline,
        ("sd15", "text2img"): StableDiffusionPipeline,
        ("sdxl", "inpaint"): StableDiffusionXLInpaintPipeline,
        ("sdxl", "text2img"): StableDiffusionXLPipeline,
    }[(kind, task)]

    kwargs = {"torch_dtype": torch.float16}
    if spec["variant"]:
        kwargs["variant"] = spec["variant"]
    if kind == "sd15":
        kwargs["safety_checker"] = None

    pipe = cls.from_pretrained(spec[task], **kwargs)

    if config.USE_CPU_OFFLOAD:
        pipe.enable_model_cpu_offload()
        pipe.vae.enable_slicing()
        if tiling:
            pipe.vae.enable_tiling()   # SDXL inpaint 디코딩 단계 OOM 방지
    else:
        pipe.to("cuda")

    _pipes[key] = pipe
    return pipe


def warmup():
    """서버 시작 시 호출. 요청마다 로딩되는 것을 방지한다."""
    _load(config.DRAFT_MODEL, "inpaint")
    _load(config.DRAFT_MODEL, "text2img")
    if config.KEEP_BOTH_LOADED:
        _load(config.REFINE_MODEL, "inpaint")


def unload(kind: str = None):
    """메모리 확보용. kind 미지정 시 전체 해제."""
    import gc
    keys = list(_pipes) if kind is None else [
        k for k in _pipes if k.startswith(kind)]
    for k in keys:
        del _pipes[k]
    gc.collect()
    torch.cuda.empty_cache()


def resolve_prompt(prompt: str = None, category: str = None) -> str:
    base = prompt or config.PROMPT_TEMPLATES[category or config.DEFAULT_CATEGORY]
    # 그림자/단일 제품 유도 문구를 붙인다. 실험 중 SHADOW_PROMPT_SUFFIX=""처럼
    # 비워서 끌 수 있도록, 빈 문자열은 건너뛰고 값이 있는 것만 이어붙인다.
    extras = [s for s in (config.SHADOW_PROMPT_SUFFIX, config.ISOLATION_PROMPT_SUFFIX) if s]
    return ", ".join([base, *extras])


def _flat_background_drafts(image, category, num_images,
                            background_mode, bg_colors, gradient_direction,
                            aspect_ratio=None, placement_override=None) -> dict:
    """background_mode가 solid/gradient일 때: diffusion을 완전히 생략하고
    PIL로만 배경을 채운 뒤 기존 그림자/원본 합성 로직을 그대로 재사용한다.

    aspect_ratio는 아직 API에 노출하지 않는 내부 인자다. None이면 정사각
    캔버스 + 항등 배치라 기존 동작과 픽셀 단위로 같다.

    제품 추출은 항상 정사각 source_size에서 하고(prepare_image), 캔버스 이동은
    place_product_on_canvas가 맡는다. 비정사각에서는 blur margin 축소를 생략해
    캔버스 배치가 제품 크기를 단독으로 책임진다.
    placement_override는 {"scale_factor", "x", "y"} 부분 지정(외부 계약 좌표계).
    지정하더라도 서버가 product+shadow footprint를 다시 검증한다.
    """
    if image is None:
        raise ValueError("solid/gradient 배경 모드는 제품 이미지(image)가 필요합니다.")

    size = config.MODELS[config.DRAFT_MODEL]["size"]
    canvas, use_margin = layout.plan_canvas(aspect_ratio, size)
    started = time.time()

    base, masks, mode = prepare_image(image, size, apply_blur_margin=use_margin)
    place, place_public = layout.resolve_placement(masks, canvas, aspect_ratio,
                                                   placement_override)
    base, masks = place_product_on_canvas(base, masks, canvas, **place.as_kwargs())
    bg_specs = resolve_background(background_mode, bg_colors, gradient_direction,
                                  category, num_images)

    images = []
    for spec in bg_specs:
        flat = render_flat_background(canvas, spec["colors"], spec.get("direction"))
        shadowed = add_ground_shadow(flat, masks.product)
        images.append(composite_product(base, shadowed, masks.product))

    return {
        "images": images,
        "seeds": [0] * num_images,        # solid/gradient는 랜덤 시드 개념이 없음
        "backgrounds": bg_specs,
        "meta": {"elapsed": round(time.time() - started, 2),
                 "model": None,
                 "mode": mode,
                 "area_ratio": round(masks.area_ratio, 3),
                 "layout": describe_product_bbox(masks.product),
                 "diffusion": False,
                 "background_mode": background_mode,
                 "resolution": size,
                 # 아래 3개는 additive. resolution은 짧은 변 정수 그대로 둔다.
                 "aspect_ratio": aspect_ratio or config.DEFAULT_ASPECT_RATIO,
                 "canvas": {"width": canvas[0], "height": canvas[1]},
                 "placement": place_public},
    }


def _place_both(base, masks, canvas_wh, gen_wh, ratio):
    """최종 캔버스와 생성 캔버스에 **같은 정규화 배치**로 제품을 올린다.

    해상도가 다르면 compute_placement의 자동 결과가 미세하게 달라지므로
    (blur pad가 절대 픽셀), 최종에서 계산한 정규화 배치를 생성 캔버스에
    override로 넣는다. A4 실험에서 검증된 방식이다.
    """
    place, public = layout.resolve_placement(masks, canvas_wh, ratio, None)
    base_cv, masks_cv = place_product_on_canvas(base, masks, canvas_wh,
                                                **place.as_kwargs())
    if tuple(gen_wh) == tuple(canvas_wh):
        return (base_cv, masks_cv), (base_cv, masks_cv), public
    ov = {k: public[k] for k in ("scale_factor", "x", "y")}
    gp = layout.compute_placement(masks, gen_wh, ratio, ov)
    layout.validate_placement(masks, gen_wh, gp, strict=True)
    base_gen, masks_gen = place_product_on_canvas(base, masks, gen_wh,
                                                  **gp.as_kwargs())
    return (base_cv, masks_cv), (base_gen, masks_gen), public


def _ai_nonsquare_drafts(image, prompt, category, num_images, seeds,
                         aspect_ratio) -> dict:
    """비정사각 AI draft (현재 3:1만).

    기존 1:1 경로는 건드리지 않고 별도 함수로 둔다. AI는 GPU가 필요해 픽셀 단위
    회귀 테스트를 돌릴 수 없으므로, 공통화보다 기존 코드 보존을 우선한다.

    흐름: 생성 해상도로 diffusion → 최종 캔버스로 업스케일 → 최종 해상도에서
    그림자·원본 제품 재합성. 제품 선명도가 생성 해상도와 분리된다.
    """
    if image is None:
        raise ValueError("비정사각 AI 배경은 제품 이미지(image)가 필요합니다.")

    size = config.MODELS[config.DRAFT_MODEL]["size"]
    canvas, use_margin = layout.plan_canvas(aspect_ratio, size)
    gen = layout.resolve_ai_gen_size(aspect_ratio, "draft", canvas)
    prompt = resolve_prompt(prompt, category)

    if seeds is None:
        seeds = torch.randint(0, 2**31 - 1, (num_images,)).tolist()
    gens = [torch.Generator("cuda").manual_seed(s) for s in seeds]
    started = time.time()

    base, masks, mode = prepare_image(image, size, apply_blur_margin=use_margin)
    (base_cv, masks_cv), (base_gen, masks_gen), public = _place_both(
        base, masks, canvas, gen, aspect_ratio)

    # VAE tiling을 끈 인스턴스를 쓴다. 3:1 draft(1536x512)에서 좌측 가장자리에
    # 색 띠가 생기는 것이 seed 고정 A/B로 확인됐다(ON 19px / OFF 0px, ON 재현 일치).
    # 1:1은 같은 조건에서 재현되지 않아 기존 인스턴스를 그대로 쓴다.
    # 실험 기록: outputs/verification/api/ai_nonsquare_smoke/tilingab_*_summary.txt
    pipe = _load(config.DRAFT_MODEL, "inpaint", tiling=False)
    outs = pipe(prompt=prompt,
                negative_prompt=config.NEGATIVE_PROMPT,
                image=base_gen,
                mask_image=masks_gen.inpaint,
                height=gen[1], width=gen[0],
                num_inference_steps=config.DRAFT_STEPS,
                num_images_per_prompt=num_images,
                generator=gens).images
    if tuple(gen) != tuple(canvas):
        outs = [o.resize(canvas, Image.LANCZOS) for o in outs]
    # 그림자·합성은 항상 최종 캔버스 해상도에서 (1:1 경로와 같은 순서)
    shadowed = [add_ground_shadow(o, masks_cv.product) for o in outs]
    images = [composite_product(base_cv, o, masks_cv.product) for o in shadowed]

    return {
        "images": images,
        "seeds": seeds,
        "backgrounds": [None] * num_images,
        "meta": {"elapsed": round(time.time() - started, 2),
                 "model": config.DRAFT_MODEL,
                 "mode": mode,
                 "area_ratio": round(masks_cv.area_ratio, 3),
                 "layout": describe_product_bbox(masks_cv.product),
                 "diffusion": True,
                 "background_mode": "ai",
                 "resolution": size,
                 "aspect_ratio": aspect_ratio,
                 "canvas": {"width": canvas[0], "height": canvas[1]},
                 "placement": public},
    }


def _ai_nonsquare_refine(draft, original, prompt, category, strength,
                         aspect_ratio) -> dict:
    """비정사각 AI refine (현재 3:1만).

    입력은 **사용자가 고른 실제 draft**다. draft를 못 찾았을 때의 대체 배경 같은
    폴백을 두지 않는다. original_image가 없으면 마스크·배치·제품 재합성이 빠져
    검증한 경로와 달라지므로 호출 전에 거부해야 한다(api.py에서 400).
    """
    if original is None:
        raise ValueError(
            "비정사각 AI 배경 refine에는 original_image가 필요합니다.")

    size = config.MODELS[config.REFINE_MODEL]["size"]
    canvas, use_margin = layout.plan_canvas(aspect_ratio, size)
    gen = layout.resolve_ai_gen_size(aspect_ratio, "refine", canvas)
    prompt = resolve_prompt(prompt, category)
    strength = config.REFINE_STRENGTH if strength is None else strength
    started = time.time()

    base, masks, _mode = prepare_image(original, size,
                                       apply_blur_margin=use_margin)
    (base_cv, masks_cv), (base_gen, masks_gen), public = _place_both(
        base, masks, canvas, gen, aspect_ratio)

    draft_in = draft.convert("RGB").resize(gen, Image.LANCZOS)
    pipe = _load(config.REFINE_MODEL, "inpaint")
    out = pipe(prompt=prompt,
               negative_prompt=config.NEGATIVE_PROMPT,
               image=draft_in,
               mask_image=masks_gen.inpaint,
               height=gen[1], width=gen[0],
               num_inference_steps=config.REFINE_STEPS,
               strength=strength).images[0]
    if tuple(gen) != tuple(canvas):
        out = out.resize(canvas, Image.LANCZOS)
    out = add_ground_shadow(out, masks_cv.product)
    pre_product = out
    out = composite_product(base_cv, out, masks_cv.product)

    return {
        "image": out,
        "pre_product": pre_product,
        "base": base_cv,
        "product_mask": masks_cv.product,
        "meta": {"elapsed": round(time.time() - started, 2),
                 "model": config.REFINE_MODEL,
                 "strength": strength,
                 "layout": describe_product_bbox(masks_cv.product),
                 "diffusion": True,
                 "background_mode": "ai",
                 "resolution": size,
                 "aspect_ratio": aspect_ratio,
                 "canvas": {"width": canvas[0], "height": canvas[1]},
                 "placement": public},
    }


def generate_drafts(image=None,
                    prompt: str = None,
                    category: str = None,
                    num_images: int = None,
                    seeds: list[int] = None,
                    background_mode: str = "ai",
                    bg_colors: list[str] = None,
                    gradient_direction: str = None,
                    aspect_ratio: str = None,
                    placement_override: dict = None) -> dict:
    """1단계: 시안 여러 장 생성.

    image가 있으면 inpaint(제품 보존), 없으면 text2img.
    background_mode="ai"(기본값)면 기존 diffusion 경로를 그대로 사용한다.
    "solid"/"gradient"면 diffusion을 생략하고 PIL로만 배경을 채운다.

    aspect_ratio / placement_override는 solid/gradient 경로에만 적용된다.
    AI 경로의 비정사각 생성은 아직 지원하지 않는다(A4). 둘 다 None이면
    기존 동작과 완전히 동일하다.
    """
    num_images = num_images or config.NUM_DRAFTS

    if background_mode != "ai":
        return _flat_background_drafts(image, category, num_images,
                                       background_mode, bg_colors, gradient_direction,
                                       aspect_ratio, placement_override)
    if aspect_ratio not in (None, "1:1"):
        # 비정사각 AI는 별도 경로. 아래 1:1 코드는 그대로 둔다.
        return _ai_nonsquare_drafts(image, prompt, category, num_images, seeds,
                                    aspect_ratio)

    prompt = resolve_prompt(prompt, category)
    size = config.MODELS[config.DRAFT_MODEL]["size"]

    if seeds is None:
        seeds = torch.randint(0, 2**31 - 1, (num_images,)).tolist()
    gens = [torch.Generator("cuda").manual_seed(s) for s in seeds]

    started = time.time()

    if image is not None:
        base, masks, mode = prepare_image(image, size)
        pipe = _load(config.DRAFT_MODEL, "inpaint")
        outs = pipe(prompt=prompt,
                    negative_prompt=config.NEGATIVE_PROMPT,
                    image=base,
                    mask_image=masks.inpaint,
                    height=size, width=size,
                    num_inference_steps=config.DRAFT_STEPS,
                    num_images_per_prompt=num_images,
                    generator=gens).images
        # 접지 그림자 후처리는 원본 제품을 덮어씌우기(composite_product) 전에 적용해야
        # 제품 바로 아래로 삐져나온 그림자가 최종 결과에 남는다.
        shadowed = [add_ground_shadow(o, masks.product) for o in outs]
        images = [composite_product(base, o, masks.product) for o in shadowed]
        meta_extra = {"mode": mode, "area_ratio": round(masks.area_ratio, 3),
                     "layout": describe_product_bbox(masks.product)}
    else:
        pipe = _load(config.DRAFT_MODEL, "text2img")
        images = pipe(prompt=prompt,
                      negative_prompt=config.NEGATIVE_PROMPT,
                      height=size, width=size,
                      num_inference_steps=config.DRAFT_STEPS,
                      num_images_per_prompt=num_images,
                      generator=gens).images
        meta_extra = {"mode": "text2img"}

    return {
        "images": images,
        "seeds": seeds,
        "backgrounds": [None] * num_images,   # ai 모드는 색상 개념이 없음
        "meta": {"elapsed": round(time.time() - started, 2),
                 "model": config.DRAFT_MODEL,
                 "diffusion": True,
                 "background_mode": "ai",
                 "resolution": size,
                 **meta_extra},
    }


def _flat_background_refine(original, background: dict,
                            aspect_ratio=None, placement_override=None) -> dict:
    """background_mode가 solid/gradient일 때의 2단계.

    draft(768 시안)를 단순 확대하지 않고, 원본 이미지+마스크로 1024에서
    "동일한 배경 설정"을 다시 렌더링한다. diffusion은 호출하지 않는다.

    aspect_ratio/placement_override는 _flat_background_drafts와 같은 의미다.
    None이면 항등 경로라 기존 정사각 동작과 동일하다.
    """
    if original is None:
        raise ValueError("solid/gradient 배경 refine에는 original(원본 이미지)이 필요합니다.")

    size = config.MODELS[config.REFINE_MODEL]["size"]
    canvas, use_margin = layout.plan_canvas(aspect_ratio, size)
    started = time.time()

    base, masks, mode = prepare_image(original, size, apply_blur_margin=use_margin)
    place, place_public = layout.resolve_placement(masks, canvas, aspect_ratio,
                                                   placement_override)
    base, masks = place_product_on_canvas(base, masks, canvas, **place.as_kwargs())
    flat = render_flat_background(canvas, background["colors"], background.get("direction"))
    shadowed = add_ground_shadow(flat, masks.product)
    out = composite_product(base, shadowed, masks.product)

    return {
        "image": out,
        # 아래 3개는 텍스트를 제품 "뒤"에 깔기 위한(z_order="behind") 재료다.
        # image는 이미 제품까지 합성된 최종본이라 그 위엔 제품 뒤 레이어를 만들 수 없다.
        # 호출자(api.py)가 pre_product 위에 문구를 그린 뒤 composite_product를 다시
        # 호출하면 제품이 문구 일부를 가리는 합성이 된다. 기존 키(image/meta)는 그대로다.
        "pre_product": shadowed,        # 제품 합성 직전 상태(배경+그림자)
        "base": base,                   # 보존해야 할 원본 제품 이미지
        "product_mask": masks.product,  # composite_product에 넘길 마스크
        "meta": {"elapsed": round(time.time() - started, 2),
                 "model": None,
                 "strength": None,
                 "mode": mode,
                 "area_ratio": round(masks.area_ratio, 3),
                 "layout": describe_product_bbox(masks.product),
                 "diffusion": False,
                 "background_mode": background["mode"],
                 "resolution": size,
                 "aspect_ratio": aspect_ratio or config.DEFAULT_ASPECT_RATIO,
                 "canvas": {"width": canvas[0], "height": canvas[1]},
                 "placement": place_public},
    }


def refine(draft: Image.Image,
           original=None,
           prompt: str = None,
           category: str = None,
           strength: float = None,
           background: dict = None,
           aspect_ratio: str = None,
           placement_override: dict = None) -> dict:
    """2단계: 선택한 시안을 고품질로 다시 렌더링.

    original(사용자 원본 사진)이 주어지면 제품 영역을 다시 보존한다.
    SDXL은 이미지 전체를 재해석하므로 이 단계가 없으면 제품이 변형된다.

    background가 주어지고 mode가 "solid"/"gradient"면 diffusion을 완전히
    생략한다(_flat_background_refine). background가 없거나 mode="ai"면
    기존 동작 그대로다.

    aspect_ratio / placement_override는 solid/gradient 경로에만 적용된다.
    둘 다 None이면 기존 동작과 완전히 동일하다.
    """
    if background and background.get("mode") in ("solid", "gradient"):
        return _flat_background_refine(original, background,
                                       aspect_ratio, placement_override)
    if aspect_ratio not in (None, "1:1"):
        # 비정사각 AI는 별도 경로. 아래 1:1 코드는 그대로 둔다.
        return _ai_nonsquare_refine(draft, original, prompt, category, strength,
                                    aspect_ratio)

    prompt = resolve_prompt(prompt, category)
    strength = config.REFINE_STRENGTH if strength is None else strength
    size = config.MODELS[config.REFINE_MODEL]["size"]

    draft = draft.convert("RGB").resize((size, size), Image.LANCZOS)
    started = time.time()

    if original is not None:
        base, masks, _ = prepare_image(original, size)
        pipe = _load(config.REFINE_MODEL, "inpaint")
        out = pipe(prompt=prompt,
                   negative_prompt=config.NEGATIVE_PROMPT,
                   image=draft,
                   mask_image=masks.inpaint,
                   height=size, width=size,
                   num_inference_steps=config.REFINE_STEPS,
                   strength=strength).images[0]
        out = add_ground_shadow(out, masks.product)
        pre_product = out           # 제품 합성 직전 상태 (z_order="behind"용, 아래 반환 참고)
        product_mask = masks.product
        out = composite_product(base, out, masks.product)
    else:
        from diffusers import StableDiffusionXLImg2ImgPipeline
        key = f"{config.REFINE_MODEL}_img2img"
        if key not in _pipes:
            spec = config.MODELS[config.REFINE_MODEL]
            pipe = StableDiffusionXLImg2ImgPipeline.from_pretrained(
                spec["text2img"], torch_dtype=torch.float16,
                variant=spec["variant"])
            if config.USE_CPU_OFFLOAD:
                pipe.enable_model_cpu_offload()
                pipe.vae.enable_slicing()
                pipe.vae.enable_tiling()
            else:
                pipe.to("cuda")
            _pipes[key] = pipe
        # strength 0.35 부근이 구도 유지와 디테일 개선의 균형점 (실험 결과)
        out = _pipes[key](prompt=prompt, image=draft,
                          strength=min(strength, 0.35),
                          num_inference_steps=config.REFINE_STEPS).images[0]
        # img2img 폴백 경로는 원본/마스크가 없어 제품을 따로 합성하지 않는다.
        # 따라서 "제품 뒤" 레이어라는 개념 자체가 성립하지 않으므로 None을 준다
        # (호출자가 z_order="behind" 요청을 명시적으로 거부할 수 있게 하기 위함).
        base = None
        pre_product = None
        product_mask = None

    layout = describe_product_bbox(masks.product) if original is not None else None
    return {
        "image": out,
        # z_order="behind" 재료. 자세한 설명은 _flat_background_refine 참고.
        "pre_product": pre_product,
        "base": base,
        "product_mask": product_mask,
        "meta": {"elapsed": round(time.time() - started, 2),
                 "model": config.REFINE_MODEL,
                 "strength": strength,
                 "layout": layout,
                 "diffusion": True,
                 "background_mode": "ai",
                 "resolution": size},
    }
