# -*- coding: utf-8 -*-
"""2026-08-26 실패 캡처에서 **가상대기열 화면** 픽스처를 만든다.

무슨 일이 있었나 (고객 진단 ZIP
`…-20260826-085814.zip`, v1.0.7, Windows 10, 08:36~08:58 KST):

  08:57:32  [예약하기] 를 눌렀습니다 (#timecareConfirm).
  08:57:40  준비 실패(no_modal): 예약 확인창이 열리지 않았습니다.

확인창 자리에 실제로 나타난 것은 **넷퍼널(NetFunnel) 가상대기열 레이어**였다.
`page_source/0005_modal_not_open.html` 의 꼬리에 그 마크업이 통째로 남아 있고,
`network_modal_not_open.json` 에 `nf.childcare.go.kr:8443/ts.wseq?opcode=5101`
(대기열 진입) → `opcode=5002` 폴링이 줄줄이 찍혀 있다.

레이어가 스스로 이렇게 적어 놓았다:

    ※ 재접속하시면 대기시간이 더 길어집니다.

그런데 v1.0.7 은 확인창이 안 열리면 **검색 화면부터 준비를 통째로 다시** 했다.
그래서 매번 대기열 맨 뒤로 갔고, 캡처 세 장에 그 대가가 그대로 남았다:

    1회차  앞에 72명   예상 2분 10초
    2회차  앞에 138명  예상 3분 50초
    3회차  앞에 177명  예상 4분 32초

이 픽스처는 그 상태를 실제 브라우저에서 재현하기 위한 것이다.

만드는 방식: 이미 개인정보가 지워져 있는 `grid_selected_row_added.html`
(= 칸 선택 + 선택표 1행, 확인창 없음) 에 **오늘 캡처의 진짜 대기열 레이어
마크업**을 그대로 붙인다. 오늘 캡처의 페이지 본문에는 아동 실명이 평문으로
남아 있으므로 본문은 쓰지 않는다. 붙이는 조각에는 개인정보가 한 글자도 없다
(아래에서 모양 검사로 확인하고, 실패하면 0 이 아닌 코드로 끝난다).
"""
from __future__ import annotations

import re
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "fixtures" / "real"
BASE = OUT / "grid_selected_row_added.html"
TARGET = OUT / "netfunnel_waiting.html"

START = '<div id="NetFunnel_Loading_Popup"'
PAGE = "0005_modal_not_open.html"

# 픽스처는 커밋된다. 이 모양이 하나라도 남으면 만들지 않는다.
PII_SHAPES = (
    r"(?<!\d)\d{18}(?!\d)",
    r"\d{6}\s*-\s*[1-4]\d{6}",
    r"[\w.+-]+@[\w-]+\.[\w.]+",
    r"01[016789][-\s.]?\d{3,4}[-\s.]?\d{4}",
)

RE_SCRIPT = re.compile(r"<script\b[^>]*>.*?</script>", re.S | re.I)
RE_SCRIPT_SELF = re.compile(r"<script\b[^>]*/?>", re.I)


def extract_layer(html: str) -> str:
    """대기열 레이어 + 뒤에 깔리는 딤 두 장을 통째로 꺼낸다."""
    i = html.find(START)
    if i < 0:
        raise SystemExit(f"{PAGE} 안에 대기열 레이어가 없습니다.")
    j = html.find("</body>", i)
    if j < 0:
        j = len(html)
    block = html[i:j]
    # ts.wseq 스크립트 태그는 세션성 key 를 물고 있고 픽스처에는 필요 없다.
    block = RE_SCRIPT.sub("", block)
    block = RE_SCRIPT_SELF.sub("", block)
    return block.strip()


def main(zip_path: str) -> int:
    src = Path(zip_path)
    if not src.exists():
        print(f"ZIP 이 없습니다: {src}", file=sys.stderr)
        return 2
    if not BASE.exists():
        print(f"바탕 픽스처가 없습니다: {BASE}", file=sys.stderr)
        return 2

    zf = zipfile.ZipFile(src)
    member = next((n for n in zf.namelist() if n.endswith(PAGE)), "")
    if not member:
        print(f"ZIP 안에 {PAGE} 가 없습니다.", file=sys.stderr)
        return 2
    layer = extract_layer(zf.read(member).decode("utf-8", "replace"))

    leaks = []
    for pat in PII_SHAPES:
        for hit in re.findall(pat, layer):
            leaks.append((pat, str(hit)[:24]))
    if leaks:
        print("대기열 조각에 개인정보 모양이 남아 있습니다:", leaks[:5], file=sys.stderr)
        return 1

    base = BASE.read_text(encoding="utf-8")
    if "</body>" not in base:
        print("바탕 픽스처에 </body> 가 없습니다.", file=sys.stderr)
        return 1
    note = ("<!-- 아래는 2026-08-26 08:57 고객 PC 캡처의 진짜 넷퍼널 대기열 "
            "레이어다. [예약하기] 를 누른 뒤 예약 확인창 대신 이것이 떴다. -->")
    html = base.replace("</body>", f"{note}\n{layer}\n</body>", 1)
    TARGET.write_text(html, encoding="utf-8")
    print(f"{TARGET.name:32s} <- {PAGE} 의 대기열 레이어 "
          f"({len(layer)}바이트) + {BASE.name}")
    return 0


if __name__ == "__main__":
    default = ("/home/bfdev/neoworks/apps/gateway/artifacts/private/"
               "05788f12-b025-48ba-bb01-7c45121013d8/"
               "1787702295153-aisarang-reservation-2309842-20260826-085814.zip")
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else default))
