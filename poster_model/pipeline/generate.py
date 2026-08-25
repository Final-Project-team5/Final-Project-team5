"""시안 생성(1단계) 및 고품질 렌더링(2단계)."""

import time

import numpy as np
import torch
from PIL import Image

from . import config
from . import layout
from . import pipe_lock
from . import prompt_budget
from .masking import (add_ground_shadow, composite_product, describe_product_bbox,
                      make_masks, place_product_on_canvas, prepare_image,
                      render_flat_background, resolve_background, rotate_product)

_pipes = {}


def _bbox_center_norm(product_mask, size_wh):
    """제품 bbox 중심의 정규화 좌표. as_public()의 x/y와 같은 규약이다."""
    W, H = size_wh
    a = np.array(product_mask.convert("L")) > 128
    ys, xs = np.where(a)
    if len(xs) == 0:
        raise ValueError("제품 마스크가 비어 있습니다.")
    bw, bh = int(xs.max()) - int(xs.min()) + 1, int(ys.max()) - int(ys.min()) + 1
    return (int(xs.min()) + bw / 2) / W, (int(ys.min()) + bh / 2) / H


def _place_rotated(base, masks, canvas_wh, cx_n, cy_n):
    """expand로 커진 프레임을 **원래 캔버스로 되돌린다.** 중심을 유지한다.

    1:1 AI 경로에는 placement 단계가 없어서 base를 그대로 diffusion에 넣는다.
    expand로 프레임이 커지면 출력 크기까지 달라지므로, 회전 경로에서만 여기서
    캔버스를 원복한다.

    배율은 **필요할 때만 줄인다.** 1.0으로 들어가면 그대로 쓰고, 회전으로 커진
    bbox가 캔버스를 벗어날 때만 이분 탐색으로 낮춘다. 확대는 하지 않는다.
    끝까지 들어가지 않으면 strict 검증이 거부한다(조용히 자르지 않는다).
    """
    def attempt(sf):
        p = layout.compute_placement(masks, canvas_wh, None,
                                     {"x": cx_n, "y": cy_n, "scale_factor": sf})
        return p, layout.validate_placement(masks, canvas_wh, p,
                                            strict=False)["ok"]

    place, ok = attempt(1.0)
    if not ok:
        lo, hi = 0.05, 1.0
        for _ in range(16):
            mid = (lo + hi) / 2
            cand, cand_ok = attempt(mid)
            if cand_ok:
                place, lo = cand, mid
            else:
                hi = mid
    layout.validate_placement(masks, canvas_wh, place, strict=True)
    return place_product_on_canvas(base, masks, canvas_wh, **place.as_kwargs())


def _prepare(src, size, apply_blur_margin: bool = True,
             rotation_deg: float = 0.0, fit_canvas=None):
    """prepare_image + (필요할 때만) 제품 회전.

    **rotation_deg == 0이면 prepare_image 결과를 그대로 돌려준다.** 회전 함수를
    거치지 않으므로 기존 경로와 픽셀 단위로 같다.

    회전이 있을 때만 fit="expand"를 **여기서 명시**한다. rotate_product 자체의
    기본값(source)은 바꾸지 않는다 — 전역 기본 동작을 건드리지 않기 위해서다.
    expand가 필요한 이유는 3:1/3:4가 blur margin을 끄기 때문에 제품이 소스
    프레임을 꽉 채운 채 회전하게 되고, 최종 캔버스에는 자리가 있는데도 거부되기
    때문이다.

    Args:
        fit_canvas: 지정하면 회전 후 그 캔버스로 되돌린다(중심 유지).
            **뒤에 placement 단계가 없는 경로(1:1 AI)만 지정한다.**
            3:1/3:4와 flat 경로는 이후 resolve_placement가 회전된 마스크를
            다시 재서 배치하므로 지정하지 않는다 — 여기서 되돌리면 리샘플이
            두 번 일어난다.
    """
    base, masks, mode = prepare_image(src, size,
                                      apply_blur_margin=apply_blur_margin)
    if rotation_deg:
        # 회전 **전** 중심을 기록해 둔다. expand로 프레임이 커지면 같은 픽셀
        # 좌표라도 정규화 값이 달라지기 때문이다.
        cx_n, cy_n = _bbox_center_norm(masks.product, base.size)
        base, masks = rotate_product(base, masks, rotation_deg, fit="expand")
        if fit_canvas is not None:
            base, masks = _place_rotated(base, masks, fit_canvas, cx_n, cy_n)
    return base, masks, mode


