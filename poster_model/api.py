"""광고 포스터 생성 API.

실행:
    uvicorn api:app --host 0.0.0.0 --port 8000
"""

import base64
import io
import re
import time
from contextlib import asynccontextmanager
from typing import Literal, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from PIL import Image
from pydantic import BaseModel, ConfigDict, Field

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
    # 사용자가 고른 폰트. 하나를 골라 headline과 sub에 **공통** 적용한다
    # (프론트에서 폰트를 하나만 선택하는 계약).
    # 보내지 않으면 기존 기본 렌더링 경로가 그대로 유지된다.
    # Literal이 아니라 str로 받는 이유: Literal은 pydantic이 422를 내는데,
    # 여기서는 어떤 폰트가 왜 안 되는지 구분된 400을 내려야 한다.
    # 실제 허용값 검사는 _validate_font_id에서 한다.
    font_id: Optional[str] = None
    # 타이포 스타일 프리셋. config.TONE_PRESETS의 키를 이름으로 받는다.
    #
    # 지금까지 API는 프리셋 5개 값 중 headline_size / sub_size **두 개만**
    # 전달해서, 두 톤을 실제로 가르는 stroke_width / fill_color /
    # headline_font_role이 렌더러까지 넘어가지 않았다. tone을 받아 서버가
    # 다섯 값을 모두 푼다(verification 스크립트는 TONE_PRESETS를 직접 읽어
    # 프리셋대로 그리는데, 실제 API 경로에서만 그 효과가 빠져 있었다).
    #
    # 개별 필드(headline_size 등)를 함께 보내면 **그쪽이 이긴다** — 프론트가
    # 미리보기에서 계산한 값이 있으면 그것과 어긋나면 안 되기 때문이다.
    # 보내지 않으면 render_text 기본값이 그대로 쓰여 기존 렌더 동작이 유지된다.
    #
    # 챗봇 spec.tone(simple/warm/luxury/energetic)과는 다른 축이다. 그쪽은
    # 배경 프롬프트로 가고, 이 tone은 문구 타이포에만 쓰인다.
    #
    # Literal이 아니라 str인 이유는 font_id와 같다(구분된 400을 내려야 한다).
    tone: Optional[str] = None


class BackgroundSpec(BaseModel):
    """solid/gradient 배경 설정. draft 응답에 실제 적용된 값이 담겨 내려가고,
    refine 요청에서는 그 값을 그대로 되돌려주면 된다(서버 무상태 원칙).
    """
    mode: Literal["solid", "gradient", "ai"]
    colors: list[str] = Field(default_factory=list)   # "#RRGGBB" 형식. solid=1개, gradient=2개
    direction: Optional[Literal["vertical", "horizontal", "diagonal"]] = None


