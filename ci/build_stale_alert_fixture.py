# -*- coding: utf-8 -*-
"""2026-09-18 09:00:00 의 **거짓 실패** 캡처에서 픽스처를 만든다.

이 프로젝트에서 09-15 의 거짓 성공과 짝을 이루는 실패다. 방향만 반대다.

무슨 일이 있었나 (고객 진단 ZIP `…-20260918-090021.zip`, v1.0.16 직전판 1.0.15,
Windows 10 10.0.19045, 인계 모드, serverOffsetMs -786.9):

  08:45:58  고객이 손으로 [예약하기] → 확인창 열림
  08:46:00  **14분 이른 제출 한 건**이 나갔다 (InsertOcreqst, t0=1789688760327)
            서버: {"returnmsg":"아직 예약 가능한 시간이 아닙니다.","returnval":""}
            사이트는 이 글자를 #layer-alert-popup-contents2 에 찍는다
  08:46:03  고객이 알림을 닫고 확인창을 다시 열었다
            → **그런데 사이트는 그 글자를 지우지 않는다.**
              껍데기만 `display:none` 으로 숨긴다
  08:59:59  발사 직전 캡처(0001_handover_preflight.html)에 그 글자가 그대로 있다
  09:00:00  우리 [확인] 발사 → 예약 **성공**
  09:00:01  우리 판정: `too_early`  ← 14분 묵은 저 글자를 읽었다
  09:00:21  result=fail. 고객은 성공한 아침을 실패로 보고받았다

성공의 증거는 같은 ZIP 안에 네 겹으로 있다:
  1. 대기열 표(opcode=5101)가 `__aisarang_fired_at` 과 **같은 ms** 에 나갔다
  2. 695ms 뒤 opcode=5004 = `NetFunnel_Complete()`. 사이트는 이것을 ajax
     success 콜백 **안에서만** 부른다 (실물 스크립트)
  3. 곧바로 `/?menuno=245` 이동. 실물 스크립트는 `returnval == "success"`
     분기에서만 이동한다
  4. 신청현황에 새 줄: `2026-10-02 09:00~17:00 ... 상태: 예약` (ocseq 5733117).
     08:45 의 중복확인이 `{"returnValue":"N"}` 이었으므로 그 줄은 그날 생겼다

픽스처는 그 화면의 **구조만** 재현한다. 오늘 캡처의 페이지 본문에는 아동
실명이 평문으로 남아 있으므로 본문은 쓰지 않는다(`하면 안 되는 것` 참고).
이미 개인정보가 지워져 있는 `grid_selected_row_added.html` 위에,
**숨은 채로 글자가 남아 있는 알림 껍데기**를 얹는다. 그것이 이 버그의 전부다.

    python ci/build_stale_alert_fixture.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "fixtures" / "real"
BASE = OUT / "grid_selected_row_added.html"
TARGET = OUT / "stale_alert_after_reopen.html"

# 2026-09-18 캡처의 원문. 지어낸 글자가 아니다.
#   page_source/0001_handover_preflight.html:
#   <div class="popup_wrap s_size wp400 type-alert2" id="layer-alert-popup2"
#        style="display: none;">
#     <p class="f_18" id="layer-alert-popup-contents2">아직 예약 가능한 시간이 아닙니다.</p>
STALE_TEXT = "아직 예약 가능한 시간이 아닙니다."

# 숨은 껍데기. `display:none` 이 이 버그의 핵심이다. 사람 눈에는 없고,
# page_source 훑기에는 있다.
STALE_SHELL = f"""
<div class="popup_wrap s_size wp400 type-alert2" id="layer-alert-popup2" style="display: none;">
	<div class="popup_inner_wrap maxw525" tabindex="0">
        <a href="javascript:void(0)" class="popup_close" role="button" id="layer-popup-close2" title="닫기"><span class="hidden">닫기</span></a>
        <h5>알림</h5>
        <section class="mt30 pl30 pr30">
            <p class="f_18" id="layer-alert-popup-contents2">{STALE_TEXT}</p>
            <div class="btn_group">
                <a href="#none" class="btn" id="layer-popup-close2">확인</a>
            </div>
        </section>
    </div>
</div>
"""

PII_SHAPES = (
    r"(?<!\d)\d{18}(?!\d)",
    r"\d{6}\s*-\s*[1-4]\d{6}",
    r"[\w.+-]+@[\w-]+\.[\w.]+",
    r"01[016789][-\s.]?\d{3,4}[-\s.]?\d{4}",
)


def _check_no_pii(fragment: str) -> None:
    for shape in PII_SHAPES:
        m = re.search(shape, fragment)
        if m:
            raise SystemExit(f"개인정보 모양이 조각에 있습니다: {m.group(0)!r}")


def main() -> int:
    if not BASE.is_file():
        raise SystemExit(f"기준 픽스처가 없습니다: {BASE}")
    _check_no_pii(STALE_SHELL)

    html = BASE.read_text(encoding="utf-8")

    # 기준 픽스처의 **빈** alert2 껍데기를 글자가 남아 있는 숨은 껍데기로 바꾼다.
    i = html.find('id="layer-alert-popup2"')
    if i < 0:
        # 껍데기가 없으면 body 끝에 붙인다. 구조상 같은 자리다.
        j = html.rfind("</body>")
        if j < 0:
            raise SystemExit("기준 픽스처에 </body> 가 없습니다.")
        out = html[:j] + STALE_SHELL + html[j:]
    else:
        start = html.rfind("<div", 0, i)
        depth = 0
        end = None
        for m in re.finditer(r"<div\b|</div>", html[start:]):
            depth += 1 if m.group(0) == "<div" else -1
            if depth == 0:
                end = start + m.end()
                break
        if end is None:
            raise SystemExit("알림 껍데기의 </div> 짝을 찾지 못했습니다.")
        out = html[:start] + STALE_SHELL + html[end:]

    TARGET.write_text(out, encoding="utf-8")
    _check_no_pii(STALE_TEXT)

    # 만든 것이 정말 '숨어 있는데 글자는 있다' 인지 확인한다.
    body = TARGET.read_text(encoding="utf-8")
    assert STALE_TEXT in body, "문구가 안 들어갔습니다"
    assert "display: none" in body, "숨김 상태가 아닙니다"
    print(f"wrote {TARGET.relative_to(HERE.parent)} ({len(body)} bytes)")
    print(f"  stale text present : {STALE_TEXT!r}")
    print(f"  shell hidden       : display:none")
    return 0


if __name__ == "__main__":
    sys.exit(main())
