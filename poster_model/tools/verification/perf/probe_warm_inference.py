"""추론 warmup 실험 — 첫 요청 cold overhead 의 정체를 가른다 (production 무수정).

## 배경

`warmup()` 에 누락 경로를 채운 뒤에도 첫 요청이 느리다.

    draft  (SD1.5 768)    8.91 → 6.37      one-time  약  2.5s
    refine (SDXL 1024)   64.09 → 10.70     one-time  약 53.4s

`_load()` 는 파이프라인 **객체 생성과 캐시**만 한다. 그 뒤에도 남는 비용이므로
원인은 "첫 실행" 쪽에 있다.

## 확인된 것 / 아직 확인되지 않은 것 — 구분해서 읽을 것

**확인된 것 (코드 수준)**

    from_pretrained 가 low_cpu_mem_usage 를 지정하지 않는다.

**mmap 이 쓰이는 조건 — 모든 모델에 일반화하지 말 것**

    diffusers 의 mmap 은 **safetensors 를 실제로 로드하는 경로**에서
    `disable_mmap=False`(기본) 일 때 적용된다.
    safetensors 가 없어 pickle(.bin) 로 떨어지는 저장소는 torch.load 를 타므로
    **로드 시점에 전량 RAM 으로 읽힌다. 첫 추론의 page-in 이 없다.**

    서버 로그상 SD1.5 inpaint 는 safetensors 가 없어 unsafe serialization
    fallback 을 타고 있다. 즉 저장소마다 다르다.

    → 그래서 이 스크립트는 시작할 때 **저장소별로 실제 가중치 파일 형식과
      크기를 출력한다.** 특히 핵심 경로인 SDXL img2img(= MODELS["sdxl"]
      ["text2img"] 저장소)가 safetensors 를 쓰는지 반드시 확인한다.

**아직 확인되지 않은 것**

    그 53초가 실제로 **디스크 page-in 때문인지**는 확정되지 않았다.
    아래는 최우선 가설이며, /proc 측정 결과로 귀속한다.

## 가설 (귀속 전. 우선순위 순)

    ① mmap page-in                   최우선 가설
       safetensors + mmap 인 저장소에서, 첫 추론의 GPU 전송 때 페이지가
       디스크에서 읽힌다.
           SDXL 5GB / 53.4s ≈ 94 MB/s   ← GCP pd-balanced 수준과 어긋나지 않는다

       **SD1.5 와의 7배 처리량 차이(1.7GB / 2.5s ≈ 680 MB/s)를 이 가설이
       설명할 수 있는지가 관건이다.** 만약 SD1.5 쪽이 .bin(torch.load) 이라
       이미 전량 RAM 에 있었다면 애초에 page-in 이 없었던 것이고, 그러면 두
       수치가 서로 모순되지 않는다. 시작 시 출력하는 파일 형식이 이 판단의
       근거가 된다. **다만 그것만으로 확정하지 않고 RssFile 증가로 귀속한다.**

    ② CUDA / cuDNN 첫 커널 오토튠     5~15s 수준으로 추정
    ③ offload H2D 전송                L4 기준 1s 미만으로 추정

## 무엇으로 가르는가 — RssFile 증가가 주 지표다

처음에는 major page fault 를 주 지표로 잡았다가, 검증에서 **못 쓴다는 것을
확인했다.** page cache 를 비운 96MB 파일을 mmap 순차 접근했을 때:

    RSS 증가    +96.0 MB      정확하다
    디스크읽기  192.0 MB      시스템 전체 값이라 부풀려진다
    majflt            1 건    ← 96MB 를 읽었는데 1 건

리눅스가 **readahead** 로 앞당겨 읽어 두기 때문에 순차 접근은 대부분 minor
fault 로 처리된다. **majflt 는 page-in 을 크게 과소 계수한다.**

그리고 RSS 는 둘로 나눠 봐야 한다.

    RssFile   파일 매핑이 상주로 바뀐 양   ← **mmap page-in 은 여기로 잡힌다**
    RssAnon   익명 메모리(torch 텐서 등)   ← .bin 로드나 연산 버퍼는 여기

따라서 보는 순서는 이렇다.

    ① RssFile 증가        주 지표. mmap page-in 을 직접 겨냥
    ② /proc/diskstats     보조. 시스템 전체라 다른 프로세스 I/O 가 섞인다
                          (그래서 poster.service 를 반드시 내려야 한다)
    ③ VmRSS / RssAnon     맥락. RssAnon 이 늘면 page-in 이 아니라 연산 버퍼다
    ④ majflt              참고. 크면 의미 있지만, 작다고 page-in 이 없는 건 아님

## 이 스크립트가 하는 일

한 프로세스 안에서 구간을 나눠 잰다. 프로세스를 새로 띄워야 cold 상태가 되므로
A/B 는 **별도 실행**으로 비교한다.

    phase 0  import pipeline
    phase 1  pipeline.warmup()            현재 production 이 하는 것 (_load 만)
    phase 2  추론 warmup  (--infer-warm)  ← 실험 대상. B 에서만 실행
    phase 3  실제 요청 1회                 ← 개선하려는 값
    phase 4  실제 요청 2회                 warm baseline

    A:  --target refine
    B:  --target refine --infer-warm

    phase 3 이 A 대비 B 에서 얼마나 줄었는지가 결과다.
    phase 2 는 startup 증가분이다.

## 실행 전 반드시 — poster.service 를 내릴 것

systemd 서버와 probe 를 동시에 띄우면 RAM · GPU · page cache 조건이 오염된다.
서버가 이미 모델을 매핑해 두면 probe 의 cold 측정이 성립하지 않는다.
스크립트가 시작할 때 8000 포트와 poster.service 를 확인하고, 살아 있으면 멈춘다.

    sudo systemctl stop poster.service
    ss -lntp | grep :8000     # 아무것도 안 나와야 한다

## page cache 를 반드시 통제할 것

    시나리오 1  캐시 드롭 후        재부팅 직후에 해당. 최악값
                sudo sync && sudo sh -c 'echo 3 > /proc/sys/vm/drop_caches'
    시나리오 2  캐시 유지           systemd 재시작만 한 실제 배포 상황

## production 을 고치지 않는다

`pipeline.warmup()` 과 `pipeline.refine()` / `generate_drafts()` 를 그대로
호출한다. 추론 warmup 도 이 스크립트 안에서만 한다.

## 실행 (GCP)

    sudo systemctl stop poster.service
    cd /home/spai1033/Final-Project-team5/poster_model
    source ~/venv/adgen/bin/activate      # 실제 venv 경로에 맞출 것
    PYTHONPATH="$PWD" python -u ~/probe_warm_inference.py --target refine
"""
import argparse
import json
import os
import time