def _load(kind: str, task: str, tiling: bool = True):
    """kind: 'sd15' | 'sdxl', task: 'inpaint' | 'text2img' | 'img2img'.

    tiling=False면 VAE tiling을 끈 **별도 인스턴스**를 따로 캐시한다.
    같은 객체의 tiling을 요청마다 켰다 껐다 하면 동시 요청이 서로 간섭하므로
    상태를 토글하지 않고 인스턴스를 나눈다. 기본값이 True라 기존 호출부는
    동작이 그대로다.

    'img2img'는 refine(original=None) 경로가 쓰는 SDXL img2img다. 그 경로는
    아래에서 `_pipes[f"{REFINE_MODEL}_img2img"]`를 직접 만들어 쓰는데, 여기서
    만드는 키·객체가 그것과 **완전히 같도록** 맞춰 두었다. 그래야 warmup에서
    미리 올려두면 요청 경로가 그대로 캐시를 타고, 요청 경로 코드는 손대지
    않아도 된다.

        키       f"{kind}_{task}"  →  "sdxl_img2img"      (기존과 동일)
        repo     MODELS[kind]["text2img"]                 (img2img 항목이 없다)
        offload  enable_model_cpu_offload + slicing + tiling  (기존과 동일)
    """
    key = f"{kind}_{task}" if tiling else f"{kind}_{task}_notile"
    if key in _pipes:
        return _pipes[key]

    from diffusers import (StableDiffusionInpaintPipeline,
                           StableDiffusionPipeline,
                           StableDiffusionXLImg2ImgPipeline,
                           StableDiffusionXLInpaintPipeline,
                           StableDiffusionXLPipeline)

    spec = config.MODELS[kind]
    cls = {
        ("sd15", "inpaint"): StableDiffusionInpaintPipeline,
        ("sd15", "text2img"): StableDiffusionPipeline,
        ("sdxl", "inpaint"): StableDiffusionXLInpaintPipeline,
        ("sdxl", "text2img"): StableDiffusionXLPipeline,
        ("sdxl", "img2img"): StableDiffusionXLImg2ImgPipeline,
    }[(kind, task)]

    kwargs = {"torch_dtype": torch.float16}
    if spec["variant"]:
        kwargs["variant"] = spec["variant"]
    if kind == "sd15":
        kwargs["safety_checker"] = None

    # MODELS에는 img2img 항목이 없다. img2img는 text2img 가중치를 그대로 쓴다
    # (refine의 기존 인라인 로딩과 같은 repo).
    repo = spec["text2img"] if task == "img2img" else spec[task]
    pipe = cls.from_pretrained(repo, **kwargs)

    # 가중치를 어디에 둘지.
    if config.USE_CPU_OFFLOAD:
        pipe.enable_model_cpu_offload()   # 호스트 RAM 상주, 필요할 때만 GPU로
    else:
        pipe.to("cuda")                   # VRAM 상주

    # VAE 메모리 대책은 위 선택과 **무관하다**. 디코딩 단계에서 큰 중간 텐서가
    # 잡히는 것을 나눠 처리하는 것이라, 가중치가 어디 있든 필요하다.
    #
    # 이전에는 이 두 줄이 offload 분기 안에 있어서, offload를 끄면 slicing/tiling까지
    # 같이 꺼졌다. 그러면 RAM 문제를 고치면서 VRAM 디코딩에서 새로 터진다.
    # 관심사가 다르므로 분리해 둔다.
    pipe.vae.enable_slicing()
    if tiling:
        pipe.vae.enable_tiling()   # SDXL inpaint 디코딩 단계 OOM 방지

    _pipes[key] = pipe
    return pipe


