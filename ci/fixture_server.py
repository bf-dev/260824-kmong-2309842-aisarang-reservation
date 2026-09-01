# -*- coding: utf-8 -*-
"""녹화된 아이사랑 응답을 되먹이는 로컬 서버 (우리 CI 전용).

GitHub Actions 러너에서는 childcare.go.kr 로 나가는 연결이 막힌다(러너 IP 대역
문제이고 고객 PC 와는 무관하다). 그래도 프로즌 exe 의 전체 경로
(Date 헤더 기반 서버시각 동기화 → 기관 목록 파싱 → 진단 업로드)는 진짜 Windows
에서 진짜로 돌려봐야 한다. 그래서 실제 사이트에서 받아 저장해 둔 응답을
그대로 돌려준다.

http.server 는 응답마다 RFC 형식의 Date 헤더를 스스로 붙이므로 시각 동기화
경로도 흉내가 아니라 진짜로 동작한다.

v1.0.10 부터는 진짜 사이트가 붙이는 **밀리초 서버시각 쿠키**도 같이 붙인다.

    Set-Cookie: egovLatestServerTime=<epoch ms>; path=/; secure;SameSite=None;Secure;

실측(2026-09-01, childcare.go.kr HEAD)이 이 모양이고, 이제 clock.sync 가
Date 헤더가 아니라 이 값을 쓴다. 여기서 안 붙이면 프로즌 exe 검증이 **출하되는
경로가 아니라 예전 폴백 경로**를 돌게 된다. 그러면 확인한 것이 확인한 게 아니다.
"""
from __future__ import annotations

import os
import sys
import time
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
# 2026-08-25 갱신: 아래 두 조각은 원래 고객 화면녹화를 보고 우리가 복원한
# 것이었다(#clsNm / #useHour / #gridTable / #btnAdd / #slotTable / #btnReserve).
# 실물 캡처가 들어온 지금은 그 이름들이 **전부 틀렸다**는 것이 확인됐다.
# 우리 코드에 유리하게 생긴 픽스처는 통과해도 아무것도 증명하지 못하므로
# 실제 응답의 id/class/구조로 갈아끼웠다.
# 실물 원본은 ci/fixtures/real/ 에 그대로 들어 있다.
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