from PIL import Image


# ------------------------------------------------------------------ 사전 점검
def preflight(allow_service: bool):
    """poster.service / 8000 포트가 살아 있으면 멈춘다."""
    problems = []
    for path in ("/proc/net/tcp", "/proc/net/tcp6"):
        try:
            with open(path) as f:
                next(f)
                for line in f:
                    p = line.split()
                    if p[1].endswith(":1F90") and p[3] == "0A":   # 8000, LISTEN
                        problems.append(f"8000 포트가 LISTEN 중입니다 ({path})")
                        break
        except Exception:
            pass
    try:
        import subprocess
        r = subprocess.run(["systemctl", "is-active", "poster.service"],
                           capture_output=True, text=True, timeout=5)
        if r.stdout.strip() == "active":
            problems.append("poster.service 가 active 입니다")
    except Exception:
        pass

    if not problems:
        print("  [사전 점검] poster.service / 8000 포트 모두 비어 있음  OK")
        return
    print("\n" + "!" * 96)
    for p in problems:
        print(f"  {p}")
    print("""
  서버와 probe 를 동시에 띄우면 RAM · GPU · page cache 조건이 오염됩니다.
  서버가 이미 모델을 매핑해 두면 cold 측정 자체가 성립하지 않습니다.

      sudo systemctl stop poster.service
      ss -lntp | grep :8000        # 아무것도 안 나와야 합니다
""".rstrip())
    print("!" * 96)
    if not allow_service:
        raise SystemExit(2)
    print("  --allow-service-running 지정됨. 강행합니다 (측정 신뢰도 낮음)\n")


# ------------------------------------------------------ 가중치 파일 형식 확인
def _hub_snapshot(repo_id):
    """HF 캐시에서 저장소 스냅샷 디렉터리를 찾는다. 없으면 None."""
    root = os.environ.get("HF_HOME") or os.path.expanduser("~/.cache/huggingface")
    base = os.path.join(root, "hub", "models--" + repo_id.replace("/", "--"),
                        "snapshots")
    if not os.path.isdir(base):
        return None
    subs = [os.path.join(base, d) for d in os.listdir(base)]
    subs = [d for d in subs if os.path.isdir(d)]
    return max(subs, key=os.path.getmtime) if subs else None


