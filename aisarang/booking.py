# -*- coding: utf-8 -*-
"""시간제보육 예약 화면의 실제 조작 순서 (4·5단계).

이 파일의 근거는 추측이 아니라 **고객이 자기 인증서 세션을 직접 화면녹화해서
보내준 영상**이다 (2026-08-25, 51초, 프레임 증거: docs/site-map/recording/).
그 영상에서 읽어낸 순서를 그대로 코드로 옮겼다:

  1. 시간제보육신청 검색 화면
       구분 라디오(독립반/통합반) → 지역(시/도 + 시/군/구 2단 선택) → 조회
  2. 결과 목록에서 센터의 [시간제보육 예약] 버튼
  3. "시간제보육 아동 선택": 아동 라디오 하나를 고르고 진행
  4. 센터 상세: 이용기관명 / 예약 가능일(2주 범위) / 반명(select) /
     이용시간(select, 1~9시간)
  5. 날짜×시간 표: 행 = 2026-09-02(수) ~ 2026-09-08(화), 열 = 09,10,...,18
     칸 값 = 남은 정원 숫자, 또는 X(이용불가). 숫자 칸을 클릭하면
     이용시간만큼 연속된 칸이 선택 표시된다.
  6. [추가] → 아래 선택표에 행이 생긴다 (선택 / 반명 / 이용일 / 이용시간)
  7. 그 행의 체크박스를 켠다
  8. [예약하기] → "예약" 모달이 뜬다 (월 60시간 안내 + "예약하시겠습니까?")
  9. 모달의 [확인] → **이때 비로소 예약이 전송된다**

핵심 타이밍 (고객 진술, 2026-08-25):
  이용일 자체는 자정에 목록에 나타나지만 **예약이 되는 것은 09:00 정각**이다.
  그래서 고객은 9시 전에 8단계까지 다 해두고 모달을 열어둔 채 기다리다가,
  정각에 [확인] 한 번만 누른다. 실패는 언제나 그 한 번의 클릭이 조금 늦거나
  조금 이른 것이었다.

  → 그래서 이 모듈은 준비(1~8단계)와 발사(9단계)를 분리한다.
    준비는 여유 있게 끝내고, 모달을 붙잡은 채로 대기하다가,
    [확인] 요청만 서버 09:00:00 에 '도착'하도록 쏜다.

서버가 돌려주는 두 문구 (고객 진술, 2026-08-25):
  "예약시간전"  → 너무 일렀다. 자리는 아직 살아 있으므로 즉시 재시도한다.
  "정원초과"    → 그 칸은 이미 나갔다. 두들겨봐야 소용없으니 멈추고 보고한다.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

# ---------------------------------------------------------------- 결과 분류

# 근거의 등급이 다르다는 것을 분명히 해 둔다.
#
#   [고객 진술만] "예약시간전" / "정원초과"
#       고객이 글로 적어준 두 단어다. 2026-08-25 고객 진단 캡처
#       (요청 373건, 페이지 14장)를 전부 뒤졌지만 **한 건도 없다**.
#       고객이 확인창에서 멈춰 InsertOcreqst.html 이 호출된 적이 없기
#       때문이다. 아직 서버 실물로 확인되지 않았으므로 표기 흔들림을
#       넓게 열어 둔다.
#
#   [실물 확인] NOT_BOOKABLE_WORDS 는 OccasionTimeMainSlPL.html 응답의
#       사이트 자바스크립트에서 그대로 옮긴 문구다.
TOO_EARLY_WORDS = ("예약시간전", "예약 시간 전", "예약시간 전",
                   "예약시간이 아닙니다",
                   "아직 예약", "예약시작", "예약이 시작되지")

FULL_WORDS = ("정원초과", "정원 초과", "정원이 초과", "정원이 마감",
              "마감되었습니다", "잔여 정원", "정원이 없습니다")

OK_WORDS = ("예약이 완료", "신청이 완료", "정상적으로 신청", "정상적으로 예약",
            "예약되었습니다", "신청되었습니다", "완료되었습니다")

# 실측: 사이트가 클릭 시점에 스스로 막는 문구들. '아직 안 열렸다' 가 아니라
# '이 칸은 안 된다' 이므로 **다시 쏴봐야 소용없다**. 예전에는 이 중
# "예약 가능 시간이 아닙니다" 가 TOO_EARLY 에 들어 있어서, 영영 열리지 않을
# 칸에 대고 정각의 남은 시간을 전부 태우는 경로였다.
#
#   selectDay2()     칸 값이 "X" -> "예약 가능 시간이 아닙니다."
#   f_AddQualRow()   예약대기만 되는 칸(값 "0") -> 같은 문구
#   fnCompare()      -> "이용시간이 중복되었습니다."
#   SelectDupleTime  -> "해당 아동은 이미 예약되어 있습니다."
#   selectDay2()     -> "해당월의 벌점이 초과하여 예약하실 수 없습니다."
#                       "결제요청 후 3일 경과한 경우 예약이 불가능합니다."
#                       "점심시간(12:00~13:00)만 예약은 불가능합니다."
#   fnSetCl()        -> "해당 아동으로 신청 할 수 있는 반이 없습니다."
NOT_BOOKABLE_WORDS = (
    # 실물 그대로. '가능' 이 들어간 이 형태만 사이트가 쓴다.
    # "예약시간이 아닙니다"(가능 없음)는 우리가 넓혀둔 추정형이고
    # '아직 …' 뉘앙스라 TOO_EARLY 쪽에 남겨 둔다. 두 문자열은 서로
    # 부분일치하지 않으므로 섞이지 않는다.
    "예약 가능 시간이 아닙니다", "예약가능시간이 아닙니다",
    "해당월의 벌점이 초과",
    "결제요청 후 3일",
    "점심시간", "단독 예약은 불가",
    "이용시간이 중복",
    "이미 예약되어 있습니다",
    "신청 할 수 있는 반이 없습니다",
    "개월 미만 아동만",
)

# 확인창은 '결과' 가 아니라 '질문' 이다.
# 실측 본문: "월 이용 시간이 60시간을 초과할 경우 바우처 지원이 불가합니다.
#             ※ 시간당 5,000원으로 이용
#             8월 현재 예약 시간 포함하여 60시간을 초과합니다.
#             예약하시겠습니까?"
# 여기에 '불가' 와 '초과합니다' 가 둘 다 들어 있다. 예전 FAIL_WORDS 에 그
# 두 조각이 있었으므로, 확인창이 아직 화면에 있는 동안 read_outcome 이 돌면
# **성공한 예약을 '실패' 로 보고**할 수 있었다.
QUESTION_WORDS = ("하시겠습니까",)

FAIL_WORDS = ("이미 신청", "이미 예약", "중복", "실패", "오류가 발생",
              "처리중입니다")

# 결과 코드
R_OK = "ok"
R_TOO_EARLY = "too_early"
R_FULL = "full"
R_FAIL = "fail"
R_NOT_BOOKABLE = "not_bookable"
R_UNKNOWN = "unknown"


def classify(text: str) -> str:
    """서버/화면 문구를 결과 코드로 바꾼다.

    순서가 중요하다.
      0. **질문은 결과가 아니다.** 확인창 본문이 결과로 분류되면 안 된다.
      1. 완료 문구가 있으면 그것이 최종이다.
      2. '정원초과' 안에 '초과' 가 있으므로 일반 실패보다 먼저 본다.
      3. 사이트가 스스로 막는 문구는 재시도 대상이 아니다(R_NOT_BOOKABLE).
      4. '예약시간전' 만 재시도 대상이다.
    """
    t = (text or "").replace(" ", " ")
    if not t.strip():
        return R_UNKNOWN
    for w in OK_WORDS:
        if w in t:
            return R_OK
    for w in QUESTION_WORDS:
        if w in t:
            return R_UNKNOWN
    for w in FULL_WORDS:
        if w in t:
            return R_FULL
    for w in NOT_BOOKABLE_WORDS:
        if w in t:
            return R_NOT_BOOKABLE
    for w in TOO_EARLY_WORDS:
        if w in t:
            return R_TOO_EARLY
    for w in FAIL_WORDS:
        if w in t:
            return R_FAIL
    return R_UNKNOWN


def result_is_retryable(code: str) -> bool:
    """다시 쏘는 게 의미 있는 결과인가. '예약시간전' 만 그렇다.

    '예약 가능 시간이 아닙니다'(R_NOT_BOOKABLE)는 사이트가 그 칸 자체를
    거절한 것이라, 다시 쏘면 정각의 남은 시간을 그냥 태운다.
    """
    return code == R_TOO_EARLY


# ---------------------------------------------------------------- 자료구조

@dataclass
class Cell:
    date: str            # YYYYMMDD
    hour: int            # 9 ~ 17 (실측 헤더는 09~17)
    text: str            # 화면에 적힌 그대로 ("0", "1", "X")
    capacity: int | None  # 숫자면 남은 인원, X 면 None
    row: int
    col: int
    el_id: str = ""      # 실물 <a> 의 id: "tm_<시각>_<행>"

    @property
    def blocked(self) -> bool:
        return self.capacity is None

    @property
    def available(self) -> bool:
        """진짜로 예약이 되는 칸인가.

        0 은 '자리 없음' 이 아니라 **예약대기만 가능** 이다. 사이트의
        selectDay2 를 보면 칸 값이 "0" 일 때 wait_gb 를 Y 로 두고
        resbgntm/resendtm 을 비운다. 그 상태로 [추가] 를 누르면
        f_AddQualRow 가 reswaitdt 를 보고 "예약 가능 시간이 아닙니다" 로
        막는다. 그래서 0 은 우리에게도 누를 수 없는 칸이다. (실측 확인)
        """
        return self.capacity is not None and self.capacity > 0

    def why(self) -> str:
        if self.blocked:
            return "이용불가(X)"
        if self.capacity == 0:
            return "남은 자리 0명"
        return f"남은 자리 {self.capacity}명"


@dataclass
class Grid:
    rows: list = field(default_factory=list)       # [{date,label,row}]
    cells: list = field(default_factory=list)      # [Cell]
    headers: list = field(default_factory=list)
    table_index: int = -1

    def find(self, date: str, hour: int) -> Cell | None:
        for c in self.cells:
            if c.date == date and c.hour == hour:
                return c
        return None

    def row_cells(self, date: str) -> list:
        return sorted([c for c in self.cells if c.date == date], key=lambda c: c.hour)

    def has_date(self, date: str) -> bool:
        return any(r.get("date") == date for r in self.rows)

    def summary(self, date: str) -> str:
        cells = self.row_cells(date)
        if not cells:
            return f"{date}: 표에 없음"
        return f"{date}: " + " ".join(f"{c.hour:02d}={c.text}" for c in cells)


@dataclass
class Prepared:
    """9단계(확인) 직전까지 만들어진 상태. 이게 다 참이어야 발사한다."""
    center: dict = field(default_factory=dict)
    target_date: str = ""
    start_hour: int = 0
    hours: int = 0
    class_name: str = ""
    child_name: str = ""
    cell_text: str = ""
    cell_capacity: int | None = None
    cell_selected: bool = False
    row_index: int = -1
    row_text: str = ""
    row_ticked: bool = False
    modal_open: bool = False
    modal_text: str = ""
    armed: bool = False
    grid_summary: str = ""

    def ready(self) -> bool:
        """안전 불변식. 하나라도 거짓이면 [확인] 을 누르지 않는다."""
        return bool(self.cell_selected and self.row_ticked
                    and self.modal_open and self.armed)

    def blockers(self) -> list:
        out = []
        if not self.cell_selected:
            out.append("날짜 칸이 선택되지 않았습니다")
        if not self.row_ticked:
            out.append("선택표의 행이 체크되지 않았습니다")
        if not self.modal_open:
            out.append("예약 확인창이 열려 있지 않습니다")
        if not self.armed:
            out.append("확인 버튼을 찾지 못했습니다")
        return out

    def as_meta(self) -> dict:
        return {
            "targetDate": self.target_date,
            "startHour": self.start_hour,
            "hours": self.hours,
            "class": self.class_name,
            "child": self.child_name,
            "cellText": self.cell_text,
            "cellCapacity": self.cell_capacity,
            "cellSelected": self.cell_selected,
            "rowTicked": self.row_ticked,
            "rowText": self.row_text,
            "modalOpen": self.modal_open,
            "modalText": (self.modal_text or "")[:400],
            "grid": self.grid_summary,
        }


# ---------------------------------------------------------------- JS 조각
#
# 2026-08-25 이전에는 선택자를 하나도 하드코딩하지 않았다. 녹화가 흐려서
# id/class 를 읽을 수 없었고, 서버가 인증서 세션에만 그려주는 화면이라
# 우리가 직접 볼 수도 없었다. 그래서 "표의 첫 칸이 날짜인 표", "체크박스가
# 있는 표", "보이는 버튼의 글자" 같은 구조와 글자로 찾았다.
#
# 2026-08-25, 고객이 자기 PC 에서 진짜 공동인증서 세션으로 진단 기록 모드를
# 돌리고 예약 흐름을 손으로 끝까지 걸었다. 그 캡처 안에
# /icms/occasion/OccasionTimeMainSlPL.html 응답과 4~9단계 화면이 통째로 있다.
# 이제 **실물 id 를 1순위로 쓰고**, 사이트가 바뀌었을 때를 대비해 예전의
# 구조 추론을 2순위로 남긴다. 둘 다 실패하면 아무것도 누르지 않는다.
#
# 실측된 마크업(그대로 옮김):
#   <th id="day_0" class="table_tit1" scope="row">2026-08-26(수)
#       <input type="hidden" name="resdt" id="resdt" value="20260826"></th>
#   <td><a href="javascript:;" class="time-option" id="tm_9_0"
#          onclick="selectDay2(this,'9',0);"><i class="count" title="이용가능">1</i></a></td>
#   고른 뒤: class="time-option on" title="선택됨", 안쪽 <i class="count on">
#   이용불가: <i class="count not" title="이용불가능">X</i>

_JS_SCAN_GRID = r"""
function txt(e){ return ((e.innerText || e.textContent || '').replace(/\s+/g,' ')).trim(); }
function vis(e){
  if (!e) return false;
  var r = e.getBoundingClientRect();
  if (r.width <= 0 || r.height <= 0) return false;
  var s = window.getComputedStyle(e);
  return s.visibility !== 'hidden' && s.display !== 'none';
}

