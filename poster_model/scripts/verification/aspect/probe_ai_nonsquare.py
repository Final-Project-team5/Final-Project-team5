"""A4 — AI 배경 비정사각 생성 실험 (GPU 필요).

production을 전혀 건드리지 않는다. pipeline의 기존 함수만 가져다 쓰고 diffusion
파이프는 **직접** 호출한다. generate_drafts / refine을 타지 않으므로 A3의
`non-square + ai -> 400` 제한도 그대로다.

트랙
    0   메모리 계측 진단. Stage 1의 reserved 16.7GB가 무엇인지 확인만 한다
    1   Stage 1 (완료) — feasibility. 재현용으로 남겨둔다
    A   3:1 제품 확대 + 생성 해상도 후보 비교
    B   3:4 object continuation이 투명 제품에 몰리는지
    C   glass 3:4의 "제품 위 여백" 가설 (placement override만 사용)

측정 설계
    - 케이스 1개당 프로세스 1개. 앞 실행의 단편화가 뒤 실행 peak에 섞이지 않는다
    - 모델 로드 시간과 추론 시간을 분리한다
    - CUDA peak stats를 모델 로드 후 / 추론 직전에 reset한다
    - 마지막 denoising step에서 다시 reset해 UNet peak와 VAE decode peak를 나눈다

Track A의 해상도 비교 규칙
    생성 해상도가 달라도 **최종 캔버스(3:1 refine 기준 3072x1024)로 맞춘 뒤**
    같은 조건에서 지표를 잰다. 제품은 마지막에 최종 해상도 원본으로 composite
    하므로 제품 선명도와 배경 생성 해상도가 분리된다.
    업스케일은 LANCZOS 하나로 고정한다(이번 단계에서 알고리즘을 튜닝하지 않는다).

실행 (프로젝트 루트에서)
    source .venv/bin/activate
    PYTHONPATH="$PWD" python scripts/verification/aspect/probe_ai_nonsquare.py --dry-run
    PYTHONPATH="$PWD" python scripts/verification/aspect/probe_ai_nonsquare.py --track 0 --all
    PYTHONPATH="$PWD" python scripts/verification/aspect/probe_ai_nonsquare.py --track B --all

결과: outputs/verification/aspect/ai_nonsquare/
    probe_log.jsonl   케이스당 1줄. 실패해도 남는다
    <case>.png        최종 결과 / <case>_raw.png 합성 전 / <case>_band.png 상단 띠
    summary_<track>.txt
"""
import argparse
import inspect
import json
import os
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT_DIR = ROOT / "outputs" / "verification" / "aspect" / "ai_nonsquare"
LOG = OUT_DIR / "probe_log.jsonl"

CATEGORY = {"glass": "goods", "cake": "food", "cosmetic": "beauty",
            "snack": "food", "monster_side": "food", "monster_top": "food"}
STAGES = {"draft": ("sd15", 768), "refine": ("sdxl", 1024)}
SEED = 12345

# Track D — 복잡한 배경 프롬프트. R1/R2에서 **완전히 동일하게** 사용한다.
COMPLEX_PROMPTS = {
    "P1": (  # 자연물·소품 디테일: 미세 텍스처가 업스케일에서 뭉개지는지
        "advertising product photo on a rustic oak table with visible wood grain, "
        "rough stone slab surface, scattered fresh basil leaves, a small potted herb, "
        "tiny crumbs and small ceramic props, warm side lighting, "
        "shallow depth of field with soft bokeh in the background, "
        "fine texture, highly detailed"),
    "P2": (  # 구조적·기하학적 디테일: 경계선과 반복 패턴이 깨지는지
        "advertising studio scene with stepped stone pedestals, geometric acrylic props, "
        "sharp straight edges and clean curved surfaces, layered platforms, "
        "strong directional lighting with crisp shadow boundaries, "
        "repeating tile pattern on the floor, minimal color palette, highly detailed"),
}
UPSCALE = "LANCZOS"          # 고정. 이번 단계에서 알고리즘을 비교하지 않는다


@dataclass
class Case:
    cid: str
    track: str
    image: str
    stage: str                  # draft | refine
    ratio: str                  # 1:1 | 3:1 | 3:4
    gen_short: int              # diffusion을 돌릴 짧은 변
    final_short: int            # 지표를 재고 결과를 저장할 짧은 변
    bleed: str = "A"            # A=검정 캔버스, B=블러 캔버스
    y_delta: float = 0.0        # placement y 조정 (0.0 = 서버 자동값)
    prompt: str = None          # None이면 카테고리 기본 프롬프트
    draft_from: str = None      # refine 입력으로 쓸 draft 케이스 id (파일명 직접 지정)
    note: str = ""

    @property
    def upscaled(self):
        return self.gen_short != self.final_short


# --------------------------------------------------------------- case matrix

