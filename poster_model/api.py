"""광고 포스터 생성 API.

실행:
    uvicorn api:app --host 0.0.0.0 --port 8000
"""

import base64
import io
import re
from contextlib import asynccontextmanager
from typing import Literal, Optional

from fastapi import FastAPI, HTTPException
from PIL import Image
from pydantic import BaseModel, Field

import pipeline


# ---------------------------------------------------------------- 유틸

def b64_to_image(data: str) -> Image.Image:
    if "," in data[:64]:                  # data:image/png;base64,... 형태 허용
        data = data.split(",", 1)[1]
    try:
        return Image.open(io.BytesIO(base64.b64decode(data)))
    except Exception as exc:
        raise HTTPException(400, f"이미지 디코딩 실패: {exc}")


def image_to_b64(img: Image.Image, fmt: str = "PNG") -> str:
    buf = io.BytesIO()
    img.save(buf, format=fmt)
    return base64.b64encode(buf.getvalue()).decode()


_HEX_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")


def _validate_hex_colors(colors: Optional[list]) -> None:
    for c in colors or []:
        if not _HEX_RE.match(c):
            raise HTTPException(400, f"색상은 #RRGGBB 형식이어야 합니다: {c}")


def _validate_background_colors(mode: str, colors: Optional[list], field: str) -> None:
    """배경 색상 검증 — 형식과, solid/gradient일 때의 최소 개수를 함께 본다.

    ai 모드는 색상 개념이 없어 빈 배열이든 미지정이든 그대로 통과시킨다.

    colors가 None(미지정)이면 카테고리 기본 팔레트를 쓰므로 문제가 없다.
    빈 배열([])은 "색을 지정했는데 하나도 없는" 모순된 입력이라 거부한다 —
    특히 refine의 background.colors는 기본값이 []여서, mode만 solid로 주고
    colors를 빠뜨리면 render_flat_background()의 colors[0]에서 IndexError가 나
    500으로 떨어진다. 스키마를 통과한 요청이 내부 오류가 되지 않도록 여기서 막는다.
    """
    _validate_hex_colors(colors)
    if mode in ("solid", "gradient") and colors is not None and len(colors) == 0:
        raise HTTPException(
            400, f"solid/gradient 배경에는 {field}가 최소 1개 필요합니다.")


# ---------------------------------------------------------------- 스키마

class TextSpec(BaseModel):
    headline: str = ""
    sub: str = ""
    # 좌표 모드(권장): 이미지 폭/높이 대비 0~1 비율. 프론트가 슬라이딩으로 조정한 최종 위치를
    # 그대로 전달하면 된다. 둘 다 주어져야 좌표 모드로 동작하며, 생략 시 position으로 폴백한다.
    x: Optional[float] = Field(default=None, ge=0, le=1)
    y: Optional[float] = Field(default=None, ge=0, le=1)
    # position은 하위 호환용 폴백. x, y가 오면 무시된다.
    position: Literal["top", "center", "bottom"] = "top"
    align: Literal["left", "center", "right"] = "left"
    style: Literal["plain", "bar"] = "bar"
    # 짧은 변 대비 폰트 크기 비율(0~1). 생략 시 config 기본값 사용.
    # 프론트 미리보기와 실제 합성 결과가 어긋나지 않도록, 지정할 경우
    # 프론트가 미리보기에서 계산한 값을 그대로 전달해야 한다.
    headline_size: Optional[float] = Field(default=None, gt=0, le=1)
    sub_size: Optional[float] = Field(default=None, gt=0, le=1)
    # 문구를 제품보다 앞(front)에 그릴지 뒤(behind)에 그릴지. 기본값은 둘 다 "front"라
    # 이 필드를 안 보내면 기존 동작과 완전히 동일하다.
    # behind는 refine 단계에서만, 그리고 원본 이미지로 제품을 합성하는 경로에서만 지원된다.
    # 두 값이 서로 다르면 headline과 sub를 각각 다른 레이어에 그려야 해서 render_text를
    # 두 번 호출하게 되고, 그 경우 style="bar"는 바가 두 개 그려져 기존 결과와 달라지므로
    # 허용하지 않는다(style="plain"만 허용). 두 값이 같으면 기존처럼 한 번에 그리므로
    # bar도 그대로 쓸 수 있다.
    headline_z_order: Literal["front", "behind"] = "front"
    sub_z_order: Literal["front", "behind"] = "front"
    # headline과 sub의 z_order가 달라 따로 그릴 때 sub의 좌표. 좌표 모드(x, y)를 쓰면서
    # 레이어를 분리하는 경우, sub를 headline과 같은 자리에 겹쳐 그리지 않도록 반드시 지정해야 한다.
    sub_x: Optional[float] = Field(default=None, ge=0, le=1)
    sub_y: Optional[float] = Field(default=None, ge=0, le=1)


