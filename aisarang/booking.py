# -*- coding: utf-8 -*-
"""시간제보육 예약 화면의 실제 조작 순서 (4·5단계).

이 파일의 근거는 추측이 아니라 **고객이 자기 인증서 세션을 직접 화면녹화해서
보내준 영상**이다 (2026-08-25, 51초, 프레임 증거: docs/site-map/recording/).
그 영상에서 읽어낸 순서를 그대로 코드로 옮겼다:

  1. 시간제보육신청 검색 화면
       구분 라디오(독립반/통합반) → 지역(시/도 + 시/군/구 2단 선택) → 조회
  2. 결과 목록에서 센터의 [시간제보육 예약] 버튼
  3. "시간제보육 아동 선택" — 아동 라디오 하나를 고르고 진행
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

# 사이트가 돌려주는 문구. 고객이 실제로 본 두 문구가 기준이고, 표기 흔들림
# (띄어쓰기/조사)까지 같이 잡는다.
TOO_EARLY_WORDS = ("예약시간전", "예약 시간 전", "예약시간이 아닙니다",
                   "예약가능시간이 아닙니다", "예약 가능 시간이 아닙니다",
                   "예약시간 전", "아직 예약", "예약시작")
FULL_WORDS = ("정원초과", "정원 초과", "정원이 초과", "정원이 마감",
              "마감되었습니다", "잔여 정원", "정원이 없습니다")
OK_WORDS = ("예약이 완료", "신청이 완료", "정상적으로 신청", "정상적으로 예약",
            "예약되었습니다", "신청되었습니다", "완료되었습니다")
FAIL_WORDS = ("이미 신청", "이미 예약", "중복", "불가", "실패", "초과합니다",
              "오류가 발생")

# 결과 코드
R_OK = "ok"
R_TOO_EARLY = "too_early"
R_FULL = "full"
R_FAIL = "fail"
R_UNKNOWN = "unknown"


def classify(text: str) -> str:
    """서버/화면 문구를 결과 코드로 바꾼다.

    순서가 중요하다. '정원초과' 안에 '초과' 가 들어 있어서 일반 실패 규칙보다
    먼저 봐야 하고, '예약시간전' 은 실패가 아니라 '아직 안 열렸다' 이다.
    """
    t = (text or "").replace(" ", " ")
    if not t.strip():
        return R_UNKNOWN
    for w in OK_WORDS:
        if w in t:
            return R_OK
    for w in TOO_EARLY_WORDS:
        if w in t:
            return R_TOO_EARLY
    for w in FULL_WORDS:
        if w in t:
            return R_FULL
    for w in FAIL_WORDS:
        if w in t:
            return R_FAIL
    return R_UNKNOWN


def result_is_retryable(code: str) -> bool:
    """다시 쏘는 게 의미 있는 결과인가. '예약시간전' 만 그렇다."""
    return code == R_TOO_EARLY


# ---------------------------------------------------------------- 자료구조

@dataclass
class Cell:
    date: str            # YYYYMMDD
    hour: int            # 9 ~ 18
    text: str            # 화면에 적힌 그대로 ("0", "2", "X")
    capacity: int | None  # 숫자면 남은 인원, X 면 None
    row: int
    col: int

    @property
    def blocked(self) -> bool:
        return self.capacity is None

    @property
    def available(self) -> bool:
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
# 선택자를 하드코딩하지 않는다. 녹화가 흐려서 id/class 를 읽을 수 없고,
# 서버가 인증서 세션에만 그려주는 화면이라 우리가 직접 볼 수도 없다.
# 그래서 "표의 첫 칸이 날짜인 표", "체크박스가 있는 표", "보이는 버튼의 글자"
# 같은 **구조와 글자**로 찾는다. 매 실행마다 DOM 전체를 올리므로 다음 판에서
# 좁힐 수 있다.

_JS_SCAN_GRID = r"""
function txt(e){ return ((e.innerText || e.textContent || '').replace(/\s+/g,' ')).trim(); }
function vis(e){
  if (!e) return false;
  var r = e.getBoundingClientRect();
  return r.width > 0 && r.height > 0;
}
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
      var head = headers[c] !== undefined ? headers[c] : '';
      var hm = head.match(/(\d{1,2})/);
      var hour = hm ? parseInt(hm[1], 10) : (8 + c);
      cells.push({date: date, hour: hour, text: txt(cs[c]), row: r, col: c});
    }
  }
  if (rows.length) {
    return {tableIndex: t, headers: headers, rows: rows, cells: cells};
  }
}
return null;
"""

# 칸의 '선택됨' 표시는 사이트마다 class 일 수도 style 일 수도 있다.
# 그래서 이름을 맞히지 않고, 클릭 전후의 지문을 비교해서 바뀐 칸을 센다.
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
    var inner = e.querySelector('a,button,span,div,input');
    var ist = inner ? window.getComputedStyle(inner) : null;
    out.push(r + ':' + c + '|' + (e.className || '') + '|' + st.backgroundColor +
             '|' + (inner ? (inner.className || '') : '') +
             '|' + (ist ? ist.backgroundColor : '') +
             '|' + (e.getAttribute('aria-selected') || '') +
             '|' + (inner && inner.checked ? '1' : '0'));
  }
}
return out;
"""