class PlacementSpec(BaseModel):
    """제품 배치 override. 전부 선택이며, 지정한 필드만 서버 기본값을 덮는다.

    x, y는 **제품 bbox 중심점**의 캔버스 정규화 좌표(0~1)다. 좌상단이 아니다.
    좌상단을 기준으로 두면 배율을 바꿀 때마다 사용자가 잡은 지점이 같이 움직인다.
    TextSpec.x / TextSpec.y와 같은 정규화 규약을 쓴다.

    scale_factor는 **서버 기본 배율 대비 배수**다(1.0 = 기본값 그대로). 내부의
    소스 누끼 대비 절대 배율은 클라이언트가 해석할 수 없어 노출하지 않는다.

    응답 meta.placement에는 source / region_overflow가 더 있지만 그 둘은
    response-only다. 이어서 적용할 때는 scale_factor / x / y 세 개만 담는다.
    응답 객체를 통째로 되보내고 extra 무시에 기대는 구조를 쓰지 않는다.
    le=3은 비상식적인 값을 스키마에서 거르는 용도다. 실제 허용 상한은 제품마다
    다르며(자동 배율이 이미 크면 여유가 적다), 확대 품질 상한을 넘으면 400과
    함께 max_scale_factor를 알려준다.
    """
    # extra="forbid" — 응답 placement 객체를 통째로 되보내는 것을 막는다.
    # source / region_overflow는 response-only이며, 조용히 무시하면 클라이언트가
    # 그 값이 반영된 줄 알게 된다.
    model_config = ConfigDict(extra="forbid")

    scale_factor: Optional[float] = Field(default=None, gt=0, le=3)
    x: Optional[float] = Field(default=None, ge=0, le=1)
    y: Optional[float] = Field(default=None, ge=0, le=1)


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
    # 아래 2개를 보내지 않으면 기존 1:1 동작과 완전히 동일하다.
    # solid/gradient 배경에서만 지원한다(AI 비정사각 생성은 미지원).
    aspect_ratio: Optional[Literal["1:1", "3:1", "3:4"]] = None
    placement: Optional[PlacementSpec] = None


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
    # 생략하면 draft_image 크기에서 비율을 추론한다. 768x768이면 "1:1"이라
    # 기존 클라이언트는 아무것도 보내지 않아도 동작이 같다.
    aspect_ratio: Optional[Literal["1:1", "3:1", "3:4"]] = None
    # drafts 응답 meta.placement의 scale_factor / x / y만 담아 보낸다.
    placement: Optional[PlacementSpec] = None


class RefineResponse(BaseModel):
    image: str
    meta: dict


class TextComposeRequest(BaseModel):
    """/compose/text — diffusion 없이 문구만 다시 합성한다.

    base_image에는 **문구와 AI 생성 표시가 없는 이미지**를 넣는다. 표준 흐름은
    /generate/refine을 text 없이 ai_notice=false로 호출해 받은 결과를 프론트가
    보관했다가 여기에 넘기는 것이다. 이미 구워진 픽셀은 서버가 구분할 수 없으므로
    이 조건은 계약으로만 지켜진다(문구가 있는 이미지를 넣으면 겹쳐 그려지고,
    표시가 있는 이미지에 ai_notice=true를 주면 표시가 두 번 들어간다).

    text는 /generate/refine과 **같은 TextSpec**이라 프론트가 같은 객체를 양쪽에
    그대로 쓸 수 있다. 다만 이번 단계는 front 문구만 지원하므로 z_order가
    "behind"면 400으로 거부한다.
    """
    base_image: str
    text: TextSpec
    ai_notice: bool = True


class TextComposeResponse(BaseModel):
    image: str
    meta: dict


def _validate_canvas_request(aspect_ratio, placement, background_mode, mode=None) -> None:
    """비율/배치 요청이 지원되는 조합인지 확인한다.

    AI 배경은 검증된 비율만 연다(config.AI_SUPPORTED_RATIOS). 지원하지 않는
    비율을 조용히 정사각으로 떨어뜨리지 않고 막는다.
    placement는 여전히 solid/gradient 전용이다.
    """
    non_square = aspect_ratio is not None and aspect_ratio != "1:1"
    if not non_square and placement is None:
        return
    what = "aspect_ratio" if non_square else "placement"
    if background_mode == "ai":
        if placement is not None:
            raise HTTPException(
                400, "placement는 solid/gradient 배경에서만 지원합니다 "
                     "(요청: background_mode=ai).")
        _validate_ai_ratio(aspect_ratio)
    if mode == "text2img":
        raise HTTPException(
            400, f"{what}는 제품 이미지가 있는 요청에서만 지원합니다 "
                 f"(요청: mode=text2img).")


