"""고객 진단 기록 ZIP 에서 '진짜 마크업' 픽스처를 만든다.

2026-08-25, 고객이 자기 PC(Windows 10 19045)에서 진짜 공동인증서 세션으로
진단 기록 모드를 돌리고 예약 흐름을 손으로 끝까지 걸었다. 그 ZIP 안에
/icms/occasion/OccasionTimeMainSlPL.html 응답과 4~9단계 화면이 통째로 들어 있다.
지금까지 4~9단계는 영상 복원본 추측이었고, 이제 실물이 있다.

이 스크립트가 하는 일
  1. ZIP 두 개를 풀어 페이지 소스와 ajax 응답을 꺼낸다
  2. 개인정보를 치환한다 (아동등록번호/회원번호/아이디/전화/주소/이메일)
  3. 바깥 스크립트를 걷어낸다 (픽스처는 네트워크 없이 떠야 한다)
  4. CSS 는 캡처된 실물을 그대로 같이 저장한다
     (.popup_wrap{display:none} 이 sub.css 에 있어서, 이게 없으면
      숨어 있어야 할 팝업 껍데기가 전부 보이는 것으로 렌더된다)

개인정보는 픽스처에 남기지 않는다. 커밋되는 파일이다.
"""
from __future__ import annotations

import re
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "fixtures" / "real"

# 개인정보 제거는 **값의 모양과 필드 이름**으로만 한다.
# 이 파일은 커밋된다. 그래서 여기에 고객의 진짜 값을 적어두면, 픽스처를
# 깨끗이 만들어 놓고 정작 청소 목록에 원본을 남기는 꼴이 된다. (실제로
# 처음에 그렇게 썼다가 잡았다.) 아래에는 고객의 어떤 값도 들어 있지 않다.
#
# 자릿수는 보존한다. 셀렉터가 자릿수에 의존할 수 있어서다
# (아동 라디오의 id 가 occasionChk<18자리> 다).
CHILD_ID_DUMMY = "100000000000000001"      # 18자리
RRN_DUMMY = "200101-3000000"

# 값을 통째로 갈아끼울 폼 필드 이름들. 이 화면에 실제로 실려 오는 것만.
PII_FIELDS = (
    "chilinnb", "mbrinnb", "mbrid", "registid", "updtid",
    "chname", "prtctornm", "chjumin", "jno1", "jno2",
    "cntctelno", "cntctelno1", "cntctelno2", "cntctelno3",
    "prtctormail", "chaddr", "childetailadres", "resdnczip",
    "zipcode1", "zipcode2",
)
_FIELD_DUMMY = {
    "cntctelno1": "010", "cntctelno2": "0000", "cntctelno3": "0000",
    "zipcode1": "000", "zipcode2": "00", "resdnczip": "00000",
    "chaddr": "테스트로 1", "childetailadres": "000-000",
    "prtctormail": "t***@example.com",
}

# name="..." 또는 id="..." 가 위 목록에 있는 input 의 value 를 갈아끼운다.
RE_PII_INPUT = re.compile(
    r"(<input\b[^>]*?\b(?:name|id)\s*=\s*[\"'](" + "|".join(PII_FIELDS) +
    r")[\"'][^>]*?\bvalue\s*=\s*[\"'])([^\"']*)([\"'])",
    re.I,
)

SCRUB = [
    # \b 를 쓰면 안 된다. 아동 라디오의 id 가 occasionChk<18자리> 라
    # 숫자 앞이 단어문자여서 \b 가 성립하지 않는다. 숫자 경계로 잡는다.
    (r"(?<!\d)\d{18}(?!\d)", CHILD_ID_DUMMY),              # 아동등록번호/회원번호
    (r"\b\d{6}\s*-\s*[1-4]\d{6}\b", RRN_DUMMY),            # 주민등록번호
    (r"\b\d{6}\s*-\s*[1-4]x{6}\b", RRN_DUMMY),             # 부분 가림 형태
    (r"[\w.+-]+@[\w-]+\.[\w.]+", "t***@example.com"),      # 이메일
    (r"\b01[016789][-\s.]?\d{3,4}[-\s.]?\d{4}\b", "010-0000-0000"),   # 휴대폰
]

# 네트워크를 타는 것들. 픽스처는 오프라인으로 떠야 한다.
RE_SCRIPT = re.compile(r"<script\b[^>]*>.*?</script>", re.S | re.I)
RE_NOSCRIPT = re.compile(r"<noscript\b[^>]*>.*?</noscript>", re.S | re.I)
RE_IFRAME = re.compile(r"<iframe\b[^>]*>.*?</iframe>", re.S | re.I)
RE_LINK_CSS = re.compile(r"<link\b[^>]*rel=[\"']?stylesheet[\"']?[^>]*>", re.I)
RE_LINK_HREF = re.compile(r"href=[\"']([^\"']+)", re.I)
RE_IMG_SRC = re.compile(r"(<img\b[^>]*?\ssrc=)([\"'])[^\"']*\2", re.I)