def warmup():
    """서버 시작 시 호출. 요청마다 로딩되는 것을 방지한다.

    실제 요청이 타는 _load 조합을 전부 덮는다. 아래 두 개가 빠져 있어서
    해당 경로의 **첫 요청**이 모델 로딩 시간을 그대로 물고 있었다.

        sd15_inpaint_notile   3:1 draft            _load(DRAFT, "inpaint", tiling=False)
        sdxl_img2img          refine(original=None) 서비스형 T2I 시안의 refine

    캐시 키가 요청 경로와 같아야 의미가 있다. 요청 경로의 인자를 그대로 쓴다.

        _ai_nonsquare_drafts   _load(config.DRAFT_MODEL, "inpaint", tiling=False)
        refine(original=None)  _pipes[f"{config.REFINE_MODEL}_img2img"]
                               → _load(config.REFINE_MODEL, "img2img") 와 같은 키

    SDXL 계열은 KEEP_BOTH_LOADED 아래 둔다. img2img 도 별도 SDXL 전체를
    올리므로(가중치를 공유하지 않는다) 같은 플래그로 묶는 것이 일관된다.

    ## sdxl_img2img 만 실제 추론까지 한 번 돌린다

    _load 는 파이프라인 객체를 만들 뿐이라, 그 뒤에도 **첫 추론**에 큰 비용이
    남았다. GCP(L4) 실측:

        첫 refine   73.48s  →  11.67s      기동 시 4 step 추론 1회를 넣었을 때

    총 시간이 주는 것이 아니라 **사용자가 기다리는 자리에서 서버 기동으로
    옮기는 것**이다. systemd 로 상시 실행하는 구조라 그쪽이 맞다.

    다른 파이프라인에는 넣지 않는다. draft(SD1.5) 쪽 first-call 비용은 약
    2.5초로 작아 기동 시간을 늘릴 만한 이득이 없었다.

    step 수 · strength 는 실험에서 검증된 값을 그대로 쓴다(4 step / 0.35).
    **요청 경로의 REFINE_STEPS / REFINE_STRENGTH 는 건드리지 않는다.**
    여기서 만든 이미지는 버린다.

    이 추론 한 번만 fail-open 이다. 성능 최적화지 기동 조건이 아니므로,
    실패해도 서버는 뜨고 첫 요청만 느려진다. **_load 는 감싸지 않는다** —
    모델을 못 올리는 것은 최적화 실패가 아니라 기동 실패이므로 그대로 올린다.
    """
    _load(config.DRAFT_MODEL, "inpaint")
    _load(config.DRAFT_MODEL, "text2img")
    _load(config.DRAFT_MODEL, "inpaint", tiling=False)
    if config.KEEP_BOTH_LOADED:
        _load(config.REFINE_MODEL, "inpaint")
        pipe = _load(config.REFINE_MODEL, "img2img")
        size = config.MODELS[config.REFINE_MODEL]["size"]
        try:
            pipe(prompt="warmup",
                 image=Image.new("RGB", (size, size), (255, 255, 255)),
                 strength=0.35, num_inference_steps=4)
        except Exception as e:      # fail-open. 첫 요청이 느려질 뿐이다
            print(f"[warmup] sdxl_img2img 추론 warmup 실패 — 무시하고 계속합니다: "
                  f"{type(e).__name__}: {e}")


def unload(kind: str = None):
    """메모리 확보용. kind 미지정 시 전체 해제."""
    import gc
    keys = list(_pipes) if kind is None else [
        k for k in _pipes if k.startswith(kind)]
    for k in keys:
        del _pipes[k]
    gc.collect()
    torch.cuda.empty_cache()


def resolve_prompt(prompt: str = None, category: str = None,
                   subject_kind: str = "product",
                   model_kind: str = None) -> str:
    """품질 baseline + 사용자 prompt + 경로별 suffix를 이어붙인다.

    이전에는 `prompt or PROMPT_TEMPLATES[category]` 였다. 사용자 prompt가
    있으면 카테고리 품질 지시가 통째로 사라졌다. 이제는 대체하지 않고
    baseline 뒤에 붙인다.

    subject_kind
        "product"  카테고리 품질 baseline + 제품 유도 접미사
        "service"  서비스 품질 baseline  + 제품 접미사 없음

        서비스형에 "single product only" / "shadow under product"가 붙던
        문제를 여기서 닫는다. category=None -> goods fallback 경로도 타지
        않는다. 기본값이 "product"라 subject_kind를 안 보내는 기존 호출은
        분기 기준에서 종전과 같은 경로를 탄다.

    model_kind
        "sd15" / "sdxl" — 이 모델의 CLIP tokenizer 기준으로 토큰 예산을 맞춘다.
        baseline과 제품 constraint는 보호하고, 넘치면 사용자 prompt의 뒤쪽부터
        버린다. None이면 종전과 같이 그대로 이어붙인다(하위호환).

        이전에는 길어지면 맨 뒤의 SHADOW/ISOLATION 접미사가 먼저 잘렸다.
        실서버 로그(95 > 77)에서 실제로 그 부분이 truncation 됐다. 이제 그
        자리는 보호 영역이라 잘리지 않는다.

        SDXL은 text encoder가 둘이라 tokenizer/tokenizer_2 중 큰 값을 쓴다.
    """
    if subject_kind == "service":
        base = config.SERVICE_QUALITY_BASELINE
        extras = []                      # 제품 전제 접미사를 붙이지 않는다
    else:
        base = config.PROMPT_TEMPLATES[category or config.DEFAULT_CATEGORY]
        # 그림자/단일 제품 유도 문구를 붙인다. 실험 중 SHADOW_PROMPT_SUFFIX=""처럼
        # 비워서 끌 수 있도록, 빈 문자열은 건너뛰고 값이 있는 것만 이어붙인다.
        extras = [s for s in (config.SHADOW_PROMPT_SUFFIX,
                              config.ISOLATION_PROMPT_SUFFIX) if s]

    user = (prompt or "").strip()

    if model_kind is not None:
        try:
            fitted = prompt_budget.fit_prompt(
                base, user, extras,
                count=prompt_budget.counter_for(model_kind))
        except Exception as e:
            # 예산 계산 실패가 생성을 막지 않는다. 종전 동작으로 내려간다.
            print(f"[prompt_budget] skipped: {type(e).__name__}: {e}")
        else:
            r = fitted["report"]
            if r["dropped_segments"] or not r["within_budget"]:
                print(f"[prompt_budget] {subject_kind}/{model_kind} "
                      f"tokens={fitted['tokens']} kept={r['kept_segments']} "
                      f"dropped={r['dropped_segments']} {r['dropped']}")
            return fitted["prompt"]

    parts = [base] + ([user] if user else []) + extras
    return ", ".join(parts)


