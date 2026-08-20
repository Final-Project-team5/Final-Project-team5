"""Step 5 fixture — 사람이 직접 쓴 RenderSpec 4종.

목적은 하나다.

    같은 제품인데 서로 다른 RenderSpec 을 주면
    **실제로 구조적으로 다른 포스터가 만들어지는가**

AI Design Planner 가 Spec 을 만드는 단계가 아니다. 사람이 쓴다.

**`design_language` 이름을 바꾸는 것이 아니라 실제 필드가 달라져야 한다.**
grid · zones · product · typography · palette · motif · copy_blocks ·
layers · background 가 함께 움직인다. 배경색만·spot 색만·제품 몇 px 만
바뀌는 것은 실패다.

서체 제약 — 번들 폰트로 정확히 표현되는 조합만 쓴다 (§13-3).

    sans/regular · sans/medium · serif/bold · display/bold · display/black

`serif/regular`(얇은 명조)가 없다. Premium minimal 이 원하는 얼굴이 바로
그것이라, B fixture 는 **품질 평가를 보류**한다 (§13-3 A/B 중 B안).
지원되지 않는 조합을 다른 굵기로 대체해서 "Premium minimal 결과"라고
평가하지 않는다.
"""

from __future__ import annotations

from dynamic import SCHEMA_VERSION, BriefCopy, CopyExtra, CopyItem, CreativeBrief

LAYERS = ["background", "motif_under", "type_under", "product", "motif_over", "type_over"]


def brief() -> CreativeBrief:
    """모든 fixture 가 **같은 카피와 같은 제품 신호**를 쓴다.

    이래야 차이가 전부 RenderSpec 에서 온다.
    """
    return CreativeBrief(
        business_type="retail",
        category="cosmetics",
        tone="minimal_product",
        output_ratio="1:1",
        copy=BriefCopy(
            eyebrow=CopyItem("스킨케어", source="derived", editable=False),
            headline=CopyItem("촉촉함을 오래", source="user"),
            benefit=CopyItem("12시간 수분 지속", source="generated"),
            token=CopyItem("30%", source="user"),
            cta=CopyItem("지금 구매하기", source="generated"),
            extra=(
                CopyExtra("side_note", "NEW ARRIVAL"),
                CopyExtra("brand", "MAISON"),
                CopyExtra("period", "9.1 – 9.14"),
            ),
        ),
        category_label="스킨케어",
        product_signals={
            "palette": {
                "dominant": "#D8CFC4",
                "accent": "#2E6F5E",
                "neutral": "#EFEAE3",
            }
        },
    )


def _role(rid, family, weight, step, ratio, space_after, color, **kw):
    out = {
        "id": rid,
        "family": family,
        "weight": weight,
        "size_step": step,
        "line_ratio": ratio,
        "space_after": space_after,
        "color_role": color,
    }
    out.update(kw)
    return out


