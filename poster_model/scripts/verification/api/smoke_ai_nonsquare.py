"""A4-2 — 3:1 AI production 경로 GPU E2E 검증 (GPU 필요).

**production 코드를 그대로 호출합니다.** 실험 스크립트(probe_ai_nonsquare.py)와
달리 api.py의 엔드포인트를 FastAPI TestClient로 in-process 호출하므로,
validation → pipeline → 배치 → 업스케일 → 합성까지 실제 경로가 전부 실행됩니다.

in-process로 도는 이유는 peak VRAM을 같은 프로세스에서 재야 하기 때문입니다.
별도 uvicorn 서버에 HTTP로 붙으면 클라이언트 쪽에서 peak를 측정할 수 없습니다.

파이프는 **관찰만** 합니다. `_load`가 돌려주는 객체를 프록시로 감싸 호출 인자
(width/height/image/mask)를 기록하고 실제 파이프를 그대로 실행합니다.
production 파일은 수정하지 않습니다.

실행 (프로젝트 루트에서)
    source .venv/bin/activate

    # 무엇을 할지만 확인 (GPU/모델 로드 없음)
    PYTHONPATH="$PWD" python scripts/verification/api/smoke_ai_nonsquare.py --dry-run

    # 실제 검증
    PYTHONPATH="$PWD" python scripts/verification/api/smoke_ai_nonsquare.py

    # 문구 합성 없이
    PYTHONPATH="$PWD" python scripts/verification/api/smoke_ai_nonsquare.py --no-text

결과: outputs/verification/api/ai_nonsquare_smoke/
    draft_3x1.png          2304x768   AI draft 결과
    refine_3x1.png         3072x1024  실제 draft를 입력으로 한 refine 결과
    refine_3x1_text.png    3072x1024  문구 overlay까지 적용한 결과
    compare.png            draft / refine 나란히
    smoke_log.json         전 항목 수치
    summary.txt            표 요약
"""
import argparse
import base64
import contextlib
import io
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT_DIR = ROOT / "outputs" / "verification" / "api" / "ai_nonsquare_smoke"
IMAGE = "snack"
CATEGORY = "food"
TEXT = {"headline": "여름 한정 특가", "sub": "지금 만나보세요",
        "x": 0.06, "y": 0.30, "align": "left", "style": "plain"}

PIPE_CALLS = []
RAW_IMAGES = []          # 파이프가 돌려준 원본(업스케일 전) 이미지
LOADS = []               # _load(kind, task, tiling) 호출 기록 — 어느 인스턴스를 썼는지
STAGE = {}               # 단계별 관측 결과
SEED = 20260808          # 고정 시드. tiling 비교에서 노이즈를 변수에서 뺀다.

# Step 1 seed scan용 고정 목록. 첫 값은 tiling A/B에서 이미 0px로 확인된 시드라
# 기준점 역할을 한다. 스캔 마지막에 이 값을 한 번 더 돌려 실행 순서·GPU 상태가
# 섞이지 않았는지 본다.
SCAN_SEEDS = [20260808, 11, 1234, 77777, 424242,
              998877, 31337, 555, 8080808, 6543210]
# 현재 tiling 변형. _Observer가 파이프 로드 직후 적용한다.
# 기본값은 "keep" — production이 정한 상태를 **건드리지 않는다**. 이게 "on"이면
# production이 tiling을 끈 인스턴스를 스크립트가 다시 켜버려, 수정 검증이
# 무효가 된다. tiling A/B처럼 의도적으로 바꿀 때만 on/off를 넣는다.
TILING = {"mode": "keep"}


def b64_of(path):
    return base64.b64encode(Path(path).read_bytes()).decode()


def decode(data):
    from PIL import Image
    return Image.open(io.BytesIO(base64.b64decode(data)))


def nvidia_smi():
    try:
        r = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.used,memory.total",
                            "--format=csv,noheader,nounits"],
                           capture_output=True, text=True, timeout=10)
        n, u, t = [x.strip() for x in r.stdout.strip().splitlines()[0].split(",")]
        return {"name": n, "used_mb": int(u), "total_mb": int(t)}
    except Exception:
        return None


class _Observer:
    """실제 파이프를 감싸 호출 인자만 기록한다. 동작은 그대로 위임한다.

    tiling 변형이 요청되면 **이미 로드된 VAE에만** disable_tiling()을 건다.
    config를 영구 수정하지 않으며 production 파일도 그대로다.
    """

    def __init__(self, pipe, kind, task, tiling=True):
        self._pipe, self._kind, self._task = pipe, kind, task
        self._tiling_requested = tiling
        _apply_tiling(pipe)

    def __call__(self, **kw):
        out = None
        PIPE_CALLS.append({
            "model": self._kind, "task": self._task,
            "width": kw.get("width"), "height": kw.get("height"),
            "image_size": getattr(kw.get("image"), "size", None),
            "mask_size": getattr(kw.get("mask_image"), "size", None),
            "steps": kw.get("num_inference_steps"),
            "strength": kw.get("strength"),
            "num_images": kw.get("num_images_per_prompt"),
            "tiling_requested": self._tiling_requested})
        out = self._pipe(**kw)
        try:                       # 업스케일 전 원본을 그대로 보관 (관측용)
            RAW_IMAGES.append([im.copy() for im in out.images])
        except Exception:
            pass
        return out

    def __getattr__(self, name):
        return getattr(self._pipe, name)


@contextlib.contextmanager
def deterministic_draft_seed(torch, seed=None):
    """production이 draft 시드를 뽑는 **그 호출 하나만** 결정적으로 만든다.

    generate.py의 해당 지점은 이 형태다.
        seeds = torch.randint(0, 2**31 - 1, (num_images,)).tolist()

    torch.randint를 통째로 바꾸면 diffusion 도중 torch/diffusers 내부가 쓰는
    난수까지 영향을 받아 "tiling만 변수"라는 통제가 오히려 깨진다. 그래서
      - low/high/size가 위 signature와 정확히 일치할 때만 고정값을 돌려주고
      - 그 외 호출은 원래 함수에 그대로 위임하며
      - **한 번 매칭되면 즉시 원본을 복원**한다.
    빠져나갈 때도 finally로 복원한다.

    시드가 실제로 고정됐는지는 drafts 응답의 seed 값으로 확인할 수 있다.
    """
    orig = torch.randint
    sd = SEED if seed is None else int(seed)
    used = {"matched": False, "seed": sd}

    def controlled(low, high, size, *a, **kw):
        if (not used["matched"] and low == 0 and high == 2 ** 31 - 1
                and isinstance(size, tuple) and len(size) == 1
                and not a and not kw):
            used["matched"] = True
            torch.randint = orig                      # 매칭 즉시 원복
            return torch.tensor([sd + i for i in range(size[0])])
        return orig(low, high, size, *a, **kw)

    torch.randint = controlled
    try:
        yield used
    finally:
        torch.randint = orig