_JS_CLICK_CELL = r"""
var t = document.querySelectorAll('table')[arguments[0]];
if (!t) return false;
var trs = t.querySelectorAll('tr');
if (arguments[1] >= trs.length) return false;
var cs = trs[arguments[1]].querySelectorAll('th,td');
if (arguments[2] >= cs.length) return false;
var cell = cs[arguments[2]];
// 클릭 가능한 알맹이가 있으면 그것을, 없으면 칸 자체를 누른다.
var inner = cell.querySelector('a,button,input,label,span');
var target = inner || cell;
try { target.scrollIntoView({block: 'center'}); } catch (e) {}
target.click();
return true;
"""

# 선택표(선택/반명/이용일/이용시간). 주의: **아동 선택 표에도 라디오가 있다**
# (영상 r04). 그래서 "체크박스가 있는 첫 표" 로 잡으면 아동 표를 집는다.
# 점수를 매겨 "체크박스 + 이용일(날짜)" 를 가진 표를 우선한다.
_JS_SCAN_SLOT_ROWS = r"""
function txt(e){ return ((e.innerText || e.textContent || '').replace(/\s+/g,' ')).trim(); }
var tables = document.querySelectorAll('table');
var best = null;
for (var t = 0; t < tables.length; t++) {
  var tb = tables[t];
  var trs = tb.querySelectorAll('tr');
  var rows = [], dated = 0, boxes = 0;
  for (var r = 0; r < trs.length; r++) {
    var box = trs[r].querySelector("input[type=checkbox]");
    var kind = 'checkbox';
    if (!box) { box = trs[r].querySelector("input[type=radio]"); kind = 'radio'; }
    if (!box) continue;
    if (kind === 'checkbox') boxes++;
    var cs = trs[r].querySelectorAll('th,td');
    var texts = [];
    for (var c = 0; c < cs.length; c++) texts.push(txt(cs[c]));
    var joined = texts.join(' ');
    var m = joined.match(/(20\d\d)\D?(\d{2})\D?(\d{2})/);
    if (m) dated++;
    rows.push({row: r, checked: !!box.checked, kind: kind, texts: texts,
               text: joined, date: m ? (m[1] + m[2] + m[3]) : ''});
  }
  if (!rows.length) continue;
  // 이용일이 있는 표 > 체크박스인 표 > 그냥 라디오 표
  var score = dated * 10 + boxes * 3;
  if (best === null || score > best.score) {
    best = {score: score, tableIndex: t, rows: rows};
  }
}
if (!best) return null;
return {tableIndex: best.tableIndex, rows: best.rows};
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

# "예약" 모달. 제목/본문/버튼을 글자로 찾는다. 영상에서 확인한 본문은
# 월 60시간 초과 안내 + "예약하시겠습니까?" 이고 버튼은 확인 / 취소 두 개다.
_JS_MODAL = r"""
function txt(e){ return ((e.innerText || e.textContent || '').replace(/\s+/g,' ')).trim(); }
function vis(e){
  var r = e.getBoundingClientRect();
  if (r.width <= 0 || r.height <= 0) return false;
  var s = window.getComputedStyle(e);
  return s.visibility !== 'hidden' && s.display !== 'none' && s.opacity !== '0';
}
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
  var hasOk = false;
  var btns = e.querySelectorAll("button,a,input[type=button],input[type=submit],span[onclick]");
  for (var b = 0; b < btns.length; b++) {
    if (!vis(btns[b])) continue;
    var lb = txt(btns[b]) || (btns[b].value || '');
    if (lb.indexOf('확인') >= 0 || lb.toLowerCase() === 'ok') { hasOk = true; break; }
  }
  if (!hasOk) continue;
  // 가장 안쪽(=가장 짧은) 후보가 진짜 모달이다.
  if (best === null || body.length < best.len) best = {el: e, len: body.length, text: body};
}
if (!best) return null;
window.__aisarang_modal = best.el;
return {text: best.text};
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
var btns = m.querySelectorAll("button,a,input[type=button],input[type=submit],span[onclick]");
for (var i = 0; i < btns.length; i++) {
  if (!vis(btns[i])) continue;
  var lb = txt(btns[i]);
  if (lb.indexOf('취소') >= 0 || lb.indexOf('닫기') >= 0) continue;
  if (lb.indexOf('확인') >= 0 || lb.toLowerCase() === 'ok') { btn = btns[i]; break; }
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
var cands = document.querySelectorAll(
  "[role=dialog],[role=alertdialog],.layer,.layer_popup,.popup,.modal,.alert,.msg,.message");
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

def select_child(driver, child_name: str = "", log=lambda *_: None) -> str:
    """"시간제보육 아동 선택" 의 라디오를 고른다.

    영상 확인: 선택 / 아동명 / 생년월일 / 개월수 네 칸짜리 표에 라디오가 있고,
    아동이 하나면 이미 골라져 있다. 이름을 지정하면 그 행을, 아니면 첫 행을 고른다.
    """
    picked = _js(driver, r"""
    function txt(e){ return ((e.innerText || e.textContent || '').replace(/\s+/g,' ')).trim(); }
    var want = (arguments[0] || '').trim();
    var trs = document.querySelectorAll('tr');
    var fallback = null;
    for (var r = 0; r < trs.length; r++) {
      var box = trs[r].querySelector("input[type=radio]");
      if (!box) continue;
      var line = txt(trs[r]);
      if (!line) continue;
      if (fallback === null) fallback = {box: box, line: line};
      if (want && line.indexOf(want) >= 0) {
        if (!box.checked) box.click();
        return line;
      }
    }
    if (fallback) {
      if (!fallback.box.checked) fallback.box.click();
      return fallback.line;
    }
    return null;
    """, child_name, default=None)
    if picked:
        log(f"아동 선택: {picked}")
        # 아동을 고른 뒤 진행 버튼이 있으면 누른다(영상의 파란 버튼).
        for label in ("시간제보육 예약", "시간제보육예약", "다음", "확인", "선택"):
            if _js(driver, _JS_CLICK_TEXT_BUTTON, label, None):
                log(f"'{label}' 로 진행했습니다.")
                time.sleep(1.2)
                break
        return str(picked)
    log("아동 선택 화면이 아닙니다(건너뜁니다).")
    return ""


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
    // 1) 라벨이 '반명' 인 select 를 먼저
    var target = null;
    for (var i = 0; i < sels.length; i++) {
      var row = sels[i].closest('tr,div,li');
      var line = row ? (row.innerText || '') : '';
      for (var w = 0; w < labelWords.length; w++) {
        if (line.indexOf(labelWords[w]) >= 0) { target = sels[i]; break; }
      }
      if (target) break;
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
    var target = null;
    for (var i = 0; i < sels.length; i++) {
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
                            col=int(c.get("col", -1))))
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
             default=False)
    if not ok:
        log("날짜 칸을 누르지 못했습니다.")
        return False
    time.sleep(0.35)
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