# ──────────────────────────────────────────────────────────────────────────
# A — Clean editorial
#     넓은 type zone · 오른쪽 큰 제품 · rule 그래픽 · 절제된 정보량
# ──────────────────────────────────────────────────────────────────────────
def fixture_a() -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "canvas": {"ratio": "1:1"},
        "design_language": "editorial",
        "grid": {
            "columns": 6,
            "margin_density": "normal",
            "gutter_scale": "normal",
            "baseline_scale": "normal",
        },
        "zones": {
            "type": {"col_start": 0, "col_span": 4},
            "product": {"col_start": 2, "col_span": 4},
            "overlap_intent": "allowed",
        },
        "product": {
            "fit": "zone_width",
            "anchor": {"x": "right", "y": "bottom"},
            "bleed": ["bottom"],
            "rotation": "none",
            "grounding": "contact",
        },
        "background": {
            "mode": "flat",
            "material": "paper",
            "lighting": "flat",
            "texture": "paper_grain",
            "whitespace_strategy": "balanced",
        },
        "typography": {
            "measure_cols": 4,
            "break_strategy": "semantic",
            "scale_step": 1.0,
            "roles": [
                _role("eyebrow", "sans", "medium", -2, 1.4, "tight", "spot",
                      tracking_em=0.16, transform="uppercase", max_lines=1),
                _role("headline", "display", "bold", 3, 0.95, "normal", "ink",
                      tracking_em=-0.02, max_lines=3),
                _role("caption", "sans", "medium", -2, 1.4, "none", "spot",
                      tracking_em=0.24, transform="uppercase", max_lines=1),
                _role("token", "display", "black", 5, 1.0, "none", "spot",
                      align="right", max_lines=1),
            ],
        },
        "palette": {
            "strategy": "neutral_support",
            "source": "product",
            "background_tone": "light",
            "roles": ["bg", "ink", "spot", "emphasis"],
            "rhythm": {"spot_min_regions": 3, "spot_path": "diagonal"},
        },
        "motif": {
            "shape": "rule",
            "min_repeats": 3,
            "instances": [
                {
                    "role": "eyebrow_marker",
                    "grid_ref": {"col_start": 0, "col_span": 1, "row_anchor": "top"},
                    "orientation": "horizontal",
                    "weight": "thick",
                    "color_role": "spot",
                    "layer": "motif_under",
                },
                {
                    "role": "bottom_rule",
                    "grid_ref": {"col_start": 0, "col_span": 6,
                                 "row_anchor": "before:discount_token"},
                    "orientation": "horizontal",
                    "weight": "hair",
                    "color_role": "ink→spot",
                    "split_at": {"col": 2},
                    "layer": "motif_over",
                },
                {
                    "role": "spine_bar",
                    "grid_ref": {"col_start": "margin_left", "row_anchor": "center",
                                 "row_span": 30},
                    "orientation": "vertical",
                    "weight": "thick",
                    "color_role": "spot",
                    "layer": "motif_under",
                },
            ],
        },
        "copy_blocks": [
            {"id": "eyebrow", "role": "eyebrow", "content_ref": "brief.copy.eyebrow",
             "type_role": "eyebrow",
             "grid_ref": {"col_start": 0, "col_span": 4, "row_anchor": "top"},
             "priority": 3, "color_role": "spot", "layer": "type_under"},
            {"id": "headline", "role": "headline", "content_ref": "brief.copy.headline",
             "type_role": "headline",
             "grid_ref": {"col_start": 0, "col_span": 4, "row_anchor": "after:eyebrow"},
             "priority": 1, "color_role": "ink", "layer": "type_under"},
            {"id": "side_caption", "role": "caption",
             "content_ref": "brief.copy.extra.side_note", "type_role": "caption",
             "grid_ref": {"col_start": "margin_left", "row_anchor": "center"},
             "orientation": "rotate_ccw",
             "priority": 4, "color_role": "spot", "layer": "type_over"},
            {"id": "discount_token", "role": "token", "content_ref": "brief.copy.token",
             "type_role": "token",
             "grid_ref": {"col_start": 0, "col_span": 6, "row_anchor": "bottom",
                          "align": "right"},
             "priority": 1, "color_role": "spot", "layer": "type_over"},
        ],
        "layers": list(LAYERS),
        "safety": {
            "critical_blocks": ["headline", "discount_token"],
            "must_be_visible": ["bottom_rule"],
        },
    }