class BackgroundSpec(BaseModel):
    """solid/gradient 배경 설정. draft 응답에 실제 적용된 값이 담겨 내려가고,
    refine 요청에서는 그 값을 그대로 되돌려주면 된다(서버 무상태 원칙).
    """
    mode: Literal["solid", "gradient", "ai"]
    colors: list[str] = Field(default_factory=list)   # "#RRGGBB" 형식. solid=1개, gradient=2개
    direction: Optional[Literal["vertical", "horizontal", "diagonal"]] = None


class DraftRequest(BaseModel):
    mode: Literal["inpaint", "text2img"]
    image: Optional[str] = None
    prompt: Optional[str] = None
    category: Optional[Literal["food", "beauty", "goods"]] = None
    num_images: int = Field(default=3, ge=1, le=4)
    # background_mode 기본값은 "ai" — 이 필드를 안 보내면 기존 동작과 완전히 동일하다.
    background_mode: Literal["solid", "gradient", "ai"] = "ai"
    bg_colors: Optional[list[str]] = None       # 지정 안 하면 카테고리 기본 팔레트 사용
    gradient_direction: Optional[Literal["vertical", "horizontal", "diagonal"]] = None


class DraftItem(BaseModel):
    id: str
    image: str
    seed: int
    # ai 모드일 땐 None. solid/gradient일 땐 실제 적용된 색상 정보가 담긴다.
    # 프론트는 사용자가 고른 시안의 이 값을 그대로 refine 요청의 background에 담아 보내면 된다.
    background: Optional[BackgroundSpec] = None


class DraftResponse(BaseModel):
    drafts: list[DraftItem]
    meta: dict


class RefineRequest(BaseModel):
    draft_image: str
    original_image: Optional[str] = None   # 제품 보존이 필요할 때
    prompt: Optional[str] = None
    category: Optional[Literal["food", "beauty", "goods"]] = None
    text: Optional[TextSpec] = None
    ai_notice: bool = True
    # drafts 응답의 background를 그대로 echo. 생략하면(None) 기존처럼 ai(diffusion) 경로.
    background: Optional[BackgroundSpec] = None


class RefineResponse(BaseModel):
    image: str
    meta: dict


# ---------------------------------------------------------------- 문구 레이어

def _layer_info(spec: "TextSpec", which: str, meta: dict) -> dict:
    """meta.text_layers에 남길 레이어별 요약. 기존 meta.text 구조는 건드리지 않고,
    실제로 어떤 순서/좌표/크기로 그려졌는지만 additive하게 덧붙인다.
    """
    if which == "headline":
        return {"z_order": spec.headline_z_order,
                "x": spec.x, "y": spec.y,
                "applied_size": meta.get("applied_headline_ratio")}
    return {"z_order": spec.sub_z_order,
            "x": spec.sub_x if spec.sub_x is not None else spec.x,
            "y": spec.sub_y if spec.sub_y is not None else spec.y,
            "applied_size": meta.get("applied_sub_ratio")}