def matrix(track: str) -> list:
    """트랙별 케이스를 행 단위로 확정한다. 총 실행 횟수가 여기서 결정된다."""
    C = []

    if track == "0":
        # 메모리 계측 진단만. glass 하나로 baseline과 최대 부하를 1회씩.
        C += [Case("t0_refine_1x1", "0", "glass", "refine", "1:1", 1024, 1024,
                   note="baseline"),
              Case("t0_refine_3x1", "0", "glass", "refine", "3:1", 1024, 1024,
                   note="최대 부하")]

    elif track == "1":
        # Stage 1 (완료). 재현용.
        for stage in ("draft", "refine"):
            short = STAGES[stage][1]
            for ratio in ("1:1", "3:1", "3:4"):
                for bleed in (("A",) if ratio == "1:1" else ("A", "B")):
                    C.append(Case(f"t1_{stage}_{ratio.replace(':', 'x')}_{bleed}",
                                  "1", "glass", stage, ratio, short, short, bleed))

    elif track == "A":
        # 3:1. 생성 해상도 후보를 모두 최종 규격(3072x1024)으로 맞춰 비교한다.
        #
        # refine R0(3072x1024 직접 생성)는 **제외**한다. Track 0 계측에서
        # inference 1430.51s (UNet 652.28 / decode 778.23), peak reserved
        # 16.664GB로 보고된 VRAM 11.994GB를 넘었고, Stage 1의 같은 계열이
        # 42~53s였던 것과 비교해 실행시간 변동성도 컸다. 메모리 이동 방식을
        # spill로 단정하지는 않되, 서비스 관점에서 후보에서 뺀다.
        # R0의 feasibility/cost 근거는 Stage 1 glass 결과 + Track 0 결과를 쓴다.
        RES_REFINE = {"R1": 768, "R2": 576}                  # R0 제외
        RES_DRAFT = {"R0": 768, "R1": 512, "R2": 384}        # draft는 그대로
        # refine: 제품 3종 x 후보 2개 = 6  (품질 판단의 본체)
        for img in ("cake", "snack", "cosmetic"):
            for tag, gen in RES_REFINE.items():
                C.append(Case(f"tA_refine_{img}_{tag}", "A", img, "refine", "3:1",
                              gen, 1024, note=tag))
        # draft: 1종 x 후보 3개 = 3  (draft는 빠르므로 R0를 포함해 경향 확인)
        for tag, gen in RES_DRAFT.items():
            C.append(Case(f"tA_draft_cake_{tag}", "A", "cake", "draft", "3:1",
                          gen, 768, note=tag))

    elif track == "B":
        # 3:4. 투명성과 세로 길이를 분리한다.
        #   monster_side = 불투명 + 세로형 (glass의 대조군)
        for img in ("snack", "cake", "cosmetic", "monster_side"):
            for stage in ("draft", "refine"):
                short = STAGES[stage][1]
                C.append(Case(f"tB_{stage}_{img}_A", "B", img, stage, "3:4",
                              short, short, "A"))
        # 대조군에서 bleed A/B가 여전히 무차별인지 한 제품만 재확인
        for stage in ("draft", "refine"):
            short = STAGES[stage][1]
            C.append(Case(f"tB_{stage}_monster_side_B", "B", "monster_side",
                          stage, "3:4", short, short, "B",
                          note="A/B 재확인"))

    elif track == "C":
        # glass 3:4의 "제품 위 여백" 가설. placement y만 바꾼다.
        for tag, dy in (("auto", 0.0), ("up10", -0.10), ("up20", -0.20)):
            C.append(Case(f"tC_refine_glass_{tag}", "C", "glass", "refine", "3:4",
                          1024, 1024, "A", dy, note=f"y{dy:+.2f}"))

    elif track == "D":
        # 3:1 refine R2를 production 후보로 확정하기 위한 최종 소규모 검증.
        #
        # **refine 입력 draft를 먼저 만든다.** Track A/B의 refine은 입력 draft를
        # 찾지 못해 flat(단색) stand-in으로 돌았고(로그의 draft_source=flat_stand_in),
        # strength=0.35로는 단색 입력이 복잡한 배경이 되지 않는다. 그래서 배경E가
        # 0.24~1.54(실제 draft 입력일 때는 16~24)에 그쳤다. 프롬프트만 바꿔서는
        # 복잡한 배경을 볼 수 없으므로 draft 2회를 먼저 돌린다.
        #
        # draft는 R0(2304x768 직접)로 만든다. 두 refine 후보에 **같은 입력**을 주어
        # refine 해상도만 변수로 남기기 위해서다(production 잠정안은 draft R1이지만,
        # 여기서는 입력 품질을 변수에서 제외하는 쪽이 비교에 유리하다).
        for pk in ("P1", "P2"):
            C.append(Case(f"tD_draft_snack_{pk}", "D", "snack", "draft", "3:1",
                          768, 768, prompt=COMPLEX_PROMPTS[pk],
                          note=f"{pk} 입력 생성"))
        for pk in ("P1", "P2"):
            for tag, gen in (("R1", 768), ("R2", 576)):
                C.append(Case(f"tD_refine_snack_{pk}_{tag}", "D", "snack", "refine",
                              "3:1", gen, 1024, prompt=COMPLEX_PROMPTS[pk],
                              draft_from=f"tD_draft_snack_{pk}",
                              note=f"{pk} / {tag}"))

    else:
        raise SystemExit(f"알 수 없는 트랙: {track}")
    return C


ALL_TRACKS = ["0", "1", "A", "B", "C", "D"]


# --------------------------------------------------------------- 진단 수집

def nvidia_smi():
    try:
        r = subprocess.run(["nvidia-smi",
                            "--query-gpu=name,memory.used,memory.total",
                            "--format=csv,noheader,nounits"],
                           capture_output=True, text=True, timeout=10)
        name, used, total = [x.strip() for x in r.stdout.strip().splitlines()[0].split(",")]
        return {"name": name, "used_mb": int(used), "total_mb": int(total)}
    except Exception:
        return None