// ---- 1순위: 실물 마크업 (#crtminfo 안의 표, th#day_N + a.time-option#tm_H_R)
function realGrid() {
  var box = document.getElementById('crtminfo');
  if (!box) return null;
  var tb = box.querySelector('table');
  if (!tb || !vis(tb)) return null;
  var all = document.querySelectorAll('table');
  var tableIndex = -1;
  for (var i = 0; i < all.length; i++) if (all[i] === tb) { tableIndex = i; break; }

  var headers = [];
  var hc = tb.querySelectorAll('thead th');
  for (var i = 0; i < hc.length; i++) headers.push(txt(hc[i]));

  var trs = tb.querySelectorAll('tr');
  var rows = [], cells = [];
  for (var r = 0; r < trs.length; r++) {
    var head = trs[r].querySelector('th[id^=day_]');
    if (!head) continue;
    // 날짜의 정답은 화면 글자가 아니라 숨은 input 이다. 사이트가 폼에
    // 실어 보내는 값이 이것이고 형식이 YYYYMMDD 로 고정이다.
    var hid = head.querySelector('input[name=resdt]');
    var label = txt(head);
    var date = '';
    if (hid && /^\d{8}$/.test(hid.value || '')) {
      date = hid.value;
    } else {
      var m = label.match(/(20\d\d)\D?(\d{2})\D?(\d{2})/);
      if (!m) continue;
      date = m[1] + m[2] + m[3];
    }
    rows.push({date: date, label: label, row: r});

    // 칸은 '그 줄의 모든 td' 가 아니라 **a[id^=tm_] 이 있는 td 만** 센다.
    // 같은 tr 안에 화면에 안 보이는 td#pp_N(벌점) / td#bm_N(개월수) /
    // td#nsc_N 이 붙어 있다. 그 안의 숫자("2","10")를 잔여 인원으로 읽으면
    // 있지도 않은 18/19/20시가 '자리 있음' 으로 잡힌다. 실측에서 실제로
    // 126칸이어야 할 표가 168칸으로 읽혔다.
    var cs = trs[r].querySelectorAll('th,td');
    for (var c = 0; c < cs.length; c++) {
      if (cs[c].tagName !== 'TD') continue;
      var a = cs[c].querySelector('a[id^=tm_]');
      if (!a) continue;
      if (!vis(cs[c])) continue;
      // 시각의 정답도 헤더 글자가 아니라 a 의 id 다: tm_<시각>_<행>.
      // 헤더는 '09' 로 0을 채우지만 id 는 'tm_9_0' 으로 채우지 않는다.
      var im = (a.id || '').match(/^tm_(\d{1,2})_(\d+)$/);
      var hour;
      if (im) {
        hour = parseInt(im[1], 10);
      } else {
        var hcell = headers[c] !== undefined ? headers[c] : '';
        var hm2 = hcell.match(/(\d{1,2})/);
        if (!hm2) continue;
        hour = parseInt(hm2[1], 10);
      }
      var mark = a.querySelector('i.count');
      cells.push({date: date, hour: hour, text: txt(mark || a),
                  row: r, col: c, id: a.id || ''});
    }
  }
  if (!rows.length || !cells.length) return null;
  return {tableIndex: tableIndex, headers: headers, rows: rows, cells: cells,
          how: 'crtminfo'};
}

var real = realGrid();
if (real) return real;

// ---- 2순위: 예전의 구조 추론. 사이트가 통째로 바뀌었을 때만 여기로 온다.
var tables = document.querySelectorAll('table');
for (var t = 0; t < tables.length; t++) {
  var tb = tables[t];
  if (!vis(tb)) continue;
  var trs = tb.querySelectorAll('tr');
  var headers = [];
  if (trs.length) {
    var hc = trs[0].querySelectorAll('th,td');
    for (var i = 0; i < hc.length; i++) headers.push(txt(hc[i]));
  }
  var rows = [], cells = [];
  for (var r = 0; r < trs.length; r++) {
    var cs = trs[r].querySelectorAll('th,td');
    if (cs.length < 2) continue;
    var first = txt(cs[0]);
    var m = first.match(/(20\d\d)\D?(\d{2})\D?(\d{2})/);
    if (!m) continue;
    var date = m[1] + m[2] + m[3];
    rows.push({date: date, label: first, row: r});
    for (var c = 1; c < cs.length; c++) {
      if (!vis(cs[c])) continue;          // 숨은 열은 시간대가 아니다
      var head = headers[c] !== undefined ? headers[c] : '';
      var hm = head.match(/(\d{1,2})/);
      if (!hm) continue;                  // 시각을 8+열번호로 날조하지 않는다
      cells.push({date: date, hour: parseInt(hm[1], 10),
                  text: txt(cs[c]), row: r, col: c, id: ''});
    }
  }
  if (rows.length && cells.length) {
    return {tableIndex: t, headers: headers, rows: rows, cells: cells,
            how: 'structural'};
  }
}
return null;
"""

# 칸의 '선택됨' 표시. 실측: 고른 칸은 a 에 class "on" 과 title="선택됨" 이
# 붙고 안쪽 <i class="count"> 에도 "on" 이 붙는다. 그 이름을 직접 보되,
# 사이트가 표시 방법을 바꿨을 때를 대비해 예전처럼 클릭 전후의 지문
# (class/배경색/checked)도 같이 기록해서 비교한다.
_JS_CELL_MARKS = r"""
var t = document.querySelectorAll('table')[arguments[0]];
if (!t) return null;
var out = [];
var trs = t.querySelectorAll('tr');
for (var r = 0; r < trs.length; r++) {
  var cs = trs[r].querySelectorAll('th,td');
  for (var c = 0; c < cs.length; c++) {
    var e = cs[c];
    var st = window.getComputedStyle(e);
    var inner = e.querySelector('a[id^=tm_]') ||
                e.querySelector('a,button,span,div,input');
    var ist = inner ? window.getComputedStyle(inner) : null;
    out.push(r + ':' + c + '|' + (e.className || '') + '|' + st.backgroundColor +
             '|' + (inner ? (inner.className || '') : '') +
             '|' + (ist ? ist.backgroundColor : '') +
             '|' + (e.getAttribute('aria-selected') || '') +
             '|' + (inner && inner.checked ? '1' : '0') +
             '|' + (inner ? (inner.getAttribute('title') || '') : ''));
  }
}
return out;
"""

# 누를 대상은 <a class="time-option" id="tm_H_R"> 다. 사이트의 onclick
# (selectDay2)이 그 a 에 달려 있다. 예전에는 칸 안의 아무 a/button/span 이나
# 눌렀는데, 실측 마크업에서는 a 안에 <i class="count"> 가 들어 있어서
# span 류를 먼저 집으면 엉뚱한 것을 누를 수 있다.
_JS_CLICK_CELL = r"""
var t = document.querySelectorAll('table')[arguments[0]];
if (!t) return false;
var trs = t.querySelectorAll('tr');
if (arguments[1] >= trs.length) return false;
var cs = trs[arguments[1]].querySelectorAll('th,td');
if (arguments[2] >= cs.length) return false;
var cell = cs[arguments[2]];
var wantId = arguments[3] || '';
var target = null;
if (wantId) {
  var byId = cell.querySelector("a[id='" + wantId + "']");
  if (byId) target = byId;
}
if (!target) target = cell.querySelector('a[id^=tm_]');
if (!target) target = cell.querySelector('a,button,input,label,span');
if (!target) target = cell;
// 화면에 안 보이는 칸은 누르지 않는다(숨은 벌점/개월 열 방어).
var r = target.getBoundingClientRect();
if (r.width <= 0 || r.height <= 0) return false;
try { target.scrollIntoView({block: 'center'}); } catch (e) {}
target.click();
return true;
"""

# 그 칸이 실제로 '선택됨' 이 되었는지, 사이트의 진짜 표시로 확인한다.
_JS_CELL_IS_ON = r"""
var id = arguments[0];
if (!id) return null;
var a = document.getElementById(id);
if (!a) return null;
var cls = ' ' + (a.className || '') + ' ';
return {on: cls.indexOf(' on ') >= 0,
        title: a.getAttribute('title') || '',
        innerOn: !!a.querySelector('i.count.on')};