def _render_text_layers(spec: "TextSpec", result: dict):
    """문구를 z_order에 맞는 레이어에 그린다.

    렌더링 순서는 항상 다음과 같다:
        pre_product(배경+그림자) -> behind 문구 -> 제품 합성 -> front 문구

    headline과 sub의 z_order가 같으면 기존과 동일하게 render_text를 한 번만 호출한다
    (front/front는 지금까지의 코드 경로 그대로). 서로 다를 때만 레이어별로 나눠 호출한다.

    Returns: (이미지, 기존 형식의 text meta, text_layers dict)
    """
    final_img = result["image"]
    has_head, has_sub = bool(spec.headline), bool(spec.sub)

    def draw(img, headline, sub, sub_coords: bool):
        """sub_coords=True면 sub 전용 좌표(sub_x/sub_y)를 기준점으로 쓴다."""
        x = spec.sub_x if sub_coords and spec.sub_x is not None else spec.x
        y = spec.sub_y if sub_coords and spec.sub_y is not None else spec.y
        return pipeline.render_text(
            img, headline, sub,
            x=x, y=y,
            position=spec.position,
            align=spec.align,
            style=spec.style,
            headline_size=spec.headline_size,
            sub_size=spec.sub_size,
            return_meta=True)

    # 두 문구의 z_order가 같으면(또는 한쪽만 있으면) 한 번에 그린다 — 기존 동작 그대로.
    separate = has_head and has_sub and spec.headline_z_order != spec.sub_z_order
    if not separate:
        z = spec.headline_z_order if has_head else spec.sub_z_order
        if z == "behind":
            _require_behind_support(result)
            layered = draw(result["pre_product"], spec.headline, spec.sub, sub_coords=False)
            img, text_meta = layered
            img = pipeline.composite_product(result["base"], img, result["product_mask"])
        else:
            img, text_meta = draw(final_img, spec.headline, spec.sub, sub_coords=False)
        layers = {}
        if has_head:
            layers["headline"] = _layer_info(spec, "headline", text_meta)
        if has_sub:
            layers["sub"] = _layer_info(spec, "sub", text_meta)
        return img, text_meta, layers

    # 여기서부터는 headline과 sub이 서로 다른 레이어 — render_text를 두 번 호출한다.
    if spec.style != "plain":
        raise HTTPException(
            400,
            "headline_z_order와 sub_z_order가 다르면 문구를 레이어별로 나눠 그려야 해서 "
            'style="bar"는 바가 두 번 그려집니다. style="plain"을 쓰거나 두 z_order를 같게 하세요.')
    if spec.x is not None and spec.y is not None and (spec.sub_x is None or spec.sub_y is None):
        raise HTTPException(
            400,
            "headline_z_order와 sub_z_order가 다르고 좌표 모드(x, y)를 쓰는 경우, "
            "sub가 headline과 겹치지 않도록 sub_x와 sub_y를 함께 지정해야 합니다.")
    _require_behind_support(result)

    behind_head = spec.headline_z_order == "behind"

    # 1) behind 문구를 pre_product(배경+그림자) 위에 먼저 그린다.
    img = result["pre_product"]
    if behind_head:
        img, head_meta = draw(img, spec.headline, "", sub_coords=False)
    else:
        img, sub_meta = draw(img, "", spec.sub, sub_coords=True)

    # 2) 제품을 합성한다 — 이 시점에 제품이 behind 문구의 일부를 가린다.
    img = pipeline.composite_product(result["base"], img, result["product_mask"])

    # 3) front 문구를 제품 위에 그린다.
    if behind_head:
        img, sub_meta = draw(img, "", spec.sub, sub_coords=True)
    else:
        img, head_meta = draw(img, spec.headline, "", sub_coords=False)

    # 기존 meta.text 구조(단일 dict)를 유지하기 위해 headline 쪽 meta를 기준으로 삼고,
    # sub의 실제 적용 크기만 채워 넣는다. 레이어별 상세는 text_layers에 따로 남는다.
    text_meta = {**head_meta, "applied_sub_px": sub_meta.get("applied_sub_px"),
                 "applied_sub_ratio": sub_meta.get("applied_sub_ratio")}
    layers = {"headline": _layer_info(spec, "headline", head_meta),
              "sub": _layer_info(spec, "sub", sub_meta)}
    return img, text_meta, layers