def device_info(torch):
    """GPU와 allocator 환경. reserved 지표를 해석하려면 이게 함께 있어야 한다."""
    d = {"gpu_name": None, "total_memory_gb": None, "mem_get_info_gb": None,
         "allocator_backend": None,
         "PYTORCH_CUDA_ALLOC_CONF": os.environ.get("PYTORCH_CUDA_ALLOC_CONF"),
         "torch_version": torch.__version__,
         "cuda_version": getattr(torch.version, "cuda", None)}
    if not torch.cuda.is_available():
        return d
    p = torch.cuda.get_device_properties(0)
    free, total = torch.cuda.mem_get_info()
    d.update(gpu_name=p.name,
             total_memory_gb=round(p.total_memory / 2 ** 30, 3),
             mem_get_info_gb={"free": round(free / 2 ** 30, 3),
                              "total": round(total / 2 ** 30, 3)})
    try:
        d["allocator_backend"] = torch.cuda.get_allocator_backend()
    except Exception:
        pass
    return d


def alloc_counters(torch):
    try:
        s = torch.cuda.memory_stats()
        return {"num_alloc_retries": s.get("num_alloc_retries"),
                "num_ooms": s.get("num_ooms")}
    except Exception:
        return {"num_alloc_retries": None, "num_ooms": None}


# --------------------------------------------------------------- 캔버스 준비

def build_inputs(image_name, ratio, short, bleed, y_delta=0.0, force_public=None):
    """소스 준비 → W×H 캔버스 이동. production 함수만 사용한다.

    force_public이 주어지면 그 정규화 배치를 override로 적용한다. 생성 캔버스와
    최종 캔버스에서 **같은 상대 배치**를 쓰기 위한 장치다(해상도가 다르면
    자동 계산 결과가 미세하게 달라진다).
    """
    from PIL import Image, ImageFilter
    import numpy as np
    from pipeline import config, layout
    from pipeline.masking import place_product_on_canvas, prepare_image

    rk = None if ratio == "1:1" else ratio
    canvas, use_margin = layout.plan_canvas(rk, short)
    src = ROOT / "image" / f"{image_name}.jpg"
    if not src.exists():
        raise FileNotFoundError(f"image/{image_name}.jpg 가 없습니다.")

    base, masks, mode = prepare_image(str(src), short, apply_blur_margin=use_margin)

    override = dict(force_public) if force_public else None
    if y_delta:
        auto = layout.compute_placement(masks, canvas, rk)
        pub = auto.as_public(canvas)
        override = {"scale_factor": pub["scale_factor"], "x": pub["x"],
                    "y": round(pub["y"] + y_delta, 4)}
    if override:
        override = {k: override[k] for k in ("scale_factor", "x", "y")
                    if k in override}

    # y를 옮긴 위치도 기존 배치 검증을 통과해야 한다. 통과 못하면 케이스를 버린다.
    place = layout.compute_placement(masks, canvas, rk, override)
    layout.validate_placement(masks, canvas, place, strict=True)
    base_cv, masks_cv = place_product_on_canvas(base, masks, canvas,
                                                **place.as_kwargs())

    if bleed == "B" and canvas != base.size:
        bg = base.resize(canvas, Image.LANCZOS).filter(
            ImageFilter.GaussianBlur(config.BG_BLUR))
        base_cv = Image.composite(base_cv, bg, masks_cv.product.convert("L"))

    return {"canvas": canvas, "base": base_cv, "masks": masks_cv,
            "placement": place, "public": place.as_public(canvas),
            "prepare_mode": mode, "blur_margin": use_margin,
            "source_objects": count_objects(
                np.array(masks.product.convert("L")) > 128, base.size)}


def count_objects(binary, size_wh, min_ratio=0.01):
    """면적이 캔버스의 min_ratio 이상인 연결요소 수. duplication **프록시**."""
    import cv2
    import numpy as np
    n, _l, stats, _c = cv2.connectedComponentsWithStats(
        binary.astype(np.uint8), connectivity=8)
    thr = size_wh[0] * size_wh[1] * min_ratio
    return int(sum(1 for i in range(1, n) if stats[i, cv2.CC_STAT_AREA] >= thr))


# --------------------------------------------------------------- 품질 지표

