"""광고 문구 합성.

diffusion 모델은 정상적인 글자를 생성하지 못하므로 PIL로 합성한다.
"""

from PIL import Image, ImageDraw, ImageFont

from . import config

# 외곽선 불투명도. 렌더러 구현 세부값이라 config가 아니라 여기에 둔다.
# spacing OFF의 stroke_fill과 spacing ON의 stroke 레이어가 **같은 값**을 써야
# 두 경로의 외곽선 농도가 같아진다.
STROKE_ALPHA = 190


# --------------------------------------------------------------- letter_spacing
# letter_spacing 계약
#     None  → legacy whole-string 경로 (draw.text 한 번)
#     0     → legacy whole-string 경로
#     > 0   → 커닝을 유지한 per-glyph 경로
#
# 0과 아주 작은 양수 사이에서 렌더 경로가 갈리는 불연속은 **의도된 기능 경계**다
# (0 = 자간 OFF, 양수 = 자간 ON). 판정은 _use_spacing() 한 곳에서만 한다.

def _use_spacing(letter_spacing) -> bool:
    """요청값 기준으로 판정한다.

    font_px를 곱한 결과가 아무리 작아도(예: 0.001 × 12px) 요청이 양수면 자간
    경로를 탄다. 요청과 렌더 경로가 1:1로 대응해야 계약을 설명할 수 있다.
    """
    return letter_spacing is not None and letter_spacing > 0


def _spacing_px(font_px, letter_spacing) -> float:
    """자간 단위는 **font size 대비 비율**이다. 반올림하지 않는다.

    font_px=100, letter_spacing=0.02 → 글자 사이 2px. 정수로 반올림하면 작은
    폰트에서 비율이 계단식으로 무너지고, per-glyph 오프셋이 어차피 float이라
    정수화할 이유가 없다. headline과 sub는 **각자의 font_px**로 계산한다 —
    같은 비율이 두 블록에서 같은 시각 밀도를 만드는 것이 ratio를 쓰는 이유다.
    """
    if not _use_spacing(letter_spacing):
        return 0.0
    return float(font_px) * float(letter_spacing)


def _advances(draw, text: str, font) -> list[float]:
    """글자별 **문맥 advance**. 뒤 글자와의 커닝이 포함된다.

        adv[j]   = textlength(text[j:j+2]) - textlength(text[j+1])   (j < n-1)
        adv[n-1] = textlength(text[n-1])

    글자를 하나씩 재서 더하면(=단순 advance 합) 커닝이 통째로 사라진다.
    prefix 폭(textlength(text[:i]))을 쓰는 방식도 (i-1, i) 쌍의 커닝을 담지
    못해 글자마다 한 쌍씩 밀린다. 문맥 advance는 쌍 커닝을 그대로 담는다.

    **spacing OFF 경로에서는 호출되지 않는다.**
    """
    n = len(text)
    if n == 0:
        return []
    if n == 1:
        return [draw.textlength(text, font=font)]
    out = [draw.textlength(text[j:j + 2], font=font)
           - draw.textlength(text[j + 1], font=font) for j in range(n - 1)]
    out.append(draw.textlength(text[-1], font=font))
    return out


def _text_width(draw, text: str, font, sp: float = 0.0) -> float:
    """폭 계산의 **단일 진입점**. 줄바꿈·정렬·bar 폭·fit 판정이 모두 이걸 쓴다.

    sp <= 0이면 draw.textlength()를 그대로 돌려준다. 그래서 자간을 쓰지 않는
    기존 경로는 **정의상** 이전과 같은 값이 나온다.
    글자 사이는 n-1개이므로 마지막 글자 뒤에는 자간이 붙지 않는다.
    """
    if not text:
        return 0.0
    if sp <= 0:
        return draw.textlength(text, font=font)
    return draw.textlength(text, font=font) + sp * (len(text) - 1)