# 실물 마크업 그대로. OccasionTimeMainSlPL.html 응답에서 옮겼다.
#   반명   <select name="clname" id="clname" onchange="fnSerChange();">
#   이용시간 <select name="rtm" id="rtm" onchange="fnTimeReset();">  값 1~9
#   표     #crtminfo > table,  행머리 th#day_N + input[name=resdt],
#          칸 <a class="time-option" id="tm_<시각>_<행>">  안에 <i class="count">
#          같은 tr 끝에 화면에 안 보이는 td#pp_N / td#bm_N / td#nsc_N
#   추가   <a id="timecareTableAddBtn" onclick="f_AddQualRow();">추가</a>
#   선택표 <table id="INFOQUALF">, 행 tr#tId_N,
#          체크박스 input#rowSchChkNoN[name=rowQualChkNo],
#          내용은 글자가 아니라 input value 에 들어 있다
#   예약하기 <a id="timecareConfirm" onclick="fnSave();">예약하기</a>
_USEINFO_FRAGMENT = """
<div id="divOccasionTimeSlPL">
  <form name="sfrm" method="post">
  <table>
    <tbody>
      <tr><th scope="row">반명 <i class="required">*</i></th>
        <td><select class="selectbox" name="clname" id="clname"
                    onchange="fnSerChange();" title="반명 선택">
          <option value="">선택</option>
          <option value="1" selected>매송아이</option>
        </select></td></tr>
      <tr><th scope="row">이용시간 <i class="required">*</i></th>
        <td><select class="selectbox" name="rtm" id="rtm"
                    onchange="fnTimeReset();" title="이용시간 선택">
          <option value="">선택</option>
          <option value="1">1</option><option value="2">2</option>
          <option value="3">3</option><option value="4">4</option>
          <option value="5">5</option><option value="6">6</option>
          <option value="7">7</option><option value="8">8</option>
          <option value="9" selected>9</option>
        </select></td></tr>
    </tbody>
  </table>

  <div id="crtminfo" class="board boardlist sticky_th t_center">
    <table>
      <caption>예약상태 날짜와 시간에 대한 내용의 테이블</caption>
      <thead><tr><th scope="col">날짜/시간</th>
        <th scope="col">09</th><th scope="col">10</th><th scope="col">11</th></tr></thead>
      <tbody>
        <tr>
          <th id="day_0" class="table_tit1" scope="row">2026-09-08(화)<input
              type="hidden" name="resdt" id="resdt" value="20260908"></th>
          <td><a href="javascript:;" class="time-option" id="tm_9_0"
                 onclick="selectDay2(this,'9',0);"><i class="count" title="이용가능">2</i></a></td>
          <td><a href="javascript:;" class="time-option" id="tm_10_0"
                 onclick="selectDay2(this,'10',0);"><i class="count" title="이용가능">2</i></a></td>
          <td><a href="javascript:;" class="time-option" id="tm_11_0"
                 onclick="selectDay2(this,'11',0);"><i class="count" title="이용가능">2</i></a></td>
          <td id="pp_0" style="display: none;">2</td>
          <td id="bm_0" style="display: none;">10</td>
          <td id="nsc_0" style="display: none;">0</td>
        </tr>
      </tbody>
    </table>
  </div>

  <div class="btn_right">
    <a href="javascript:;" id="timecareTableAddBtn" class="btn h50"
       onclick="f_AddQualRow();">추가</a>
    <a href="javascript:;" id="timecareTableCancelBtn" class="btn gray h50"
       onclick="f_DelQualRow();">삭제</a>
  </div>

  <table id="INFOQUALF">
    <caption>시간제보육사업 이용일, 이용시간 예약하기 내용의 테이블</caption>
    <thead><tr><th scope="col">선택</th><th scope="col">반명</th>
      <th scope="col">이용일</th><th scope="col">이용시간</th></tr></thead>
    <tbody></tbody>
  </table>

  <div class="btn_right">
    <a href="javascript:;" class="btn h50" id="timecareConfirm"
       onclick="openModal();">예약하기</a>
    <a href="javascript:;" class="btn lightgray h50" id="tooltip"
       data-rel="pop_bb" pop-href="#pop-up-tt01">예약대기</a>
  </div>
  </form>
</div>
"""

# 확인창은 실물 껍데기를 그대로 쓴다. 사이트는 icmsLayerPopup.confirm2 를
# 쓰고, 그 껍데기가 페이지에 **두 벌** 들어 있다(하나만 열린다). 그리고
# id="layer-confirm-popup-close2" 는 한 껍데기 안에서도 두 번 나온다.
# 우리 선택자가 '보이는 쪽' 을 고르는지 여기서 같이 확인된다.
_CONFIRM_SHELL = """
<div class="popup_wrap s_size wp400 type-confirm2" id="layer-confirm-popup2"
     style="display:none;width:420px;height:200px;">
  <div class="popup_inner_wrap maxw525" tabindex="0">
    <a href="javascript:void(0)" class="popup_close" role="button"
       id="layer-confirm-popup-close2" title="닫기"><span class="hidden">닫기</span></a>
    <h5 id="layer-confirm-popup-title2">예약</h5>
    <section class="mt30 pl30 pr30">
      <p class="f_18" id="layer-confirm-popup-contents2"></p>
      <div class="btn_group">
        <a href="#none" class="btn" id="layer-confirm-popup-confirm2"
           onclick="doReserve();">확인</a>
        <a href="#none" class="btn gray" id="layer-confirm-popup-close2"
           onclick="closeModal();">취소</a>
      </div>
    </section>
  </div>
</div>
"""

