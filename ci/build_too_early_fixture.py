# -*- coding: utf-8 -*-
"""2026-08-27 09:00:00 실패 캡처에서 **'예약시간전' 알림 화면** 픽스처를 만든다.

무슨 일이 있었나 (고객 진단 ZIP `…-20260827-090021.zip`, v1.0.8,
Windows 10 10.0.19045, 인계 모드의 첫 실전 발사):

  08:59:59  발사 직전 점검: 확인창 감지됨 · 선택표 체크 켜짐
  09:00:00  [확인] 1발째 · 도착 추정 정각 -296ms
            · 서버: 알림 아직 예약 가능한 시간이 아닙니다. 확인 [too_early]
  09:00:01  선택표 체크 켜짐 · 확인창 없음 ([예약하기] 를 눌러주세요)

[확인] 한 번에 확인창이 소비됐고, 그 자리에 이 알림이 떴다.
`page_source/0002_handover_after.html` 에 마크업이 그대로 남아 있다:

    <div class="popup_wrap s_size wp400 type-alert2" id="layer-alert-popup2">
      <h5>알림</h5>
      <p class="f_18" id="layer-alert-popup-contents2">아직 예약 가능한 시간이 아닙니다.</p>
      <a href="#none" class="btn" id="layer-popup-close2">확인</a>

**이 문구가 서버 원문(InsertOcreqst.html 의 returnmsg)이다.** v1.0.8 까지 우리
CI 픽스처는 우리가 지어낸 '예약시간전' 을 찍고 있었고, 그래서 분류기 시험이
순환논증이었다. 이 픽스처가 그것을 끝낸다.

만드는 방식은 `build_netfunnel_fixture.py` 와 같다. 이미 개인정보가 지워져 있는
`grid_selected_row_added.html`(= 칸 선택 + 선택표 1행 + [예약하기] 버튼, 확인창
없음)의 **빈 알림 껍데기**를 오늘 캡처의 **내용이 채워진 진짜 껍데기**로 바꾸고
보이게 켠다. 오늘 캡처의 페이지 본문에는 아동 실명이 평문으로 남아 있으므로
본문은 쓰지 않는다. 갈아끼우는 조각에는 개인정보가 한 글자도 없다(아래에서
모양 검사로 확인하고, 실패하면 0 이 아닌 코드로 끝난다).
"""
from __future__ import annotations

import re
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "fixtures" / "real"
BASE = OUT / "grid_selected_row_added.html"
TARGET = OUT / "too_early_alert.html"

PAGE = "page_source/0002_handover_after.html"
SHELL_ID = "layer-alert-popup2"
REAL_TEXT = "아직 예약 가능한 시간이 아닙니다."

PII_SHAPES = (
    r"(?<!\d)\d{18}(?!\d)",
    r"\d{6}\s*-\s*[1-4]\d{6}",
    r"[\w.+-]+@[\w-]+\.[\w.]+",
    r"01[016789][-\s.]?\d{3,4}[-\s.]?\d{4}",
)

RE_SCRIPT = re.compile(r"<script\b[^>]*>.*?</script>", re.S | re.I)
RE_SCRIPT_SELF = re.compile(r"<script\b[^>]*/?>", re.I)


def _shell(html: str) -> str:
    """id=layer-alert-popup2 껍데기를 여닫는 div 짝을 세어 통째로 꺼낸다."""
    i = html.find(f'id="{SHELL_ID}"')
    if i < 0:
        raise SystemExit(f"{PAGE} 안에 #{SHELL_ID} 이 없습니다.")
    start = html.rfind("<div", 0, i)
    depth = 0
    for m in re.finditer(r"<div\b|</div>", html[start:]):
        depth += 1 if m.group(0) == "<div" else -1
        if depth == 0:
            return html[start:start + m.end()]
    raise SystemExit("알림 껍데기의 </div> 짝을 찾지 못했습니다.")


def _shown(block: str) -> str:
    """style 을 display: block 으로 못박는다. 화면에 떠 있던 그 순간이 기준이다."""
    head_end = block.find(">")
    head, rest = block[:head_end], block[head_end:]
    head = re.sub(r'\s*style="[^"]*"', "", head)
    return head + ' style="display: block;"' + rest


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

    block = _shell(zf.read(member).decode("utf-8", "replace"))
    block = RE_SCRIPT.sub("", block)
    block = RE_SCRIPT_SELF.sub("", block)
    if REAL_TEXT not in block:
        print(f"캡처의 알림에 '{REAL_TEXT}' 가 없습니다.", file=sys.stderr)
        return 1

    leaks = []
    for pat in PII_SHAPES:
        for hit in re.findall(pat, block):
            leaks.append((pat, str(hit)[:24]))
    if leaks:
        print("알림 조각에 개인정보 모양이 남아 있습니다:", leaks[:5], file=sys.stderr)
        return 1

    base = BASE.read_text(encoding="utf-8")
    old = _shell(base)
    note = ("<!-- 아래는 2026-08-27 09:00:00 고객 PC 캡처의 진짜 알림 레이어다. "
            "[확인] 한 발이 확인창을 소비하고 그 자리에 이것이 떴다. "
            "문구는 InsertOcreqst.html 의 returnmsg 원문이다. -->")
    html = base.replace(old, f"{note}\n{_shown(block)}", 1)
    if html == base:
        print("바탕 픽스처의 알림 껍데기를 갈아끼우지 못했습니다.", file=sys.stderr)
        return 1
    TARGET.write_text(html, encoding="utf-8")
    print(f"{TARGET.name:32s} <- {PAGE} 의 #{SHELL_ID} "
          f"({len(block)}바이트) + {BASE.name}")
    return 0


if __name__ == "__main__":
    default = ("/home/bfdev/neoworks/apps/gateway/artifacts/private/"
               "05788f12-b025-48ba-bb01-7c45121013d8/"
               "1787788821324-aisarang-reservation-2309842-20260827-090021.zip")
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else default))