def _validate_ai_ratio(ratio: Optional[str]) -> None:
    """AI 배경에서 지원하는 비율인지 확인한다.

    3:4는 제품 외부에 구조를 생성하는 continuation이 확인됐고, 투명/위험 제품을
    구분하는 정책이 아직 없어 기술적으로 미지원 상태다.
    """
    if ratio is None or ratio in pipeline.config.AI_SUPPORTED_RATIOS:
        return
    raise HTTPException(400, detail={
        "error": "aspect_ratio_not_supported_for_ai",
        "message": f"aspect_ratio {ratio!r}는 AI 배경에서 아직 지원하지 않습니다. "
                   f"solid/gradient 배경에서는 사용할 수 있습니다.",
        "requested": ratio,
        "supported": list(pipeline.config.AI_SUPPORTED_RATIOS)})


def _canvas_meta(meta: dict, aspect_ratio: Optional[str]) -> dict:
    """응답 meta에 resolved 비율/캔버스/배치를 채운다.

    - aspect_ratio는 요청에서 생략됐어도 resolved 값("1:1")을 내려준다.
    - placement는 실제 제품 배치가 있는 경로에서만 값이 있고, text2img처럼
      배치 개념이 없는 경로는 null이다. 기존 경로의 동작은 바꾸지 않는다.
    - resolution(짧은 변 정수)은 그대로 두고 canvas를 추가만 한다.
    """
    out = dict(meta)
    out.setdefault("aspect_ratio", aspect_ratio or "1:1")
    if "canvas" not in out:
        size = out.get("resolution")
        out["canvas"] = ({"width": size, "height": size} if size else None)
    out.setdefault("placement", None)
    return out


# ---------------------------------------------------------------- 문구 레이어

def _layer_info(spec: "TextSpec", which: str, meta: dict,
                sub_coords: bool = False) -> dict:
    """meta.text_layers에 남길 레이어별 요약. 기존 meta.text 구조는 건드리지 않고,
    실제로 어떤 순서/좌표/크기로 그려졌는지만 additive하게 덧붙인다.

    sub_coords는 **sub를 별도로 렌더링하면서 sub_x/sub_y를 실제로 썼는지**다.
    headline과 sub를 한 번에 그리는 경우 sub_x/sub_y는 렌더링에 쓰이지 않으므로,
    여기서도 기록하면 "응답 meta"와 "실제 적용 좌표"가 어긋난다.
    _render_text_layers의 draw(sub_coords=...)와 같은 규칙을 쓴다.
    """
    if which == "headline":
        return {"z_order": spec.headline_z_order,
                "x": spec.x, "y": spec.y,
                "applied_size": meta.get("applied_headline_ratio")}
    return {"z_order": spec.sub_z_order,
            "x": spec.sub_x if sub_coords and spec.sub_x is not None else spec.x,
            "y": spec.sub_y if sub_coords and spec.sub_y is not None else spec.y,
            "applied_size": meta.get("applied_sub_ratio")}


def _validate_font_id(spec: "TextSpec | None"):
    """text.font_id를 실제 렌더링 전에 검사한다.

    **diffusion을 돌기 전에** 부르는 것이 중요하다. 렌더링 시점에 터지면
    수백 초짜리 생성을 다 돌고 나서 400이 나간다.

    폴백은 하지 않는다. 사용자가 고른 폰트가 아닌 결과를 내보내면 프론트가
    무엇이 잘못됐는지 알 수 없기 때문이다(placement/aspect_ratio와 같은 기준).
    """
    if spec is None or not spec.font_id:
        return
    try:
        pipeline.resolve_font_id_path(spec.font_id)
    except pipeline.FontRejection as e:
        raise HTTPException(400, detail=e.payload)


def _validate_tone(spec: "TextSpec | None") -> None:
    """text.tone을 실제 렌더링 전에 검사한다.

    **diffusion을 돌기 전에** 부르는 것이 중요하다. 렌더링 시점에 터지면
    수백 초짜리 생성을 다 돌고 나서 400이 나간다. _validate_font_id와
    같은 이유·같은 자리에서 부른다.

    폴백은 하지 않는다. 사용자가 고른 톤이 아닌 결과를 내보내면 프론트가
    무엇이 잘못됐는지 알 수 없기 때문이다.
    """
    if spec is None or not spec.tone:
        return
    if spec.tone not in pipeline.config.TONE_PRESETS:
        raise HTTPException(400, detail={
            "code": "unknown_tone",
            "message": f"지원하지 않는 tone입니다: {spec.tone!r}",
            "supported": sorted(pipeline.config.TONE_PRESETS),
        })