def quality_metrics(raw_final, product_mask, out_prefix, band_ratio=0.20):
    """모든 후보를 **최종 캔버스로 맞춘 뒤** 같은 조건에서 잰다.

    continuation은 제품 **위아래 양쪽**을 잰다. Track C에서 제품을 위로 올리자
    상단 continuation은 줄었지만 넓어진 아래 여백에 유리 바닥이 새로 생겨,
    상단만 보면 "개선"으로 보이는 문제가 실측으로 확인됐다.

    전부 프록시다. 자동 판정에 쓰지 않는다. 판단은 _top_band.png / _bottom_band.png
    육안 확인과 함께 한다. 실측으로 확인된 한계가 셋 있다.

    1) 절대 임계를 걸 수 없다. 1:1 기준선이 상단 1.192인데 육안으로는 hallucination이
       없었다. 마스크 경계의 합성 블러와 배경 텍스처 때문에 baseline이 1.0~1.2에서 시작한다.
    2) 배경이 평탄하면 분모가 폭발적으로 작아진다. Track B refine에서 배경 에너지가
       0.41~1.54까지 떨어져(draft는 15~41) 육안상 아무 일도 없는데 ratio가 5~20으로 나왔다.
       **배경 조건이 다른 케이스끼리 ratio를 직접 비교하면 안 된다.**
    3) refine의 하단 띠에는 draft에서 넘어온 접지 그림자가 그대로 들어간다.
       Track B에서 하단 에너지가 제품 종류와 무관하게 6~8로 균일했고, band 이미지에서
       전부 그림자 타원이 확인됐다. 하단 ratio는 continuation이 아니라 그림자를 재고 있다.
       (draft는 입력에 그림자가 없어 이 문제가 없다)

    그래서 ratio와 함께 top/bottom/background_edge_energy 원값을 반드시 같이 본다.
    """
    import cv2
    import numpy as np
    from PIL import Image

    img = np.array(raw_final.convert("RGB"))
    gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY).astype(np.float32)
    H, W = gray.shape
    m = np.array(product_mask.convert("L")) > 128
    bg = ~cv2.dilate(m.astype(np.uint8), np.ones((16, 16), np.uint8)).astype(bool)

    out = {"background_laplacian_var": None, "horizontal_ncc_max": None,
           "top_continuation_ratio": None, "bottom_continuation_ratio": None,
           "top_band_edge_energy": None, "bottom_band_edge_energy": None,
           "background_edge_energy": None,
           "top_band_path": None, "bottom_band_path": None,
           # 호환용. 예전 로그의 continuation_ratio / band_path는 **상단만** 의미했다.
           "continuation_ratio": None, "band_edge_energy": None, "band_path": None,
           "continuation_note": "ratio는 상대 비교용 proxy. 절대 임계 판정 금지"}
    if bg.sum() < 100:
        return out

    lap = cv2.Laplacian(gray, cv2.CV_32F)
    out["background_laplacian_var"] = round(float(lap[bg].var()), 2)

    # 가로 자기유사도: 배경만 남기고 3등분해 서로 NCC. 좌우 반복 프록시.
    g = gray.copy()
    g[~bg] = float(gray[bg].mean())
    w3 = W // 3
    strips = []
    for i in range(3):
        t = g[:, i * w3:(i + 1) * w3]
        t = t - t.mean()
        sd = t.std()
        strips.append(t / sd if sd > 1e-6 else t)
    out["horizontal_ncc_max"] = round(
        max(float((strips[a] * strips[b]).mean()) for a, b in ((0, 1), (1, 2), (0, 2))), 4)

    ys, xs = np.where(m)
    if not len(xs):
        return out
    bx0, bx1 = int(xs.min()), int(xs.max())
    by0, by1 = int(ys.min()), int(ys.max())
    bh = by1 - by0 + 1
    sob = (np.abs(cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3))
           + np.abs(cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)))
    bge = float(sob[bg].mean())
    out["background_edge_energy"] = round(bge, 2)

    # 제품 bbox 위/아래로 각각 제품 높이의 band_ratio 만큼 띠를 떼어 본다.
    for side, y_from, y_to in (("top", max(0, by0 - int(bh * band_ratio)), by0),
                               ("bottom", by1 + 1,
                                min(H, by1 + 1 + int(bh * band_ratio)))):
        if y_to - y_from < 4:
            continue
        band = sob[y_from:y_to, bx0:bx1 + 1]
        e = float(band.mean())
        out[f"{side}_band_edge_energy"] = round(e, 2)
        if bge > 1e-6:
            out[f"{side}_continuation_ratio"] = round(e / bge, 3)
        bp = Path(f"{out_prefix}_{side}_band.png")
        Image.fromarray(img[y_from:y_to, bx0:bx1 + 1]).save(bp)
        out[f"{side}_band_path"] = str(bp.relative_to(ROOT))

    # 호환 필드 — 예전 이름은 상단을 가리킨다
    out["continuation_ratio"] = out["top_continuation_ratio"]
    out["band_edge_energy"] = out["top_band_edge_energy"]
    out["band_path"] = out["top_band_path"]
    return out


# --------------------------------------------------------------- 케이스 실행

def make_stand_in_draft(image_name, ratio, canvas, public, draft_from=None):
    """refine 입력용 draft. 같은 비율의 draft 결과가 있으면 재사용한다.

    없으면 flat(solid) 배경으로 대체한다. draft가 실패해도 refine feasibility를
    독립적으로 볼 수 있어야 하기 때문이다. 어느 쪽인지 draft_source로 남는다.
    """
    from PIL import Image
    if draft_from:
        # 케이스 id로 직접 지정. glob 추측에 의존하지 않는다.
        p = OUT_DIR / f"{draft_from}.png"
        if not p.exists():
            raise FileNotFoundError(
                f"refine 입력 draft가 없습니다: {p.name}. "
                f"먼저 {draft_from} 케이스를 실행하세요.")
        return Image.open(p).convert("RGB").resize(canvas, Image.LANCZOS), p.name
    rk = ratio.replace(":", "x")
    for p in sorted(OUT_DIR.glob(f"*draft*{rk}*{image_name}*.png")):
        if "_raw" in p.name or "_band" in p.name:
            continue
        return Image.open(p).convert("RGB").resize(canvas, Image.LANCZOS), p.name
    from pipeline.masking import (add_ground_shadow, composite_product,
                                  render_flat_background, resolve_background)
    d = build_inputs(image_name, ratio, min(canvas), "A", force_public=public)
    spec = resolve_background("solid", None, None, CATEGORY[image_name], 1)[0]
    flat = render_flat_background(d["canvas"], spec["colors"], spec.get("direction"))
    out = composite_product(d["base"],
                            add_ground_shadow(flat, d["masks"].product),
                            d["masks"].product)
    return out.resize(canvas, Image.LANCZOS), "flat_stand_in"