def css_order(html: str, available: set[str]) -> list[str]:
    """페이지에 적힌 그대로의 CSS 순서를 되살린다.

    캐스케이드 순서가 결과를 바꾼다. 알파벳순으로 붙이면 sub.css 의
    `.popup_wrap { display:none }` 이 다른 규칙에 밀려, 숨어 있어야 할
    확인창 두 번째 사본이 '보인다' 로 렌더된다.
    """
    out = []
    for tag in RE_LINK_CSS.findall(html):
        m = RE_LINK_HREF.search(tag)
        if not m:
            continue
        name = m.group(1).split("?")[0].split("/")[-1]
        if name in available and name not in out:
            out.append(name)
    for name in sorted(available):     # 페이지에 없던 것은 뒤에
        if name not in out:
            out.append(name)
    return [f"assets/{n}" for n in out]


# 기록기(v1.0.6)의 마스킹이 CSS 선택자 `input[type="password"]` 를 비밀번호로
# 오인해 닫는 `]` 를 ***REDACTED*** 로 바꿔놓았다. 그 자리에서 CSS 문법이 깨져
# 크롬이 sub.css 를 10091번째 글자에서 읽다 멈추고, 뒤에 있던
# `.popup_wrap{display:none}` 이 죽는다. masking.py 는 고쳤지만 **이미 받은
# 캡처**는 깨진 채로 남아 있으므로 여기서 되돌린다.
RE_MASKED_ATTR = re.compile(
    r"(\[\s*type\s*=\s*([\"'])(?:password|passwd|pwd)\2)\*\*\*REDACTED\*\*\*",
    re.I,
)


def repair_masked_css(css: str) -> str:
    return RE_MASKED_ATTR.sub(r"\1]", css)


def scrub(text: str) -> str:
    # 1) 이름으로 아는 폼 필드는 값을 통째로 갈아끼운다.
    def _field(m):
        dummy = _FIELD_DUMMY.get(m.group(2).lower(), "0")
        return m.group(1) + dummy + m.group(4)
    text = RE_PII_INPUT.sub(_field, text)
    # 2) 나머지는 모양으로 잡는다.
    for pat, rep in SCRUB:
        text = re.sub(pat, rep, text)
    return text


def offline(html: str, css_hrefs: list[str]) -> str:
    """스크립트/아이프레임을 걷고 CSS 를 로컬 자산으로 바꾼다."""
    html = RE_SCRIPT.sub("", html)
    html = RE_NOSCRIPT.sub("", html)
    html = RE_IFRAME.sub("", html)
    html = RE_LINK_CSS.sub("", html)
    html = RE_IMG_SRC.sub(r"\1\2data:,\2", html)
    links = "\n".join(f'<link rel="stylesheet" href="{h}">' for h in css_hrefs)
    if "</head>" in html:
        html = html.replace("</head>", links + "\n</head>", 1)
    else:
        html = links + "\n" + html
    return html


