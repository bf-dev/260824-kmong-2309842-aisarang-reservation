# -*- coding: utf-8 -*-
"""2026-09-01 09:00:00 실패 캡처에서 **'선예약' 알림 화면** 픽스처를 만든다.

무슨 일이 있었나 (고객 진단 ZIP `…-20260901-090020.zip`, v1.0.9,
Windows 10 10.0.19045, 인계 모드):

  08:59:59  조준 확정: 도착 목표 정각 +685ms (시각 오차 ±435ms + 여유 250ms)
  09:00:02  [확인] 1발째 · 도착 추정 정각 +686ms
            · 서버: 알림 1건 예약 중 1건 예약이 선예약으로 인해 예약되지
              않았습니다. 확인 [unknown]
  09:00:10  사이트가 가상대기열을 띄웠습니다 (앞에 319명)

`page_source/0002_handover_after.html` 에 마크업이 그대로 남아 있다:

    <div class="popup_wrap s_size wp400 type-alert2" id="layer-alert-popup2">
      <h5>알림</h5>
      <p class="f_18" id="layer-alert-popup-contents2">
        1건 예약 중 1건 예약이 선예약으로 인해 예약되지 않았습니다.</p>
      <a href="#none" class="btn" id="layer-popup-close2">확인</a>

**이 문구가 서버 원문(InsertOcreqst.html 의 returnmsg)이다.** 우리가 지어낸
글자가 한 자도 섞이지 않도록, 분류기 테스트는 이 파일에서 문구를 읽어
booking.TAKEN_REAL 과 대조한다. (v1.0.8 때 지어낸 '예약시간전' 픽스처로
분류기 시험이 순환논증이 됐던 사고를 되풀이하지 않기 위한 장치다.)

만드는 방식은 `build_too_early_fixture.py` 와 같다. 이미 개인정보가 지워진
`grid_selected_row_added.html` 의 **빈 알림 껍데기**를 그날 캡처의 **내용이
채워진 진짜 껍데기**로 바꾸고 보이게 켠다. 캡처 본문에는 아동 실명이 평문으로
있으므로 본문은 쓰지 않는다. 갈아끼우는 조각은 아래에서 모양 검사를 통과해야
하고, 실패하면 0 이 아닌 코드로 끝난다.
"""
from __future__ import annotations

import re
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "fixtures" / "real"
BASE = OUT / "grid_selected_row_added.html"
TARGET = OUT / "taken_alert.html"

PAGE = "page_source/0002_handover_after.html"
SHELL_ID = "layer-alert-popup2"
# 캡처에서 반드시 보여야 하는 조각. 건수 접두사는 제출 줄 수에 따라 변하므로
# 변하지 않는 뼈대만 확인한다.
REAL_MARK = "선예약으로 인해 예약되지 않았습니다."

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
    if REAL_MARK not in block:
        print(f"캡처의 알림에 '{REAL_MARK}' 가 없습니다.", file=sys.stderr)
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
    note = ("<!-- 아래는 2026-09-01 09:00:00 고객 PC 캡처의 진짜 알림 레이어다. "
            "도착 추정 정각 +686ms 에 서버가 돌려준 returnmsg 원문이고, "
            "그날 목표일(20260915)의 여석은 08:59 캡처에서 시간대마다 2 였다. "
            "즉 686ms 안에 두 자리가 모두 나갔다는 뜻이다. -->")
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
               "1788220821293-aisarang-reservation-2309842-20260901-090020.zip")
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else default))