"""

# 선택표(선택/반명/이용일/이용시간). 주의: **아동 선택 표에도 라디오가 있고,
# 그 행에는 생년월일이 들어 있다** (실제 마크업: "박승우 2025.10.22 10개월").
#
# v1.0.5 의 점수식은 `dated * 10 + boxes * 3` 이었다. 아동 표의 생년월일이
# 날짜 정규식을 그대로 통과하기 때문에, 진짜 선택표가 아직 안 그려진 화면에서는
# **아동 표가 이긴다**(고객 진단 캡처로 재현했다). 그러면 tick_slot_row 가
# 아동 라디오를 켜놓고 "선택표 행을 체크했습니다" 라고 남기고,
# slot_row_is_ticked 도 참을 돌려주어 open_modal 의 안전장치까지 통과한다.
#
# 그래서 판정을 날짜 하나에 걸지 않는다.
#   · 아동 표는 **배제**한다: 캡션/머리글에 아동명·생년월일·개월수가 있거나,
#     행에 "N개월" 만 있고 이용시간 구간이 없으면 선택표가 아니다.
#   · 선택표의 특징은 **체크박스 + 이용시간 구간**("09 00 - 18 00 (9시간)") 이다.
#
# 2026-08-25 실측으로 하나가 더 드러났다. 선택표 칸의 내용은 **글자가 아니라
# input 의 value** 다:
#   <td><input id="sdate0" value="2026-08-28(금)" readonly>
#       <input type="hidden" id="resdt0" value="20260828"></td>
#   <td><input id="restime0" value="09 : 00  ~  10 : 00  (1시간)" readonly> ...
# innerText/textContent 는 input 의 값을 포함하지 않으므로 예전 코드에서는
# 이 행이 통째로 빈 문자열("   ")로 읽혔다. 그 결과 date 가 늘 비어서
# tick_slot_row 가 날짜로 행을 찾지 못하고 매번 rows[-1] 폴백으로 떨어졌고,
# 안전장치에 남는 row_text 도 비어 있었다. 이제 value 를 같이 읽는다.
_JS_SCAN_SLOT_ROWS = r"""
function txt(e){ return ((e.innerText || e.textContent || '').replace(/\s+/g,' ')).trim(); }
// 칸의 글자 + 그 안 input 들의 value 를 합쳐서 읽는다.
function cellText(e){
  var parts = [];
  var t = txt(e);
  if (t) parts.push(t);
  var ins = e.querySelectorAll('input');
  for (var i = 0; i < ins.length; i++) {
    var ty = (ins[i].type || '').toLowerCase();
    if (ty === 'checkbox' || ty === 'radio' || ty === 'button') continue;
    var v = (ins[i].value || '').replace(/\s+/g, ' ').trim();
    if (v && parts.indexOf(v) < 0) parts.push(v);
  }
  return parts.join(' ');
}
var RE_DATE = /(20\d\d)\D?(\d{2})\D?(\d{2})/;
var RE_MONTHS = /\d+\s*개\s*월/;
var RE_SPAN = /\d{1,2}\s*[:시]?\s*\d{2}\s*[-~]\s*\d{1,2}\s*[:시]?\s*\d{2}|\d+\s*시간/;
var CHILDISH = /아동\s*명|생년월일|개월수|아동\s*선택/;
var SLOTTISH = /이용일|이용\s*시간|반명/;
var tables = document.querySelectorAll('table');

function readRows(tb) {
  var trs = tb.querySelectorAll('tr');
  var rows = [], dated = 0, boxes = 0, spans = 0, months = 0;
  for (var r = 0; r < trs.length; r++) {
    var box = trs[r].querySelector("input[type=checkbox]");
    var kind = 'checkbox';
    if (!box) { box = trs[r].querySelector("input[type=radio]"); kind = 'radio'; }
    if (!box) continue;
    if (kind === 'checkbox') boxes++;
    var cs = trs[r].querySelectorAll('th,td');
    var texts = [];
    for (var c = 0; c < cs.length; c++) texts.push(cellText(cs[c]));
    var joined = texts.join(' ');
    // 이용일의 정답은 숨은 input[id^=resdt] 의 YYYYMMDD 다.
    var hid = trs[r].querySelector("input[id^=resdt]");
    var date = '';
    if (hid && /^\d{8}$/.test(hid.value || '')) {
      date = hid.value;
      dated++;
    } else {
      var m = joined.match(RE_DATE);
      if (m) { date = m[1] + m[2] + m[3]; dated++; }
    }
    if (RE_SPAN.test(joined)) spans++;
    if (RE_MONTHS.test(joined)) months++;
    rows.push({row: r, checked: !!box.checked, kind: kind, texts: texts,
               text: joined, date: date, boxId: box.id || ''});
  }
  return {rows: rows, dated: dated, boxes: boxes, spans: spans, months: months};
}

// ---- 1순위: 실물 선택표 #INFOQUALF
var infoq = document.getElementById('INFOQUALF');
if (infoq) {
  var got = readRows(infoq);
  if (got.rows.length) {
    var all0 = document.querySelectorAll('table');
    var ti = -1;
    for (var i = 0; i < all0.length; i++) if (all0[i] === infoq) { ti = i; break; }
    return {tableIndex: ti, rows: got.rows, score: 1000, how: 'INFOQUALF',
            spans: got.spans, boxes: got.boxes, skipped: []};
  }
}

// ---- 2순위: 예전의 점수식 (사이트가 바뀌었을 때)
var best = null;
var skipped = [];
for (var t = 0; t < tables.length; t++) {
  var tb = tables[t];
  var head = '';
  try {
    var cap = tb.querySelector('caption');
    var thead = tb.querySelector('thead');
    head = (cap ? txt(cap) : '') + ' ' + (thead ? txt(thead) : '');
  } catch (e) { head = ''; }

  var g = readRows(tb);
  var rows = g.rows, dated = g.dated, boxes = g.boxes;
  var spans = g.spans, months = g.months;
  if (!rows.length) continue;

  // 아동 표는 후보에서 아예 뺀다. 여기 행을 체크하면 엉뚱한 것이 예약된다.
  if (CHILDISH.test(head) || (months > 0 && spans === 0)) {
    skipped.push({tableIndex: t, why: 'child_table'});
    continue;
  }
  // 이용시간 구간이 있는 표 > 체크박스 표 > 이용일만 있는 표
  var score = spans * 10 + boxes * 6 + dated * 3 + (SLOTTISH.test(head) ? 5 : 0);
  if (score <= 0) { skipped.push({tableIndex: t, why: 'no_signal'}); continue; }
  if (best === null || score > best.score) {
    best = {score: score, tableIndex: t, rows: rows, spans: spans, boxes: boxes};
  }
}
if (!best) return {tableIndex: -1, rows: [], skipped: skipped, how: 'none'};
return {tableIndex: best.tableIndex, rows: best.rows, score: best.score,
        spans: best.spans, boxes: best.boxes, skipped: skipped, how: 'scored'};
"""

_JS_TICK_ROW = r"""
var t = document.querySelectorAll('table')[arguments[0]];
if (!t) return false;
var trs = t.querySelectorAll('tr');
if (arguments[1] >= trs.length) return false;
var box = trs[arguments[1]].querySelector("input[type=checkbox],input[type=radio]");
if (!box) return false;
if (!box.checked) {
  try { box.scrollIntoView({block: 'center'}); } catch (e) {}
  box.click();
  if (!box.checked) {
    box.checked = true;
    box.dispatchEvent(new Event('change', {bubbles: true}));
  }
}
return !!box.checked;
"""

_JS_CLICK_TEXT_BUTTON = r"""
function txt(e){ return ((e.innerText || e.textContent || e.value || '').replace(/\s+/g,' ')).trim(); }
function vis(e){
  var r = e.getBoundingClientRect();
  if (r.width <= 0 || r.height <= 0) return false;
  var s = window.getComputedStyle(e);
  return s.visibility !== 'hidden' && s.display !== 'none' && s.opacity !== '0';
}
var want = arguments[0];
var scopeSel = arguments[1] || null;
var scope = document;
if (scopeSel) { var s = document.querySelector(scopeSel); if (s) scope = s; }
var nodes = scope.querySelectorAll("button,a,input[type=button],input[type=submit],span[onclick],div[onclick]");
for (var i = 0; i < nodes.length; i++) {
  var e = nodes[i];
  if (!vis(e)) continue;
  var label = txt(e);
  if (label === want || (label.length <= want.length + 4 && label.indexOf(want) >= 0)) {
    try { e.scrollIntoView({block: 'center'}); } catch (err) {}
    e.click();
    return label;
  }
}
return null;
"""

# "예약" 확인창.
#
# 2026-08-25 실측으로 이 부분이 완전히 정리됐다. 예약 흐름은
# icmsLayerPopup.**confirm2** 를 쓴다 (layerpopup.js):
#
#   icmsLayerPopup.confirm2({title:"예약", contents: confirmText,
#                            thisFocus:"#timecareConfirm"}, function(res){ ... })
#   confirm2 는 #layer-confirm-popup-title2 / -contents2 를 채우고
#   #layer-confirm-popup2 와 #dimmed_confirm2 를 show() 한다.
#   [확인] 에 콜백을 묶는 대상은 **#layer-confirm-popup-confirm2** 다.
#
# 그래서 확인 버튼은 `#layer-confirm-popup-confirm` 이 아니라
# **`-confirm2`** 다. 전자를 눌렀다면 사이트가 그 버튼에 아무 콜백도 묶지
# 않았으므로 조용히 아무 일도 일어나지 않았을 것이다.
#
# 그리고 이 페이지에는 공용 팝업 껍데기가 **두 벌** 들어 있다.
#   1번째: style="display: block"  <- 지금 떠 있는 진짜 창, 본문이 채워져 있다
#   2번째: 인라인 style 없음        <- .popup_wrap{display:none} 으로 숨어 있고 본문이 비어 있다
# id 가 중복이므로 getElementById 는 못 쓴다(첫 번째만 준다는 보장이 없고,
# 어느 쪽이 열린 것인지도 알 수 없다). **querySelectorAll + 가시성** 으로
# 고른다. 같은 이유로 id="layer-confirm-popup-close2" 는 한 껍데기 안에서도
# 두 번(X 닫기, [취소]) 나온다.
#
# 본문 문구도 이제 실물이다: "…예약하시겠습니까?" (월 60시간 초과 시에는
# 그 안내가 앞에 붙고 마지막 줄이 예약하시겠습니까? 다).
_JS_MODAL = r"""
function txt(e){ return ((e.innerText || e.textContent || '').replace(/\s+/g,' ')).trim(); }
function vis(e){
  if (!e) return false;
  var r = e.getBoundingClientRect();
  if (r.width <= 0 || r.height <= 0) return false;
  var s = window.getComputedStyle(e);
  return s.visibility !== 'hidden' && s.display !== 'none' && s.opacity !== '0';
}
function okButtonIn(e) {
  // 실물 id 우선. 없으면 글자로.
  var byId = e.querySelectorAll("[id='layer-confirm-popup-confirm2']");
  for (var i = 0; i < byId.length; i++) if (vis(byId[i])) return byId[i];
  var btns = e.querySelectorAll(
    "button,a,input[type=button],input[type=submit],span[onclick]");
  for (var b = 0; b < btns.length; b++) {
    if (!vis(btns[b])) continue;
    var lb = txt(btns[b]) || (btns[b].value || '');
    if (lb.indexOf('취소') >= 0 || lb.indexOf('닫기') >= 0) continue;
    if (lb.indexOf('확인') >= 0 || lb.toLowerCase() === 'ok') return btns[b];
  }
  return null;
}

// ---- 1순위: 사이트의 진짜 확인창. 보이는 #layer-confirm-popup2 를 고른다.
var shells = document.querySelectorAll("[id='layer-confirm-popup2']");
for (var i = 0; i < shells.length; i++) {
  var e = shells[i];
  if (!vis(e)) continue;
  var bodyEl = null;
  var ps = e.querySelectorAll("[id='layer-confirm-popup-contents2']");
  for (var k = 0; k < ps.length; k++) { if (txt(ps[k])) { bodyEl = ps[k]; break; } }
  var body = bodyEl ? txt(bodyEl) : txt(e);
  if (!body) continue;
  var ok = okButtonIn(e);
  if (!ok) continue;
  window.__aisarang_modal = e;
  window.__aisarang_ok_hint = ok;
  return {text: body, how: 'layer-confirm-popup2',
          shells: shells.length, okId: ok.id || ''};
}

// ---- 2순위: 사이트가 바뀌었을 때. 예전처럼 글자로 찾는다.
var best = null;
var cands = document.querySelectorAll(
  "div,section,dialog,[role=dialog],[role=alertdialog],.layer,.popup,.modal");