def _flat_background_drafts(image, category, num_images,
                            background_mode, bg_colors, gradient_direction,
                            aspect_ratio=None, placement_override=None,
                            rotation_deg: float = 0.0) -> dict:
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

    base, masks, mode = _prepare(image, size, apply_blur_margin=use_margin,
                                 rotation_deg=rotation_deg)
    place, place_public = layout.resolve_placement(masks, canvas, aspect_ratio,
                                                   placement_override)
    base, masks = place_product_on_canvas(base, masks, canvas, **place.as_kwargs())
    bg_specs = resolve_background(background_mode, bg_colors, gradient_direction,
                                  category, num_images)

    images = []
    for spec in bg_specs:
        flat = render_flat_background(canvas, spec["colors"], spec.get("direction"))
        shadowed = add_ground_shadow(flat, masks.product,
                                     rotation_deg=rotation_deg)
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
                         aspect_ratio, rotation_deg: float = 0.0,
                         subject_kind: str = "product") -> dict:
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
    prompt = resolve_prompt(prompt, category, subject_kind, config.DRAFT_MODEL)

    if seeds is None:
        seeds = torch.randint(0, 2**31 - 1, (num_images,)).tolist()
    gens = [torch.Generator("cuda").manual_seed(s) for s in seeds]
    started = time.time()

    base, masks, mode = _prepare(image, size, apply_blur_margin=use_margin,
                                 rotation_deg=rotation_deg)
    (base_cv, masks_cv), (base_gen, masks_gen), public = _place_both(
        base, masks, canvas, gen, aspect_ratio)

    # VAE tiling을 끈 인스턴스를 쓴다. 3:1 draft(1536x512)에서 좌측 가장자리에
    # 색 띠가 생기는 것이 seed 고정 A/B로 확인됐다(ON 19px / OFF 0px, ON 재현 일치).
    # 1:1은 같은 조건에서 재현되지 않아 기존 인스턴스를 그대로 쓴다.
    # 실험 기록: outputs/verification/api/ai_nonsquare_smoke/tilingab_*_summary.txt
    with pipe_lock.pipe_guard("nonsquare_drafts"):
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
    shadowed = [add_ground_shadow(o, masks_cv.product,
                                  rotation_deg=rotation_deg) for o in outs]
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
                         aspect_ratio, rotation_deg: float = 0.0,
                         subject_kind: str = "product") -> dict:
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
    prompt = resolve_prompt(prompt, category, subject_kind, config.REFINE_MODEL)
    strength = config.REFINE_STRENGTH if strength is None else strength
    started = time.time()

    base, masks, _mode = _prepare(original, size,
                                  apply_blur_margin=use_margin,
                                  rotation_deg=rotation_deg)
    (base_cv, masks_cv), (base_gen, masks_gen), public = _place_both(
        base, masks, canvas, gen, aspect_ratio)

    draft_in = draft.convert("RGB").resize(gen, Image.LANCZOS)
    with pipe_lock.pipe_guard("nonsquare_refine"):
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
    out = add_ground_shadow(out, masks_cv.product, rotation_deg=rotation_deg)
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
                    placement_override: dict = None,
                    rotation_deg: float = 0.0,
                    subject_kind: str = "product") -> dict:
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
                                       aspect_ratio, placement_override,
                                       rotation_deg=rotation_deg)
    if aspect_ratio not in (None, "1:1"):
        # 비정사각 AI는 별도 경로. 아래 1:1 코드는 그대로 둔다.
        return _ai_nonsquare_drafts(image, prompt, category, num_images, seeds,
                                    aspect_ratio, rotation_deg=rotation_deg,
                                    subject_kind=subject_kind)

    prompt = resolve_prompt(prompt, category, subject_kind, config.DRAFT_MODEL)
    size = config.MODELS[config.DRAFT_MODEL]["size"]

    if seeds is None:
        seeds = torch.randint(0, 2**31 - 1, (num_images,)).tolist()
    gens = [torch.Generator("cuda").manual_seed(s) for s in seeds]

    started = time.time()

    if image is not None:
        # 1:1 AI 경로는 뒤에 placement 단계가 없다. 회전 시 프레임이
        # 커지지 않도록 여기서 원래 캔버스로 되돌린다(중심 유지).
        base, masks, mode = _prepare(image, size, rotation_deg=rotation_deg,
                                     fit_canvas=(size, size))
        with pipe_lock.pipe_guard("drafts_inpaint"):
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
        shadowed = [add_ground_shadow(o, masks.product,
                                     rotation_deg=rotation_deg) for o in outs]
        images = [composite_product(base, o, masks.product) for o in shadowed]
        meta_extra = {"mode": mode, "area_ratio": round(masks.area_ratio, 3),
                     "layout": describe_product_bbox(masks.product)}
    else:
        with pipe_lock.pipe_guard("drafts_text2img"):
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
                            aspect_ratio=None, placement_override=None,
                            rotation_deg: float = 0.0) -> dict:
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

    base, masks, mode = _prepare(original, size, apply_blur_margin=use_margin,
                                 rotation_deg=rotation_deg)
    place, place_public = layout.resolve_placement(masks, canvas, aspect_ratio,
                                                   placement_override)
    base, masks = place_product_on_canvas(base, masks, canvas, **place.as_kwargs())
    flat = render_flat_background(canvas, background["colors"], background.get("direction"))
    shadowed = add_ground_shadow(flat, masks.product,
                                     rotation_deg=rotation_deg)
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
           placement_override: dict = None,
           rotation_deg: float = 0.0,
           subject_kind: str = "product") -> dict:
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
                                       aspect_ratio, placement_override,
                                       rotation_deg=rotation_deg)
    if aspect_ratio not in (None, "1:1"):
        # 비정사각 AI는 별도 경로. 아래 1:1 코드는 그대로 둔다.
        return _ai_nonsquare_refine(draft, original, prompt, category, strength,
                                    aspect_ratio, rotation_deg=rotation_deg,
                                    subject_kind=subject_kind)

    prompt = resolve_prompt(prompt, category, subject_kind, config.REFINE_MODEL)
    strength = config.REFINE_STRENGTH if strength is None else strength
    size = config.MODELS[config.REFINE_MODEL]["size"]

    draft = draft.convert("RGB").resize((size, size), Image.LANCZOS)
    started = time.time()

    if original is not None:
        base, masks, _ = _prepare(original, size, rotation_deg=rotation_deg,
                                  fit_canvas=(size, size))
        with pipe_lock.pipe_guard("refine_inpaint"):
            pipe = _load(config.REFINE_MODEL, "inpaint")
            out = pipe(prompt=prompt,
                       negative_prompt=config.NEGATIVE_PROMPT,
                       image=draft,
                       mask_image=masks.inpaint,
                       height=size, width=size,
                       num_inference_steps=config.REFINE_STEPS,
                       strength=strength).images[0]
        out = add_ground_shadow(out, masks.product, rotation_deg=rotation_deg)
        pre_product = out           # 제품 합성 직전 상태 (z_order="behind"용, 아래 반환 참고)
        product_mask = masks.product
        out = composite_product(base, out, masks.product)
    else:
        from diffusers import StableDiffusionXLImg2ImgPipeline
        key = f"{config.REFINE_MODEL}_img2img"
        # 인스턴스 생성부터 호출까지 한 구간이다. 생성을 밖에 두면 두 스레드가
        # 같은 key의 pipeline을 중복 생성해 불필요한 VRAM 사용이 발생할 수 있다.
        with pipe_lock.pipe_guard("refine_img2img"):
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