def _glyph_offsets(draw, text: str, font, sp: float = 0.0) -> list[float]:
    """글자 i의 x 오프셋. 문맥 advance 누적 + 누적 자간.

    _text_width와 같은 advance를 공유하므로 예측 폭과 실제 배치가 어긋나지 않는다.
    """
    offs, cur = [], 0.0
    for j, adv in enumerate(_advances(draw, text, font)):
        offs.append(cur + sp * j)
        cur += adv
    return offs


def _split_long_word(draw, word: str, font, max_width: float,
                     sp: float = 0.0) -> list[str]:
    """공백 없이 max_width보다 긴 한 덩어리를 글자 단위로만 쪼갠다(최후 수단).

    마지막 조각이 1글자만 남으면, 폭이 허용하는 한 이전 조각에서 한 글자를
    당겨와 최소한 2글자로 만든다("마지막 줄에 한 글자만 남는 형태" 방지).
    """
    lines, cur = [], ""
    for ch in word:
        if _text_width(draw, cur + ch, font, sp) <= max_width:
            cur += ch
        else:
            if cur:
                lines.append(cur)
            cur = ch
    if cur:
        lines.append(cur)

    if len(lines) >= 2 and len(lines[-1]) == 1 and len(lines[-2]) > 1:
        candidate = lines[-2][-1] + lines[-1]
        if _text_width(draw, candidate, font, sp) <= max_width:
            lines[-2] = lines[-2][:-1]
            lines[-1] = candidate
    return lines


def _wrap(draw, text: str, font, max_width: float,
          sp: float = 0.0) -> list[str]:
    """공백 기준 어절 단위로 우선 줄바꿈하고, 한 어절이 max_width보다 길 때만
    글자 단위로 쪼갠다. 순수 글자 단위 분리는 "매일을 위한 클린 케 / 어"처럼
    단어 중간을 끊어 가독성을 해치므로 최후의 수단으로만 쓴다.

    문구에 "\n"이 들어 있으면 사용자가 직접 지정한 줄바꿈으로 보고 그 지점에서
    먼저 나눈 뒤, 각 줄을 폭 기준으로 다시 줄바꿈한다. PIL의 textlength()는
    멀티라인 문자열을 측정하지 못해(ValueError) 이 분리를 먼저 하지 않으면 죽는다.
    """
    if not text:
        return []

    if "\n" in text:
        lines = []
        for segment in text.split("\n"):
            lines.extend(_wrap(draw, segment, font, max_width, sp))
        return lines

    words = text.split(" ")
    lines: list[str] = []
    cur = ""
    for word in words:
        if not word:
            continue
        candidate = f"{cur} {word}" if cur else word
        if _text_width(draw, candidate, font, sp) <= max_width:
            cur = candidate
            continue

        if cur:
            lines.append(cur)
            cur = ""

        if _text_width(draw, word, font, sp) <= max_width:
            cur = word
        else:
            # 어절 하나가 통째로 한 줄보다 긴 경우(영문 긴 단어 등)에만 글자 단위 분리
            split = _split_long_word(draw, word, font, max_width, sp)
            if split:
                lines.extend(split[:-1])
                cur = split[-1]

    if cur:
        lines.append(cur)
    return lines