_REC_PAGE = """<!doctype html>
<html lang="ko"><head><meta charset="utf-8">
<title>시간제보육 입소신청 (진단 기록 점검용)</title>
<style>.popup_wrap { display: none; }</style></head>
<body>
<h1>시간제보육 입소신청</h1>
<div id="childbox">불러오는 중...</div>
<div id="useinfo"></div>

""" + _CONFIRM_SHELL + """
<!-- 숨어 있는 두 번째 사본. 실물 페이지와 같은 상황을 만든다. -->
""" + _CONFIRM_SHELL.replace('style="display:none;width:420px;height:200px;"', '') + """

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
// 실물 f_AddQualRow 와 같은 모양으로 행을 만든다: 내용은 글자가 아니라
// input 의 value 에 들어간다. 이게 선택표를 읽는 코드의 진짜 난이도다.
function addRow() {
  var tb = document.getElementById('INFOQUALF').getElementsByTagName('TBODY')[0];
  if (tb.getElementsByTagName('TR').length) { return; }
  tb.innerHTML =
    '<tr id="tId_0">' +
    '<td><input type="checkbox" id="rowSchChkNo0" name="rowQualChkNo" class="chkHd">' +
    '<label for="rowSchChkNo0" class="checkbox"><span></span></label></td>' +
    '<td><input name="resclname0" type="text" id="resclname0" value="매송아이" ' +
    'class="uin" readonly="readonly" title="반명0">' +
    '<input name="resclseq0" type="hidden" value="1" id="resclseq0"></td>' +
    '<td><input name="sdate0" type="text" id="sdate0" value="2026-09-08(화)" ' +
    'class="uin" readonly="readonly" title="이용일0">' +
    '<input name="resdt0" type="hidden" id="resdt0" value="20260908"></td>' +
    '<td><input name="restime0" type="text" id="restime0" ' +
    'value="09 : 00  ~  18 : 00  (9시간)" class="uin" readonly="readonly" title="이용시간0">' +
    '<input name="resbgntm0" type="hidden" value="09 : 00" id="resbgntm0">' +
    '<input name="resendtm0" type="hidden" value="18 : 00" id="resendtm0">' +
    '<input name="rtm0" type="hidden" value="9" id="rtm0"></td></tr>';
}
// 실물 selectDay2 처럼 고른 칸에 class "on" 과 title="선택됨" 을 붙인다.
function selectDay2(obj, num, row) {
  var a = document.getElementById('tm_' + num + '_' + row);
  if (!a) { return; }
  a.className = 'time-option on';
  a.setAttribute('title', '선택됨');
  var i = a.querySelector('i.count');
  if (i) { i.className = 'count on'; }
}
function f_AddQualRow() { addRow(); }
function openModal() {
  // 실물 insertOcreqst 처럼 confirm2 를 띄운다. 60시간 초과 안내가 붙는
  // 경우까지 같은 문구로 재현한다.
  var shells = document.querySelectorAll("[id='layer-confirm-popup2']");
  var ps = shells[0].querySelectorAll("[id='layer-confirm-popup-contents2']");
  ps[0].innerHTML = '월 이용 시간이 60시간을 초과할 경우 바우처 지원이 불가합니다.' +
                    ' ※ 시간당 5,000원으로 이용<br>9월 현재 예약 시간 포함하여' +
                    ' 60시간을 초과합니다.<br>예약하시겠습니까?';
  shells[0].style.display = 'block';
}
function fnSave() { openModal(); }
function closeModal() {
  var shells = document.querySelectorAll("[id='layer-confirm-popup2']");
  shells[0].style.display = 'none';
}
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
        # 진짜 사이트(eGovFrame)가 붙이는 밀리초 서버시각. 위 머리말 참고.
        # 요청이 들어온 순간을 찍는다는 점까지 같게 맞춘다.
        self.send_header(
            "Set-Cookie",
            f"egovLatestServerTime={int(time.time() * 1000)}; "
            f"path=/; secure;SameSite=None;Secure;")
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