def _tone_kwargs(spec: "TextSpec") -> dict:
    """tone 프리셋을 render_text 인자로 푼다.

    tone을 안 주면 프리셋이 비어 있어 headline_font_role="headline",
    stroke_width=None, fill_color=None이 되는데, 이는 render_text의 현재
    기본값과 같다. 즉 tone 미지정 요청은 기존 렌더 동작이 그대로 유지된다.

    개별 필드가 프리셋을 이긴다 — 프론트 미리보기가 계산한 headline_size가
    있는데 서버가 프리셋 값으로 덮으면 미리보기와 결과가 어긋난다.
    font_id도 마찬가지로 headline_font_role보다 우선하며, 그 우선순위는
    render_text 안에 이미 있다.
    """
    preset = pipeline.config.TONE_PRESETS.get(spec.tone or "", {})
    return {
        "headline_size": (spec.headline_size if spec.headline_size is not None
                          else preset.get("headline_size")),
        "sub_size": (spec.sub_size if spec.sub_size is not None
                     else preset.get("sub_size")),
        "headline_font_role": preset.get("headline_font_role", "headline"),
        "stroke_width": preset.get("stroke_width"),
        "fill_color": preset.get("fill_color"),
    }


def _ignored_fields(spec: "TextSpec") -> list:
    """요청에는 들어왔지만 실제 렌더링에 쓰이지 않은 필드 이름.

    sub_x/sub_y는 sub를 headline과 **따로** 그릴 때만 쓰인다. 즉 headline과 sub가
    둘 다 있고 z_order가 서로 다를 때뿐이다. 그 외에는 sub도 headline과 같은
    좌표(x, y)로 그려지므로 sub_x/sub_y는 무시된다.

    무시된 사실을 응답에서 바로 알 수 있게 하려는 목적이다. 400으로 막지 않는
    이유는 /generate/refine과 /compose/text가 **같은 TextSpec 객체**를 그대로 받아야
    하기 때문이다(한쪽만 거부하면 프론트가 호출 전에 필드를 지우는 전처리를 넣어야
    하고, 빠뜨리면 편집이 통째로 실패한다).

    두 엔드포인트가 같은 기준을 쓰도록 spec만 보고 판단한다.
    """
    separate = (bool(spec.headline) and bool(spec.sub)
                and spec.headline_z_order != spec.sub_z_order)
    if separate:
        return []
    return [n for n in ("sub_x", "sub_y") if getattr(spec, n) is not None]


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
            font_id=spec.font_id,
            **_tone_kwargs(spec),
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
    # 이 경로에서만 sub를 따로 그리며 sub_x/sub_y를 실제로 사용한다.
    layers = {"headline": _layer_info(spec, "headline", head_meta),
              "sub": _layer_info(spec, "sub", sub_meta, sub_coords=True)}
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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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
    # 새 필드를 안 보내면 즉시 반환하므로 기존 요청의 검증 순서·메시지는 그대로다.
    # 먼저 두어야 placement/aspect_ratio 관련 400이 "image가 필요합니다"에
    # 가려지지 않는다.
    _validate_canvas_request(req.aspect_ratio, req.placement,
                             req.background_mode, req.mode)
    if req.mode == "inpaint" and not req.image:
        raise HTTPException(400, "inpaint 모드에는 image가 필요합니다.")
    if req.background_mode != "ai" and not req.image:
        raise HTTPException(400, "solid/gradient 배경 모드는 image가 필요합니다.")
    _validate_background_colors(req.background_mode, req.bg_colors, "bg_colors")

    image = b64_to_image(req.image) if req.image else None
    override = (req.placement.model_dump(exclude_none=True)
                if req.placement else None) or None
    try:
        result = pipeline.generate_drafts(
            image=image,
            prompt=req.prompt,
            category=req.category,
            num_images=req.num_images,
            background_mode=req.background_mode,
            bg_colors=req.bg_colors,
            gradient_direction=req.gradient_direction,
            aspect_ratio=req.aspect_ratio,
            placement_override=override,
        )
    except pipeline.LayoutRejection as e:
        # 캔버스 이탈·확대 상한 초과 등. 보정하지 않고 거부하며, 복구용
        # 기본 배치를 suggested로 함께 내려준다.
        raise HTTPException(400, detail=e.payload)

    backgrounds = result.get("backgrounds") or [None] * len(result["images"])
    drafts = [
        DraftItem(id=f"d{i+1}", image=image_to_b64(img), seed=seed,
                 background=BackgroundSpec(**bg) if bg else None)
        for i, (img, seed, bg) in enumerate(
            zip(result["images"], result["seeds"], backgrounds))
    ]
    return DraftResponse(drafts=drafts,
                         meta=_canvas_meta(result["meta"], req.aspect_ratio))


