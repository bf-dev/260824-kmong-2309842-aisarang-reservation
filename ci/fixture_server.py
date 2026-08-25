# -*- coding: utf-8 -*-
"""녹화된 아이사랑 응답을 되먹이는 로컬 서버 (우리 CI 전용).

GitHub Actions 러너에서는 childcare.go.kr 로 나가는 연결이 막힌다(러너 IP 대역
문제이고 고객 PC 와는 무관하다). 그래도 프로즌 exe 의 전체 경로
(Date 헤더 기반 서버시각 동기화 → 기관 목록 파싱 → 진단 업로드)는 진짜 Windows
에서 진짜로 돌려봐야 한다. 그래서 실제 사이트에서 받아 저장해 둔 응답을
그대로 돌려준다.

http.server 는 응답마다 RFC 형식의 Date 헤더를 스스로 붙이므로 시각 동기화
경로도 흉내가 아니라 진짜로 동작한다.
"""
from __future__ import annotations

import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
FIX = os.path.join(HERE, "fixtures")


def _read(name: str) -> bytes:
    with open(os.path.join(FIX, name), "rb") as f:
        return f.read()


# ---------------------------------------------------------------- 진단 기록용
# 진단 기록 모드(recorder.py)를 진짜 크롬으로 검증하기 위한 화면이다.
# 실제 사이트와 같은 모양으로 만든다: 화면은 ajax 로 채워지고, 우리가 아직
# 못 본 그 응답들(SelectOccasionChild / OccasionTimeMainSlPL)이 그 경로로 온다.
#
# 두 가지 계기가 심어져 있다. 둘 다 "기록기가 아무것도 누르지 않는다" 를
# 기계적으로 증명하기 위한 것이다.
#   window.__humanClicks  이 문서에서 일어난 클릭 수 (사람이 누른 것만 올라야 한다)
#   window.__reserved     [확인] 이 눌렸는지. 기록 모드에서는 끝까지 false 여야 한다.
_CHILD_FRAGMENT = """
<table id="childTable">
  <caption>시간제보육 아동 선택</caption>
  <thead><tr><th>선택</th><th>아동명</th><th>생년월일</th><th>개월수</th></tr></thead>
  <tbody>
    <tr>
      <td><input type="radio" name="occasionChk" title="아동가 선택"
                 onclick="listChildSelect();" data-usereqstcnt="1"></td>
      <td>아동가</td><td>2025.10.22</td><td>10개월</td>
    </tr>
  </tbody>
</table>
"""

_USEINFO_FRAGMENT = """
<div id="divOccasionTimeSlPL">
  <p>반명
    <select id="clsNm"><option value="">선택</option><option value="1" selected>매송아이</option></select>
    이용시간
    <select id="useHour"><option value="">선택</option><option value="9" selected>9</option></select>
  </p>
  <table id="gridTable">
    <thead><tr><th>날짜/시간</th><th>09</th><th>10</th><th>11</th></tr></thead>
    <tbody>
      <tr><td>2026-09-08(화)</td><td class="cell">2</td><td class="cell">2</td><td class="cell">2</td></tr>
    </tbody>
  </table>
  <button type="button" id="btnAdd" onclick="addRow();">추가</button>
  <table id="slotTable">
    <thead><tr><th>선택</th><th>반명</th><th>이용일</th><th>이용시간</th></tr></thead>
    <tbody id="slotBody"></tbody>
  </table>
  <button type="button" id="btnReserve" onclick="openModal();">예약하기</button>
</div>
"""

