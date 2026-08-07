#!/usr/bin/env python3
"""
번들 폰트 검증 스크립트 (v2)

폰트별로 (ttf + LICENSE 파일) 세트가 들어있는 폴더를 훑으면서
1) name table 신원 확인  2) 글리프 수  3) 문자 커버리지(cmap + 실제 외곽선)
4) LICENSE 파일 존재  5) 파일 checksum
을 확인하고 마크다운 리포트 파일을 직접 생성한다.

터미널 출력을 리다이렉트하지 않고 파이썬이 UTF-8로 파일을 직접 쓰므로
Windows cp949 인코딩 문제가 발생하지 않는다.

사용법:
    python verify_fonts.py "C:\\Users\\JW\\Desktop\\fonts-expansion"
    python verify_fonts.py <폴더> --out FONT_REPORT.md
"""

import argparse
import hashlib
import sys
from pathlib import Path

from fontTools.ttLib import TTFont

# name table ID → 사람이 읽을 이름
NAME_IDS = {
    1: "family",
    2: "subfamily",
    4: "full_name",
    5: "version",
    6: "postscript",
    13: "license",
    14: "license_url",
}

# 커버리지를 확인할 문자 집합
CHARSETS = {
    "영문 대문자": [chr(c) for c in range(0x41, 0x5B)],
    "영문 소문자": [chr(c) for c in range(0x61, 0x7B)],
    "숫자": [chr(c) for c in range(0x30, 0x3A)],
    "기본 문장부호": list(".,!?:;'\"()-–—…·"),
    "통화·기호": list("₩$%&@#*+/~"),
    "한글 음절(전체 11172)": [chr(c) for c in range(0xAC00, 0xD7A4)],
    "한글 자모": [chr(c) for c in range(0x3131, 0x3164)],
    "한자(샘플)": list("韓國語文字漢字書體美風水火山川"),
}

# 광고 문구에서 실제로 자주 쓰이는 기호 — 빠지면 렌더링 시 두부가 됨
RISKY_CHARS = "–—…·₩"


def get_names(font):
    """name table에서 주요 항목만 뽑는다. 영문(3,1,0x409) 우선."""
    out = {}
    for rec in font["name"].names:
        key = NAME_IDS.get(rec.nameID)
        if not key:
            continue
        try:
            value = rec.toUnicode().strip()
        except Exception:
            continue
        is_en = rec.platformID == 3 and rec.langID == 0x409
        if key not in out or is_en:
            out[key] = value
    return out


def coverage(font):
    """cmap에 있는지 + 실제 외곽선이 있는지 둘 다 본다."""
    cmap = font.getBestCmap()
    glyf = font["glyf"] if "glyf" in font else None

    def has_outline(ch):
        name = cmap.get(ord(ch))
        if name is None:
            return False
        if glyf is None:  # CFF(OTF)는 glyf가 없음 → cmap만 신뢰
            return True
        g = glyf[name]
        if g.numberOfContours == 0 and not ch.isspace():
            return False
        return True

    result = {}
    for label, chars in CHARSETS.items():
        ok = [c for c in chars if has_outline(c)]
        missing = [c for c in chars if c not in ok]
        result[label] = (len(ok), len(chars), missing)
    return result


def sha256(path, n=16):
    return hashlib.sha256(path.read_bytes()).hexdigest()[:n]


def find_license(font_path):
    """같은 폴더에서 라이선스 파일을 찾는다."""
    for p in font_path.parent.iterdir():
        if p.is_file() and (
            "license" in p.name.lower()
            or "ofl" in p.name.lower()
            or "라이선스" in p.name
        ):
            return p
    return None


def inspect(font_path, root):
    font = TTFont(str(font_path), fontNumber=0, lazy=True)
    names = get_names(font)
    return {
        "rel": font_path.relative_to(root).as_posix(),
        "path": font_path,
        "names": names,
        "num_glyphs": font["maxp"].numGlyphs,
        "coverage": coverage(font),
        "license_file": find_license(font_path),
        "sha256": sha256(font_path),
        "size_kb": font_path.stat().st_size // 1024,
    }


def verdict(r):
    """한글 커버리지 기준으로 사용 가능 여부를 판정."""
    han_ok, han_total, _ = r["coverage"]["한글 음절(전체 11172)"]
    if han_ok == han_total:
        return "사용 가능"
    if han_ok >= 2350:
        return "부분 (완성형만)"
    if han_ok > 0:
        return "부족"
    return "한글 없음"