def report_weight_files(config, variant_hint=None):
    """저장소별로 실제 가중치 파일 형식과 크기를 출력한다.

    **mmap 은 safetensors 를 실제 로드하는 경로에서만 적용된다.**
    safetensors 가 없어 .bin(pickle) 로 떨어지면 torch.load 로 전량 RAM 에
    읽히므로 첫 추론의 page-in 이 없다. 저장소마다 다르므로 확인이 필요하다.

    심볼릭 링크를 따라 실제 blob 크기를 잰다(HF 캐시는 blobs 를 링크한다).
    """
    print("\n  [가중치 파일 형식] mmap 여부는 저장소마다 다르다")
    out = {}
    seen = set()
    for kind, spec in config.MODELS.items():
        for task in ("inpaint", "text2img"):
            repo = spec.get(task)
            if not repo or repo in seen:
                continue
            seen.add(repo)
            snap = _hub_snapshot(repo)
            info = {"repo": repo, "kind": kind, "snapshot": snap,
                    "safetensors_MB": 0.0, "bin_MB": 0.0,
                    "safetensors_files": 0, "bin_files": 0,
                    "variant_files": []}
            if snap:
                for dirpath, _dirs, files in os.walk(snap):
                    for fn in files:
                        fp = os.path.join(dirpath, fn)
                        try:
                            mb = os.path.getsize(os.path.realpath(fp)) / 2**20
                        except OSError:
                            continue
                        if fn.endswith(".safetensors"):
                            info["safetensors_MB"] += mb
                            info["safetensors_files"] += 1
                            if ".fp16." in fn:
                                info["variant_files"].append(fn)
                        elif fn.endswith(".bin"):
                            info["bin_MB"] += mb
                            info["bin_files"] += 1
            info["safetensors_MB"] = round(info["safetensors_MB"], 1)
            info["bin_MB"] = round(info["bin_MB"], 1)
            if snap is None:
                verdict = "캐시 못 찾음 (경로/HF_HOME 확인)"
            elif info["safetensors_files"] and not info["bin_files"]:
                verdict = "safetensors 만 → mmap 적용. page-in 대상 ★"
            elif info["safetensors_files"] and info["bin_files"]:
                verdict = "둘 다 존재 → safetensors 우선. mmap 가능 ★"
            elif info["bin_files"]:
                verdict = ".bin 만 → torch.load. 로드 시 전량 RAM. page-in 없음"
            else:
                verdict = "가중치 파일 못 찾음"
            info["verdict"] = verdict
            out[repo] = info
            print(f"    {kind:5s} {task:9s} {repo}")
            print(f"          safetensors {info['safetensors_MB']:9.1f} MB "
                  f"({info['safetensors_files']}개)   "
                  f".bin {info['bin_MB']:9.1f} MB ({info['bin_files']}개)")
            print(f"          → {verdict}")
    print("\n    ※ SDXL img2img 는 MODELS['sdxl']['text2img'] 저장소를 쓴다. "
          "그 줄이 핵심이다.")
    return out


# ------------------------------------------------------------------ 계측
def _disk_read_bytes():
    """/proc/diskstats 누적 읽기 바이트. 섹터 512B. **시스템 전체** 값이다."""
    total = 0
    try:
        with open("/proc/diskstats") as f:
            for line in f:
                p = line.split()
                if len(p) < 7 or p[2].startswith(("loop", "ram", "dm-")):
                    continue
                total += int(p[5]) * 512
    except Exception:
        return None
    return total


def _majflt():
    """major page fault 누적. readahead 때문에 page-in 을 과소 계수한다(참고용)."""
    try:
        with open("/proc/self/stat") as f:
            s = f.read()
        return int(s[s.rindex(")") + 2:].split()[9])
    except Exception:
        return None


def _rss_parts():
    """VmRSS / RssAnon / RssFile / RssShmem (MB).

    RssFile 이 **파일 매핑이 상주로 바뀐 양**이라 mmap page-in 을 직접 겨냥한다.
    RssAnon 은 torch.load 로 읽은 텐서나 연산 버퍼 쪽이다.
    """
    keys = {"VmRSS": "VmRSS", "RssAnon": "RssAnon",
            "RssFile": "RssFile", "RssShmem": "RssShmem"}
    out = {}
    try:
        with open("/proc/self/status") as f:
            for line in f:
                k = line.split(":")[0]
                if k in keys:
                    out[keys[k]] = round(int(line.split()[1]) / 1024, 1)
    except Exception:
        return {}
    return out