_REC_PAGE = """<!doctype html>
<html lang="ko"><head><meta charset="utf-8">
<title>시간제보육 입소신청 (진단 기록 점검용)</title></head>
<body>
<h1>시간제보육 입소신청</h1>
<div id="childbox">불러오는 중...</div>
<div id="useinfo"></div>

<div class="popup_wrap" id="resModal" style="display:none;width:420px;height:200px;">
  <h2>예약</h2>
  <p id="modalText">예약하시겠습니까?</p>
  <button type="button" id="btnOk" onclick="doReserve();">확인</button>
  <button type="button" id="btnCancel" onclick="closeModal();">취소</button>
</div>

<div class="popup_wrap" id="noticeLayer" style="display:none;width:300px;height:120px;">
  <p>안내 레이어</p><button type="button" onclick="closeLayer();">닫기</button>
</div>

<script>
window.__humanClicks = 0;
window.__reserved = false;
document.addEventListener('click', function () { window.__humanClicks++; }, true);

function post(url, done) {
  var x = new XMLHttpRequest();
  x.open('POST', url, true);
  x.setRequestHeader('Content-Type', 'application/x-www-form-urlencoded');
  x.onload = function () { done(x.responseText); };
  x.send('stcode=11650000416&unityYn=N');
}
post('/icms/occasion/SelectOccasionChild.html', function (html) {
  document.getElementById('childbox').innerHTML = html;
});
function listChildSelect() {
  post('/icms/occasion/OccasionTimeMainSlPL.html', function (html) {
    document.getElementById('useinfo').innerHTML = html;
  });
}
function addRow() {
  document.getElementById('slotBody').innerHTML =
    '<tr><td><input type="checkbox"></td><td>매송아이</td>' +
    '<td>2026-09-08(화)</td><td>09 00 - 18 00 (9시간)</td></tr>';
}
function openModal() { document.getElementById('resModal').style.display = 'block'; }
function closeModal() { document.getElementById('resModal').style.display = 'none'; }
function openLayer() { document.getElementById('noticeLayer').style.display = 'block'; }
function closeLayer() { document.getElementById('noticeLayer').style.display = 'none'; }
// 기록 모드가 이 함수에 닿는 일은 절대 없어야 한다.
function doReserve() { window.__reserved = true; }
</script>
</body></html>
"""


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):  # 조용히
        pass

    def _send(self, body: bytes, ctype: str) -> None:
        self.send_response(200)          # Date 헤더가 여기서 자동으로 붙는다
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def do_HEAD(self):
        self._send(b"", "text/html; charset=UTF-8")

    def do_GET(self):
        # 진단 기록 모드 검증용 화면. 사람이 버튼을 누르면 ajax 로 이용정보
        # 화면을 받아 그려넣는다(실제 사이트가 하는 것과 같은 모양).
        if self.path.split("?")[0] == "/rec":
            return self._send(_REC_PAGE.encode("utf-8"), "text/html; charset=UTF-8")
        self._send(b"<html><body>fixture</body></html>", "text/html; charset=UTF-8")

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length).decode("utf-8", "replace") if length else ""
        path = self.path.split("?")[0]

        if path.endswith("NurseryMapSidoList.html"):
            return self._send(_read("sido.json"), "application/json; charset=UTF-8")
        if path.endswith("NurseryMapGuGunList.html"):
            return self._send(_read("gugun_11000.json"),
                              "application/json; charset=UTF-8")
        if path.endswith("TmpCareSlLAjax.html"):
            unity = "Y" if "unityYn=Y" in raw else "N"
            return self._send(_read(f"centers_11650_{unity}.html"),
                              "text/html; charset=UTF-8")
        if path.endswith("TmpCareOperView.html"):
            return self._send("<div>운영사항</div>".encode(),
                              "text/html; charset=UTF-8")
        if path.endswith("SelectOccasionChild.html"):
            return self._send(_CHILD_FRAGMENT.encode("utf-8"),
                              "text/html; charset=UTF-8")
        if path.endswith("OccasionTimeMainSlPL.html"):
            return self._send(_USEINFO_FRAGMENT.encode("utf-8"),
                              "text/html; charset=UTF-8")
        return self._send(b"{}", "application/json; charset=UTF-8")


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 18642
    # ThreadingHTTPServer 여야 한다. 단일 스레드면 keep-alive 연결 하나가
    # 서버를 붙잡아, 두 번째 연결(주기적 시각 재측정)이 통째로 굶는다.
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