@app.post("/generate/refine", response_model=RefineResponse)
def generate_refine(req: RefineRequest):
    draft = b64_to_image(req.draft_image)
    original = b64_to_image(req.original_image) if req.original_image else None

    bg_mode = req.background.mode if req.background else "ai"
    _validate_canvas_request(req.aspect_ratio, req.placement, bg_mode)
    # 폰트는 diffusion 전에 확인한다. 렌더링 직전에 터지면 생성을 다 돌고 나서
    # 400이 나가 GPU 시간을 통째로 버린다.
    _validate_font_id(req.text)
    _validate_tone(req.text)
    # draft 크기에서 **항상** 비율을 추론하고, 명시값이 있으면 교차 검증한다.
    # aspect_ratio를 보낼 때만 추론하면, 3:1 시안을 고른 프론트가 필드를
    # 빠뜨렸을 때 조용히 1:1로 떨어진다. 그 실패를 막는 것이 목적이다.
    # 정사각 draft는 크기와 무관하게 "1:1"로 추론되므로 기존 클라이언트는
    # 아무것도 보내지 않아도 동작이 같다.
    try:
        ratio, warnings = pipeline.resolve_aspect_ratio(
            req.aspect_ratio, draft.size)
    except pipeline.LayoutRejection as e:
        raise HTTPException(400, detail=e.payload)

    if bg_mode == "ai":
        # 요청 필드가 아니라 **추론된 비율**로도 확인한다. aspect_ratio를 보내지
        # 않고 3:4 draft를 넣는 경로가 위 검사만으로는 통과하기 때문이다.
        _validate_ai_ratio(ratio)
        if ratio != "1:1" and original is None:
            # 원본이 없으면 img2img 폴백으로 빠져 마스크·배치·제품 재합성이
            # 통째로 빠진다. 검증한 3:1 경로와 다른 동작이므로 거부한다.
            # (1:1은 기존 폴백을 그대로 유지한다)
            raise HTTPException(400, detail={
                "error": "original_image_required_for_nonsquare_ai",
                "message": "비정사각 AI 배경 refine에는 original_image가 "
                           "필요합니다. 제품 보존을 위한 마스크와 재합성이 "
                           "필요하기 때문입니다.",
                "aspect_ratio": ratio})

    background = None
    if req.background:
        _validate_background_colors(req.background.mode, req.background.colors,
                                    "background.colors")
        if req.background.mode in ("solid", "gradient") and original is None:
            raise HTTPException(400, "solid/gradient 배경 refine에는 original_image가 필요합니다.")
        background = {"mode": req.background.mode,
                     "colors": req.background.colors,
                     "direction": req.background.direction}

    override = (req.placement.model_dump(exclude_none=True)
                if req.placement else None) or None
    try:
        result = pipeline.refine(draft, original=original,
                                 prompt=req.prompt, category=req.category,
                                 background=background,
                                 aspect_ratio=ratio,
                                 placement_override=override)
    except pipeline.LayoutRejection as e:
        raise HTTPException(400, detail=e.payload)
    img = result["image"]

    meta = _canvas_meta(result["meta"], ratio)
    if warnings:
        meta = {**meta, "warnings": warnings}
    if req.text and (req.text.headline or req.text.sub):
        img, text_meta, layers = _render_text_layers(req.text, result)
        meta = {**meta, "text": text_meta, "text_layers": layers}
        ignored = _ignored_fields(req.text)
        if ignored:
            meta["ignored_fields"] = ignored

    # AI 생성물 표시는 모든 문구 합성이 끝난 뒤 최상단에 한 번만 적용한다.
    if req.ai_notice:
        img = pipeline.add_ai_notice(img)

    return RefineResponse(image=image_to_b64(img), meta=meta)