for (var i = 0; i < cands.length; i++) {
  var e = cands[i];
  if (!vis(e)) continue;
  var body = txt(e);
  if (!body) continue;
  if (body.length > 1500) continue;
  var asks = body.indexOf('예약하시겠습니까') >= 0 ||
             body.indexOf('하시겠습니까') >= 0 ||
             body.indexOf('신청하시겠습니까') >= 0;
  if (!asks) continue;
  if (!okButtonIn(e)) continue;
  // 가장 안쪽(=가장 짧은) 후보가 진짜 모달이다.
  if (best === null || body.length < best.len) best = {el: e, len: body.length, text: body};
}
if (!best) return null;
window.__aisarang_modal = best.el;
window.__aisarang_ok_hint = null;
return {text: best.text, how: 'text', shells: shells.length, okId: ''};
"""

# 발사 순간에 하는 일을 최소화한다. 미리 [확인] 버튼을 window 에 물려두고,
# 정각에는 click 한 줄만 실행한다(왕복 한 번, 파싱 없음).
_JS_ARM = r"""
function txt(e){ return ((e.innerText || e.textContent || e.value || '').replace(/\s+/g,' ')).trim(); }
function vis(e){
  var r = e.getBoundingClientRect();
  if (r.width <= 0 || r.height <= 0) return false;
  var s = window.getComputedStyle(e);
  return s.visibility !== 'hidden' && s.display !== 'none' && s.opacity !== '0';
}
var m = window.__aisarang_modal;
if (!m || !vis(m)) return false;
var btn = null;
// 1순위: 실물 확인 버튼. 반드시 **떠 있는 껍데기 안의** 것이어야 한다.
// 같은 id 가 페이지에 두 개 있고, 숨은 쪽에는 사이트가 콜백을 묶지 않았다.
var byId = m.querySelectorAll("[id='layer-confirm-popup-confirm2']");
for (var i = 0; i < byId.length; i++) { if (vis(byId[i])) { btn = byId[i]; break; } }
// 2순위: 글자로. 취소/닫기는 건너뛴다.
if (!btn) {
  var btns = m.querySelectorAll("button,a,input[type=button],input[type=submit],span[onclick]");
  for (var i = 0; i < btns.length; i++) {
    if (!vis(btns[i])) continue;
    var lb = txt(btns[i]);
    if (lb.indexOf('취소') >= 0 || lb.indexOf('닫기') >= 0) continue;
    if (lb.indexOf('확인') >= 0 || lb.toLowerCase() === 'ok') { btn = btns[i]; break; }
  }
}
if (!btn) return false;
window.__aisarang_ok = btn;
window.__aisarang_fired_at = null;
window.__aisarang_fire = function () {
  var b = window.__aisarang_ok;
  if (!b) return false;
  var r = b.getBoundingClientRect();
  if (r.width <= 0 || r.height <= 0) return false;   // 창이 닫혔으면 쏘지 않는다
  window.__aisarang_fired_at = Date.now();
  b.click();
  return true;
};
return true;
"""

_JS_FIRE = "return (window.__aisarang_fire ? window.__aisarang_fire() : false);"

_JS_STILL_ARMED = r"""
var b = window.__aisarang_ok;
if (!b) return false;
var r = b.getBoundingClientRect();
if (r.width <= 0 || r.height <= 0) return false;
var s = window.getComputedStyle(b);
return s.visibility !== 'hidden' && s.display !== 'none';
"""

# ---------------------------------------------------------------- 가상대기열
#
# 2026-08-26 실측. 고객 PC 캡처(page_source/0005_modal_not_open.html)의
# 꼬리에 이 마크업이 통째로 들어 있고, network 로그에는
# nf.childcare.go.kr:8443/ts.wseq?opcode=5101(진입) → opcode=5002(폴링) 이
# 줄줄이 찍혀 있다. **[예약하기] 를 누르면 대기열에 선다.** 확인창은 순번이
# 올 때까지 열리지 않는다.
#
#   <div id="NetFunnel_Loading_Popup" style="display: block; ...">
#     <b>시간제 보육 예약 <span>대기 중</span>입니다.</b>
#     <b>예상대기시간 : <span id="NetFunnel_Loading_Popup_TimeLeft">2분  10초 </span></b>
#     <div id="Progress_Print">6 % (5/77) - ... sec</div>
#     현재 앞에 <span id="NetFunnel_Loading_Popup_Count">72</span> 명,
#     뒤에 <span id="NetFunnel_Loading_Popup_NextCnt">26</span> 명의 대기자가 있습니다.
#     ※ 재접속하시면 대기시간이 더 길어집니다. <span id="NetFunnel_Countdown_Stop">[중지]</span>
#
# 마지막 줄이 이 판의 전부다. v1.0.7 은 확인창이 8초 안에 안 열리면 검색
# 화면부터 다시 했고, 그래서 매번 대기열 맨 뒤로 갔다. 캡처 세 장:
# 앞에 72명 → 138명 → 177명, 예상 2분10초 → 3분50초 → 4분32초.
_JS_QUEUE = r"""
function txt(e){ return ((e.innerText || e.textContent || '').replace(/\s+/g,' ')).trim(); }
function vis(e){
  if (!e) return false;
  var r = e.getBoundingClientRect();
  if (r.width <= 0 || r.height <= 0) return false;
  var s = window.getComputedStyle(e);
  return s.visibility !== 'hidden' && s.display !== 'none' && s.opacity !== '0';
}
var out = {queue: false, ahead: null, behind: null, eta: '', progress: ''};
var qs = document.querySelectorAll("[id='NetFunnel_Loading_Popup']");
for (var i = 0; i < qs.length; i++) {
  if (!vis(qs[i])) continue;
  out.queue = true;
  var a = qs[i].querySelector("[id='NetFunnel_Loading_Popup_Count']");
  var b = qs[i].querySelector("[id='NetFunnel_Loading_Popup_NextCnt']");
  var t = qs[i].querySelector("[id='NetFunnel_Loading_Popup_TimeLeft']");
  var p = qs[i].querySelector("[id='Progress_Print']");
  if (a && /^\d+$/.test(txt(a))) out.ahead = parseInt(txt(a), 10);
  if (b && /^\d+$/.test(txt(b))) out.behind = parseInt(txt(b), 10);
  if (t) out.eta = txt(t);
  if (p) out.progress = txt(p);
  return out;
}
// 넷퍼널 스킨이 바뀌었을 때. 레이어 문구는 실물 그대로다.
var all = document.querySelectorAll("div,section");
for (var i = 0; i < all.length; i++) {
  if (!vis(all[i])) continue;
  var s = txt(all[i]);
  if (s.length > 800) continue;
  if (s.indexOf('대기 중입니다') < 0 || s.indexOf('대기자가 있습니다') < 0) continue;
  out.queue = true;
  var m = s.match(/앞에\s*(\d+)\s*명/);   if (m)  out.ahead = parseInt(m[1], 10);
  var m2 = s.match(/뒤에\s*(\d+)\s*명/);  if (m2) out.behind = parseInt(m2[1], 10);
  var m3 = s.match(/예상대기시간\s*:?\s*([^*]{0,20})/); if (m3) out.eta = m3[1].trim();
  return out;
}
return out;
"""


# 화면 어디든 떠 있는 안내 문구(레이어 알림, alert 대체 팝업)를 그대로 읽어온다.
_JS_READ_NOTICE = r"""
function txt(e){ return ((e.innerText || e.textContent || '').replace(/\s+/g,' ')).trim(); }
function vis(e){
  var r = e.getBoundingClientRect();
  if (r.width <= 0 || r.height <= 0) return false;
  var s = window.getComputedStyle(e);
  return s.visibility !== 'hidden' && s.display !== 'none' && s.opacity !== '0';
}
var out = [];
// 실제 사이트의 알림/확인창 컨테이너는 class="popup_wrap ..." 이다.
// `.popup` 은 popup_wrap 에 **맞지 않는다**(클래스 이름 전체가 popup_wrap 이다).
// 그래서 이 경로가 통째로 죽어 있었고 read_outcome 이 page_source 훑기 하나에만
// 의존했다. 이름을 맞히는 대신 부분일치로 잡는다(popup_wrap, pop_bs, layer_popup ...).
var cands = document.querySelectorAll(
  "[role=dialog],[role=alertdialog],[class*=popup],[class*=pop_],[class*=layer]," +
  ".popup_wrap,.layer,.modal,.alert,.msg,.message");
for (var i = 0; i < cands.length; i++) {
  var e = cands[i];
  if (!vis(e)) continue;
  var b = txt(e);
  if (b && b.length < 600) out.push(b);
}
return out;
"""


# ---------------------------------------------------------------- 안전한 실행

def _js(driver, script, *args, default=None):
    try:
        return driver.execute_script(script, *args)
    except Exception:
        return default


# ---------------------------------------------------------------- 1~2단계

def choose_kind(driver, unity_yn: str, log=lambda *_: None) -> bool:
    """구분 라디오. 독립반(N) / 통합반(Y)."""
    want = "통합반" if (unity_yn or "N").upper() == "Y" else "독립반"
    hit = _js(driver, _JS_CLICK_TEXT_BUTTON, want, None)
    if hit:
        log(f"구분: {want}")
        return True
    ok = _js(driver, r"""
    var want = arguments[0];
    var labs = document.querySelectorAll('label');
    for (var i = 0; i < labs.length; i++) {
      if ((labs[i].innerText || '').indexOf(want) >= 0) {
        var forId = labs[i].getAttribute('for');
        var inp = forId ? document.getElementById(forId) : labs[i].querySelector('input');
        if (inp) { inp.click(); return true; }
        labs[i].click(); return true;
      }
    }
    return false;
    """, want, default=False)
    log(f"구분: {want}" if ok else f"구분({want}) 라디오를 찾지 못했습니다.")
    return bool(ok)


def choose_region(driver, sido_name: str, gugun_name: str,
                  log=lambda *_: None) -> bool:
    """지역 2단 선택. 드롭다운을 열고 시/도 → 시/군/구 를 글자로 고른다.

    영상에서 확인: 지역 칸을 누르면 왼쪽 '시/도' 목록과 오른쪽 '시/군/구'
    목록이 두 칸으로 열린다. 일반 <select> 가 아니라 목록 위젯이라
    글자로 찾아 누르는 방식이 맞다. 진짜 <select> 인 경우도 같이 처리한다.
    """
    done_sido = _select_option_by_text(driver, sido_name)
    if not done_sido:
        _js(driver, _JS_CLICK_TEXT_BUTTON, "지역", None)
        time.sleep(0.2)
        done_sido = bool(_js(driver, _JS_CLICK_TEXT_BUTTON, sido_name, None))
    time.sleep(0.4)
    done_gugun = _select_option_by_text(driver, gugun_name)
    if not done_gugun:
        done_gugun = bool(_js(driver, _JS_CLICK_TEXT_BUTTON, gugun_name, None))
    log(f"지역: {sido_name} {gugun_name}"
        + ("" if (done_sido and done_gugun) else "  (일부 자동 선택 실패)"))
    return bool(done_sido and done_gugun)


def _select_option_by_text(driver, text: str) -> bool:
    """진짜 <select> 안에 그 글자의 option 이 있으면 고른다."""
    return bool(_js(driver, r"""
    var want = arguments[0];
    var sels = document.querySelectorAll('select');
    for (var i = 0; i < sels.length; i++) {
      var s = sels[i];
      for (var o = 0; o < s.options.length; o++) {
        var t = (s.options[o].text || '').trim();
        if (t === want || t.indexOf(want) >= 0) {
          s.selectedIndex = o;
          s.dispatchEvent(new Event('change', {bubbles: true}));
          return true;
        }
      }
    }
    return false;
    """, text, default=False))


def press_search(driver, log=lambda *_: None) -> bool:
    hit = _js(driver, _JS_CLICK_TEXT_BUTTON, "조회", None)
    log("조회를 눌렀습니다." if hit else "조회 버튼을 찾지 못했습니다.")
    time.sleep(1.2)
    return bool(hit)


def open_center(driver, center: dict, log=lambda *_: None) -> bool:
    """결과 목록에서 그 센터의 [시간제보육 예약] 을 누른다.

    사이트가 하는 것과 같은 gotoOccasionRes(stcode, unityYn, ...) 경로다.
    목록에서 못 찾으면 automation.open_reservation_page 의 폼 POST 로 넘어간다.
    """
    ok = _js(driver, r"""
    var stcode = arguments[0], name = arguments[1];
    var nodes = document.querySelectorAll('[data-stcode]');
    for (var i = 0; i < nodes.length; i++) {
      if ((nodes[i].getAttribute('data-stcode') || '') === stcode) {
        nodes[i].click();
        return 'stcode';
      }
    }
    if (typeof gotoOccasionRes === 'function') {
      gotoOccasionRes(stcode, arguments[2] || 'N', '');
      return 'gotoOccasionRes';
    }
    return null;
    """, center.get("stcode", ""), center.get("name", ""),
        center.get("unityYn", "N"), default=None)
    if ok:
        log(f"센터를 열었습니다: {center.get('name')} ({ok})")
        time.sleep(1.5)
        return True
    log("목록에서 센터 버튼을 찾지 못했습니다. 폼 전송으로 엽니다.")
    return False


# ---------------------------------------------------------------- 3단계 아동

# 여기부터는 **고객 PC 가 올려준 진짜 마크업**이 근거다
# (2026-08-25T05:24Z 진단 ZIP, page_source/0002_reservation_page.html,
#  인증서 세션에서만 열리는 화면이라 이 경로 말고는 볼 방법이 없었다).
#
# 사이트가 실제로 하는 일:
#   <input type="radio" name="occasionChk" onclick="listChildSelect();" ...>
#   function listChildSelect() {
#     if (usereqstcnt < 1) { alert('이용신청서를 먼저 등록해주세요.'); ... }
#     else if ($('#unityyn').val() == 'N') $('[data-tab=divOccasionTimeSlPL]').trigger('click');
#     else                                 $('[data-tab=divOccasionTimePils]').trigger('click');
#   }
# 그 탭 클릭이 fnChildInfo() → POST /icms/occasion/OccasionTimeMainSlPL.html 을
# 불러서 반명/이용시간/날짜표를 ajax 로 그려넣는다.
#
# 그래서 두 가지가 중요하다.
#   1. 라디오가 이미 켜져 있으면 click 이 안 나가고, 그러면 이용정보 화면이
#      아예 안 열린다. 항상 누른다.
#   2. 화면이 ajax 로 늦게 채워진다. 채워질 때까지 기다리고 나서 다음 단계로 간다.
#   3. **엉뚱한 라디오를 누르면 안 된다.** name=occasionChk 를 못 찾았을 때
#      예전 코드는 document 전체의 "tr input[type=radio]" 를 그대로 썼다.
#      이 화면에는 라디오가 여러 군데 있다(검색 화면의 구분 라디오, 표 안의
#      선택 라디오). 그래서 슬롯 표를 찾을 때와 같은 방식으로 표에 점수를
#      매긴다. 아동 표는 **생년월일이 있고 개월수 열이 있는 표**다.
#   4. **이름을 지정했는데 그 아동이 목록에 없으면 아무것도 누르지 않는다.**
#      예전 코드는 조용히 첫 번째 아동을 눌렀다. 아이가 둘 이상 등록돼 있으면
#      그대로 다른 아이가 예약된다. 되돌릴 수 없는 실패라 여기서 멈춘다.
_JS_PICK_CHILD = r"""
function txt(e){ return ((e.innerText || e.textContent || '').replace(/\s+/g,' ')).trim(); }
function norm(s){ return (s || '').replace(/\s+/g, '').toLowerCase(); }
var RE_BIRTH = /(19|20)\d\d\s*[-.\/]\s*\d{1,2}\s*[-.\/]\s*\d{1,2}/;
var RE_MONTHS = /\d+\s*개\s*월/;
var want = norm(arguments[0]);