def main(zip_path: str) -> int:
    src = Path(zip_path)
    if not src.exists():
        print(f"ZIP 이 없습니다: {src}", file=sys.stderr)
        return 2

    OUT.mkdir(parents=True, exist_ok=True)
    assets = OUT / "assets"
    assets.mkdir(exist_ok=True)

    zf = zipfile.ZipFile(src)
    names = zf.namelist()

    def read(member: str) -> str:
        return zf.read(member).decode("utf-8", "replace")

    # --- CSS: 실물 그대로 (팝업 display:none 규칙이 여기 있다)
    css_files = []
    for member in names:
        if not member.startswith("record/bodies/") or not member.endswith(".css.txt"):
            continue
        # 026_sub.css.txt -> sub.css
        stem = member.split("/")[-1]
        nice = re.sub(r"^\d+_", "", stem)[: -len(".txt")]
        # CSS 는 손대지 않고 그대로 쓴다. 단, 기록기가 스스로 망가뜨린
        # 자리는 되돌린다(아래 repair_masked_css 참고).
        # 예전에 url(...) 을 data:, 로 바꿔 놓았더니 CSS 가 중간에서 깨져
        # 크롬이 121KB 짜리 sub.css 를 94개 규칙만 읽고 멈췄다. 그 바람에
        # `.popup_wrap{display:none}` (65394번째 글자) 가 통째로 죽었고,
        # 숨어 있어야 할 확인창 두 번째 사본이 '보인다' 로 판정됐다.
        # 바깥 네트워크는 크롬의 host-resolver 규칙으로 막으므로 url() 은
        # 그냥 두면 된다(로컬 404 로 조용히 실패한다).
        body = repair_masked_css(read(member))
        (assets / nice).write_text(body, encoding="utf-8")
        css_files.append(nice)
    available = set(css_files)
    print(f"CSS {len(available)}개: {', '.join(sorted(available))}")

    # --- 4~9단계 실물 페이지
    wanted_pages = {
        "0010_11_after_add_and_tick.html": "grid_ready.html",
        "0011_12_after_add_and_tick.html": "grid_selected_row_added.html",
        "0012_13_modal_open.html": "modal_open.html",
    }
    css_hrefs: list[str] = []
    for member in names:
        base = member.split("/")[-1]
        if base in wanted_pages:
            raw = read(member)
            css_hrefs = css_order(raw, available)
            html = offline(scrub(raw), css_hrefs)
            (OUT / wanted_pages[base]).write_text(html, encoding="utf-8")
            print(f"{wanted_pages[base]:32s} <- {base} ({len(html)}바이트)")
    if not css_hrefs:
        css_hrefs = [f"assets/{c}" for c in sorted(available)]

    # --- 스크립트를 남긴 원본 한 벌.
    # DOM 판정용 픽스처는 스크립트를 걷어내지만, "사이트가 실제로 이 함수를
    # 부르는가"(listChildSelect / fnChildInfo / icmsLayerPopup.confirm2 / 반 1개
    # 자동선택) 같은 것은 글자로만 확인할 수 있다. 개인정보는 똑같이 지운다.
    for member in names:
        if member.split("/")[-1] == "0012_13_modal_open.html":
            (OUT / "modal_open.raw.html").write_text(
                scrub(read(member)), encoding="utf-8")
            print(f"{'modal_open.raw.html':32s} <- {member.split('/')[-1]} (스크립트 보존)")
    for member in names:
        if member.endswith("02_OccasionTimeMainSlPL.html.html"):
            (OUT / "occasion_time_main_slpl.raw.html").write_text(
                scrub(read(member)), encoding="utf-8")
            print(f"{'occasion_time_main_slpl.raw.html':32s} <- ajax 응답 (스크립트 보존)")

    # --- 이용정보 화면 ajax 응답 원본 (조각이라 껍데기를 씌운다)
    for member in names:
        if member.endswith("02_OccasionTimeMainSlPL.html.html"):
            frag = scrub(read(member))
            frag = RE_SCRIPT.sub("", frag)
            links = "\n".join(f'<link rel="stylesheet" href="{h}">' for h in css_hrefs)
            doc = ("<!DOCTYPE html><html lang=\"ko\"><head><meta charset=\"utf-8\">"
                   f"<title>OccasionTimeMainSlPL</title>{links}</head><body>"
                   f"{frag}</body></html>")
            (OUT / "occasion_time_main_slpl.html").write_text(doc, encoding="utf-8")
            print(f"{'occasion_time_main_slpl.html':32s} <- {member.split('/')[-1]} "
                  f"({len(doc)}바이트)")

    # --- 개인정보가 남았는지 최종 검사. 남으면 0 이 아닌 코드로 끝난다.
    # 더미 자체는 모양이 같으므로(18자리 등) 허용 목록으로 걸러낸다.
    allowed = {CHILD_ID_DUMMY, RRN_DUMMY, "t***@example.com",
               "010-0000-0000"} | set(_FIELD_DUMMY.values())
    leaks = []
    for f in sorted(OUT.rglob("*.html")):      # CSS 는 개인정보를 담지 않는다
        body = f.read_text(encoding="utf-8", errors="replace")
        for pat, _ in SCRUB:
            for hit in re.findall(pat, body):
                text = hit if isinstance(hit, str) else "".join(hit)
                if text not in allowed:
                    leaks.append((f.name, pat, text[:24]))
    if leaks:
        print("개인정보가 남아 있습니다:", leaks[:10], file=sys.stderr)
        return 1
    print(f"개인정보 잔존 검사 통과 ({len(list(OUT.rglob('*.html')))}개 파일)")
    return 0


if __name__ == "__main__":
    default = ("/home/bfdev/neoworks/apps/gateway/artifacts/private/"
               "05788f12-b025-48ba-bb01-7c45121013d8/"
               "1787648258593-aisarang-reservation-2309842-20260825-175739.zip")
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else default))