@app.post("/compose/text", response_model=TextComposeResponse)
def compose_text(req: TextComposeRequest):
    """이미 만들어진 이미지에 문구만 다시 합성한다. diffusion을 돌지 않는다.

    /generate/refine과 렌더링 순서가 같다: 문구를 그린 뒤 AI 생성 표시를 최상단에
    올린다. 그래서 표시가 문구에 가려지지 않는다.
    """
    spec = req.text
    if not (spec.headline or spec.sub):
        raise HTTPException(
            400, "합성할 문구가 없습니다. headline 또는 sub 중 하나는 필요합니다.")
    if "behind" in (spec.headline_z_order, spec.sub_z_order):
        # behind는 제품 마스크와 합성 전 배경이 필요한데 이 API에는 그 재료가 없다.
        # 조용히 front로 바꾸지 않고 명시적으로 거부한다.
        raise HTTPException(400, detail={
            "error": "text_behind_not_supported",
            "message": '/compose/text는 제품 뒤 문구(z_order="behind")를 아직 '
                       "지원하지 않습니다. 제품 마스크와 합성 전 배경이 필요한데 "
                       "이 경로에는 없습니다. /generate/refine을 사용하세요.",
            "supported": ["front"]})
    _validate_font_id(spec)
    _validate_tone(spec)

    base = b64_to_image(req.base_image)
    started = time.time()

    img, text_meta = pipeline.render_text(
        base, spec.headline, spec.sub,
        x=spec.x, y=spec.y,
        position=spec.position,
        align=spec.align,
        style=spec.style,
        font_id=spec.font_id,
        **_tone_kwargs(spec),
        return_meta=True)

    layers = {}
    if spec.headline:
        layers["headline"] = _layer_info(spec, "headline", text_meta)
    if spec.sub:
        layers["sub"] = _layer_info(spec, "sub", text_meta)

    # 표시는 문구 합성이 끝난 뒤 최상단에 한 번만 (refine과 같은 순서)
    if req.ai_notice:
        img = pipeline.add_ai_notice(img)

    W, H = base.size
    meta = {
        "elapsed": round(time.time() - started, 2),
        "diffusion": False,
        # 짧은 변. refine의 resolution과 같은 의미다.
        "resolution": min(W, H),
        "canvas": {"width": W, "height": H},
        "ai_notice": req.ai_notice,
        "text": text_meta,
        "text_layers": layers,
    }
    # refine과 같은 기준. 무시된 필드가 없으면 키 자체를 넣지 않는다.
    ignored = _ignored_fields(spec)
    if ignored:
        meta["ignored_fields"] = ignored
    return TextComposeResponse(image=image_to_b64(img), meta=meta)