# ──────────────────────────────────────────────────────────────────────────
# B — Premium minimal
#     4단 · 넓은 여백 · 작은 중앙 제품 · 정보 3개 · 모티프 최소
#     ⚠ serif/regular(얇은 명조) 미번들 → **품질 평가 보류** (§13-3)
# ──────────────────────────────────────────────────────────────────────────
def fixture_b() -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "canvas": {"ratio": "1:1"},
        "design_language": "premium_minimal",
        "grid": {
            "columns": 4,
            "margin_density": "loose",
            "gutter_scale": "loose",
            "baseline_scale": "coarse",
        },
        "zones": {
            # 열은 겹치지만 제품은 위·문구는 아래로 **세로가 갈려 실제 2D 로는
            # 겹치지 않는다.**  v0.3 부터 overlap_intent 는 열 교집합이 아니라
            # 최종 요소의 2D 관계 선언이므로 none 이 맞다 (§4-7)
            "type": {"col_start": 0, "col_span": 4},
            "product": {"col_start": 1, "col_span": 2},
            "overlap_intent": "none",
        },
        "product": {
            "fit": "area_cap",
            "area_cap": 0.14,
            "anchor": {"x": "center", "y": "top"},
            "bleed": [],
            "rotation": "none",
            "grounding": "contact",
        },
        "background": {
            "mode": "flat",
            "material": "paper",
            "lighting": "soft_top",
            "texture": "none",
            "whitespace_strategy": "generous",
        },
        "typography": {
            "measure_cols": 4,
            "break_strategy": "semantic",
            "scale_step": 0.9,
            "roles": [
                # 의도는 얇은 명조(serif/regular)였다. 미번들이라 serif/bold 로 적되
                # 이 fixture 는 품질 평가를 보류한다 — 대체가 아니라 **명시적 표기**다
                _role("headline", "serif", "bold", 1, 1.45, "tight", "ink",
                      tracking_em=0.02, align="center", max_lines=2),
                _role("benefit", "sans", "regular", -1, 1.6, "none", "ink",
                      tracking_em=0.0, align="center", max_lines=2),
                _role("brand", "sans", "regular", -1, 1.6, "none", "ink",
                      tracking_em=0.3, transform="uppercase", align="center", max_lines=1),
            ],
        },
        "palette": {
            "strategy": "monochromatic",
            "source": "product",
            "background_tone": "light",
            "roles": ["bg", "ink"],
            "rhythm": {"spot_min_regions": 1, "spot_path": "none"},
        },
        "motif": {
            "shape": "frame",
            "min_repeats": 1,
            "instances": [
                {
                    "role": "hairline_frame",
                    "grid_ref": {"col_start": 0, "col_span": 4, "row_anchor": "top",
                                 "row_span": 26},
                    "orientation": "horizontal",
                    "weight": "hair",
                    "color_role": "ink",
                    "layer": "motif_under",
                },
            ],
        },
        # 제품이 위, 문구가 아래. 선언 순서가 곧 해석 순서다
        "copy_blocks": [
            {"id": "headline", "role": "headline", "content_ref": "brief.copy.headline",
             "type_role": "headline",
             "grid_ref": {"col_start": 0, "col_span": 4, "row_anchor": "lower",
                          "align": "center"},
             "priority": 1, "color_role": "ink", "layer": "type_under"},
            {"id": "benefit", "role": "benefit", "content_ref": "brief.copy.benefit",
             "type_role": "benefit",
             "grid_ref": {"col_start": 0, "col_span": 4, "row_anchor": "after:headline",
                          "align": "center"},
             "priority": 2, "color_role": "ink", "layer": "type_under"},
            {"id": "brand", "role": "brand", "content_ref": "brief.copy.extra.brand",
             "type_role": "brand",
             "grid_ref": {"col_start": 0, "col_span": 4, "row_anchor": "after:benefit",
                          "align": "center"},
             "priority": 3, "color_role": "ink", "layer": "type_under"},
        ],
        "layers": list(LAYERS),
        "safety": {
            "critical_blocks": ["headline"],
            "must_be_visible": [],
        },
    }