def _apply_tiling(pipe):
    """TILING 설정을 로드된 VAE에 반영한다. slicing/offload는 건드리지 않는다."""
    vae = getattr(pipe, "vae", None)
    if vae is None:
        return None
    if TILING["mode"] == "off" and hasattr(vae, "disable_tiling"):
        vae.disable_tiling()
    elif TILING["mode"] == "on" and hasattr(vae, "enable_tiling"):
        vae.enable_tiling()
    return getattr(vae, "use_tiling", None)


def _vae_state():
    """실제로 tiling/slicing이 어떤 상태인지 캐시된 파이프에서 읽는다."""
    import pipeline.generate as G
    out = {}
    for key, obj in G._pipes.items():
        vae = getattr(getattr(obj, "_pipe", obj), "vae", None)
        if vae is not None:
            out[key] = {"use_tiling": getattr(vae, "use_tiling", None),
                        "use_slicing": getattr(vae, "use_slicing", None)}
    return out


def left_band_px(path, thr=30, span=60):
    """좌측 가장자리 색 띠 폭(px). 인접 안쪽(30~60열) 평균과 비교한다."""
    import numpy as np
    from PIL import Image
    a = np.array(Image.open(path).convert("RGB"), np.float32)
    ref = a[:, 30:span + 1].mean((0, 1))
    dev = np.abs(a.mean(0) - ref).max(1)
    n = 0
    for i in range(30):
        if dev[i] <= thr:
            break
        n += 1
    return (n, [round(float(v), 1) for v in a[:, 0].mean(0)],
            [round(float(v), 1) for v in ref])


def build_edge_compare():
    """tiling on/off의 좌측 가장자리를 나란히 붙인다."""
    from PIL import Image, ImageDraw
    rows = []
    for stage in ("draft_3x1", "refine_3x1"):
        for mode in ("tiling_on", "tiling_off", ""):
            f = OUT_DIR / f"{stage}{('_' + mode) if mode else ''}.png"
            if not f.exists():
                continue
            n, c0, ref = left_band_px(f)
            im = Image.open(f).convert("RGB").crop((0, 0, 160, Image.open(f).height))
            im = im.resize((int(im.width * 380 / im.height), 380), Image.LANCZOS)
            rows.append((f"{stage}  {mode or 'tiling_on(기존)'}\n띠 {n}px  col0={c0}",
                         im))
    if not rows:
        return
    W = sum(x.width + 18 for _, x in rows) + 18
    sheet = Image.new("RGB", (W, 440), (250, 250, 250))
    dr = ImageDraw.Draw(sheet)
    x = 18
    for lab, im in rows:
        for j, line in enumerate(lab.split("\n")):
            dr.text((x, 6 + j * 13), line, fill=(20, 20, 20))
        sheet.paste(im, (x, 40))
        dr.rectangle([x, 40, x + im.width, 40 + im.height], outline=(190, 190, 190))
        x += im.width + 18
    out = OUT_DIR / "edge_compare_tiling.png"
    sheet.save(out)
    print(f"\n좌측 가장자리 비교: {out}")
    for lab, _ in rows:
        print("  " + lab.replace("\n", "   "))


def bbox_from_meta(meta):
    """meta.layout(비율)에서 최종 캔버스 기준 제품 bbox를 복원한다."""
    lay, cv = meta.get("layout"), meta.get("canvas")
    if not lay or not cv or lay.get("bbox_w_ratio") is None:
        return None
    W, H = cv["width"], cv["height"]
    w, h = lay["bbox_w_ratio"] * W, lay["bbox_h_ratio"] * H
    cx, cy = lay["center_x_ratio"] * W, lay["center_y_ratio"] * H
    return [round(cx - w / 2), round(cy - h / 2), round(cx + w / 2), round(cy + h / 2)]


def measure(client, name, method, body, torch, note=None, seed=None):
    """엔드포인트 1회 호출 + 시간·메모리 측정.

    **호출 직전에 reset_peak_memory_stats()** 를 실행해 단계별 peak를 독립적으로
    잰다. 같은 프로세스에 SD1.5와 SDXL이 계속 캐시되므로, reset을 안 하면 앞
    단계의 peak가 뒤 단계에 그대로 남는다.

    다만 reset 이후에도 **이미 상주 중인 메모리는 peak에 포함**된다(reset은
    peak를 현재값으로 되돌리는 것이지 0으로 만들지 않는다). 그래서
    allocated/reserved의 before·after를 함께 남기고, 이번 호출이 추가로 쓴 양은
    delta_peak_* 로 따로 계산해 둔다.

    모델은 일부러 unload하지 않는다. production처럼 같은 프로세스에 캐시된
    상태를 그대로 보는 편이 실제 운영 조건에 가깝다.
    """
    PIPE_CALLS.clear()
    LOADS.clear()
    cuda = bool(torch and torch.cuda.is_available())
    rec = {"step": name, "note": note}
    if cuda:
        torch.cuda.synchronize()
        a0 = torch.cuda.memory_allocated() / 2 ** 30
        r0 = torch.cuda.memory_reserved() / 2 ** 30
        torch.cuda.reset_peak_memory_stats()          # ← 단계별 독립 측정
        rec.update(allocated_before_gb=round(a0, 3),
                   reserved_before_gb=round(r0, 3))
    rec["nvidia_smi_before"] = nvidia_smi()

    import torch as _t
    _sd = SEED if seed is None else int(seed)
    _t.manual_seed(_sd)
    if _t.cuda.is_available():
        _t.cuda.manual_seed_all(_sd)
    t0 = time.time()
    r = client.post(method, json=body)
    if cuda:
        torch.cuda.synchronize()
    rec.update(status=r.status_code, elapsed_sec=round(time.time() - t0, 2),
               pipe_calls=list(PIPE_CALLS), nvidia_smi_after=nvidia_smi(), loads=list(LOADS))

    if cuda:
        pa = torch.cuda.max_memory_allocated() / 2 ** 30
        pr = torch.cuda.max_memory_reserved() / 2 ** 30
        rec.update(peak_allocated_gb=round(pa, 3), peak_reserved_gb=round(pr, 3),
                   allocated_after_gb=round(torch.cuda.memory_allocated() / 2**30, 3),
                   reserved_after_gb=round(torch.cuda.memory_reserved() / 2**30, 3),
                   # 이번 호출이 기존 상주분 위에 추가로 쓴 양.
                   # 로그에 기록된 반올림 값끼리 빼서, JSON만 보고도
                   # delta == peak - before 가 그대로 맞아떨어지게 한다.
                   delta_peak_allocated_gb=round(
                       round(pa, 3) - rec["allocated_before_gb"], 3),
                   delta_peak_reserved_gb=round(
                       round(pr, 3) - rec["reserved_before_gb"], 3))
    if r.status_code != 200:
        rec["error"] = r.json().get("detail")
    return r, rec