function rowsOf(list) {
  var out = [];
  for (var i = 0; i < list.length; i++) {
    var box = list[i];
    var row = box.closest('tr');
    out.push({box: box, line: row ? txt(row) : ''});
  }
  return out;
}

// 1순위: 사이트가 실제로 쓰는 이름(고객 진단 ZIP 의 진짜 마크업).
var rows = rowsOf(document.querySelectorAll("input[type=radio][name=occasionChk]"));
var how = 'occasionChk';

// 2순위: 이름이 바뀌었을 때. 표마다 점수를 매겨 '아동 표' 만 쓴다.
if (!rows.length) {
  var tables = document.querySelectorAll('table');
  var best = null;
  for (var t = 0; t < tables.length; t++) {
    var trs = tables[t].querySelectorAll('tr');
    var found = [], dated = 0, months = 0;
    for (var r = 0; r < trs.length; r++) {
      var box = trs[r].querySelector("input[type=radio]");
      if (!box) continue;
      var line = txt(trs[r]);
      if (RE_BIRTH.test(line)) dated++;
      if (RE_MONTHS.test(line)) months++;
      found.push({box: box, line: line});
    }
    if (!found.length) continue;
    var head = txt(tables[t]);
    var headScore = (/개\s*월/.test(head) ? 3 : 0)
                  + (/아동\s*명|생년월일/.test(head) ? 3 : 0);
    var score = dated * 10 + months * 3 + headScore;
    if (score <= 0) continue;          // 아동 표처럼 안 생겼으면 쓰지 않는다
    if (best === null || score > best.score) {
      best = {score: score, rows: found, tableIndex: t};
    }
  }
  if (!best) return {found: false, reason: 'no_child_table'};
  rows = best.rows;
  how = 'scored_table#' + best.tableIndex + '(score ' + best.score + ')';
}

var lines = [];
for (var i = 0; i < rows.length; i++) lines.push(rows[i].line);

var hit = null;
if (want) {
  for (var i = 0; i < rows.length; i++) {
    if (norm(rows[i].line).indexOf(want) >= 0) { hit = rows[i]; break; }
  }
  if (!hit) {
    // 아무것도 누르지 않고 그대로 돌아간다. 다른 아이를 예약하느니 멈춘다.
    return {found: true, matched: false, clicked: false, how: how,
            count: rows.length, candidates: lines};
  }
}
var pick = hit || rows[0];
try { pick.box.scrollIntoView({block: 'center'}); } catch (err) {}
// 이미 켜져 있어도 누른다. 사이트의 onclick(listChildSelect)이 이용정보 화면을
// 여는 유일한 트리거이기 때문이다.
pick.box.click();
return {found: true, matched: !!hit, clicked: true, how: how,
        count: rows.length, candidates: lines, line: pick.line};