def _vram():
    try:
        import torch
        if not torch.cuda.is_available():
            return None
        return {"alloc_MB": round(torch.cuda.memory_allocated() / 2**20, 1),
                "reserved_MB": round(torch.cuda.memory_reserved() / 2**20, 1),
                "max_alloc_MB": round(torch.cuda.max_memory_allocated() / 2**20, 1)}
    except Exception:
        return None


class Phase:
    """구간 시간 · RSS 분해 · 디스크 읽기 · majflt · VRAM 을 함께 기록한다."""

    rows = []

    def __init__(self, name):
        self.name = name

    def __enter__(self):
        self.t = time.time()
        self.d = _disk_read_bytes()
        self.m = _majflt()
        self.r = _rss_parts()
        return self

    def __exit__(self, *a):
        dt = time.time() - self.t
        d1, m1, r1 = _disk_read_bytes(), _majflt(), _rss_parts()
        delta = {k: round(r1.get(k, 0) - self.r.get(k, 0), 1) for k in r1}
        row = {
            "phase": self.name,
            "sec": round(dt, 2),
            "rss_delta_MB": delta,           # VmRSS / RssAnon / RssFile / RssShmem
            "rss_after_MB": r1,
            "disk_read_MB": None if (self.d is None or d1 is None)
                            else round((d1 - self.d) / 2**20, 1),
            "majflt": None if (self.m is None or m1 is None) else m1 - self.m,
            "vram": _vram(),
        }
        Phase.rows.append(row)
        dr = "   -  " if row["disk_read_MB"] is None else f"{row['disk_read_MB']:8.1f}"
        vr = row["vram"]["reserved_MB"] if row["vram"] else 0
        print(f"  {self.name:28s} {dt:7.2f}s  "
              f"RssFile+ {delta.get('RssFile', 0):9.1f}MB ★  "
              f"RssAnon+ {delta.get('RssAnon', 0):9.1f}MB  "
              f"VmRSS {r1.get('VmRSS', 0):9.1f}MB  "
              f"디스크 {dr}MB  majflt {row['majflt']:8}  "
              f"VRAM {vr:7.1f}MB", flush=True)


# ------------------------------------------------------------------ 작업 정의
def _white(px):
    return Image.new("RGB", (px, px), (255, 255, 255))


def make_calls(pipeline, target):
    """(추론warmup 함수, 실제요청 함수).

    실제요청은 **production 공개 함수를 그대로** 부른다.
    추론warmup 은 같은 파이프라인 객체를 최소 step 으로 한 번 돌린다.
    """
    cfg = pipeline.config
    from pipeline import generate as G

    if target == "draft":
        size = cfg.MODELS[cfg.DRAFT_MODEL]["size"]

        def real():
            return pipeline.generate_drafts(
                image=None, prompt="a plain studio background",
                num_images=1, seeds=[12345],
                background_mode="ai", aspect_ratio="1:1")

        def warm(steps):
            pipe = G._load(cfg.DRAFT_MODEL, "text2img")
            pipe(prompt="warmup", negative_prompt="",
                 height=size, width=size,
                 num_inference_steps=steps, num_images_per_prompt=1)

    elif target == "refine":
        size = cfg.MODELS[cfg.REFINE_MODEL]["size"]

        def real():
            return pipeline.refine(draft=_white(size), original=None,
                                   prompt="a plain studio background")

        def warm(steps):
            key = f"{cfg.REFINE_MODEL}_img2img"
            pipe = G._pipes.get(key) or G._load(cfg.REFINE_MODEL, "img2img")
            pipe(prompt="warmup", image=_white(size),
                 strength=0.35, num_inference_steps=steps)
    else:
        raise SystemExit(f"알 수 없는 target: {target}")

    return warm, real