# ──────────────────────────────────────────────────────────────────────────
# C — Promotion
#     제품 크게(세로 꽉) · 할인 강하게 · 정보 5개 · block 그래픽
# ──────────────────────────────────────────────────────────────────────────
def fixture_c() -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "canvas": {"ratio": "1:1"},
        "design_language": "promotion",
        "grid": {
            "columns": 6,
            "margin_density": "tight",
            "gutter_scale": "tight",
            "baseline_scale": "fine",
        },
        "zones": {
            "type": {"col_start": 0, "col_span": 4},
            "product": {"col_start": 2, "col_span": 4},
            "overlap_intent": "required",
        },
        "product": {
            "fit": "zone_height",
            "anchor": {"x": "right", "y": "bottom"},
            "bleed": ["bottom", "right"],
            "rotation": "slight_ccw",
            "grounding": "none",
        },
        "background": {
            "mode": "gradient",
            "material": "none",
            "lighting": "dramatic",
            "texture": "none",
            "whitespace_strategy": "dense",
        },
        "typography": {
            "measure_cols": 4,
            "break_strategy": "width",
            "scale_step": 1.0,
            "roles": [
                _role("eyebrow", "sans", "medium", -1, 1.3, "tight", "emphasis",
                      tracking_em=0.1, transform="uppercase", max_lines=1),
                _role("headline", "display", "black", 4, 1.02, "tight", "ink",
                      tracking_em=-0.01, max_lines=2),
                _role("benefit", "sans", "medium", 0, 1.3, "tight", "ink", max_lines=2),
                _role("token", "display", "black", 6, 1.0, "none", "spot", max_lines=1),
                _role("cta", "sans", "medium", 0, 1.2, "none", "ink",
                      align="center", max_lines=1),
            ],
        },
        "palette": {
            "strategy": "complementary",
            "source": "product",
            "background_tone": "light",
            "roles": ["bg", "ink", "spot", "emphasis"],
            "rhythm": {"spot_min_regions": 5, "spot_path": "perimeter"},
        },
        "motif": {
            "shape": "block",
            "min_repeats": 5,
            "pattern": {
                "role": "edge_blocks",
                "repeat": 5,
                "spacing": {"unit": "col", "value": 1.0},
                "region": {"col_start": 0, "col_span": 6, "row_anchor": "top",
                           "row_span": 3},
                "angle": "vertical",
                "phase": "start",
                "weight": "thick",
                "color_role": "spot",
                "layer": "motif_under",
            },
            "instances": [
                {
                    "role": "cta_plate",
                    "grid_ref": {"col_start": 0, "col_span": 4,
                                 "row_anchor": "before:cta", "row_span": 4},
                    "orientation": "horizontal",
                    "weight": "thick",
                    "color_role": "spot",
                    "layer": "motif_over",
                },
            ],
        },
        "copy_blocks": [
            {"id": "eyebrow", "role": "eyebrow", "content_ref": "brief.copy.eyebrow",
             "type_role": "eyebrow",
             "grid_ref": {"col_start": 0, "col_span": 4, "row_anchor": "upper"},
             "priority": 4, "color_role": "emphasis", "layer": "type_under"},
            {"id": "headline", "role": "headline", "content_ref": "brief.copy.headline",
             "type_role": "headline",
             "grid_ref": {"col_start": 0, "col_span": 4, "row_anchor": "after:eyebrow"},
             "priority": 1, "color_role": "ink", "layer": "type_under"},
            {"id": "benefit", "role": "benefit", "content_ref": "brief.copy.benefit",
             "type_role": "benefit",
             "grid_ref": {"col_start": 0, "col_span": 4, "row_anchor": "after:headline"},
             "priority": 3, "color_role": "ink", "layer": "type_under"},
            {"id": "discount_token", "role": "token", "content_ref": "brief.copy.token",
             "type_role": "token",
             "grid_ref": {"col_start": 0, "col_span": 4, "row_anchor": "after:benefit"},
             "priority": 1, "color_role": "spot", "layer": "type_over"},
            {"id": "cta", "role": "cta", "content_ref": "brief.copy.cta",
             "type_role": "cta",
             "grid_ref": {"col_start": 0, "col_span": 4, "row_anchor": "bottom",
                          "align": "center"},
             "priority": 2, "color_role": "ink", "layer": "type_over"},
        ],
        "layers": list(LAYERS),
        "safety": {
            "critical_blocks": ["headline", "discount_token", "cta"],
            "must_be_visible": ["cta_plate"],
        },
    }