def run_variant(client, torch, img_b64, args, tag):
    """한 가지 tiling 설정으로 draft → refine (→ text)까지 실행한다."""
    suffix = f"_{tag}" if tag else ""
    log = {"vae_tiling": TILING["mode"], "seed": SEED, "steps": []}
    return _run_steps(client, torch, img_b64, args, suffix, log)


def run_seed_scan(client, torch, img_b64, args):
    """Step 1 — draft만 여러 시드로 돌려 좌측 색 띠가 재현되는지 본다.

    refine은 돌리지 않는다. 최초 smoke에서 draft에 이미 13px 띠가 있었고 refine이
    그 draft를 입력으로 받았으므로, 원인이 draft 단계에 있다면 비싼 refine을 돌릴
    이유가 없다.

    마지막 실행은 **첫 시드를 한 번 더** 돌린다. 같은 시드가 순번 1과 마지막에서
    다른 결과를 내면 시드가 아니라 실행 순서/GPU 상태 쪽을 봐야 한다는 신호다.

    한 프로세스 안에서 연속 실행하므로 첫 실행에만 모델 로드 시간이 포함된다.
    """
    seeds = [int(x) for x in args.seeds] if args.seeds else SCAN_SEEDS[:args.seed_scan]
    order = seeds + [seeds[0]]          # 마지막에 첫 시드 반복
    log = {"mode": "seed_scan", "image": args.image, "gpu": nvidia_smi(),
           "seeds_requested": seeds, "run_order": order,
           "note": "draft만 실행. refine·production 설정 변경 없음.", "runs": []}

    for i, sd in enumerate(order, 1):
        tag = f"seedscan_{i:02d}_seed{sd}"
        with deterministic_draft_seed(torch, sd) as ctl:
            r, rec = measure(client, tag, "/generate/drafts", {
                "mode": "inpaint", "image": img_b64, "category": CATEGORY,
                "num_images": 1, "background_mode": "ai", "aspect_ratio": "3:1"},
                torch, seed=sd,
                note=("첫 실행 — 모델 로드 포함" if i == 1 else
                      "첫 시드 반복 (순서/GPU 상태 대조)" if i == len(order) else None))
        row = {"run_index": i, "seed_requested": sd,
               "seed_patch_matched": ctl["matched"],
               "seed_returned": None, "seed_controlled": None,
               "left_band_px": None, "col0_rgb": None, "neighbor_rgb": None,
               "elapsed_sec": rec.get("elapsed_sec"), "status": rec.get("status"),
               "output_path": None,
               "peak_allocated_gb": rec.get("peak_allocated_gb"),
               "peak_reserved_gb": rec.get("peak_reserved_gb"),
               "nvidia_smi_before": rec.get("nvidia_smi_before"),
               "is_repeat_of_first": i == len(order),
               "note": rec.get("note")}

        if r.status_code == 200:
            d = r.json()["drafts"][0]
            row["seed_returned"] = d["seed"]
            row["seed_controlled"] = (d["seed"] == sd)
            f = OUT_DIR / f"{tag}.png"
            decode(d["image"]).save(f)
            row["output_path"] = str(f.relative_to(ROOT))
            n, c0, ref = left_band_px(f)
            row.update(left_band_px=n, col0_rgb=c0, neighbor_rgb=ref)
        else:
            row["error"] = r.json().get("detail")

        log["runs"].append(row)
        flag = "  <== 띠 발생" if (row["left_band_px"] or 0) > 0 else ""
        print(f"  {i:2d}/{len(order)}  seed={sd:<10d} 반환={row['seed_returned']}"
              f"  제어={row['seed_controlled']}  띠={row['left_band_px']}px"
              f"  {row['elapsed_sec']}s{flag}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "seedscan_log.json").write_text(
        json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")

    hit = [r for r in log["runs"] if (r["left_band_px"] or 0) > 0]
    first, last = log["runs"][0], log["runs"][-1]
    lines = [f"{'#':4s}{'seed':12s}{'반환seed':12s}{'제어':6s}{'띠px':7s}"
             f"{'elapsed':10s}{'peakR':9s}{'비고':22s}",
             "-" * 84]
    for r in log["runs"]:
        lines.append(f"{r['run_index']:<4d}{r['seed_requested']:<12d}"
                     f"{str(r['seed_returned']):12s}{str(r['seed_controlled']):6s}"
                     f"{str(r['left_band_px']):7s}{str(r['elapsed_sec']):10s}"
                     f"{str(r['peak_reserved_gb']):9s}{(r.get('note') or ''):22s}")
    lines += ["",
              f"띠가 관측된 실행: {len(hit)} / {len(log['runs'])}",
              f"첫 시드 재현 대조: 순번 1 = {first['left_band_px']}px, "
              f"순번 {last['run_index']} = {last['left_band_px']}px "
              f"({'일치' if first['left_band_px'] == last['left_band_px'] else '불일치 — 순서/GPU 상태 확인 필요'})",
              "",
              "해석 주의: 이 스캔에서 0px만 나왔다면 'seed 영향이 아니다'가 아니라",
              "**해당 seed 범위에서 재현 실패**로만 판단한다. 재현 케이스를 확보하지",
              "못한 상태에서는 원인 후보를 지워도 확정되는 것이 없다."]
    txt = "\n".join(lines)
    (OUT_DIR / "seedscan_summary.txt").write_text(txt, encoding="utf-8")
    print("\n" + txt)

    build_seed_edge_sheet([r for r in log["runs"] if r["output_path"]])
    return log


def build_seed_edge_sheet(rows, width=110):
    """각 실행의 좌측 가장자리를 나란히 붙여 육안 확인용 시트를 만든다."""
    from PIL import Image, ImageDraw
    cells = []
    for r in rows:
        f = ROOT / r["output_path"]
        if not f.exists():
            continue
        im = Image.open(f).convert("RGB")
        c = im.crop((0, 0, width, im.height))
        c = c.resize((int(c.width * 360 / c.height), 360), Image.LANCZOS)
        cells.append((f"#{r['run_index']} s={r['seed_requested']}\n띠 {r['left_band_px']}px", c))
    if not cells:
        return
    W = sum(c.width + 10 for _, c in cells) + 10
    sheet = Image.new("RGB", (W, 404), (250, 250, 250))
    dr = ImageDraw.Draw(sheet)
    x = 10
    for lab, c in cells:
        for j, line in enumerate(lab.split("\n")):
            dr.text((x, 4 + j * 12), line, fill=(20, 20, 20))
        sheet.paste(c, (x, 34))
        dr.rectangle([x, 34, x + c.width, 34 + c.height], outline=(200, 200, 200))
        x += c.width + 10
    out = OUT_DIR / "seedscan_edges.png"
    sheet.save(out)
    print(f"좌측 가장자리 비교: {out}")


def run_stage_trace(client, torch, img_b64, args):
    """Step 2 — 좌측 띠가 draft 파이프라인의 어느 단계에서 처음 생기는지 본다.

    production 로직·설정은 건드리지 않고 **관측만** 한다.
      s1  SD1.5 생성 직후          1536×512   (_Observer가 보관한 파이프 반환값)
      s2  LANCZOS 업스케일 직후    2304×768   (add_ground_shadow의 입력)
      s2b 그림자 합성 후           2304×768   (add_ground_shadow의 반환값, 참고)
      s3  제품 합성 후 최종        2304×768   (composite_product의 반환값 = 응답)

    generate 모듈의 이름을 잠시 감쌌다가 finally에서 반드시 원복한다.
    """
    import pipeline.generate as G
    seeds = [int(x) for x in args.stage_trace]
    log = {"mode": "stage_trace", "image": args.image, "gpu": nvidia_smi(),
           "seeds": seeds, "note": "draft만. production 로직·설정 변경 없음.",
           "runs": []}

    for idx, sd in enumerate(seeds, 1):
        RAW_IMAGES.clear()
        STAGE.clear()
        real_shadow, real_comp = G.add_ground_shadow, G.composite_product

        def shadow_hook(img, mask, *a, **kw):
            STAGE["s2_upscaled"] = img.copy()          # 업스케일 직후 = 그림자 입력
            out = real_shadow(img, mask, *a, **kw)
            STAGE["s2b_shadowed"] = out.copy()
            return out

        def comp_hook(base, gen, mask, *a, **kw):
            out = real_comp(base, gen, mask, *a, **kw)
            STAGE["s3_final"] = out.copy()
            return out

        G.add_ground_shadow, G.composite_product = shadow_hook, comp_hook
        try:
            with deterministic_draft_seed(torch, sd) as ctl:
                r, rec = measure(client, f"stage_trace_seed{sd}", "/generate/drafts", {
                    "mode": "inpaint", "image": img_b64, "category": CATEGORY,
                    "num_images": 1, "background_mode": "ai", "aspect_ratio": "3:1"},
                    torch, seed=sd,
                    note=("첫 실행 — 모델 로드 포함" if idx == 1 else None))
        finally:
            G.add_ground_shadow, G.composite_product = real_shadow, real_comp

        row = {"seed": sd, "status": rec.get("status"),
               "elapsed_sec": rec.get("elapsed_sec"),
               "seed_patch_matched": ctl["matched"], "seed_returned": None,
               "seed_controlled": None,
               # 어느 파이프 인스턴스를 썼는지. 이게 없으면 띠가 0px일 때
               # 수정 덕분인지 다른 이유인지 로그만으로 구분할 수 없다.
               "loads": rec.get("loads"), "pipe_calls": rec.get("pipe_calls"),
               "stages": []}
        if r.status_code == 200:
            d = r.json()["drafts"][0]
            row["seed_returned"] = d["seed"]
            row["seed_controlled"] = (d["seed"] == sd)

        if RAW_IMAGES:
            STAGE["s1_gen"] = RAW_IMAGES[0][0]
        order = [("s1_gen", "SD1.5 생성 직후"),
                 ("s2_upscaled", "LANCZOS 업스케일 직후"),
                 ("s2b_shadowed", "그림자 합성 후 (참고)"),
                 ("s3_final", "제품 합성 후 최종")]
        for key, label in order:
            im = STAGE.get(key)
            if im is None:
                row["stages"].append({"stage": key, "label": label, "missing": True})
                continue
            f = OUT_DIR / f"trace_seed{sd}_{key}_{im.width}x{im.height}.png"
            im.save(f)
            n, c0, ref = left_band_px(f)
            # 폭이 다른 단계를 나란히 보려면 최종 폭(2304) 기준으로 환산해야 한다
            norm = round(n * 2304 / im.width, 1)
            row["stages"].append({
                "stage": key, "label": label, "size": [im.width, im.height],
                "left_band_px": n, "left_band_px_at_2304": norm,
                "col0_rgb": c0, "neighbor_rgb": ref,
                "path": str(f.relative_to(ROOT))})
        log["runs"].append(row)

        print(f"\n  seed={sd}  (반환={row['seed_returned']}, "
              f"제어={row['seed_controlled']}, {row['elapsed_sec']}s)")
        for st in row["stages"]:
            if st.get("missing"):
                print(f"    {st['label']:22s} — 관측 실패")
                continue
            print(f"    {st['label']:22s} {st['size'][0]}x{st['size'][1]:<5d}"
                  f" 띠 {st['left_band_px']:3d}px"
                  f" (2304 환산 {st['left_band_px_at_2304']:5.1f})"
                  f"  col0={st['col0_rgb']}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "stagetrace_log.json").write_text(
        json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [f"{'seed':11s}{'단계':24s}{'크기':13s}{'띠px':7s}{'2304환산':10s}{'col0':22s}",
             "-" * 88]
    for run in log["runs"]:
        for st in run["stages"]:
            if st.get("missing"):
                continue
            lines.append(f"{run['seed']:<11d}{st['label']:24s}"
                         f"{_sz(st):13s}"
                         f"{st['left_band_px']:<7d}{st['left_band_px_at_2304']:<10.1f}"
                         f"{str(st['col0_rgb']):22s}")
        lines.append("")
    lines += ["해석 주의: 띠 폭은 인접 안쪽(30~60열) 대비 편차 30 초과 구간이며 proxy다.",
              "단계 간 폭 비교는 2304 환산 열로 본다(s1은 1536 기준이라 그대로 비교 불가).",
              "이 실험은 '어느 단계에서 처음 나타나는가'만 본다. 원인은 아직 확정하지 않는다."]
    txt = "\n".join(lines)
    (OUT_DIR / "stagetrace_summary.txt").write_text(txt, encoding="utf-8")
    print("\n" + txt)
    build_stage_sheet(log)
    return log


def run_tiling_ab(client, torch, img_b64, args):
    """Step 3 — 재현 seed를 고정하고 VAE tiling 축 하나만 비교한다 (draft만).

    이전 tiling A/B는 seed=20260808이라 띠 자체가 나오지 않아 판정력이 없었다.
    이번에는 재현 seed로 돌린다.

    --ratio로 비율을 고른다. 3:1에서 확인된 현상이 1:1에도 있는지 보려면 같은
    조건에서 1:1을 재야 한다. 지금까지의 실험 산출물은 전부 cpu_offload=False
    (=tiling 미적용)라 1:1이 안전하다는 근거가 없다.

    **VAE tiling은 decode 단계에 걸리고, 우리가 s1으로 보는 이미지가 바로 decode
    결과**다. 그래서 s1의 띠 폭이 이 실험의 핵심 지표다.

    실행 순서는 ON → OFF → ON. 마지막 ON은 순서·GPU 상태 대조용이다.
    같은 프로세스에서 같은 파이프 객체에 tiling만 켜고 끈다.
    """
    import pipeline.generate as G
    sd = int(args.tiling_ab)
    ratio = args.ratio
    rtag = ratio.replace(":", "x")
    order = ["on", "off", "on"]
    log = {"mode": "tiling_ab", "image": args.image, "seed": sd,
           "aspect_ratio": ratio, "gpu": nvidia_smi(), "run_order": order,
           "note": "draft만. production 로직·설정 변경 없음. 변수는 vae.use_tiling 하나.",
           "runs": []}

    for i, mode in enumerate(order, 1):
        TILING["mode"] = mode
        for obj in G._pipes.values():             # 이미 로드된 파이프에도 반영
            _apply_tiling(getattr(obj, "_pipe", obj))
        RAW_IMAGES.clear()

        with deterministic_draft_seed(torch, sd) as ctl:
            r, rec = measure(client, f"tilingab_{rtag}_{i}_{mode}", "/generate/drafts", {
                "mode": "inpaint", "image": img_b64, "category": CATEGORY,
                "num_images": 1, "background_mode": "ai", "aspect_ratio": ratio},
                torch, seed=sd,
                note=("첫 실행 — 모델 로드 포함" if i == 1 else
                      "첫 조건 반복 (순서/GPU 상태 대조)" if i == len(order) else None))

        row = {"run_index": i, "vae_tiling": mode, "aspect_ratio": ratio,
               "seed_requested": sd,
               "seed_patch_matched": ctl["matched"], "seed_returned": None,
               "seed_controlled": None, "status": rec.get("status"),
               "elapsed_sec": rec.get("elapsed_sec"),
               "peak_allocated_gb": rec.get("peak_allocated_gb"),
               "peak_reserved_gb": rec.get("peak_reserved_gb"),
               "vae_state": _vae_state(), "is_repeat_of_first": i == len(order),
               "note": rec.get("note"), "stages": []}
        if r.status_code == 200:
            d = r.json()["drafts"][0]
            row["seed_returned"] = d["seed"]
            row["seed_controlled"] = (d["seed"] == sd)
            targets = []
            if RAW_IMAGES:
                targets.append(("s1_gen", "SD1.5 생성 직후 (VAE decode 결과)",
                                RAW_IMAGES[0][0]))
            targets.append(("s3_final", "제품 합성 후 최종", decode(d["image"])))
            for key, label, im in targets:
                f = (OUT_DIR /
                     f"tilingab_{rtag}_{i}_{mode}_{key}_{im.width}x{im.height}.png")
                im.save(f)
                n, c0, ref = left_band_px(f)
                row["stages"].append({
                    "stage": key, "label": label, "size": [im.width, im.height],
                    "left_band_px": n,
                    "left_band_px_at_2304": round(n * 2304 / im.width, 1),
                    "col0_rgb": c0, "neighbor_rgb": ref,
                    "path": str(f.relative_to(ROOT))})
        else:
            row["error"] = r.json().get("detail")
        log["runs"].append(row)

        st = {x["stage"]: x for x in row["stages"]}
        print(f"  {i}/{len(order)}  {ratio}  tiling={mode.upper():3s}  seed={sd}"
              f"  반환={row['seed_returned']}  제어={row['seed_controlled']}"
              f"  s1 띠={st.get('s1_gen', {}).get('left_band_px')}px"
              f"  최종 띠={st.get('s3_final', {}).get('left_band_px')}px"
              f"  {row['elapsed_sec']}s")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / f"tilingab_{rtag}_seed{sd}_log.json").write_text(
        json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")

    def band(run, key):
        for x in run["stages"]:
            if x["stage"] == key:
                return x["left_band_px"]
        return None

    lines = [f"aspect_ratio={ratio}, seed={sd} 고정, "
             f"변수는 vae.use_tiling 하나 (draft만)", "",
             f"{'#':4s}{'tiling':8s}{'s1 띠':9s}{'최종 띠':9s}{'elapsed':10s}"
             f"{'peakR':9s}{'use_tiling(sd15/sdxl)':24s}{'비고':24s}",
             "-" * 100]
    for run in log["runs"]:
        vs = run.get("vae_state") or {}
        tl = "/".join(str(vs.get(k, {}).get("use_tiling")) for k in ("sd15_inpaint", "sdxl_inpaint"))
        lines.append(f"{run['run_index']:<4d}{run['vae_tiling'].upper():8s}"
                     f"{str(band(run, 's1_gen')):9s}{str(band(run, 's3_final')):9s}"
                     f"{str(run['elapsed_sec']):10s}{str(run['peak_reserved_gb']):9s}"
                     f"{tl:24s}{(run.get('note') or ''):24s}")
    on_runs = [r for r in log["runs"] if r["vae_tiling"] == "on"]
    off_runs = [r for r in log["runs"] if r["vae_tiling"] == "off"]
    on_b = [band(r, "s1_gen") for r in on_runs]
    off_b = [band(r, "s1_gen") for r in off_runs]
    lines += ["",
              f"s1 띠  ON {on_b}  /  OFF {off_b}",
              f"순서 대조: 첫 ON = {on_b[0]}px, 마지막 ON = {on_b[-1]}px "
              f"({'일치' if len(set(on_b)) == 1 else '불일치 — 순서/GPU 상태 확인 필요'})",
              "",
              "판정 기준",
              "  ON에서 띠, OFF에서 사라짐  → tiling 영향 유력",
              "  ON/OFF 둘 다 띠 유지       → tiling 우선순위 낮추고 다음 후보로",
              "",
              "주의: 띠 폭은 인접 안쪽(30~60열) 대비 편차 30 초과 구간이며 proxy다.",
              "비율 간 비교는 **절대 px**로 본다. 띠가 latent 경계에서 생긴다면 폭은",
              "이미지 폭과 무관하게 비슷해야 하므로, 2304 환산값은 이 비교에 쓰지 않는다.",
              "이 실험은 tiling 축 하나만 본다. 다른 원인 후보는 아직 배제하지 않는다."]
    txt = "\n".join(lines)
    (OUT_DIR / f"tilingab_{rtag}_seed{sd}_summary.txt").write_text(txt, encoding="utf-8")
    print("\n" + txt)

    build_stage_sheet({"runs": [
        {"seed": f"#{r['run_index']} {r['vae_tiling'].upper()}", "stages": r["stages"]}
        for r in log["runs"]]})
    return log


def _sz(st):
    return f"{st['size'][0]}x{st['size'][1]}"


def build_stage_sheet(log):
    """seed × 단계로 좌측 가장자리를 격자 배치한다."""
    from PIL import Image, ImageDraw
    rows = []
    for run in log["runs"]:
        cells = []
        for st in run["stages"]:
            if st.get("missing"):
                continue
            im = Image.open(ROOT / st["path"]).convert("RGB")
            c = im.crop((0, 0, max(60, int(im.width * 0.05)), im.height))
            c = c.resize((int(c.width * 300 / c.height), 300), Image.LANCZOS)
            cells.append((f"{st['label']}  {st['left_band_px']}px", c))
        if cells:
            lab = run["seed"]
            rows.append((lab if isinstance(lab, str) else f"seed={lab}", cells))
    if not rows:
        return
    cw = max(c.width for _, cs in rows for _, c in cs) + 12
    W = 110 + cw * max(len(cs) for _, cs in rows)
    H = sum(300 + 34 for _ in rows) + 14
    sheet = Image.new("RGB", (W, H), (250, 250, 250))
    dr = ImageDraw.Draw(sheet)
    y = 8
    for title, cells in rows:
        dr.text((8, y + 140), title, fill=(20, 20, 20))
        x = 110
        for lab, c in cells:
            dr.text((x, y), lab, fill=(60, 60, 60))
            sheet.paste(c, (x, y + 20))
            dr.rectangle([x, y + 20, x + c.width, y + 20 + c.height],
                         outline=(200, 200, 200))
            x += cw
        y += 334
    out = OUT_DIR / "stagetrace_edges.png"
    sheet.save(out)
    print(f"단계별 좌측 가장자리: {out}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", default=IMAGE)
    ap.add_argument("--no-text", action="store_true", help="문구 합성 단계를 건너뛴다")
    ap.add_argument("--tiling-ab", default=None, metavar="SEED",
                    help="재현 seed를 고정하고 VAE tiling ON/OFF만 비교 "
                         "(draft만, ON→OFF→ON 순서로 3회)")
    ap.add_argument("--ratio", choices=("1:1", "3:1"), default="3:1",
                    help="--tiling-ab에서 사용할 비율. 기본 3:1")
    ap.add_argument("--stage-trace", nargs="+", default=None, metavar="SEED",
                    help="Step 2: 지정한 시드로 draft를 돌리며 생성/업스케일/합성 "
                         "각 단계 이미지를 저장하고 좌측 띠를 측정한다")
    ap.add_argument("--seed-scan", type=int, default=0, metavar="N",
                    help="Step 1: draft만 N개 시드로 실행하고 좌측 띠 재현 여부를 본다. "
                         "마지막에 첫 시드를 한 번 더 반복한다")
    ap.add_argument("--seeds", nargs="+", default=None,
                    help="스캔에 쓸 시드를 직접 지정 (--seed-scan 대신)")
    ap.add_argument("--vae-tiling", choices=("keep", "on", "off", "both"),
                    default="keep",
                    help="VAE tiling 변형. 기본 keep은 production 설정을 그대로 둔다. "
                         "both는 한 프로세스에서 on→off를 같은 시드로 연속 실행한다")
    ap.add_argument("--seed", type=int, default=None,
                    help="전체 smoke에서 쓸 시드 고정 (기본 20260808)")
    ap.add_argument("--dry-run", action="store_true",
                    help="실행 계획만 출력 (GPU/모델 로드 없음)")
    args = ap.parse_args()

    src = ROOT / "image" / f"{args.image}.jpg"
    if args.dry_run:
        print(f"""
대상 제품   image/{args.image}.jpg   (존재: {src.exists()})
production 코드를 그대로 호출합니다. 파이프는 관찰만 하고 수정하지 않습니다.

  1) POST /generate/drafts   background_mode=ai, aspect_ratio=3:1, num_images=1
     기대  diffusion 1536x512  →  결과 2304x768
  2) POST /generate/refine   draft_image = 1)의 실제 결과, original_image = 원본
     aspect_ratio 미전송 (draft 크기에서 3:1 추론되는지 확인)
     기대  diffusion 1728x576  →  결과 3072x1024
  3) POST /generate/refine   위와 동일 + text
     ※ SDXL refine을 **다시 한 번 전부 실행**하고 그 위에 문구를 합성한다.
       시간/VRAM은 overlay 단독 비용이 아니라 "refine 재실행 + overlay"다.
  4) sanity  3:4 + ai → 400 / 3:1 refine + original 없음 → 400 / meta 내부 해상도 미노출

  --seed-scan N 이면 위 대신 **draft만** N개 시드로 실행하고 좌측 색 띠 재현
  여부를 본다. 마지막에 첫 시드를 한 번 더 돌려 실행 순서·GPU 상태가 섞이지
  않았는지 대조한다. refine과 production 설정은 건드리지 않는다.

  --vae-tiling both 이면 위 1~4를 tiling ON → OFF 순서로 **같은 프로세스·같은
  시드**로 두 번 실행하고, 좌측 가장자리 비교 이미지를 만든다.
  seed는 스크립트 안에서만 고정한다. drafts 시드가 API로 노출되지 않으므로
  production이 시드를 뽑는 **그 호출 하나만** 가로채고(low/high/size가 정확히
  일치할 때만, 매칭 즉시 원복), 그 외 torch.randint는 원본에 위임한다.
  refine은 generator를 쓰지 않아 호출 직전에 전역 시드를 맞춘다.

결과: {OUT_DIR}
""")
        return

    if not src.exists():
        raise SystemExit(f"제품 이미지가 없습니다: {src}")

    import torch
    import pipeline.generate as G
    _real_load = G._load
    def _observing_load(kind, task, tiling=True):
        # production의 _load 시그니처를 그대로 받아야 한다. tiling 인자를 빠뜨리면
        # 비정사각 draft가 _load(..., tiling=False)를 부를 때 TypeError가 난다.
        LOADS.append({"kind": kind, "task": task, "tiling": tiling})
        return _Observer(_real_load(kind, task, tiling), kind, task, tiling)

    G._load = _observing_load


    sys.path.insert(0, str(ROOT))
    import api as api_module
    from fastapi.testclient import TestClient

    client = TestClient(api_module.app)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    img_b64 = b64_of(src)

    if args.tiling_ab:
        print(f"\n{'=' * 60}\nVAE tiling A/B — {args.ratio} "
              f"(재현 seed 고정, draft만)\n{'=' * 60}")
        run_tiling_ab(client, torch, img_b64, args)
        return

    if args.stage_trace:
        print(f"\n{'=' * 60}\nStep 2 — 단계별 추적 (draft만)\n{'=' * 60}")
        run_stage_trace(client, torch, img_b64, args)
        return

    if args.seed_scan or args.seeds:
        print(f"\n{'=' * 60}\nStep 1 — seed scan (draft만)\n{'=' * 60}")
        run_seed_scan(client, torch, img_b64, args)
        return

    if args.seed is not None:
        globals()["SEED"] = args.seed
        print(f"  seed 고정: {SEED}")
    modes = ["on", "off"] if args.vae_tiling == "both" else [args.vae_tiling]
    logs = []
    for i, mode in enumerate(modes):
        TILING["mode"] = mode
        # 이미 로드된 파이프에도 반영한다(both일 때 두 번째 변형).
        import pipeline.generate as G
        for obj in G._pipes.values():
            _apply_tiling(getattr(obj, "_pipe", obj))
        tag = "" if (mode == "keep" and args.vae_tiling != "both") else f"tiling_{mode}"
        print(f"\n{'=' * 60}\nVAE tiling = {mode.upper()}"
              f"{'  (첫 변형: 모델 로드 시간이 elapsed에 포함됨)' if i == 0 else ''}"
              f"\n{'=' * 60}")
        logs.append(run_variant(client, torch, img_b64, args, tag))

    build_edge_compare()
    bad = [c for lg in logs for c in lg.get("sanity", []) if not c["ok"]]
    if bad:
        raise SystemExit(f"sanity 실패 {len(bad)}건")


def _run_steps(client, torch, img_b64, args, suffix, log):
    log.update(image=args.image, gpu=nvidia_smi())

    # ---------- 1) 3:1 AI draft ----------
    print("\n[1] 3:1 AI draft")
    with deterministic_draft_seed(torch) as seed_ctl:
        r, rec = measure(client, "draft_3x1", "/generate/drafts", {
            "mode": "inpaint", "image": img_b64, "category": CATEGORY,
            "num_images": 1, "background_mode": "ai", "aspect_ratio": "3:1"}, torch,
            note="SD1.5 inpaint 1536x512 → 2304x768. 첫 변형에서는 모델 로드가 "
                 "elapsed에 포함된다.")
    rec["seed_patch_matched"] = seed_ctl["matched"]
    if r.status_code == 200:
        # 응답의 seed로 실제 고정 여부를 확인한다(추측이 아니라 관측).
        rec["draft_seed_returned"] = r.json()["drafts"][0]["seed"]
        rec["seed_controlled"] = rec["draft_seed_returned"] == SEED
    if r.status_code != 200:
        log["steps"].append(rec)
        (OUT_DIR / f"smoke_log{suffix}.json").write_text(
            json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")
        raise SystemExit(f"draft 실패 {r.status_code}: {r.text[:300]}")
    meta = r.json()["meta"]
    draft_b64 = r.json()["drafts"][0]["image"]
    im = decode(draft_b64)
    im.save(OUT_DIR / f"draft_3x1{suffix}.png")
    rec.update(output_size=list(im.size), meta=meta,
               product_bbox=bbox_from_meta(meta))
    log["steps"].append(rec)
    print(f"  {rec['elapsed_sec']}s  diffusion={rec['pipe_calls'][0]['width']}x"
          f"{rec['pipe_calls'][0]['height']}  결과={im.size}  "
          f"peak={rec.get('peak_allocated_gb')}/{rec.get('peak_reserved_gb')}GB")

    # ---------- 2) 실제 draft → refine ----------
    print("\n[2] draft → refine (aspect_ratio 미전송, 추론)")
    r, rec = measure(client, "refine_3x1", "/generate/refine", {
        "draft_image": draft_b64, "original_image": img_b64,
        "category": CATEGORY, "ai_notice": True}, torch,
        note="SDXL inpaint 1728x576 → 3072x1024. SDXL 첫 로드가 elapsed에 포함된다.")
    if r.status_code != 200:
        log["steps"].append(rec)
        (OUT_DIR / f"smoke_log{suffix}.json").write_text(
            json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")
        raise SystemExit(f"refine 실패 {r.status_code}: {r.text[:300]}")
    rmeta = r.json()["meta"]
    rim = decode(r.json()["image"])
    rim.save(OUT_DIR / f"refine_3x1{suffix}.png")
    rec.update(output_size=list(rim.size), meta=rmeta,
               product_bbox=bbox_from_meta(rmeta))
    log["steps"].append(rec)
    print(f"  {rec['elapsed_sec']}s  diffusion={rec['pipe_calls'][0]['width']}x"
          f"{rec['pipe_calls'][0]['height']}  결과={rim.size}  "
          f"peak={rec.get('peak_allocated_gb')}/{rec.get('peak_reserved_gb')}GB")

    # ---------- 3) 문구 overlay ----------
    if not args.no_text:
        print("\n[3] refine + 문구 overlay")
        r, rec = measure(client, "refine_3x1_text", "/generate/refine", {
            "draft_image": draft_b64, "original_image": img_b64,
            "category": CATEGORY, "ai_notice": True, "text": TEXT}, torch,
            note="**overlay 단독 비용이 아니다.** SDXL refine을 처음부터 다시 "
                 "실행하고 그 위에 문구를 합성하는 E2E 검증이다. 시간·VRAM은 "
                 "'refine 전체 재실행 + overlay'로 읽어야 한다.")
        if r.status_code == 200:
            tim = decode(r.json()["image"])
            tim.save(OUT_DIR / f"refine_3x1_text{suffix}.png")
            rec.update(output_size=list(tim.size),
                       text_meta=r.json()["meta"].get("text"),
                       text_layers=r.json()["meta"].get("text_layers"))
            print(f"  {rec['elapsed_sec']}s  결과={tim.size}")
        else:
            print(f"  실패 {r.status_code}: {r.text[:200]}")
        log["steps"].append(rec)

    # ---------- 4) sanity ----------
    print("\n[4] sanity (GPU 생성 없음)")
    checks = []

    def sane(name, ok, detail=""):
        checks.append({"check": name, "ok": bool(ok), "detail": str(detail)})
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}  {detail}")

    rr = client.post("/generate/drafts", json={
        "mode": "inpaint", "image": img_b64, "category": CATEGORY,
        "num_images": 1, "background_mode": "ai", "aspect_ratio": "3:4"})
    sane("3:4 + ai → 400", rr.status_code == 400, rr.status_code)
    sane("error=aspect_ratio_not_supported_for_ai",
         rr.status_code == 400
         and rr.json()["detail"].get("error") == "aspect_ratio_not_supported_for_ai")

    rr = client.post("/generate/refine", json={
        "draft_image": draft_b64, "category": CATEGORY, "ai_notice": False})
    sane("3:1 refine + original_image 없음 → 400", rr.status_code == 400, rr.status_code)
    sane("error=original_image_required_for_nonsquare_ai",
         rr.status_code == 400
         and rr.json()["detail"].get("error") == "original_image_required_for_nonsquare_ai")

    flat = json.dumps(rmeta, ensure_ascii=False)
    sane("meta에 내부 생성 해상도 미노출",
         "1536" not in flat and "1728" not in flat and "576" not in flat,
         "1728x576 / 1536x512가 응답에 없어야 함")
    sane("meta.resolution은 짧은 변 정수",
         isinstance(rmeta.get("resolution"), int), rmeta.get("resolution"))
    log["sanity"] = checks
    log["vae_state"] = _vae_state()

    # ---------- 비교 이미지 ----------
    from PIL import Image, ImageDraw
    h = 300
    cells = [("draft 2304x768", im), ("refine 3072x1024", rim)]
    if not args.no_text and (OUT_DIR / f"refine_3x1_text{suffix}.png").exists():
        cells.append(("refine + 문구", Image.open(OUT_DIR / f"refine_3x1_text{suffix}.png")))
    rows = [(lab, x.resize((int(x.width * h / x.height), h), Image.LANCZOS))
            for lab, x in cells]
    W = max(x.width for _, x in rows) + 24
    H = sum(x.height + 30 for _, x in rows) + 14
    sheet = Image.new("RGB", (W, H), (250, 250, 250))
    dr = ImageDraw.Draw(sheet)
    y = 8
    for lab, x in rows:
        dr.text((12, y), lab, fill=(20, 20, 20))
        y += 24
        sheet.paste(x, (12, y))
        y += x.height + 6
    sheet.save(OUT_DIR / f"compare{suffix}.png")

    (OUT_DIR / f"smoke_log{suffix}.json").write_text(
        json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [f"{'step':18s}{'상태':7s}{'elapsed':10s}{'diffusion':13s}{'결과':13s}"
             f"{'allocA전':10s}{'peakA':9s}{'ΔpeakA':9s}"
             f"{'reservR전':11s}{'peakR':9s}{'ΔpeakR':9s}"]
    for s in log["steps"]:
        pc = s["pipe_calls"][0] if s.get("pipe_calls") else None
        diff = f"{pc['width']}x{pc['height']}" if pc else "-"
        out = ("x".join(map(str, s["output_size"]))
               if s.get("output_size") else "-")
        lines.append(
            f"{s['step']:18s}{str(s['status']):7s}{str(s['elapsed_sec']):10s}"
            f"{diff:13s}{out:13s}"
            f"{str(s.get('allocated_before_gb')):10s}"
            f"{str(s.get('peak_allocated_gb')):9s}"
            f"{str(s.get('delta_peak_allocated_gb')):9s}"
            f"{str(s.get('reserved_before_gb')):11s}"
            f"{str(s.get('peak_reserved_gb')):9s}"
            f"{str(s.get('delta_peak_reserved_gb')):9s}")
    lines += ["",
              "peak*는 단계별로 reset 후 측정했지만 **이미 상주 중인 모델 메모리를 포함**한다.",
              "이번 호출이 추가로 쓴 양은 Δpeak* 열이다.",
              "refine_3x1_text는 overlay 단독 비용이 아니라 refine 전체 재실행 + overlay다.",
              "모델은 일부러 unload하지 않았다(production과 같은 캐시 상태)."]
    bad = [c for c in checks if not c["ok"]]
    lines += ["", f"sanity: {len(checks) - len(bad)}/{len(checks)} 통과"]
    txt = "\n".join(lines)
    (OUT_DIR / f"summary{suffix}.txt").write_text(txt, encoding="utf-8")
    print("\n" + txt)
    print(f"\n결과: {OUT_DIR}")
    return log


if __name__ == "__main__":
    main()