# ------------------------------------------------------------------ main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", choices=["draft", "refine"], required=True)
    ap.add_argument("--infer-warm", action="store_true",
                    help="startup 에서 추론을 1회 돌린다 (실험 대상)")
    ap.add_argument("--warm-steps", type=int, default=2)
    ap.add_argument("--allow-service-running", action="store_true",
                    help="poster.service 가 떠 있어도 강행 (측정 신뢰도 낮음)")
    ap.add_argument("--json", default=None)
    a = ap.parse_args()

    print("=" * 124)
    print(f"추론 warmup 실험   target={a.target}   "
          f"infer_warm={'ON' if a.infer_warm else 'OFF'}"
          + (f" (steps={a.warm_steps})" if a.infer_warm else ""))
    print("=" * 124)
    print(f"  pid={os.getpid()}   cwd={os.getcwd()}")
    preflight(a.allow_service_running)

    with Phase("0. import pipeline"):
        import pipeline

    cfg = pipeline.config
    print(f"\n  DRAFT={cfg.DRAFT_MODEL} REFINE={cfg.REFINE_MODEL}  "
          f"USE_CPU_OFFLOAD={cfg.USE_CPU_OFFLOAD}  "
          f"KEEP_BOTH_LOADED={cfg.KEEP_BOTH_LOADED}")
    print(f"  DRAFT_STEPS={cfg.DRAFT_STEPS} REFINE_STEPS={cfg.REFINE_STEPS} "
          f"REFINE_STRENGTH={cfg.REFINE_STRENGTH}")
    weights = report_weight_files(cfg)
    print()

    warm, real = make_calls(pipeline, a.target)

    with Phase("1. warmup() [_load 만]"):
        pipeline.warmup()

    if a.infer_warm:
        with Phase(f"2. 추론 warmup ({a.warm_steps}step)"):
            warm(a.warm_steps)
    else:
        print(f"  {'2. 추론 warmup':28s}   (건너뜀)")

    with Phase("3. 실제 요청 1회  ★"):
        real()

    with Phase("4. 실제 요청 2회"):
        real()

    # ---- 요약
    by = {r["phase"]: r for r in Phase.rows}
    startup = sum(r["sec"] for r in Phase.rows
                  if r["phase"].startswith(("1.", "2.")))
    p3, p4 = by["3. 실제 요청 1회  ★"], by["4. 실제 요청 2회"]
    d3 = p3["rss_delta_MB"]

    print("\n" + "-" * 124)
    print(f"  startup 합계 (phase 1+2)   {startup:7.2f}s")
    print(f"  첫 요청      (phase 3) ★   {p3['sec']:7.2f}s")
    print(f"  두번째 요청  (phase 4)     {p4['sec']:7.2f}s")
    print(f"  첫 요청의 one-time 비용    {p3['sec'] - p4['sec']:7.2f}s")
    print(f"\n  [원인 귀속용] 첫 요청 구간")
    print(f"     RssFile 증가  ★   {d3.get('RssFile', 0):10.1f} MB   "
          f"주 지표 — mmap page-in")
    print(f"     RssAnon 증가      {d3.get('RssAnon', 0):10.1f} MB   "
          f"익명 메모리(연산 버퍼 등)")
    print(f"     VmRSS 증가        {d3.get('VmRSS', 0):10.1f} MB")
    print(f"     디스크 읽기(전체)  {str(p3['disk_read_MB']):>10s} MB   보조")
    print(f"     major fault       {p3['majflt']:10,d} 건   "
          f"참고 (readahead 로 과소 계수)")
    print("     · RssFile 이 GB 단위로 늘면   → mmap page-in (가설 ①)")
    print("     · RssFile 은 그대로인데 느리면 → ① 아님. CUDA 첫 커널(②) 쪽")
    print("     ※ 한 번의 실행으로 확정하지 말 것. "
          "캐시드롭 / 캐시유지 두 시나리오를 비교해 귀속한다.")
    print("-" * 124)

    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump({"target": a.target, "infer_warm": a.infer_warm,
                       "warm_steps": a.warm_steps,
                       "config": {"use_cpu_offload": cfg.USE_CPU_OFFLOAD,
                                  "keep_both_loaded": cfg.KEEP_BOTH_LOADED,
                                  "draft_steps": cfg.DRAFT_STEPS,
                                  "refine_steps": cfg.REFINE_STEPS,
                                  "refine_strength": cfg.REFINE_STRENGTH},
                       "weight_files": weights,
                       "phases": Phase.rows,
                       "summary": {"startup_sec": round(startup, 2),
                                   "first_sec": p3["sec"],
                                   "second_sec": p4["sec"],
                                   "one_time_sec": round(p3["sec"] - p4["sec"], 2),
                                   "first_rss_delta_MB": d3,
                                   "first_disk_read_MB": p3["disk_read_MB"],
                                   "first_majflt": p3["majflt"]}},
                      f, ensure_ascii=False, indent=2)
        print(f"  JSON  {a.json}")


if __name__ == "__main__":
    main()