# ──────────────────────────────────────────────────────────────────────────
# D — Contemporary graphic
#     8단 · 제품/타이포 적극 overlap · diagonal pattern · 강한 리듬
# ──────────────────────────────────────────────────────────────────────────
def fixture_d() -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "canvas": {"ratio": "1:1"},
        "design_language": "contemporary_graphic",
        "grid": {
            "columns": 8,
            "margin_density": "normal",
            "gutter_scale": "tight",
            "baseline_scale": "normal",
        },
        "zones": {
            "type": {"col_start": 0, "col_span": 8},
            "product": {"col_start": 3, "col_span": 5},
            "overlap_intent": "required",
        },
        "product": {
            "fit": "area_cap",
            "area_cap": 0.55,
            "anchor": {"x": "right", "y": "middle"},
            "bleed": ["right"],
            "rotation": "slight_cw",
            "grounding": "none",
        },
        "background": {
            "mode": "gradient",
            "material": "none",
            "lighting": "soft_side",
            "texture": "subtle_grain",
            "whitespace_strategy": "balanced",
        },
        "typography": {
            "measure_cols": 6,
            "break_strategy": "semantic",
            "scale_step": 1.1,
            "roles": [
                _role("headline", "display", "bold", 5, 0.92, "tight", "ink",
                      tracking_em=-0.04, max_lines=3),
                _role("token", "display", "black", 6, 1.0, "none", "spot",
                      align="left", max_lines=1),
                _role("caption", "sans", "regular", -2, 1.4, "none", "ink",
                      tracking_em=0.2, transform="uppercase", max_lines=1),
            ],
        },
        "palette": {
            "strategy": "split_complementary",
            "source": "product",
            "background_tone": "light",
            "roles": ["bg", "ink", "spot", "emphasis"],
            "rhythm": {"spot_min_regions": 4, "spot_path": "vertical"},
        },
        "motif": {
            "shape": "diagonal",
            "min_repeats": 3,
            "pattern": {
                "role": "stripe_field",
                "repeat": 14,
                "spacing": {"unit": "baseline", "value": 2.5},
                "region": {"col_start": 0, "col_span": 8, "row_anchor": "top",
                           "row_span": 18},
                "angle": "diagonal_up",
                "phase": "start",
                "weight": "hair",
                "color_role": "spot",
                "layer": "motif_under",
            },
            "instances": [],
        },
        "copy_blocks": [
            {"id": "headline", "role": "headline", "content_ref": "brief.copy.headline",
             "type_role": "headline",
             "grid_ref": {"col_start": 0, "col_span": 6, "row_anchor": "center"},
             "priority": 1, "color_role": "ink", "layer": "type_over"},
            {"id": "discount_token", "role": "token", "content_ref": "brief.copy.token",
             "type_role": "token",
             "grid_ref": {"col_start": 0, "col_span": 6, "row_anchor": "after:headline",
                          "align": "left"},
             "priority": 1, "color_role": "spot", "layer": "type_over"},
            {"id": "period", "role": "caption", "content_ref": "brief.copy.extra.period",
             "type_role": "caption",
             "grid_ref": {"col_start": "margin_right", "row_anchor": "center"},
             "orientation": "rotate_cw",
             "priority": 4, "color_role": "ink", "layer": "type_over"},
        ],
        "layers": list(LAYERS),
        "safety": {
            "critical_blocks": ["headline", "discount_token"],
            "must_be_visible": [],
        },
    }


# ──────────────────────────────────────────────────────────────────────────
# C-dark — Promotion, 짙은 바탕
#     C 와 **palette.background_tone 한 줄만** 다르다.
#     bg/ink polarity 가 함께 뒤집히므로 color_role 은 하나도 고치지 않는다 —
#     그게 background_tone 이 strategy 와 독립된 축이라는 증거다 (§4-5)
# ──────────────────────────────────────────────────────────────────────────
def fixture_c_dark() -> dict:
    raw = fixture_c()
    raw["palette"]["background_tone"] = "dark"
    return raw


FIXTURES = {
    "A": ("Clean editorial", fixture_a),
    "B": ("Premium minimal", fixture_b),
    "C": ("Promotion", fixture_c),
    "D": ("Contemporary graphic", fixture_d),
}

# Step 5.5 에서 추가한 검증용 — 기본 비교 시트에는 넣지 않는다
DARK_FIXTURE = ("C-dark", "Promotion / dark ground", fixture_c_dark)

# 서체 capability 때문에 **품질 평가를 보류**하는 fixture (§13-3)
QUALITY_DEFERRED = {
    "B": "serif/regular(얇은 명조) 미번들 — 의도한 얼굴로 렌더할 수 없다",
}

__all__ = ["brief", "FIXTURES", "DARK_FIXTURE", "QUALITY_DEFERRED", "fixture_a",
           "fixture_b", "fixture_c", "fixture_d", "fixture_c_dark"]