def run_case(c: Case, offload: int):
    import torch
    from PIL import Image
    import numpy as np
    from pipeline import config, generate
    from pipeline.masking import add_ground_shadow, composite_product, make_masks

    config.USE_CPU_OFFLOAD = bool(offload)
    model = STAGES[c.stage][0]
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    prefix = str(OUT_DIR / c.cid)

    rec = {**asdict(c), "model": model, "cpu_offload": bool(offload), "seed": SEED,
           "upscale": UPSCALE if c.upscaled else None,
           "device": device_info(torch), "nvidia_smi_before": nvidia_smi(),
           "configured_steps": None, "actual_steps": None, "strength": None,
           "gen_wh": None, "final_wh": None, "gen_latent_wh": None,
           "prepare_sec": None, "model_load_sec": None, "inference_sec": None,
           "unet_sec": None, "decode_sec": None, "sec_per_step": None,
           "peak_allocated_gb": None, "peak_reserved_gb": None,
           "unet_peak_allocated_gb": None, "decode_peak_allocated_gb": None,
           "reserved_at_last_step_gb": None, "reserved_after_inference_gb": None,
           "decode_peak_isolated": None, "callback_supported": None,
           "prompt_used": None,
           "reserved_metric_exceeds_reported_vram": None,
           "num_alloc_retries": None, "num_ooms": None,
           "nvidia_smi_after": None, "status": None, "fail_stage": None,
           "error": None, "output_path": None, "raw_output_path": None,
           "source_objects": None, "detected_objects": None,
           "prepare_mode": None, "blur_margin": None, "draft_source": None,
           "placement": None, "placement_gen": None,
           "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")}

    fail = "prepare"
    try:
        t0 = time.time()
        # 최종 캔버스에서 배치를 정하고, 그 정규화 값을 생성 캔버스에 그대로 적용한다.
        fin = build_inputs(c.image, c.ratio, c.final_short, c.bleed, c.y_delta)
        gen = (fin if not c.upscaled else
               build_inputs(c.image, c.ratio, c.gen_short, c.bleed,
                            force_public=fin["public"]))
        GW, GH = gen["canvas"]
        FW, FH = fin["canvas"]
        rec.update(prepare_sec=round(time.time() - t0, 2),
                   gen_wh=[GW, GH], final_wh=[FW, FH],
                   gen_latent_wh=[GW // 8, GH // 8],
                   prepare_mode=fin["prepare_mode"], blur_margin=fin["blur_margin"],
                   source_objects=fin["source_objects"],
                   placement=fin["public"], placement_gen=gen["public"])

        prompt = c.prompt or generate.resolve_prompt(None, CATEGORY[c.image])
        rec["prompt_used"] = prompt

        fail = "model_load"
        t0 = time.time()
        pipe = generate._load(model, "inpaint")
        torch.cuda.synchronize()
        rec["model_load_sec"] = round(time.time() - t0, 2)

        if c.stage == "refine":
            draft_img, dsrc = make_stand_in_draft(c.image, c.ratio, gen["canvas"],
                                                  fin["public"], c.draft_from)
            rec["draft_source"] = dsrc
            # refine에도 generator를 넘긴다. 안 넘기면 프로세스마다 전역 RNG가
            # 달라져 재현이 안 되고, R1/R2 비교에서 노이즈가 변수로 남는다.
            # (해상도가 다르면 latent shape이 달라 노이즈가 완전히 같을 수는 없다.
            #  seed 고정은 재현성 확보용이며 "동일 노이즈"를 뜻하지 않는다.)
            kw = {"image": draft_img, "strength": config.REFINE_STRENGTH,
                  "num_inference_steps": config.REFINE_STEPS,
                  "generator": torch.Generator("cuda").manual_seed(SEED)}
            rec["strength"] = config.REFINE_STRENGTH
        else:
            kw = {"image": gen["base"],
                  "num_inference_steps": config.DRAFT_STEPS,
                  "generator": torch.Generator("cuda").manual_seed(SEED)}
        # strength가 있으면 실제 denoising step은 int(steps * strength)로 줄어든다.
        # (REFINE_STEPS=30, strength=0.35 → 10 step). 설정값과 실제값을 구분한다.
        rec["configured_steps"] = kw["num_inference_steps"]

        # --- 모델 로드 peak와 섞이지 않게 여기서 reset ---
        torch.cuda.synchronize()
        torch.cuda.reset_peak_memory_stats()
        marks = {"count": 0}

        def on_step_end(p, step, timestep, cb):
            """매 step마다 기록해 두면 마지막 step을 몰라도 값이 남는다.

            scheduler.timesteps는 쓰지 않는다. img2img/inpaint 계열은 strength를
            적용한 뒤 실제로 돌 timesteps를 따로 잘라 쓰고, scheduler 쪽은 원래
            개수(30)를 그대로 들고 있을 수 있다. 그러면 step 9에서 끝나는데
            step 29를 기다리게 되어 마크가 영영 찍히지 않는다.
            실제 step 수는 파이프라인의 num_timesteps / _num_timesteps에 있다.
            """
            marks["count"] += 1
            torch.cuda.synchronize()
            marks["t"] = time.time()
            marks["peak"] = torch.cuda.max_memory_allocated() / 2 ** 30
            marks["reserved"] = torch.cuda.memory_reserved() / 2 ** 30

            n = getattr(p, "num_timesteps", None)
            if n is None:
                n = getattr(p, "_num_timesteps", None)
            marks["n"] = n
            # 마지막 step을 알 수 있을 때만 reset해서 decode 구간을 분리한다.
            # 몰라도 위 마크는 남으므로 unet_sec/peak가 null이 되지 않는다.
            if n is not None and step == n - 1 and not marks.get("reset_done"):
                torch.cuda.reset_peak_memory_stats()
                marks["reset_done"] = True
            return cb

        fail = "inference"
        # 콜백 지원 여부를 **미리** 확인한다. 예전처럼 TypeError로 잡아 재시도하면
        # 파이프라인이 두 번 돌아 inference_sec이 두 배로 찍히고, 콜백과 무관한
        # TypeError까지 삼켜 원인을 가린다.
        try:
            supports_cb = "callback_on_step_end" in inspect.signature(
                pipe.__call__).parameters
        except (TypeError, ValueError):
            supports_cb = False
        rec["callback_supported"] = supports_cb

        torch.cuda.synchronize()
        t0 = time.time()
        common = dict(prompt=prompt, negative_prompt=config.NEGATIVE_PROMPT,
                      mask_image=gen["masks"].inpaint, height=GH, width=GW)
        if supports_cb:
            common["callback_on_step_end"] = on_step_end
        out = pipe(**common, **kw).images[0]
        torch.cuda.synchronize()
        rec["inference_sec"] = round(time.time() - t0, 2)
        # 실제 실행된 denoising step 수. 콜백 호출 횟수를 우선하고,
        # 콜백이 없으면 scheduler.timesteps 길이로 대체한다.
        actual = marks.get("count") or marks.get("n")
        if not actual:
            # 콜백 미지원 — 파이프라인이 들고 있는 실제 step 수를 읽는다.
            # scheduler.timesteps는 strength 적용 전 개수라 쓰지 않는다.
            actual = (getattr(pipe, "num_timesteps", None)
                      or getattr(pipe, "_num_timesteps", None))
        rec["actual_steps"] = actual
        rec["sec_per_step"] = (round(rec["inference_sec"] / actual, 3)
                               if actual else None)
        pa = round(torch.cuda.max_memory_allocated() / 2 ** 30, 3)
        pr = round(torch.cuda.max_memory_reserved() / 2 ** 30, 3)
        rec.update(peak_allocated_gb=pa, peak_reserved_gb=pr,
                   reserved_after_inference_gb=round(
                       torch.cuda.memory_reserved() / 2 ** 30, 3),
                   **alloc_counters(torch))
        tot = rec["device"].get("total_memory_gb")
        if tot:
            # 관측 사실만 기록한다. 이 값만으로 spilling을 단정하지 않는다.
            rec["reserved_metric_exceeds_reported_vram"] = bool(pr > tot)
        if marks.get("count"):
            rec.update(unet_sec=round(marks["t"] - t0, 2),
                       decode_sec=round(rec["inference_sec"] - (marks["t"] - t0), 2),
                       unet_peak_allocated_gb=round(marks["peak"], 3),
                       decode_peak_allocated_gb=pa,
                       reserved_at_last_step_gb=round(marks["reserved"], 3),
                       # reset이 걸렸으면 decode 단독 peak, 아니면 전체 peak다.
                       decode_peak_isolated=bool(marks.get("reset_done")))

        fail = "post"
        # 생성 해상도가 달라도 여기서 최종 규격으로 맞춘 뒤 지표를 잰다.
        raw_final = out if not c.upscaled else out.resize((FW, FH), Image.LANCZOS)
        raw_final.save(f"{prefix}_raw.png")
        rec["raw_output_path"] = str(Path(f"{prefix}_raw.png").relative_to(ROOT))

        det = make_masks(raw_final)
        rec["detected_objects"] = count_objects(
            np.array(det.product.convert("L")) > 128, (FW, FH))
        rec.update(quality_metrics(raw_final, fin["masks"].product, prefix))

        # 제품은 최종 해상도 원본으로 덮는다 → 제품 선명도와 생성 해상도가 분리된다
        shadowed = add_ground_shadow(raw_final, fin["masks"].product)
        final = composite_product(fin["base"], shadowed, fin["masks"].product)
        final.save(f"{prefix}.png")
        rec.update(output_path=str(Path(f"{prefix}.png").relative_to(ROOT)),
                   status="ok")

    except torch.cuda.OutOfMemoryError as e:
        rec.update(status="oom", fail_stage=fail, error=str(e)[:300],
                   peak_allocated_gb=round(torch.cuda.max_memory_allocated() / 2**30, 3),
                   peak_reserved_gb=round(torch.cuda.max_memory_reserved() / 2**30, 3),
                   **alloc_counters(torch))
        torch.cuda.empty_cache()
    except Exception as e:
        rec.update(status="error", fail_stage=fail,
                   error=f"{type(e).__name__}: {e}"[:300])
    finally:
        rec["nvidia_smi_after"] = nvidia_smi()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(f"  {c.cid:26s} off={offload} -> {rec['status']}"
          f"  load={rec['model_load_sec']}s infer={rec['inference_sec']}s"
          f"  peak={rec['peak_allocated_gb']}/{rec['peak_reserved_gb']}GB")
    return rec


# --------------------------------------------------------------- 드라이버

def run_all(cases):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for c in cases:
        for offload in (0, 1):
            print(f"\n=== {c.cid} (offload={offload}) ===")
            subprocess.run([sys.executable, str(Path(__file__).resolve()),
                            "--case", c.cid, "--track", c.track,
                            "--offload", str(offload)],
                           cwd=str(ROOT), env={**os.environ, "PYTHONPATH": str(ROOT)})
            last = _last_log()
            st = last.get("status") if last else "?"
            if st != "oom":       # OOM이 아닌 실패는 offload로 해결되지 않는다
                break
    write_summary(cases[0].track if cases else "?")


def _last_log():
    if not LOG.exists():
        return None
    ls = [l for l in LOG.read_text(encoding="utf-8").splitlines() if l.strip()]
    return json.loads(ls[-1]) if ls else None


def _steps(r):
    """실제/설정 step. strength가 걸리면 둘이 다르다."""
    return f"{r.get('actual_steps') or '?'}/{r.get('configured_steps') or '?'}"


def write_summary(track):
    if not LOG.exists():
        return
    rows = [json.loads(l) for l in LOG.read_text(encoding="utf-8").splitlines()
            if l.strip()]
    rows = [r for r in rows if r.get("track") == track]
    if not rows:
        return
    head = (f"{'case':27s}{'off':4s}{'gen':12s}{'final':12s}{'상태':7s}"
            f"{'infer':8s}{'step':8s}{'s/step':8s}{'peakA':7s}{'peakR':7s}"
            f"{'lapVar':9s}{'nccMax':8s}{'배경E':8s}{'상단E':8s}{'하단E':8s}"
            f"{'cont상단':10s}{'cont하단':10s}{'소스→검출':10s}")
    lines = [head, "-" * len(head)]
    for r in rows:
        g = f"{r['gen_wh'][0]}x{r['gen_wh'][1]}" if r.get("gen_wh") else "-"
        f_ = f"{r['final_wh'][0]}x{r['final_wh'][1]}" if r.get("final_wh") else "-"
        obj = ("-" if r.get("detected_objects") is None
               else f"{r['source_objects']} → {r['detected_objects']}")
        lines.append(
            f"{r['cid']:27s}{int(r['cpu_offload']):<4d}{g:12s}{f_:12s}"
            f"{(r['status'] or '?'):7s}{str(r['inference_sec']):8s}"
            f"{_steps(r):8s}"
            f"{str(r['sec_per_step']):8s}{str(r['peak_allocated_gb']):7s}"
            f"{str(r['peak_reserved_gb']):7s}"
            f"{str(r.get('background_laplacian_var')):9s}"
            f"{str(r.get('horizontal_ncc_max')):8s}"
            f"{str(r.get('background_edge_energy')):8s}"
            f"{str(r.get('top_band_edge_energy')):8s}"
            f"{str(r.get('bottom_band_edge_energy')):8s}"
            f"{str(r.get('top_continuation_ratio')):10s}"
            f"{str(r.get('bottom_continuation_ratio')):10s}{obj:10s}")
    lines += ["",
              "cont* = 밴드 에너지 / 배경 에너지. **상대 비교용 proxy이며 절대 임계 판정 금지.**",
              "  배경이 평탄하면 분모(배경E)가 0.4~1.5까지 작아져 비율이 폭증한다.",
              "  refine 하단 띠에는 draft에서 넘어온 접지 그림자가 그대로 들어간다",
              "  (하단E가 제품과 무관하게 6~8로 균일한 이유). continuation이 아니다.",
              "  배경 조건이 다른 케이스끼리 ratio를 직접 비교하지 말 것."]
    txt = "\n".join(lines)
    (OUT_DIR / f"summary_{track}.txt").write_text(txt, encoding="utf-8")
    print("\n" + txt)


def diagnose(track=None):
    """probe_log.jsonl에서 메모리 계측 진단값만 뽑아 출력한다.

    peak_reserved가 보고된 VRAM을 넘어 보이는 이유를 판단하려면 이 값들이
    함께 있어야 한다. 여기서는 사실만 나열하고 결론을 내리지 않는다.
    """
    if not LOG.exists():
        raise SystemExit(f"로그가 없습니다: {LOG}")
    rows = [json.loads(l) for l in LOG.read_text(encoding="utf-8").splitlines()
            if l.strip()]
    if track:
        rows = [r for r in rows if r.get("track") == track]
    if not rows:
        raise SystemExit("해당 트랙 기록이 없습니다.")

    # 로그는 append라 재실행하면 같은 case가 여러 줄 남는다. case당 최신 것만 쓴다.
    # timestamp가 같으면(초 단위라 충돌 가능) 뒤에 기록된 줄을 최신으로 본다.
    latest, order = {}, []
    for r in rows:
        cid = r.get("cid")
        if cid not in latest:
            order.append(cid)
        prev = latest.get(cid)
        if prev is None or (r.get("timestamp") or "") >= (prev.get("timestamp") or ""):
            latest[cid] = r
    dropped = len(rows) - len(latest)
    rows = [latest[c] for c in order]
    if dropped:
        print(f"(같은 case의 이전 기록 {dropped}건은 제외하고 최신만 사용합니다)\n")

    d = rows[-1].get("device") or {}
    print("=" * 68)
    print("환경 (마지막 기록 기준)")
    print("=" * 68)
    for k in ("gpu_name", "total_memory_gb", "mem_get_info_gb",
              "allocator_backend", "PYTORCH_CUDA_ALLOC_CONF",
              "torch_version", "cuda_version"):
        print(f"  {k:28s} {d.get(k)}")

    for r in rows:
        print()
        print("-" * 68)
        print(f"{r['cid']}  ({r.get('status')})  offload={r.get('cpu_offload')}")
        print("-" * 68)
        gw = r.get("gen_wh")
        if r.get("status") != "ok":
            print(f"  {'!! fail_stage':26s} {r.get('fail_stage')}")
            print(f"  {'!! error':26s} {r.get('error')}")
            print(f"  {'':26s} (실패한 실행의 시간·메모리 값은 성능 측정치로 "
                  f"쓸 수 없습니다)")
            print()
        print(f"  {'생성 크기':26s} {f'{gw[0]}x{gw[1]}' if gw else '-'}"
              f"   latent {r.get('gen_latent_wh')}")
        print(f"  {'configured_steps':26s} {r.get('configured_steps')}")
        print(f"  {'actual_steps':26s} {r.get('actual_steps')}"
              f"   (strength={r.get('strength')})")
        print(f"  {'inference_sec':26s} {r.get('inference_sec')}")
        print(f"  {'sec_per_step':26s} {r.get('sec_per_step')}")
        print(f"  {'unet_sec / decode_sec':26s} {r.get('unet_sec')} / {r.get('decode_sec')}")
        print(f"  {'callback_supported':26s} {r.get('callback_supported')}"
              f"   decode_peak_isolated={r.get('decode_peak_isolated')}")
        if r.get("top_continuation_ratio") is not None:
            print(f"  {'continuation 상단/하단':26s} "
                  f"{r.get('top_continuation_ratio')} / "
                  f"{r.get('bottom_continuation_ratio')}"
                  f"   (proxy. 절대 임계 판정 금지)")
        print()
        print(f"  {'peak_allocated_gb':26s} {r.get('peak_allocated_gb')}")
        print(f"  {'peak_reserved_gb':26s} {r.get('peak_reserved_gb')}")
        print(f"  {'unet_peak_allocated_gb':26s} {r.get('unet_peak_allocated_gb')}")
        print(f"  {'decode_peak_allocated_gb':26s} {r.get('decode_peak_allocated_gb')}")
        print(f"  {'reserved_at_last_step_gb':26s} {r.get('reserved_at_last_step_gb')}")
        print(f"  {'reserved_after_inference_gb':26s} {r.get('reserved_after_inference_gb')}")
        print(f"  {'num_alloc_retries':26s} {r.get('num_alloc_retries')}")
        print(f"  {'num_ooms':26s} {r.get('num_ooms')}")
        print(f"  {'reserved > 보고된 VRAM':26s} "
              f"{r.get('reserved_metric_exceeds_reported_vram')}"
              f"   (관측 사실. 원인 단정 아님)")
        print()
        for when in ("before", "after"):
            sm = r.get(f"nvidia_smi_{when}") or {}
            print(f"  {'nvidia-smi ' + when:26s} "
                  f"used={sm.get('used_mb')}MB / total={sm.get('total_mb')}MB"
                  f"  ({sm.get('name')})")
    print()
    print("판단에 참고할 점")
    print("  - peak_reserved는 caching allocator가 예약한 총량이며 즉시 물리 VRAM")
    print("    점유와 같지 않습니다. num_alloc_retries가 0이 아니면 압박이 있었다는 뜻입니다.")
    print("  - nvidia-smi used와 total_memory_gb, mem_get_info를 함께 보고 판단하세요.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--track", default=None, choices=ALL_TRACKS)
    ap.add_argument("--case", default=None, help="케이스 1개만 실행 (내부용)")
    ap.add_argument("--offload", type=int, default=0)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--diagnose", action="store_true",
                    help="로그에서 메모리 계측 진단값만 출력 (GPU 불필요)")
    ap.add_argument("--dry-run", action="store_true",
                    help="실행하지 않고 케이스 행렬만 출력 (모델 로드 없음)")
    args = ap.parse_args()

    if args.diagnose:
        diagnose(args.track)
        return

    if args.dry_run:
        from pipeline.layout import resolve_output_size
        total = 0
        for tk in (["0", "A", "B", "C"] if args.track is None else [args.track]):
            cs = matrix(tk)
            print(f"\n### Track {tk} — {len(cs)}회")
            print(f"{'case':27s}{'제품':14s}{'stage':8s}{'ratio':7s}"
                  f"{'gen':12s}{'final':12s}{'bleed':7s}{'yΔ':7s}{'비고':10s}")
            for c in cs:
                rk = None if c.ratio == "1:1" else c.ratio
                g = resolve_output_size(rk, c.gen_short)
                f_ = resolve_output_size(rk, c.final_short)
                extra = f"  입력={c.draft_from}" if c.draft_from else ""
                print(f"{c.cid:27s}{c.image:14s}{c.stage:8s}{c.ratio:7s}"
                      f"{f'{g[0]}x{g[1]}':12s}{f'{f_[0]}x{f_[1]}':12s}"
                      f"{c.bleed:7s}{c.y_delta:+.2f}   {c.note:14s}{extra}")
            if any(x.prompt for x in cs):
                print("\n  프롬프트 (R1/R2 동일):")
                for k, v in COMPLEX_PROMPTS.items():
                    if any(x.prompt == v for x in cs):
                        print(f"    {k}: {v[:96]}...")
            total += len(cs)
        if args.track is None:
            print(f"\n총 {total}회 (Track 1 Stage 1 완료분 제외)")
        print(f"결과: {OUT_DIR}")
        return

    if args.case:
        if not args.track:
            raise SystemExit("--case를 쓸 때는 --track도 필요합니다.")
        m = {c.cid: c for c in matrix(args.track)}
        if args.case not in m:
            raise SystemExit(f"알 수 없는 케이스: {args.case}\n가능: {', '.join(m)}")
        run_case(m[args.case], args.offload)
        return

    if args.all:
        if not args.track:
            raise SystemExit("--all을 쓸 때는 --track이 필요합니다.")
        run_all(matrix(args.track))
        return

    ap.print_help()


if __name__ == "__main__":
    main()