def render_text(img: Image.Image,
                headline: str,
                sub: str = "",
                x: float | None = None,
                y: float | None = None,
                position: str = "top",
                align: str = "left",
                style: str = "bar",
                headline_size: float | None = None,
                sub_size: float | None = None,
                auto_fit: bool = True,
                min_font_scale: float = 0.4,
                max_height_ratio: float | None = None,
                headline_font_role: str = "headline",
                font_id: str | None = None,
                stroke_width: int | None = None,
                fill_color: tuple | None = None,
                letter_spacing: float | None = None,
                return_meta: bool = False) -> Image.Image:
    """이미지에 문구를 합성한다.

    좌표 모드(권장): x, y를 0~1 비율로 넘기면 position은 무시되고
    텍스트 블록이 해당 좌표를 기준으로 배치된다.
        x: 텍스트 기준점의 가로 위치 (align이 left/center/right 중 어느 지점을 의미하는지 결정)
        y: 텍스트 블록 맨 윗줄의 세로 위치
    프리셋 모드(하위 호환): x, y를 생략하면 기존처럼 position으로 동작한다.

    Args:
        x, y: 0~1 비율 좌표. 둘 다 주어져야 좌표 모드로 동작한다.
        position: top | center | bottom (좌표 모드가 아닐 때만 사용)
        align: left | center | right — 좌표 모드에서는 x가 텍스트의 어느 지점인지도 결정.
            가로 사용 가능 폭(max_w)은 이 x/align 기준으로 실제 남는 여백만큼만 계산된다
            (예: align="left"이고 x=0.6이면 오른쪽으로 남은 폭만큼만 줄바꿈 허용).
        style: plain(외곽선) | bar(반투명 배경)
        headline_size, sub_size: 짧은 변 대비 폰트 크기 비율(0~1). 생략 시 config 기본값 사용.
            실사용 권장 범위는 스타일에 따라 다르다 — config.TONE_PRESETS 참고
            (예: minimal_product는 0.09~0.13, bold_promo는 0.18~0.28 권장).
            프론트 미리보기와 실제 합성 크기가 어긋나지 않도록, 지정할 경우 프론트가 계산한
            값을 그대로 전달해야 한다.
        auto_fit: True면 요청한 headline_size/sub_size를 그대로 우선 적용하되, 텍스트 블록이
            지정된 영역(아래 max_height_ratio 참고)을 벗어날 때만 이진 탐색으로 최소한만
            축소한다. 영역 안에 이미 들어오면 요청 크기를 그대로 쓴다(축소하지 않음).
        min_font_scale: auto_fit 축소의 하한선(요청 크기 대비 비율). 이보다 더 줄이지는 않고,
            그 이상 넘치면 잘리는 대신 최소 크기로 렌더링한다(문구 자체를 자르지는 않음).
        max_height_ratio: 텍스트 블록에 허용할 최대 높이(짧은 변 대비 비율). 예를 들어
            제품 bbox 위쪽 여백에만 문구를 배치하고 싶다면, 호출하는 쪽에서 그 여백의
            높이를 비율로 계산해 넘기면 auto_fit이 "이미지 하단까지"가 아니라 정확히
            그 영역 안으로만 맞춘다. 생략하면 기존처럼 y 지점부터 이미지 하단 여백까지를
            영역으로 본다(제품 등 다른 요소의 위치는 모른다는 뜻이므로, 실제 제품 사진에
            문구를 배치할 때는 호출 측에서 이 값을 반드시 계산해 넘기는 것을 권장한다).
        font_id: 사용자가 고른 폰트(config.FONT_IDS의 키). 지정하면 headline과 sub
            **모두** 이 폰트 하나로 그려지고 headline_font_role은 무시된다.
            None이면 기존 동작 그대로다(headline은 headline_font_role, sub는 "body").
            해석에 실패하면 config.FontRejection이 올라온다 — 다른 폰트로 바꾸지 않는다.
        headline_font_role: config.FONTS의 역할 이름. 기본은 "headline"(Gmarket Sans Bold,
            없으면 폴백). 절제된 톤이 필요하면 "body_medium"(Pretendard Medium) 등으로 바꿀 수 있다.
        stroke_width: style="plain"일 때 외곽선 두께. None이면 config.STROKE_WIDTH(기존 기본값)를
            쓴다. 두꺼운 스트로크가 과하게 느껴지는 스타일(예: minimal_product)에서는 0 또는
            작은 값을 직접 넘기면 된다.
        fill_color: 텍스트 채움 색(RGBA 튜플). None이면 기존처럼 흰색(255,255,255,255).
            minimal_product처럼 흰색+굵은 외곽선 대신 배경과 대비되는 단색 텍스트가
            필요할 때 어두운 색 등을 직접 넘기면 된다.
        letter_spacing: 자간. **font size 대비 비율**이다(0.02 = font_px의 2%).
            None 또는 0이면 기존 whole-string 경로를 그대로 타므로 결과가
            픽셀 단위로 같다. 양수면 커닝을 유지한 채 글자 사이만 벌리는
            per-glyph 경로로 그린다. 줄바꿈·정렬·bar 폭도 같은 자간을 반영한다.
            음수(자간 축소)는 아직 지원하지 않는다 — 0과 같이 취급된다.
        x, y: 0~1 정규화 좌표. 둘 다 주어져야 좌표 모드로 동작한다.
            x는 align 기준점(left=좌변, center=중심, right=우변),
            **y는 텍스트 블록의 중심**이다. 프론트 미리보기가 텍스트 박스 중심을
            기준으로 쓰기로 합의돼 그 기준에 맞췄다(이전에는 블록 상단이었다).
            auto_fit으로 크기가 줄어도 중심은 그대로 유지된다.
            x나 y 중 하나만 주면 좌표 모드가 아니라 position 프리셋으로 동작한다.
        return_meta: True면 (이미지, meta dict) 튜플을 반환한다. meta에는 실제 적용된
            폰트 크기(px/비율), 요청 크기 대비 축소 여부 등 검증용 정보가 담긴다.
            기본값 False는 기존과 동일하게 이미지만 반환한다(하위 호환).

    폰트 크기는 이미지 크기에 비례해 자동 계산되므로
    768/1024 어느 쪽이든 동일한 비율로 보인다.
    """
    img = img.convert("RGBA")
    W, H = img.size
    unit = min(W, H)

    margin = int(unit * config.TEXT_MARGIN_RATIO)
    gap = int(unit * config.LINE_GAP_RATIO)
    hsize0 = int(unit * (headline_size if headline_size is not None else config.HEADLINE_RATIO))
    ssize0 = int(unit * (sub_size if sub_size is not None else config.SUB_RATIO))
    stroke = config.STROKE_WIDTH if stroke_width is None else stroke_width
    fill = fill_color if fill_color is not None else (255, 255, 255, 255)

    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    coord_mode = x is not None and y is not None

    # 가로 사용 가능 폭: 좌표 모드에서는 x/align 기준으로 실제 남는 여백만 반영해야
    # 텍스트가 오른쪽(또는 왼쪽) 이미지 밖으로 잘리지 않는다. 프리셋 모드는 기존과 동일.
    if coord_mode:
        xc = x * W
        if align == "left":
            max_w = max(int(W - margin - xc), 10)
        elif align == "right":
            max_w = max(int(xc - margin), 10)
        else:  # center
            max_w = max(int(2 * min(xc - margin, W - margin - xc)), 10)
    else:
        max_w = W - margin * 2

    # 폰트 경로는 auto_fit 루프에서 크기만 바뀌므로 여기서 한 번만 해석한다.
    # font_id가 오면 headline/sub가 같은 파일을 쓴다(프론트에서 폰트를 하나만 고른다).
    if font_id:
        head_path = sub_path = config.resolve_font_id_path(font_id)
    else:
        head_path = config.resolve_font_path(headline_font_role)
        sub_path = config.resolve_font_path("body")

    def _measure(hsize: int, ssize: int):
        """주어진 폰트 크기로 줄바꿈/블록 목록/전체 높이를 계산한다.

        블록 튜플에 자간(px)을 함께 담는다. headline과 sub는 폰트 크기가 다르고
        자간이 크기 비례이므로 값이 서로 다르다. auto_fit이 크기를 바꾸면 자간도
        같이 바뀌어야 해서 여기서 매번 다시 계산한다.
        """
        f_head = ImageFont.truetype(head_path, max(hsize, 4))
        f_sub = ImageFont.truetype(sub_path, max(ssize, 4)) if sub else None
        sp_head = _spacing_px(hsize, letter_spacing)
        sp_sub = _spacing_px(ssize, letter_spacing)
        head_lines = _wrap(draw, headline, f_head, max_w, sp_head)
        sub_lines = _wrap(draw, sub, f_sub, max_w, sp_sub) if sub else []
        blocks = [(t, f_head, int(hsize * 1.35), sp_head) for t in head_lines]
        blocks += [(t, f_sub, int(ssize * 1.35), sp_sub) for t in sub_lines]
        total_h = sum(h for _, _, h, _ in blocks) + (gap if sub_lines else 0)
        return blocks, head_lines, sub_lines, total_h

    # 1차: 요청 크기 그대로 측정. coord_mode가 아닌 프리셋(center/bottom)의 y0 계산에도 필요하다.
    blocks, head_lines, sub_lines, total_h = _measure(hsize0, ssize0)
    if not blocks:
        return img.convert("RGB")

    if coord_mode:
        # y는 텍스트 블록의 **중심**이다(프론트 미리보기와 같은 기준).
        # 이전에는 블록 상단이었다. 프리셋(position) 경로는 바뀌지 않는다.
        y0 = int(H * y - total_h / 2)
    elif position == "top":
        y0 = margin
    elif position == "center":
        y0 = (H - total_h) // 2
    else:
        y0 = H - total_h - margin

    hsize, ssize = hsize0, ssize0

    if auto_fit:
        # "지정된 영역"의 높이: max_height_ratio가 주어지면 그 값을 그대로 쓰고(호출 측이
        # 제품 bbox 등을 감안해 정확히 계산해 넘긴 경우), 없으면 기존처럼 y 지점부터
        # 이미지 하단 여백까지로 본다(다른 요소 위치를 모르는 경우의 기본 동작).
        if max_height_ratio is not None:
            max_h = max(int(unit * max_height_ratio), int(unit * 0.03))
        elif coord_mode:
            # 중심 기준이라 블록이 위아래로 대칭하게 뻗는다. 가까운 쪽 여백의
            # 2배가 상한이다(align="center"의 max_w 계산과 같은 방식).
            cy = H * y
            max_h = max(int(2 * min(cy - margin, H - margin - cy)),
                        int(unit * 0.05))
        else:
            max_h = max(H - y0 - margin, int(unit * 0.05))
        if total_h > max_h:
            lo, hi = min_font_scale, 1.0
            best_scale = min_font_scale
            for _ in range(10):
                mid = (lo + hi) / 2
                h_try = max(int(hsize0 * mid), 8)
                s_try = max(int(ssize0 * mid), 6) if sub else ssize0
                _, _, _, th = _measure(h_try, s_try)
                if th <= max_h:
                    best_scale = mid
                    lo = mid
                else:
                    hi = mid
            hsize = max(int(hsize0 * best_scale), 8)
            ssize = max(int(ssize0 * best_scale), 6) if sub else ssize0
            blocks, head_lines, sub_lines, total_h = _measure(hsize, ssize)
            # 총 높이가 바뀌면 기준점을 다시 잡아야 시각적으로 맞는다.
            # coord_mode는 y가 중심이라 total_h에 의존하고, center/bottom 프리셋도
            # 마찬가지다. top 프리셋만 total_h와 무관하다.
            if coord_mode:
                y0 = int(H * y - total_h / 2)
            elif position == "center":
                y0 = (H - total_h) // 2
            elif position != "top":
                y0 = H - total_h - margin

    def x_of(text, font, sp: float = 0.0):
        tw = _text_width(draw, text, font, sp)
        if coord_mode:
            xc = x * W
            if align == "left":
                return int(xc)
            if align == "center":
                return int(xc - tw / 2)
            return int(xc - tw)
        if align == "left":
            return margin
        if align == "center":
            return (W - tw) // 2
        return W - tw - margin

    if style == "bar":
        # bar 폭도 같은 폭 함수를 쓴다 — 자간이 켜지면 바도 같이 넓어져야 한다.
        widest = max(blocks, key=lambda b: _text_width(draw, b[0], b[1], b[3]))
        bw = _text_width(draw, widest[0], widest[1], widest[3])
        bx = x_of(widest[0], widest[1], widest[3])
        pad = int(unit * 0.027)
        draw.rounded_rectangle(
            [bx - pad, y0 - pad, bx + bw + pad, y0 + total_h + pad],
            radius=config.BAR_RADIUS,
            fill=(0, 0, 0, config.BAR_ALPHA))

    spacing_on = _use_spacing(letter_spacing)
    # 자간 ON + 외곽선일 때만 stroke를 별도 레이어에 모은다.
    # 글자마다 반투명 stroke를 그리면 겹치는 자리가 짙어져 이음매가 보인다.
    # 불투명으로 다 그린 뒤 레이어 알파를 한 번만 낮추면 legacy와 같은 농도가 된다.
    stroke_layer = None
    if spacing_on and style == "plain" and stroke:
        stroke_layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
        stroke_draw = ImageDraw.Draw(stroke_layer)

    cy = y0
    for i, (text, font, line_h, sp) in enumerate(blocks):
        xc = x_of(text, font, sp)
        if not spacing_on:
            # ---- 기존 경로. primitive와 인자를 그대로 둔다 ----
            if style == "plain":
                draw.text((xc, cy), text, font=font, fill=fill,
                          stroke_width=stroke,
                          stroke_fill=(0, 0, 0, STROKE_ALPHA))
            else:
                draw.text((xc, cy), text, font=font, fill=fill)
        else:
            # ---- 자간 경로. 글자 위치는 _text_width와 같은 advance를 쓴다 ----
            for ch, off in zip(text, _glyph_offsets(draw, text, font, sp)):
                if ch == " ":
                    continue          # 공백은 그릴 것이 없다(자간은 이미 반영됨)
                pos = (xc + off, cy)
                if stroke_layer is not None:
                    stroke_draw.text(pos, ch, font=font, fill=(0, 0, 0, 0),
                                     stroke_width=stroke,
                                     stroke_fill=(0, 0, 0, 255))
                draw.text(pos, ch, font=font, fill=fill)
        cy += line_h
        if sub_lines and i == len(head_lines) - 1:
            cy += gap

    if stroke_layer is not None:
        alpha = stroke_layer.getchannel("A").point(
            lambda v: v * STROKE_ALPHA // 255)
        stroke_layer.putalpha(alpha)
        overlay = Image.alpha_composite(stroke_layer, overlay)

    result = Image.alpha_composite(img, overlay).convert("RGB")
    if return_meta:
        meta = {
            "coord_mode": coord_mode,
            # 좌표 모드에서 y가 무엇을 가리키는지 응답에 명시한다.
            "y_anchor": "center" if coord_mode else position,
            "block_top_px": y0,
            "block_height_px": total_h,
            "style": style,
            # font_id를 쓰면 headline_font_role은 무시된다. 실제 적용값을 알 수 있게 둘 다 남긴다.
            "font_id": font_id,
            "headline_font_role": None if font_id else headline_font_role,
            "stroke_width": stroke,
            "fill_color": fill,
            # 요청값을 그대로 echo한다. None/0은 legacy 경로를 탔다는 뜻이다.
            "letter_spacing": letter_spacing,
            "max_w_px": max_w,
            "requested_headline_size": headline_size,
            "requested_sub_size": sub_size,
            "applied_headline_px": hsize,
            "applied_sub_px": ssize,
            "applied_headline_ratio": round(hsize / unit, 4),
            "applied_sub_ratio": round(ssize / unit, 4) if sub else None,
            "auto_fit": auto_fit,
            "shrunk": (hsize != hsize0) or (ssize != ssize0 if sub else False),
        }
        return result, meta
    return result


def add_ai_notice(img: Image.Image, text: str = "AI 생성 이미지") -> Image.Image:
    """AI 기본법 제31조에 따른 생성물 표시.

    시행령 기준 확인 후 크기/위치 조정 필요.
    """
    img = img.convert("RGBA")
    W, H = img.size
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    size = max(int(min(W, H) * 0.022), 12)
    font = ImageFont.truetype(config.resolve_font_path("body"), size)
    tw = draw.textlength(text, font=font)
    pad = int(size * 0.5)
    x, y = W - tw - pad * 2 - 12, H - size - pad * 2 - 12

    draw.rounded_rectangle([x, y, x + tw + pad * 2, y + size + pad * 2],
                           radius=6, fill=(0, 0, 0, 110))
    draw.text((x + pad, y + pad), text, font=font, fill=(255, 255, 255, 220))
    return Image.alpha_composite(img, overlay).convert("RGB")