def build_markdown(results, root):
    L = []
    L.append("# 폰트 검증 리포트")
    L.append("")
    L.append(f"- 검사 폴더: `{root}`")
    L.append(f"- 검사 파일 수: {len(results)}개")
    L.append("")

    # --- 요약표 ---
    L.append("## 요약")
    L.append("")
    L.append("| 폰트 | 파일 | 글리프 | 영문 | 숫자 | 한글 음절 | 판정 | LICENSE |")
    L.append("|---|---|---:|---|---|---|---|---|")
    for r in results:
        cov = r["coverage"]
        up, lo, num = cov["영문 대문자"], cov["영문 소문자"], cov["숫자"]
        han = cov["한글 음절(전체 11172)"]
        en = "O" if up[0] == up[1] and lo[0] == lo[1] else f"{up[0] + lo[0]}/52"
        L.append(
            f"| {r['names'].get('full_name', '?')} | `{r['path'].name}` | "
            f"{r['num_glyphs']:,} | {en} | "
            f"{'O' if num[0] == num[1] else f'{num[0]}/10'} | "
            f"{han[0]:,}/{han[1]:,} | {verdict(r)} | "
            f"{'있음' if r['license_file'] else '**없음**'} |"
        )
    L.append("")

    # --- 주의 필요 항목 ---
    warns = []
    for r in results:
        name = r["names"].get("full_name", r["path"].name)
        if not r["license_file"]:
            warns.append(f"- **{name}**: LICENSE 파일 없음 — OFL은 원문 동봉이 의무")
        if verdict(r) != "사용 가능":
            han = r["coverage"]["한글 음절(전체 11172)"]
            warns.append(f"- **{name}**: 한글 음절 {han[0]:,}/{han[1]:,}만 지원")
        risky_missing = [
            c for c in RISKY_CHARS
            if c in r["coverage"]["기본 문장부호"][2] + r["coverage"]["통화·기호"][2]
        ]
        if risky_missing:
            warns.append(
                f"- {name}: 광고 문구용 기호 미지원 — {' '.join(risky_missing)} "
                f"(렌더링 전 치환 필요)"
            )
    if warns:
        L.append("## 주의 필요")
        L.append("")
        L.extend(warns)
        L.append("")

    # --- 폰트별 상세 ---
    L.append("## 폰트별 상세")
    L.append("")
    for r in results:
        n = r["names"]
        L.append(f"### {n.get('full_name', r['path'].name)}")
        L.append("")
        L.append(f"- 경로: `{r['rel']}`")
        L.append(f"- 패밀리 / 굵기: {n.get('family', '?')} / {n.get('subfamily', '?')}")
        L.append(f"- 버전: {n.get('version', '?')}")
        L.append(f"- 글리프 수: {r['num_glyphs']:,}개")
        L.append(f"- 파일 크기: {r['size_kb']:,} KB")
        L.append(f"- sha256(앞 16자리): `{r['sha256']}`")
        lic = r["license_file"]
        L.append(f"- LICENSE 파일: {'`' + lic.name + '`' if lic else '**없음**'}")
        if n.get("license_url"):
            L.append(f"- 라이선스 URL: {n['license_url']}")
        L.append("")
        L.append("| 문자 집합 | 지원 | 빠진 문자 (최대 20개) |")
        L.append("|---|---|---|")
        for label, (ok, total, missing) in r["coverage"].items():
            mark = "OK" if ok == total else (f"{ok}/{total}" if ok else "없음")
            shown = " ".join(missing[:20]) if missing else "-"
            if len(missing) > 20:
                shown += f" ... (외 {len(missing) - 20:,}자)"
            L.append(f"| {label} | {mark} | {shown} |")
        L.append("")

    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("root", help="폰트 폴더 (하위 폴더까지 재귀 검사)")
    ap.add_argument("--out", default="FONT_REPORT.md", help="저장할 마크다운 파일명")
    args = ap.parse_args()

    root = Path(args.root).resolve()
    files = sorted(
        p for p in root.rglob("*") if p.suffix.lower() in (".ttf", ".otf", ".ttc")
    )
    if not files:
        print(f"[!] 폰트 파일을 못 찾음: {root}")
        return 1

    results = []
    failed = []
    for f in files:
        try:
            results.append(inspect(f, root))
        except Exception as e:
            failed.append((f, e))

    md = build_markdown(results, root)
    if failed:
        md += "\n## 읽기 실패\n\n"
        md += "\n".join(f"- `{f.name}`: {e}" for f, e in failed) + "\n"

    out = Path(args.out).resolve()
    # 파이썬이 직접 UTF-8로 쓴다 — 터미널 인코딩과 무관
    out.write_text(md, encoding="utf-8")

    # 콘솔에는 ASCII만 출력해 cp949 충돌을 피한다
    print(f"[OK] {len(results)} font(s) checked, {len(failed)} failed")
    print(f"[OK] report written: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