def _require_behind_support(result: dict) -> None:
    """z_order="behind"는 제품을 따로 합성하는 경로에서만 가능하다.

    원본 이미지 없이 돌아가는 img2img 폴백 경로는 제품 합성 단계 자체가 없어
    "제품 뒤"라는 레이어가 존재하지 않는다. 조용히 front로 떨어뜨리면 사용자가
    요청한 것과 다른 결과가 나오므로 명시적으로 거부한다.
    """
    if result.get("pre_product") is None or result.get("product_mask") is None:
        raise HTTPException(
            400,
            'z_order="behind"는 제품을 원본에서 다시 합성하는 경로에서만 지원됩니다. '
            "original_image를 함께 보내주세요.")


# ---------------------------------------------------------------- 앱

@asynccontextmanager
async def lifespan(app: FastAPI):
    pipeline.warmup()      # 요청마다 모델을 로드하지 않도록 미리 적재
    yield
    pipeline.unload()


app = FastAPI(title="광고 포스터 생성 API", lifespan=lifespan)


@app.get("/health")
def health():
    return {"status": "ok",
            "draft_model": pipeline.config.DRAFT_MODEL,
            "refine_model": pipeline.config.REFINE_MODEL}


@app.post("/admin/gc")
def admin_gc():
    """GPU 캐시/파이썬 가비지 정리.

    여러 장을 연속 생성할 때(배치 검증 등) 호출 사이에 불러서 캐시된 CUDA
    메모리를 비워준다. 로컬(WSL) 환경에서 연속 생성 시 메모리 누적으로
    시스템이 느려지거나 멈추는 문제의 완화용. 근본 원인이 아니라 완화책이라
    계속 문제가 있으면 이미지 수를 줄이거나 서버 자체를 재시작하는 게 낫다.
    """
    import gc
    gc.collect()
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.synchronize()
    except ImportError:
        pass
    return {"status": "ok"}


@app.post("/generate/drafts", response_model=DraftResponse)
def generate_drafts(req: DraftRequest):
    if req.mode == "inpaint" and not req.image:
        raise HTTPException(400, "inpaint 모드에는 image가 필요합니다.")
    if req.background_mode != "ai" and not req.image:
        raise HTTPException(400, "solid/gradient 배경 모드는 image가 필요합니다.")
    _validate_background_colors(req.background_mode, req.bg_colors, "bg_colors")

    image = b64_to_image(req.image) if req.image else None
    result = pipeline.generate_drafts(
        image=image,
        prompt=req.prompt,
        category=req.category,
        num_images=req.num_images,
        background_mode=req.background_mode,
        bg_colors=req.bg_colors,
        gradient_direction=req.gradient_direction,
    )

    backgrounds = result.get("backgrounds") or [None] * len(result["images"])
    drafts = [
        DraftItem(id=f"d{i+1}", image=image_to_b64(img), seed=seed,
                 background=BackgroundSpec(**bg) if bg else None)
        for i, (img, seed, bg) in enumerate(
            zip(result["images"], result["seeds"], backgrounds))
    ]
    return DraftResponse(drafts=drafts, meta=result["meta"])


@app.post("/generate/refine", response_model=RefineResponse)
def generate_refine(req: RefineRequest):
    draft = b64_to_image(req.draft_image)
    original = b64_to_image(req.original_image) if req.original_image else None

    background = None
    if req.background:
        _validate_background_colors(req.background.mode, req.background.colors,
                                    "background.colors")
        if req.background.mode in ("solid", "gradient") and original is None:
            raise HTTPException(400, "solid/gradient 배경 refine에는 original_image가 필요합니다.")
        background = {"mode": req.background.mode,
                     "colors": req.background.colors,
                     "direction": req.background.direction}

    result = pipeline.refine(draft, original=original,
                             prompt=req.prompt, category=req.category,
                             background=background)
    img = result["image"]

    meta = result["meta"]
    if req.text and (req.text.headline or req.text.sub):
        img, text_meta, layers = _render_text_layers(req.text, result)
        meta = {**meta, "text": text_meta, "text_layers": layers}

    # AI 생성물 표시는 모든 문구 합성이 끝난 뒤 최상단에 한 번만 적용한다.
    if req.ai_notice:
        img = pipeline.add_ai_notice(img)

    return RefineResponse(image=image_to_b64(img), meta=meta)