"""

# 지금 켜져 있는 아동 행의 글자. alert 때문에 클릭 스크립트가 끊겼을 때 쓴다.
# 여기서도 문서 전체의 아무 라디오나 집지 않는다. 생년월일이 있는 행만 아동으로 본다.
_JS_READ_CHECKED_CHILD = r"""
function txt(e){ return ((e.innerText || e.textContent || '').replace(/\s+/g,' ')).trim(); }
var RE_BIRTH = /(19|20)\d\d\s*[-.\/]\s*\d{1,2}\s*[-.\/]\s*\d{1,2}/;
var box = document.querySelector("input[type=radio][name=occasionChk]:checked");
if (box) {
  var row = box.closest('tr');
  return row ? txt(row) : null;
}
var all = document.querySelectorAll("tr input[type=radio]:checked");
for (var i = 0; i < all.length; i++) {
  var row = all[i].closest('tr');
  var line = row ? txt(row) : '';
  if (RE_BIRTH.test(line)) return line;
}
return null;
"""

# 이용정보 탭. 라디오 onclick 이 무슨 이유로든 안 돌았을 때를 위한 두 번째 경로다.
_JS_OPEN_USEINFO_TAB = r"""
var unity = document.getElementById('unityyn');
var yn = unity ? String(unity.value || 'N').toUpperCase() : 'N';
var sel = (yn === 'Y') ? '[data-tab=divOccasionTimePils]' : '[data-tab=divOccasionTimeSlPL]';
var tab = document.querySelector(sel);
if (!tab) return false;
tab.click();
return true;
"""

# 이용정보가 실제로 그려졌는지. select(반명/이용시간)나 날짜표가 보이면 됐다.
_JS_USEINFO_READY = r"""
function vis(e){
  var r = e.getBoundingClientRect();
  return r.width > 0 && r.height > 0;
}
var sels = document.querySelectorAll('select');
for (var i = 0; i < sels.length; i++) {
  if (!vis(sels[i])) continue;
  var row = sels[i].closest('tr,div,li');
  var line = row ? (row.innerText || '') : '';
  if (line.indexOf('이용시간') >= 0 || line.indexOf('반명') >= 0) return true;
}
var body = document.body ? (document.body.innerText || '') : '';
return body.indexOf('날짜/시간') >= 0;
"""


def _take_alert(driver) -> str:
    """네이티브 alert 이 떠 있으면 문구를 읽고 닫는다.

    listChildSelect() 는 이용신청서가 없으면 alert() 을 띄운다. 그걸 안 닫으면
    이후 모든 조작이 그 자리에서 막힌다.
    """
    try:
        al = driver.switch_to.alert
        text = (al.text or "").strip()
        al.accept()
        return text
    except Exception:
        return ""


@dataclass
class ChildPick:
    """아동 선택 결과. ok=False 면 준비를 그대로 멈춘다."""
    ok: bool = True
    line: str = ""
    reason: str = "child_selected"
    message: str = ""
    requested: str = ""
    candidates: list = field(default_factory=list)
    how: str = ""

    def __str__(self) -> str:      # 로그/기존 호출부 호환
        return self.line


def select_child(driver, child_name: str = "", log=lambda *_: None) -> ChildPick:
    """"시간제보육 아동 선택" 의 라디오를 고르고, 이용정보 화면이 뜰 때까지 기다린다.

    이름을 지정하면 **그 아동만** 고른다. 목록에 없으면 아무것도 누르지 않고
    실패로 돌려준다. 아이가 둘 이상 등록된 계정에서 조용히 첫 번째를 예약해
    버리는 것이 이 프로그램이 낼 수 있는 최악의 결과이기 때문이다.
    이름을 비워두면 예전처럼 첫 행을 고른다.
    """
    want = (child_name or "").strip()
    got = _js(driver, _JS_PICK_CHILD, want, default=None) or {}
    if not isinstance(got, dict):                 # 옛 반환형 방어
        got = {"found": bool(got), "matched": True, "clicked": True,
               "line": str(got or "")}

    # 클릭 안에서 사이트가 alert() 을 띄우면 스크립트 호출 자체가 그 자리에서
    # 끊긴다(라디오는 이미 눌린 뒤다). 알림을 닫고 고른 행을 다시 읽는다.
    alert_text = _take_alert(driver)
    if not got and alert_text:
        line = _js(driver, _JS_READ_CHECKED_CHILD, default=None)
        if line:
            got = {"found": True, "matched": True, "clicked": True, "line": line}

    candidates = list(got.get("candidates") or [])

    if not got.get("found"):
        log("아동 선택 화면이 아닙니다(건너뜁니다).")
        return ChildPick(ok=True, line="", reason="no_child_table",
                         requested=want, candidates=candidates)

    if want and not got.get("matched"):
        # 여기서 멈춘다. 다른 아이로 예약하는 일은 절대 없어야 한다.
        log(f"■ 지정한 아동 '{want}' 을(를) 아동 목록에서 찾지 못했습니다. "
            f"다른 아동으로 예약하지 않고 여기서 멈춥니다.")
        if candidates:
            log("  화면에 있는 아동 목록: " + " / ".join(candidates))
        log("  프로그램 화면의 '아동명' 을 위 목록에 있는 이름과 똑같이 고쳐 주세요. "
            "(비워두면 첫 번째 아동으로 진행합니다)")
        return ChildPick(
            ok=False, line="", reason="child_mismatch", requested=want,
            candidates=candidates, how=str(got.get("how") or ""),
            message=(f"지정한 아동 '{want}' 이(가) 목록에 없습니다. "
                     f"화면의 '아동명' 을 확인해 주세요. "
                     f"(등록된 아동 {got.get('count', len(candidates))}명)"))

    picked = str(got.get("line") or "")
    if not picked:
        log("아동 선택 화면이 아닙니다(건너뜁니다).")
        return ChildPick(ok=True, line="", reason="no_child_table",
                         requested=want, candidates=candidates)

    out = ChildPick(ok=True, line=picked, reason="child_selected", requested=want,
                    candidates=candidates, how=str(got.get("how") or ""))
    log(f"아동 선택: {picked}")
    if not want and int(got.get("count") or 1) > 1:
        log(f"■ 등록된 아동이 {got.get('count')}명입니다. 아동명을 비워두어 "
            f"첫 번째 아동으로 진행합니다. 다른 아이라면 화면의 '아동명' 을 적어 주세요.")
    if alert_text:
        log(f"사이트 알림: {alert_text}")
        if "이용신청서" in alert_text:
            log("아이사랑에서 이 아동의 이용신청서를 먼저 등록해야 예약 화면이 열립니다.")
            return out

    # 라디오 onclick 이 이용정보 탭을 눌러 ajax 로 화면을 채운다. 그 결과를 기다린다.
    deadline = time.time() + 15.0
    opened_tab = False
    while time.time() < deadline:
        if _js(driver, _JS_USEINFO_READY, default=False):
            log("이용정보 화면을 불러왔습니다.")
            return out
        if not opened_tab and time.time() > deadline - 12.0:
            opened_tab = bool(_js(driver, _JS_OPEN_USEINFO_TAB, default=False))
            if opened_tab:
                log("이용정보 탭을 직접 눌렀습니다.")
        got_alert = _take_alert(driver)
        if got_alert:
            log(f"사이트 알림: {got_alert}")
        time.sleep(0.4)

    log("이용정보 화면이 아직 안 보입니다. 그대로 다음 단계로 가서 다시 확인합니다.")
    return out


# ---------------------------------------------------------------- 4단계 반/시간

def select_class(driver, class_name: str = "", log=lambda *_: None) -> str:
    """반명 select. 지정이 없으면 첫 번째 실제 값을 고른다."""
    got = _js(driver, r"""
    var want = (arguments[0] || '').trim();
    var labelWords = ['반명', '반 명'];
    var sels = document.querySelectorAll('select');
    function isPlaceholder(t) {
      t = (t || '').trim();
      return !t || t === '선택' || t === '전체' || t.indexOf('선택하') === 0;
    }
    // 0) 실물: <select class="selectbox" name="clname" id="clname"
    //           onchange="fnSerChange();" title="반명 선택">
    //    option 은 selectOcTaClList.html 응답으로 채워진다(value=clseq).
    var target = document.getElementById('clname');
    // 1) 없으면 라벨이 '반명' 인 select
    for (var i = 0; !target && i < sels.length; i++) {
      var row = sels[i].closest('tr,div,li');
      var line = row ? (row.innerText || '') : '';
      for (var w = 0; w < labelWords.length; w++) {
        if (line.indexOf(labelWords[w]) >= 0) { target = sels[i]; break; }
      }
    }
    var pool = target ? [target] : sels;
    for (var i = 0; i < pool.length; i++) {
      var s = pool[i];
      for (var o = 0; o < s.options.length; o++) {
        var t = (s.options[o].text || '').trim();
        if (isPlaceholder(t)) continue;
        if (want && t.indexOf(want) < 0) continue;
        s.selectedIndex = o;
        s.dispatchEvent(new Event('change', {bubbles: true}));
        return t;
      }
    }
    return null;
    """, class_name, default=None)
    log(f"반명: {got}" if got else "반명 선택칸을 찾지 못했습니다.")
    return str(got or "")


def select_hours(driver, hours: int, log=lambda *_: None) -> int:
    """이용시간 select. 영상에서 확인한 값은 1~9(시간)."""
    got = _js(driver, r"""
    var want = String(arguments[0]);
    var sels = document.querySelectorAll('select');
    // 0) 실물: <select class="selectbox" name="rtm" id="rtm"
    //           onchange="fnTimeReset();" title="이용시간 선택">
    //    option value 는 "1".."9" (시간 수). 실측 확인.
    var target = document.getElementById('rtm');
    // 1) 없으면 같은 줄에 '이용시간' 이 적힌 select
    for (var i = 0; !target && i < sels.length; i++) {
      var row = sels[i].closest('tr,div,li');
      var line = row ? (row.innerText || '') : '';
      if (line.indexOf('이용시간') >= 0) { target = sels[i]; break; }
    }
    var pool = target ? [target] : sels;
    for (var i = 0; i < pool.length; i++) {
      var s = pool[i];
      for (var o = 0; o < s.options.length; o++) {
        var t = (s.options[o].text || '').trim();
        if (t === want || t === want + '시간') {
          s.selectedIndex = o;
          s.dispatchEvent(new Event('change', {bubbles: true}));
          return parseInt(want, 10);
        }
      }
    }
    return 0;
    """, int(hours), default=0)
    log(f"이용시간: {got}시간" if got else f"이용시간 {hours} 를 고르지 못했습니다.")
    time.sleep(0.5)
    return int(got or 0)


# ---------------------------------------------------------------- 5단계 표

_X_MARKS = ("x", "X", "ｘ", "Ｘ", "×", "✕", "－", "-")


def _parse_cell_text(text: str) -> int | None:
    t = (text or "").strip()
    if not t:
        return None
    if t in _X_MARKS:
        return None
    m = re.search(r"(\d+)", t)
    if m:
        return int(m.group(1))
    return None


def read_grid(driver, diag=None) -> Grid:
    """날짜×시간 표를 통째로 읽는다. 못 읽으면 빈 Grid."""
    raw = _js(driver, _JS_SCAN_GRID, default=None)
    g = Grid()
    if not raw:
        return g
    g.table_index = int(raw.get("tableIndex", -1))
    g.headers = list(raw.get("headers") or [])
    g.rows = list(raw.get("rows") or [])
    for c in raw.get("cells") or []:
        g.cells.append(Cell(date=str(c.get("date", "")),
                            hour=int(c.get("hour", 0)),
                            text=str(c.get("text", "")),
                            capacity=_parse_cell_text(str(c.get("text", ""))),
                            row=int(c.get("row", -1)),
                            col=int(c.get("col", -1)),
                            el_id=str(c.get("id", "") or "")))
    if diag is not None:
        try:
            diag.add_json("grid.json", {
                "tableIndex": g.table_index,
                "headers": g.headers,
                "rows": g.rows,
                "cells": [{"date": c.date, "hour": c.hour, "text": c.text,
                           "capacity": c.capacity} for c in g.cells],
            })
        except Exception:
            pass
    return g


def pick_cell(grid: Grid, date: str, preferred_hours: list) -> tuple:
    """(고른 칸, 사유). 자리가 없으면 (None, 사람이 읽을 이유).

    X 와 0 은 '자리 없음' 으로 **보고**하고 절대 누르지 않는다.
    """
    if not grid.cells:
        return None, "날짜/시간 표를 읽지 못했습니다."
    if not grid.has_date(date):
        opened = sorted({r["date"] for r in grid.rows})
        return None, (f"{date} 행이 표에 없습니다. 표에 있는 날짜: "
                      + ", ".join(opened[:10]))
    row = grid.row_cells(date)
    if preferred_hours:
        for h in preferred_hours:
            c = grid.find(date, h)
            if c is None:
                continue
            if c.available:
                return c, f"{h:02d}시 칸 (남은 자리 {c.capacity}명)"
        reasons = []
        for h in preferred_hours:
            c = grid.find(date, h)
            reasons.append(f"{h:02d}시={c.why() if c else '칸 없음'}")
        return None, "원하는 시간대에 자리가 없습니다: " + ", ".join(reasons)
    for c in row:
        if c.available:
            return c, f"열려 있는 첫 칸 {c.hour:02d}시 (남은 자리 {c.capacity}명)"
    return None, ("그 날 열린 시간대가 없습니다: "
                  + " ".join(f"{c.hour:02d}={c.text}" for c in row))


def click_cell(driver, grid: Grid, cell: Cell, log=lambda *_: None) -> bool:
    """칸을 누르고, **실제로 선택 표시가 바뀌었는지** 확인한다.

    선택 표시의 class 이름을 맞히지 않는다. 클릭 전후의 지문을 비교해서
    그 칸이 바뀌었으면 선택된 것으로 본다. 바뀐 게 없으면 실패로 본다
    (= 이 상태로는 절대 제출하지 않는다).
    """
    before = _js(driver, _JS_CELL_MARKS, grid.table_index, default=None) or []
    ok = _js(driver, _JS_CLICK_CELL, grid.table_index, cell.row, cell.col,
             cell.el_id, default=False)
    if not ok:
        log("날짜 칸을 누르지 못했습니다.")
        return False
    time.sleep(0.35)
    # 1순위: 사이트의 진짜 선택 표시로 확인한다.
    # 실측: 고른 칸은 class 에 "on" 이 붙고 title 이 "선택됨" 이 된다.
    if cell.el_id:
        mark = _js(driver, _JS_CELL_IS_ON, cell.el_id, default=None)
        if isinstance(mark, dict):
            if mark.get("on") or mark.get("title") == "선택됨":
                log(f"{cell.date} {cell.hour:02d}시 칸을 선택했습니다 "
                    f"(표시: class=on, title={mark.get('title', '')}).")
                return True
            log(f"{cell.date} {cell.hour:02d}시 칸을 눌렀지만 선택 표시가 "
                f"붙지 않았습니다. 선택되지 않은 것으로 봅니다.")
            return False
    # 2순위: 표시 방법이 바뀌었을 때. 클릭 전후 지문 비교.
    after = _js(driver, _JS_CELL_MARKS, grid.table_index, default=None) or []
    key = f"{cell.row}:{cell.col}|"
    b = {s.split("|", 1)[0]: s for s in before}
    a = {s.split("|", 1)[0]: s for s in after}
    changed = [k for k in a if k in b and a[k] != b[k]]
    mine = f"{cell.row}:{cell.col}"
    if mine in changed:
        log(f"{cell.date} {cell.hour:02d}시 칸을 선택했습니다 "
            f"(같이 바뀐 칸 {len(changed)}개).")
        return True
    if changed:
        # 사이트가 시작 칸이 아니라 이용시간만큼의 구간을 칠하는 경우가 있다.
        log(f"칸을 눌렀고 표의 {len(changed)}개 칸이 바뀌었습니다 "
            f"(시작 칸 자체의 표시는 바뀌지 않았습니다).")
        return True
    log("칸을 눌렀지만 표에 아무 변화가 없습니다. 선택되지 않은 것으로 봅니다.")
    del key, b
    return False


# 실물 id 로 먼저 누른다. 없으면 예전처럼 글자로 찾는다.
#   <a id="timecareTableAddBtn" class="btn h50" onclick="f_AddQualRow();">추가</a>
#   <a id="timecareConfirm" class="btn h50" onClick="fnSave();">예약하기</a>
# 글자만 쓰면 위험한 이웃이 있다. 같은 btn_right 안에 [삭제]·[새로고침] 이
# 있고, [예약하기] 바로 옆이 [예약대기](id=tooltip) 다.
_JS_CLICK_BY_ID = r"""
function vis(e){
  if (!e) return false;
  var r = e.getBoundingClientRect();
  if (r.width <= 0 || r.height <= 0) return false;
  var s = window.getComputedStyle(e);
  return s.visibility !== 'hidden' && s.display !== 'none';
}
var nodes = document.querySelectorAll("[id='" + arguments[0] + "']");
for (var i = 0; i < nodes.length; i++) {
  if (!vis(nodes[i])) continue;
  try { nodes[i].scrollIntoView({block: 'center'}); } catch (e) {}
  nodes[i].click();
  return ((nodes[i].innerText || nodes[i].textContent || '').replace(/\s+/g,' ')).trim()
         || arguments[0];
}
return null;
"""


def press_add(driver, log=lambda *_: None) -> bool:
    hit = _js(driver, _JS_CLICK_BY_ID, "timecareTableAddBtn", default=None)
    how = "#timecareTableAddBtn"
    if not hit:
        hit = _js(driver, _JS_CLICK_TEXT_BUTTON, "추가", None)
        how = "글자"
    log(f"[추가] 를 눌렀습니다 ({how})." if hit else "[추가] 버튼을 찾지 못했습니다.")
    time.sleep(0.6)
    return bool(hit)


_RE_SLOT_SPAN = re.compile(r"\d{1,2}\s*[:시]?\s*\d{2}\s*[-~]\s*\d{1,2}\s*[:시]?\s*\d{2}"
                           r"|\d+\s*시간")
_RE_CHILD_ROW = re.compile(r"\d+\s*개\s*월")


def _looks_like_slot_row(row: dict) -> bool:
    """그 행이 선택표(이용일/이용시간) 행처럼 생겼는가.

    아동 행("박승우 2025.10.22 10개월")과 선택표 행
    ("매송아이 2026-09-08(화) 09 00 - 18 00 (9시간)")을 글자로 가른다.
    """
    text = str(row.get("text") or "")
    if _RE_CHILD_ROW.search(text) and not _RE_SLOT_SPAN.search(text):
        return False
    return bool(_RE_SLOT_SPAN.search(text))


def read_slot_rows(driver) -> dict:
    return _js(driver, _JS_SCAN_SLOT_ROWS, default=None) or {}


def tick_slot_row(driver, date: str, log=lambda *_: None) -> tuple:
    """선택표에서 그 이용일의 행을 체크한다. (성공, 행번호, 행글자)."""
    data = read_slot_rows(driver)
    rows = data.get("rows") or []
    if not rows:
        log("선택표(선택/반명/이용일/이용시간)에 행이 없습니다.")
        return False, -1, ""
    target = None
    for r in rows:
        if r.get("date") == date:
            target = r
            break
    if target is None:
        # 이용일이 안 읽히면 마지막에 추가된 행을 쓴다(방금 [추가] 한 그 행).
        # 단, **그 행이 선택표 행처럼 생겼을 때만** 쓴다. 예전에는 무조건
        # rows[-1] 을 켰고, 화면에 선택표가 아직 없으면 그게 아동 라디오였다.
        last = rows[-1]
        if last.get("kind") != "checkbox" and not _looks_like_slot_row(last):
            log("선택표 행을 찾지 못했습니다(마지막 행이 선택표 행이 아닙니다): "
                + str(last.get("text", ""))[:80])
            return False, -1, ""
        target = last
        log(f"선택표에서 {date} 를 못 찾아 마지막 행을 씁니다: {target.get('text', '')}")
    ok = _js(driver, _JS_TICK_ROW, data.get("tableIndex", 0), target.get("row", 0),
             default=False)
    if ok:
        log(f"선택표 행을 체크했습니다: {target.get('text', '')}")
    else:
        log("선택표 행을 체크하지 못했습니다.")
    return bool(ok), int(target.get("row", -1)), str(target.get("text", ""))


def slot_row_is_ticked(driver, row_index: int = -1) -> bool:
    data = read_slot_rows(driver)
    for r in data.get("rows") or []:
        if row_index >= 0 and int(r.get("row", -1)) != row_index:
            continue
        if r.get("checked"):
            return True
    return False


# ---------------------------------------------------------------- 8~9단계 모달

def press_reserve(driver, log=lambda *_: None) -> bool:
    hit = _js(driver, _JS_CLICK_BY_ID, "timecareConfirm", default=None)
    how = "#timecareConfirm"
    if not hit:
        hit = _js(driver, _JS_CLICK_TEXT_BUTTON, "예약하기", None)
        how = "글자"
    if not hit:
        hit = _js(driver, _JS_CLICK_TEXT_BUTTON, "신청하기", None)
        how = "글자"
    log(f"[{hit}] 를 눌렀습니다 ({how})."
        if hit else "[예약하기] 버튼을 찾지 못했습니다.")
    return bool(hit)


def modal_info(driver) -> dict:
    return _js(driver, _JS_MODAL, default=None) or {}


def queue_info(driver) -> dict:
    """가상대기열(넷퍼널) 레이어가 떠 있는지, 순번이 몇인지."""
    return _js(driver, _JS_QUEUE, default=None) or {"queue": False}


def queue_line(info: dict) -> str:
    bits = []
    if info.get("ahead") is not None:
        bits.append(f"앞에 {info['ahead']}명")
    if info.get("behind") is not None:
        bits.append(f"뒤에 {info['behind']}명")
    if info.get("eta"):
        bits.append(f"예상 {info['eta']}")
    return "가상대기열 대기 중" + (" (" + ", ".join(bits) + ")" if bits else "")


# 대기열이 없을 때 확인창을 기다리는 시간. 사이트가 대기열을 안 태우면
# 확인창은 곧바로 뜬다.
QUIET_MODAL_WAIT = 8.0
# 대기열 순번을 로그에 적는 간격.
QUEUE_LOG_SECONDS = 15.0


def wait_modal(driver, timeout: float = QUIET_MODAL_WAIT, log=lambda *_: None,
               deadline_local: float | None = None) -> tuple:
    """예약 확인창이 뜰 때까지 기다린다. (본문, 대기열을 봤는가) 를 돌려준다.

    **대기열을 만나면 실패로 치지 않는다.** [예약하기] 는 예약 전송이 아니라
    가상대기열 진입이고(2026-08-25 캡처의 마지막 요청이 ts.wseq 였다),
    09시 직전에는 서버가 그 대기열을 실제로 켠다(2026-08-26 실측: 앞에 72명,
    예상 2분 10초). 이때 필요한 것은 재시도가 아니라 **기다리는 것**이다.
    대기열 레이어가 스스로 "재접속하시면 대기시간이 더 길어집니다" 라고
    적어 놓았고, v1.0.7 은 정확히 그 짓을 세 번 했다.

    deadline_local 을 주면 대기열에 서 있는 동안 그 시각까지 기다린다.
    """
    end = time.time() + timeout
    seen_queue = False
    last_log = 0.0
    while True:
        info = modal_info(driver)
        if info.get("text"):
            if seen_queue:
                log("대기열을 통과했습니다.")
            log("예약 확인창이 열렸습니다: " + info["text"][:80])
            return str(info["text"]), seen_queue

        q = queue_info(driver)
        if q.get("queue"):
            if not seen_queue:
                seen_queue = True
                log("사이트가 가상대기열을 띄웠습니다. 예약 확인창은 순번이 올 때까지 "
                    "열리지 않습니다. 다시 누르지 않고 그대로 기다립니다.")
            now = time.time()
            if now - last_log >= QUEUE_LOG_SECONDS:
                last_log = now
                log(queue_line(q))
            if deadline_local is not None:
                end = max(end, min(deadline_local, time.time() + 1.0))
        elif seen_queue:
            # 레이어가 사라졌는데 확인창이 아직 없다. 잠깐 더 본다.
            end = max(end, time.time() + 3.0)

        if time.time() >= end:
            return "", seen_queue
        time.sleep(0.2)


def arm_confirm(driver, log=lambda *_: None) -> bool:
    """[확인] 버튼을 미리 잡아둔다. 정각에는 click 한 줄만 남는다."""
    ok = bool(_js(driver, _JS_ARM, default=False))
    log("확인 버튼을 조준했습니다." if ok else "확인 버튼을 조준하지 못했습니다.")
    return ok


def still_armed(driver) -> bool:
    return bool(_js(driver, _JS_STILL_ARMED, default=False))


def fire_confirm(driver) -> bool:
    """조준해둔 [확인] 을 누른다. 이 한 줄이 예약 요청이다."""
    return bool(_js(driver, _JS_FIRE, default=False))


def dismiss_modal(driver, log=lambda *_: None) -> None:
    _js(driver, _JS_CLICK_TEXT_BUTTON, "취소", None)
    log("확인창을 닫았습니다(연습 모드).")


def read_notices(driver) -> list:
    out = _js(driver, _JS_READ_NOTICE, default=None) or []
    return [str(x) for x in out]


def read_alert(driver) -> str:
    """브라우저 기본 alert 이 떠 있으면 글자를 읽고 닫는다."""
    try:
        al = driver.switch_to.alert
        text = al.text
        al.accept()
        return str(text or "")
    except Exception:
        return ""


def read_outcome(driver, timeout: float = 6.0) -> tuple:
    """[확인] 이후 화면이 뭐라고 했는지. (코드, 원문).

    사이트가 결과를 알려주는 자리는 세 군데다:
      1) 브라우저 alert
      2) icmsLayerPopup 같은 레이어 안내
      3) 서버가 페이지에 찍어 내려주는 '세션 메세지' 블록
    셋을 다 보고, 그 중 분류가 되는 첫 문구를 쓴다.
    """
    from . import automation

    end = time.time() + timeout
    last_text = ""
    while time.time() < end:
        texts = []
        a = read_alert(driver)
        if a:
            texts.append(a)
        texts.extend(read_notices(driver))
        try:
            msg = automation.read_session_message(driver.page_source)
        except Exception:
            msg = ""
        if msg:
            texts.append(msg)
        for t in texts:
            code = classify(t)
            if code != R_UNKNOWN:
                return code, t
            if t and not last_text:
                last_text = t
        try:
            src = driver.page_source or ""
        except Exception:
            src = ""
        for w in OK_WORDS:
            if w in src:
                return R_OK, w
        for w in TOO_EARLY_WORDS:
            if w in src:
                return R_TOO_EARLY, w
        for w in FULL_WORDS:
            if w in src:
                return R_FULL, w
        time.sleep(0.15)
    return R_UNKNOWN, last_text


# ---------------------------------------------------------------- 준비(1~8)

@dataclass
class StepResult:
    ok: bool = False
    message: str = ""
    reason: str = ""
    prepared: "Prepared | None" = None
    detail: dict = field(default_factory=dict)


def prepare(driver, center: dict, target_date: str, preferred_hours: list,
            hours: int, class_name: str = "", child_name: str = "",
            log=lambda *_: None, diag=None) -> StepResult:
    """1~8단계. 끝나면 '예약' 모달이 열린 채로 [확인] 만 남는다.

    여기서 실패하면 예약은 만들어지지 않는다. 실패 모드는 언제나
    '예약이 안 됨' 이어야지 '엉뚱한 예약이 됨' 이면 안 된다.
    """
    from . import automation

    p = Prepared(center=dict(center), target_date=target_date, hours=int(hours),
                 child_name=child_name, class_name=class_name)

    # 1~2단계: 검색 화면에서 구분/지역/조회 → 센터 열기.
    try:
        driver.get(automation.config.BASE_URL + automation.config.SEARCH_PAGE)
        time.sleep(1.0)
        choose_kind(driver, center.get("unityYn", "N"), log)
        choose_region(driver, center.get("ctprvnName", ""),
                      center.get("signguName", ""), log)
        press_search(driver, log)
        automation.capture(driver, diag, "search_results")
        opened = open_center(driver, center, log)
    except Exception as exc:  # noqa: BLE001
        log(f"검색 단계에서 문제가 있어 폼 전송으로 갑니다: {type(exc).__name__}")
        opened = False
    if not opened:
        automation.open_reservation_page(driver, center, log, diag)

    automation.handle_netfunnel(driver, log)

    if automation.page_says_cert_required(driver):
        grade = automation.login_grade(driver)
        automation.capture(driver, diag, "cert_required")
        msg = ("아이디로 로그인된 상태입니다. 이 화면은 공동인증서 세션에서만 열립니다. "
               "크롬 창에서 공동인증서로 다시 로그인해 주세요."
               if grade == "id" else
               "공동인증서 로그인이 필요한 상태입니다.")
        return StepResult(False, msg, "cert_required", p, {"loginGrade": grade})

    # 3단계: 아동 선택
    pick = select_child(driver, child_name, log)
    automation.capture(driver, diag, "after_child_select")
    if not pick.ok:
        # 지정한 아동이 목록에 없다. 다른 아이로 예약하느니 예약하지 않는다.
        # 이름은 개인정보라 업로드하는 detail 에는 개수만 남긴다.
        return StepResult(False, pick.message, pick.reason, p,
                          {"requestedChild": bool(child_name),
                           "childCandidateCount": len(pick.candidates),
                           "childScan": pick.how})
    p.child_name = pick.line or child_name

    # 4단계: 반명 + 이용시간
    p.class_name = select_class(driver, class_name, log) or class_name
    got_hours = select_hours(driver, hours, log)
    p.hours = got_hours or int(hours)
    automation.capture(driver, diag, "after_class_hours")

    # 5단계: 날짜×시간 표
    grid = read_grid(driver, diag)
    p.grid_summary = grid.summary(target_date)
    log("표 상태 " + p.grid_summary)
    cell, why = pick_cell(grid, target_date, preferred_hours)
    if cell is None:
        automation.capture(driver, diag, "no_capacity")
        return StepResult(False, why, "no_capacity", p,
                          {"grid": p.grid_summary,
                           "rows": [r.get("date") for r in grid.rows]})
    log(f"고른 칸: {why}")
    p.start_hour, p.cell_text, p.cell_capacity = cell.hour, cell.text, cell.capacity

    p.cell_selected = click_cell(driver, grid, cell, log)
    if not p.cell_selected:
        automation.capture(driver, diag, "cell_not_selected")
        return StepResult(False, "날짜 칸이 선택되지 않았습니다. 이 상태로는 예약하지 않습니다.",
                          "cell_not_selected", p)

    # 6단계: 추가. 준비를 다시 하는 경우 같은 이용일이 두 줄 생기면 안 되므로
    # 이미 그 날짜 행이 있으면 누르지 않는다.
    already = any(r.get("date") == target_date
                  for r in (read_slot_rows(driver).get("rows") or []))
    if already:
        log("선택표에 이미 그 이용일 행이 있어 [추가] 를 건너뜁니다.")
    elif not press_add(driver, log):
        automation.capture(driver, diag, "add_not_found")
        return StepResult(False, "[추가] 버튼을 찾지 못했습니다.", "no_add", p)

    # 7단계: 선택표 체크
    ticked, row_idx, row_text = tick_slot_row(driver, target_date, log)
    p.row_ticked, p.row_index, p.row_text = ticked, row_idx, row_text
    automation.capture(driver, diag, "after_add_and_tick")
    if not ticked:
        return StepResult(False, "선택표의 행을 체크하지 못했습니다. 이 상태로는 예약하지 않습니다.",
                          "row_not_ticked", p)

    return StepResult(True, "준비가 끝났습니다.", "prepared", p)


def open_modal(driver, p: Prepared, log=lambda *_: None, diag=None,
               deadline_local: float | None = None) -> StepResult:
    """8단계. [예약하기] 를 눌러 확인창을 열고 [확인] 을 조준한다.

    **불변식**: 칸이 선택돼 있고 선택표 행이 체크돼 있지 않으면 누르지 않는다.

    실패 코드가 두 갈래인 것이 중요하다.
      guard_* / no_reserve_button  → [예약하기] 를 **아직 누르지 않았다.**
                                     준비를 다시 해도 잃을 것이 없다.
      no_modal / no_modal_queue    → [예약하기] 를 **이미 눌렀다.**
                                     대기열 표를 쥐고 있으므로 여기서 준비를
                                     다시 하면 순번이 맨 뒤로 간다. 절대 금지.
    """
    if not p.cell_selected:
        return StepResult(False, "날짜 칸이 선택되지 않아 [예약하기] 를 누르지 않았습니다.",
                          "guard_cell", p)
    if not slot_row_is_ticked(driver, p.row_index):
        p.row_ticked = False
        return StepResult(False, "선택표 행 체크가 풀려 있어 [예약하기] 를 누르지 않았습니다.",
                          "guard_row", p)
    p.row_ticked = True

    if not press_reserve(driver, log):
        return StepResult(False, "[예약하기] 버튼을 찾지 못했습니다.", "no_reserve_button", p)

    text, saw_queue = wait_modal(driver, QUIET_MODAL_WAIT, log,
                                 deadline_local=deadline_local)
    p.modal_open = bool(text)
    p.modal_text = text
    if not text:
        from . import automation
        automation.capture(driver, diag, "modal_not_open")
        if saw_queue:
            q = queue_info(driver)
            return StepResult(
                False,
                "가상대기열에서 순번을 기다리는 중이라 예약 확인창이 아직 "
                "열리지 않았습니다. " + queue_line(q),
                "no_modal_queue", p, {"queue": q})
        return StepResult(False, "예약 확인창이 열리지 않았습니다.", "no_modal", p)

    p.armed = arm_confirm(driver, log)
    if not p.armed:
        return StepResult(False, "확인창은 열렸지만 [확인] 버튼을 잡지 못했습니다.",
                          "not_armed", p)
    try:
        from . import automation
        automation.capture(driver, diag, "modal_open_armed")
    except Exception:
        pass
    return StepResult(True, "예약 확인창을 열어두고 대기합니다.", "modal_armed", p)


def modal_still_held(driver, p: Prepared) -> bool:
    """대기 중에 확인창이 닫히거나 체크가 풀리지 않았는지 확인한다."""
    if not still_armed(driver):
        return False
    if not slot_row_is_ticked(driver, p.row_index):
        return False
    return True


# ---------------------------------------------------------------- 발사(9)

@dataclass
class ConfirmShot:
    attempt: int = 0
    arrival_offset_ms: float = 0.0
    fired: bool = False
    code: str = R_UNKNOWN
    text: str = ""

    def as_dict(self) -> dict:
        return {"attempt": self.attempt,
                "arrivalOffsetMs": round(self.arrival_offset_ms, 1),
                "fired": self.fired, "code": self.code,
                "text": (self.text or "")[:300]}


def confirm_once(driver, p: Prepared, clock, open_epoch: float,
                 attempt: int, log=lambda *_: None) -> ConfirmShot:
    """[확인] 한 발. 도착 추정 오프셋과 서버 문구를 그대로 기록한다."""
    shot = ConfirmShot(attempt=attempt)
    if not p.ready():
        log("불변식 위반으로 [확인] 을 누르지 않았습니다: " + "; ".join(p.blockers()))
        shot.code = R_FAIL
        shot.text = "안전 조건 미충족: " + "; ".join(p.blockers())
        return shot
    t_fire = time.time()
    shot.fired = fire_confirm(driver)
    shot.arrival_offset_ms = (clock.arrival_for_local_fire(t_fire) - open_epoch) * 1000.0
    if not shot.fired:
        p.armed = False
        p.modal_open = False
        shot.code = R_UNKNOWN
        shot.text = "확인 버튼이 사라져 누르지 못했습니다."
        log(shot.text)
        return shot
    code, text = read_outcome(driver)
    shot.code, shot.text = code, text
    log(f"[확인] {attempt}발째 · 도착 추정 정각 {shot.arrival_offset_ms:+.0f}ms "
        f"· 서버: {text or '(문구 없음)'} [{code}]")
    return shot


def redrive_confirm(driver, p: Prepared, log=lambda *_: None) -> bool:
    """'예약시간전' 을 맞은 뒤 확인 경로만 다시 세운다.

    앞단(검색/센터/반/시간/칸/추가)은 건드리지 않는다. 확인창이 닫혔으면
    체크 상태를 되살리고 [예약하기] → 확인창 → 조준까지만 다시 한다.
    """
    if still_armed(driver):
        return True
    p.modal_open = False
    p.armed = False
    if not slot_row_is_ticked(driver, p.row_index):
        ok, row_idx, row_text = tick_slot_row(driver, p.target_date, log)
        p.row_ticked, p.row_index, p.row_text = ok, row_idx, row_text
        if not ok:
            return False
    if not press_reserve(driver, log):
        return False
    text, _saw_queue = wait_modal(driver, 3.0, log)
    if not text:
        return False
    p.modal_open, p.modal_text = True, text
    p.armed = arm_confirm(driver, log)
    return p.armed


def confirm_burst(driver, p: Prepared, clock, open_epoch: float,
                  retry_seconds: int = 20, retry_ms: int = 90,
                  log=lambda *_: None, diag=None, stop_event=None) -> StepResult:
    """정각에 [확인] 을 쏘고, '예약시간전' 이면 열릴 때까지 즉시 재시도한다.

    - 예약시간전 → 아직 안 열렸다. 자리는 살아 있으니 곧바로 다시 쏜다.
                   그리고 이 문구로 남은 도착 추정을 보정한다.
    - 정원초과   → 그 칸은 나갔다. 두들기지 않고 멈춘다.
    """
    shots: list = []
    deadline = open_epoch + max(retry_seconds, 1)
    attempt = 0
    corrected = False
    while clock.server_now() < deadline:
        if stop_event is not None and stop_event.is_set():
            break
        attempt += 1
        shot = confirm_once(driver, p, clock, open_epoch, attempt, log)
        shots.append(shot)

        if shot.code == R_OK:
            return StepResult(True, shot.text or "예약이 완료되었습니다.", "reserved", p,
                              {"shots": [s.as_dict() for s in shots],
                               "confirmArrivalOffsetMs": round(shot.arrival_offset_ms, 1),
                               "confirmAttempts": attempt})
        if shot.code == R_FULL:
            return StepResult(False, shot.text or "정원이 초과되었습니다.", "full", p,
                              {"shots": [s.as_dict() for s in shots],
                               "confirmArrivalOffsetMs": round(shot.arrival_offset_ms, 1),
                               "confirmAttempts": attempt})
        if shot.code == R_NOT_BOOKABLE:
            # 사이트가 그 칸 자체를 거절했다("예약 가능 시간이 아닙니다" 등).
            # 다시 쏘면 정각의 남은 시간을 태울 뿐이라 여기서 멈춘다.
            return StepResult(False, shot.text or "예약할 수 없는 시간대입니다.",
                              "not_bookable", p,
                              {"shots": [s.as_dict() for s in shots],
                               "confirmArrivalOffsetMs": round(shot.arrival_offset_ms, 1),
                               "confirmAttempts": attempt})
        if shot.code == R_FAIL and not shot.fired:
            return StepResult(False, shot.text, "guard", p,
                              {"shots": [s.as_dict() for s in shots]})

        if shot.code == R_TOO_EARLY:
            if not corrected:
                delta = clock.note_too_early(shot.arrival_offset_ms / 1000.0)
                if delta:
                    corrected = True
                    log(f"'예약시간전' 응답으로 도착 추정을 {delta * 1000:+.0f}ms 보정했습니다.")
            if not redrive_confirm(driver, p, log):
                log("확인창을 다시 세우지 못했습니다.")
                break
            time.sleep(max(retry_ms, 20) / 1000.0)
            continue

        # unknown / 그 밖의 실패: 화면을 남기고 확인 경로만 다시 세워 재시도한다.
        try:
            from . import automation
            automation.capture(driver, diag, f"confirm_{attempt}_unknown")
        except Exception:
            pass
        if not redrive_confirm(driver, p, log):
            break
        time.sleep(max(retry_ms, 20) / 1000.0)

    last = shots[-1] if shots else ConfirmShot()
    return StepResult(False, last.text or "정해진 시간 안에 예약을 마치지 못했습니다.",
                      "exhausted", p,
                      {"shots": [s.as_dict() for s in shots],
                       "confirmAttempts": attempt,
                       "confirmArrivalOffsetMs": round(last.arrival_offset_ms, 1)})
