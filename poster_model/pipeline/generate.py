"""시안 생성(1단계) 및 고품질 렌더링(2단계)."""

import time

import torch
from PIL import Image

from . import config
from .masking import (add_ground_shadow, composite_product, describe_product_bbox,
                      make_masks, prepare_image, render_flat_background, resolve_background)

_pipes = {}


def _load(kind: str, task: str):
    """kind: 'sd15' | 'sdxl', task: 'inpaint' | 'text2img'."""
    key = f"{kind}_{task}"
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
                            background_mode, bg_colors, gradient_direction) -> dict:
    """background_mode가 solid/gradient일 때: diffusion을 완전히 생략하고
    PIL로만 배경을 채운 뒤 기존 그림자/원본 합성 로직을 그대로 재사용한다.
    """
    if image is None:
        raise ValueError("solid/gradient 배경 모드는 제품 이미지(image)가 필요합니다.")

    size = config.MODELS[config.DRAFT_MODEL]["size"]
    started = time.time()

    base, masks, mode = prepare_image(image, size)
    bg_specs = resolve_background(background_mode, bg_colors, gradient_direction,
                                  category, num_images)

    images = []
    for spec in bg_specs:
        flat = render_flat_background(size, spec["colors"], spec.get("direction"))
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
                 "resolution": size},
    }


def generate_drafts(image=None,
                    prompt: str = None,
                    category: str = None,
                    num_images: int = None,
                    seeds: list[int] = None,
                    background_mode: str = "ai",
                    bg_colors: list[str] = None,
                    gradient_direction: str = None) -> dict:
    """1단계: 시안 여러 장 생성.

    image가 있으면 inpaint(제품 보존), 없으면 text2img.
    background_mode="ai"(기본값)면 기존 diffusion 경로를 그대로 사용한다.
    "solid"/"gradient"면 diffusion을 생략하고 PIL로만 배경을 채운다.
    """
    num_images = num_images or config.NUM_DRAFTS

    if background_mode != "ai":
        return _flat_background_drafts(image, category, num_images,
                                       background_mode, bg_colors, gradient_direction)

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


def _flat_background_refine(original, background: dict) -> dict:
    """background_mode가 solid/gradient일 때의 2단계.

    draft(768 시안)를 단순 확대하지 않고, 원본 이미지+마스크로 1024에서
    "동일한 배경 설정"을 다시 렌더링한다. diffusion은 호출하지 않는다.
    """
    if original is None:
        raise ValueError("solid/gradient 배경 refine에는 original(원본 이미지)이 필요합니다.")

    size = config.MODELS[config.REFINE_MODEL]["size"]
    started = time.time()

    base, masks, mode = prepare_image(original, size)
    flat = render_flat_background(size, background["colors"], background.get("direction"))
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
                 "resolution": size},
    }


def refine(draft: Image.Image,
           original=None,
           prompt: str = None,
           category: str = None,
           strength: float = None,
           background: dict = None) -> dict:
    """2단계: 선택한 시안을 고품질로 다시 렌더링.

    original(사용자 원본 사진)이 주어지면 제품 영역을 다시 보존한다.
    SDXL은 이미지 전체를 재해석하므로 이 단계가 없으면 제품이 변형된다.

    background가 주어지고 mode가 "solid"/"gradient"면 diffusion을 완전히
    생략한다(_flat_background_refine). background가 없거나 mode="ai"면
    기존 동작 그대로다.
    """
    if background and background.get("mode") in ("solid", "gradient"):
        return _flat_background_refine(original, background)

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