def press_add(driver, log=lambda *_: None) -> bool:
    hit = _js(driver, _JS_CLICK_TEXT_BUTTON, "추가", None)
    log("[추가] 를 눌렀습니다." if hit else "[추가] 버튼을 찾지 못했습니다.")
    time.sleep(0.6)
    return bool(hit)


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
        target = rows[-1]
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
    hit = _js(driver, _JS_CLICK_TEXT_BUTTON, "예약하기", None)
    if not hit:
        hit = _js(driver, _JS_CLICK_TEXT_BUTTON, "신청하기", None)
    log(f"[{hit}] 를 눌렀습니다." if hit else "[예약하기] 버튼을 찾지 못했습니다.")
    return bool(hit)


def modal_info(driver) -> dict:
    return _js(driver, _JS_MODAL, default=None) or {}


def wait_modal(driver, timeout: float = 8.0, log=lambda *_: None) -> str:
    """예약 확인창이 뜰 때까지 기다린다. 뜬 본문을 돌려준다."""
    end = time.time() + timeout
    while time.time() < end:
        info = modal_info(driver)
        if info.get("text"):
            log("예약 확인창이 열렸습니다: " + info["text"][:80])
            return str(info["text"])
        time.sleep(0.2)
    return ""


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
    p.child_name = select_child(driver, child_name, log) or child_name
    automation.capture(driver, diag, "after_child_select")

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


def open_modal(driver, p: Prepared, log=lambda *_: None, diag=None) -> StepResult:
    """8단계. [예약하기] 를 눌러 확인창을 열고 [확인] 을 조준한다.

    **불변식**: 칸이 선택돼 있고 선택표 행이 체크돼 있지 않으면 누르지 않는다.
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

    text = wait_modal(driver, 8.0, log)
    p.modal_open = bool(text)
    p.modal_text = text
    if not text:
        from . import automation
        automation.capture(driver, diag, "modal_not_open")
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
    text = wait_modal(driver, 3.0, log)
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
