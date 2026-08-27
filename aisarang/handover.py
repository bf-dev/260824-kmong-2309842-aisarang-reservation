# -*- coding: utf-8 -*-
"""인계 모드: 사람이 확인창까지 만들어 두면 프로그램은 [확인] 만 누른다.

왜 이 모드가 생겼나 (2026-08-26, 고객이 그날 예약을 놓쳤다)
------------------------------------------------------------------
v1.0.7 은 정각 240초 전에 검색부터 [예약하기] 까지 스스로 걸었다. 그런데
09시 직전의 사이트는 [예약하기] 를 누른 사람을 **가상대기열(넷퍼널)** 에
세운다. 확인창은 그 순번이 올 때까지 열리지 않는다. 우리 코드는 8초를 기다린
뒤 `no_modal` 로 판단하고 **검색 화면부터 준비를 통째로 다시** 했다.
대기열 레이어가 스스로 이렇게 적어 놓았는데도 그랬다:

    ※ 재접속하시면 대기시간이 더 길어집니다.

고객 캡처 세 장에 그 대가가 그대로 남았다 (앞에 선 사람 수 / 예상 대기):

    1회차  72명   2분 10초
    2회차  138명  3분 50초
    3회차  177명  4분 32초

고객 원문:
    "예약이 원래대로 안되니까 프로그램은 다시 처음부터 다시 아동선택을 하게
     되고 그게 반복되서 오늘은 결국 못했네요"
    "제가 아동선택부터 시간선택까지 모두 끝내놓으면 프로그램은 확인만 누르는
     방식을 변경 요청드립니다."

이 모듈이 그 요청이다.

이 모드가 하는 일과 하지 않는 일
------------------------------------------------------------------
하는 일은 하나뿐이다. **이미 열려 있는 예약 확인창의 [확인] 을 정각에 맞춰
누르는 것.** 도착 기준 조준, '예약시간전' 재발사, '정원초과' 즉시 중단은
자동 모드와 완전히 같다.

하지 않는 일: 화면 이동, 검색, 센터 열기, 아동/반/시간 선택, 칸 클릭,
[추가], 체크박스. **이 파일에는 그 코드가 존재하지 않는다.**
`tests/test_handover.py::test_handover_has_no_way_to_touch_the_page_except_the_final_confirm`
가 소스에 `.click(` / `.submit(` / `send_keys` / `ActionChains` /
`dispatchEvent` / `driver.get` 이 없다는 것을 못박는다.

v1.0.9 에서 이 목록이 딱 한 칸 넓어졌다 (2026-08-27 실전 실패의 결과)
------------------------------------------------------------------
[예약하기] 를 다시 누르는 길이 하나 생겼다. **'예약시간전' 응답 뒤에만.**
그날 09:00:00 에 우리는 정각 296ms 전에 도착했고, 서버는 그 한 발을
"아직 예약 가능한 시간이 아닙니다." 로 버렸다. 확인창은 그 클릭에 소비돼
사라졌고, v1.0.8 에는 거기서 할 수 있는 일이 없었다. 자리는 살아 있는데
쏠 창이 없었다.

사이트 스크립트 실물이 확인창을 여는 길은 `fnSave()` 하나뿐임을 보여준다
(booking.py 의 v1.0.9 주석에 원문이 있다). 그래서 되살리는 방법은
[예약하기] 재클릭밖에 없고, 그 클릭은 곧 가상대기열 진입이다. 그래서
`_Reopen` 이 여덟 개 조건을 전부 통과할 때만 열린다. 특히 대기열을 한 번이라도
보면 **영구히 잠긴다**. 테스트는 이제 "누를 수 있는 코드가 없다" 가 아니라
"[예약하기] 와 결과 알림 닫기, 그 둘 말고는 없다" 를 못박는다.

이 파일에서 페이지를 건드리는 booking 함수는 정확히 셋뿐이다.
`fire_confirm` (발사), `repress_reserve_button` (되살리기),
`close_result_alert` (되살리기 직전 알림 닫기).

안전 불변식이 달라졌다 (제일 중요한 변경)
------------------------------------------------------------------
자동 모드의 `Prepared.ready()` 는 **우리가 우리 클릭으로 세운 플래그**를 본다
(`cell_selected` 는 `click_cell` 안에서만 참이 되고 그 뒤로 다시 계산되지
않는다). 사람이 손으로 만든 화면에서는 그 플래그가 영원히 거짓이라, 그대로
두면 인계 모드는 **절대 쏘지 못한다.**

그래서 여기서는 발사 직전에 **살아 있는 페이지에서 다시 읽는다**:

  1. 예약 확인창이 실제로 떠 있는가            (보이는 #layer-confirm-popup2)
  2. 그 안의 [확인] 버튼이 실제로 보이는가      (#layer-confirm-popup-confirm2)
  3. 확인창 본문이 예약 질문인가                ("...하시겠습니까")
  4. 선택표 행의 체크가 지금도 켜져 있는가      (#INFOQUALF 의 checkbox)

하나라도 거짓이면 **누르지 않는다.** 이 서비스는 취소가 전화로만 되므로,
잘못된 예약은 놓친 예약보다 나쁘다. 그래서 막히는 쪽으로 실패한다.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from . import booking

# ---------------------------------------------------------------- 화면 읽기
#
# 한 번의 execute_script 로 발사에 필요한 모든 판정을 끝낸다. 발사 순간에
# 왕복을 여러 번 하면 그 시간이 곧 오차이기 때문이다. 이 스크립트는 읽기만
# 하고, 찾은 [확인] 버튼을 window 에 물려두기만 한다(누르지 않는다).
#
# 선택자의 근거는 전부 고객 캡처 실물이다(NOTES.md v1.0.7 절):
#   확인창 껍데기가 페이지에 **두 벌** 있고 id 가 중복이므로 getElementById 는
#   쓸 수 없다. querySelectorAll + 가시성으로 고른다.
#   최종 [확인] 은 -confirm 이 아니라 **-confirm2** 다(layerpopup.js 의
#   confirm2 가 콜백을 묶는 대상).
#   대기열 레이어는 #NetFunnel_Loading_Popup 이고 안에
#   #NetFunnel_Loading_Popup_Count(앞) / _NextCnt(뒤) / _TimeLeft(예상)
#   가 들어 있다 (2026-08-26 실패 캡처 실물).
_JS_HANDOVER_STATE = r"""
function txt(e){ return ((e.innerText || e.textContent || '').replace(/\s+/g,' ')).trim(); }
function vis(e){
  if (!e) return false;
  var r = e.getBoundingClientRect();
  if (r.width <= 0 || r.height <= 0) return false;
  var s = window.getComputedStyle(e);
  return s.visibility !== 'hidden' && s.display !== 'none' && s.opacity !== '0';
}
function okIn(e) {
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

var out = {
  modal: false, modalText: '', modalHow: '',
  confirm: false, confirmId: '',
  rows: 0, ticked: 0, rowText: '', rowDate: '',
  queue: false, queueAhead: null, queueBehind: null, queueEta: '', queueProgress: '',
  onReservePage: false, url: ''
};
try { out.url = String(document.location.href || ''); } catch (e) {}

// --- 예약 화면 위에 있는가. 확인창만 보고 쏘지 않기 위한 배경 조건이다.
out.onReservePage = !!document.getElementById('timecareConfirm')
                 || !!document.getElementById('INFOQUALF')
                 || !!document.getElementById('crtminfo');

// --- 대기열(넷퍼널). 실패가 아니라 '기다리면 되는 상태' 다.
var qs = document.querySelectorAll("[id='NetFunnel_Loading_Popup']");
for (var i = 0; i < qs.length; i++) {
  if (!vis(qs[i])) continue;
  out.queue = true;
  var a = qs[i].querySelector("[id='NetFunnel_Loading_Popup_Count']");
  var b = qs[i].querySelector("[id='NetFunnel_Loading_Popup_NextCnt']");
  var t = qs[i].querySelector("[id='NetFunnel_Loading_Popup_TimeLeft']");
  var p = qs[i].querySelector("[id='Progress_Print']");
  if (a && /^\d+$/.test(txt(a))) out.queueAhead = parseInt(txt(a), 10);
  if (b && /^\d+$/.test(txt(b))) out.queueBehind = parseInt(txt(b), 10);
  if (t) out.queueEta = txt(t);
  if (p) out.queueProgress = txt(p);
  break;
}
if (!out.queue) {
  // 넷퍼널 스킨이 바뀌었을 때를 위한 글자 경로. 레이어 문구는 실물 그대로다.
  var all = document.querySelectorAll("div,section");
  for (var i = 0; i < all.length; i++) {
    if (!vis(all[i])) continue;
    var s = txt(all[i]);
    if (s.length > 800) continue;
    if (s.indexOf('대기 중입니다') >= 0 && s.indexOf('대기자가 있습니다') >= 0) {
      out.queue = true;
      var m = s.match(/앞에\s*(\d+)\s*명/);
      if (m) out.queueAhead = parseInt(m[1], 10);
      var m2 = s.match(/뒤에\s*(\d+)\s*명/);
      if (m2) out.queueBehind = parseInt(m2[1], 10);
      var m3 = s.match(/예상대기시간\s*:?\s*([^*]{0,20})/);
      if (m3) out.queueEta = m3[1].trim();
      break;
    }
  }
}

// --- 선택표 행 체크. 사람이 손으로 켠 것을 우리가 다시 읽는다.
//     (page_source 로는 알 수 없다. click 은 attribute 가 아니라 property 를
//      바꾸므로, 살아 있는 DOM 에서 .checked 를 직접 봐야 한다.)
var tbl = document.getElementById('INFOQUALF');
var trs = tbl ? tbl.querySelectorAll('tr') : [];
for (var r = 0; r < trs.length; r++) {
  var box = trs[r].querySelector("input[type=checkbox]");
  if (!box) continue;
  out.rows++;
  if (!box.checked) continue;
  out.ticked++;
  if (out.rowText) continue;
  var parts = [];
  var cs = trs[r].querySelectorAll('th,td');
  for (var c = 0; c < cs.length; c++) {
    var t2 = txt(cs[c]);
    if (t2) parts.push(t2);
    var ins = cs[c].querySelectorAll('input');
    for (var k = 0; k < ins.length; k++) {
      var ty = (ins[k].type || '').toLowerCase();
      if (ty === 'checkbox' || ty === 'radio' || ty === 'button' || ty === 'hidden') continue;
      var v = (ins[k].value || '').replace(/\s+/g, ' ').trim();
      if (v && parts.indexOf(v) < 0) parts.push(v);
    }
  }
  out.rowText = parts.join(' ');
  var hid = trs[r].querySelector("input[id^=resdt]");
  if (hid && /^\d{8}$/.test(hid.value || '')) out.rowDate = hid.value;
}
// 사이트가 바뀌어 #INFOQUALF 가 없어졌을 때. 체크된 체크박스가 있고 그 줄에
// 이용시간 구간이 보이면 선택표 행으로 친다. 아동 표(개월수)는 배제한다.
if (!tbl) {
  var trs2 = document.querySelectorAll('table tr');
  for (var r = 0; r < trs2.length; r++) {
    var box2 = trs2[r].querySelector("input[type=checkbox]");
    if (!box2) continue;
    var line = txt(trs2[r]);
    var ins2 = trs2[r].querySelectorAll('input');
    for (var k = 0; k < ins2.length; k++) line += ' ' + (ins2[k].value || '');
    if (/\d+\s*개\s*월/.test(line)) continue;
    if (!/\d{1,2}\s*[:시]\s*\d{2}/.test(line)) continue;
    out.rows++;
    if (!box2.checked) continue;
    out.ticked++;
    if (!out.rowText) out.rowText = line.replace(/\s+/g, ' ').trim();
  }
}

// --- 예약 확인창. 보이는 껍데기 한 벌만 고른다.
var shells = document.querySelectorAll("[id='layer-confirm-popup2']");
for (var i = 0; i < shells.length; i++) {
  var e = shells[i];
  if (!vis(e)) continue;
  var bodyEl = null;
  var ps = e.querySelectorAll("[id='layer-confirm-popup-contents2']");
  for (var k = 0; k < ps.length; k++) { if (txt(ps[k])) { bodyEl = ps[k]; break; } }
  var body = bodyEl ? txt(bodyEl) : txt(e);
  if (!body) continue;
  var ok = okIn(e);
  out.modal = true; out.modalText = body; out.modalHow = 'layer-confirm-popup2';
  out.confirm = !!ok;
  out.confirmId = ok ? (ok.id || '') : '';
  if (ok) { window.__aisarang_modal = e; }
  break;
}
// 사이트가 바뀌었을 때. 예전처럼 글자로 가장 안쪽 후보를 찾는다.
if (!out.modal) {
  var best = null;
  var cands = document.querySelectorAll(
    "div,section,dialog,[role=dialog],[role=alertdialog],.layer,.popup,.modal");
  for (var i = 0; i < cands.length; i++) {
    var e2 = cands[i];
    if (!vis(e2)) continue;
    var b2 = txt(e2);
    if (!b2 || b2.length > 1500) continue;
    if (b2.indexOf('하시겠습니까') < 0) continue;
    if (!okIn(e2)) continue;
    if (best === null || b2.length < best.len) best = {el: e2, len: b2.length, text: b2};
  }
  if (best) {
    var ok2 = okIn(best.el);
    out.modal = true; out.modalText = best.text; out.modalHow = 'text';
    out.confirm = !!ok2; out.confirmId = ok2 ? (ok2.id || '') : '';
    if (ok2) { window.__aisarang_modal = best.el; }
  }
}

// --- 조준은 여기서 하지 않는다.
// window.__aisarang_modal 만 물려두고, 실제 조준(=발사 함수를 만드는 일)은
// booking._JS_ARM 이 한다. 그래야 **누를 수 있는 코드가 이 파일에 한 줄도
// 없다**는 것을 소스로 증명할 수 있다(tests/test_handover.py).
return out;
"""

# 확인창이 없을 때 옛 조준을 확실히 버린다. 화면이 바뀌었는데 낡은 손잡이가
# 남아 있으면 그것만으로 잘못 쏠 여지가 생긴다. 이 조각도 누르지 않는다.
_JS_DISARM = r"""
window.__aisarang_ok = null;
window.__aisarang_modal = null;
window.__aisarang_ok_hint = null;
return true;
"""


# ---------------------------------------------------------------- 상태

# 확인창 본문이 '예약 질문' 인지 본다. 실물 본문의 마지막 줄이
# "예약하시겠습니까?" 다(사이트 fnSave 의 confirmText 기본값). 60시간 초과
# 안내가 앞에 붙어도 마지막 줄은 그대로다.
ASK_WORDS = ("예약하시겠습니까", "신청하시겠습니까", "하시겠습니까")


@dataclass
class LiveState:
    """살아 있는 페이지에서 방금 다시 읽은 상태. 플래그를 기억하지 않는다."""
    modal: bool = False
    modal_text: str = ""
    modal_how: str = ""
    confirm: bool = False
    confirm_id: str = ""
    rows: int = 0
    ticked: int = 0
    row_text: str = ""
    row_date: str = ""
    queue: bool = False
    queue_ahead: int | None = None
    queue_behind: int | None = None
    queue_eta: str = ""
    queue_progress: str = ""
    on_reserve_page: bool = False
    armed: bool = False
    url: str = ""
    error: str = ""

    @property
    def asks(self) -> bool:
        t = self.modal_text or ""
        return any(w in t for w in ASK_WORDS)

    def ready(self) -> bool:
        """발사해도 되는가. 전부 이번 왕복에서 페이지로부터 다시 읽은 값이다."""
        return bool(self.modal and self.confirm and self.armed
                    and self.asks and self.ticked > 0)

    def blockers(self) -> list:
        out = []
        if not self.modal:
            out.append("예약 확인창이 화면에 없습니다")
        elif not self.asks:
            out.append("확인창이 예약 확인창이 아닙니다")
        if self.modal and not self.confirm:
            out.append("확인창 안에서 [확인] 버튼을 찾지 못했습니다")
        if self.modal and self.confirm and not self.armed:
            out.append("[확인] 버튼을 조준하지 못했습니다")
        if self.ticked <= 0:
            out.append("선택표 행의 체크가 켜져 있지 않습니다")
        if self.error:
            out.append(f"화면을 읽지 못했습니다({self.error})")
        return out

    def queue_line(self) -> str:
        bits = []
        if self.queue_ahead is not None:
            bits.append(f"앞에 {self.queue_ahead}명")
        if self.queue_behind is not None:
            bits.append(f"뒤에 {self.queue_behind}명")
        if self.queue_eta:
            bits.append(f"예상 {self.queue_eta}")
        return "가상대기열 대기 중" + (" (" + ", ".join(bits) + ")" if bits else "")

    def as_dict(self) -> dict:
        return {
            "modal": self.modal, "confirm": self.confirm, "armed": self.armed,
            "asks": self.asks, "modalHow": self.modal_how,
            "confirmId": self.confirm_id,
            "modalText": (self.modal_text or "")[:300],
            "rows": self.rows, "ticked": self.ticked,
            "rowText": (self.row_text or "")[:200], "rowDate": self.row_date,
            "queue": self.queue, "queueAhead": self.queue_ahead,
            "queueBehind": self.queue_behind, "queueEta": self.queue_eta,
            "queueProgress": self.queue_progress,
            "onReservePage": self.on_reserve_page,
            "ready": self.ready(), "error": self.error,
        }


def read_state(driver) -> LiveState:
    """페이지를 한 번 읽어 상태를 만들고, 확인창이 있으면 조준까지 해둔다.

    조준은 `booking._JS_ARM` 이 한다(누를 수 있는 코드는 전부 booking.py 에
    모여 있다). 확인창이 없으면 옛 조준을 버린다. 어떤 경우에도 예외를
    던지지 않는다.
    """
    try:
        raw = driver.execute_script(_JS_HANDOVER_STATE)
    except Exception as exc:  # noqa: BLE001
        return LiveState(error=type(exc).__name__)
    if not isinstance(raw, dict):
        return LiveState(error="no_state")

    armed = False
    try:
        if raw.get("modal") and raw.get("confirm"):
            armed = bool(driver.execute_script(booking._JS_ARM))
        else:
            driver.execute_script(_JS_DISARM)
    except Exception as exc:  # noqa: BLE001
        return LiveState(error=type(exc).__name__)

    return LiveState(
        modal=bool(raw.get("modal")), modal_text=str(raw.get("modalText") or ""),
        modal_how=str(raw.get("modalHow") or ""),
        confirm=bool(raw.get("confirm")), confirm_id=str(raw.get("confirmId") or ""),
        rows=int(raw.get("rows") or 0), ticked=int(raw.get("ticked") or 0),
        row_text=str(raw.get("rowText") or ""), row_date=str(raw.get("rowDate") or ""),
        queue=bool(raw.get("queue")),
        queue_ahead=raw.get("queueAhead"), queue_behind=raw.get("queueBehind"),
        queue_eta=str(raw.get("queueEta") or ""),
        queue_progress=str(raw.get("queueProgress") or ""),
        on_reserve_page=bool(raw.get("onReservePage")),
        armed=armed, url=str(raw.get("url") or ""),
    )


# ---------------------------------------------------------------- 대기 감시

# 화면을 얼마나 자주 다시 읽을지. 고객이 [예약하기] 를 누른 그 순간
# "확인창 감지됨" 으로 바뀌어야 하므로 짧게 잡는다.
POLL_SECONDS = 0.5
# 로그를 도배하지 않으면서 대기열 순번은 보이게. 같은 상태면 이 간격으로만 적는다.
LOG_EVERY_SECONDS = 15.0


def describe(state: LiveState) -> str:
    """고객이 화면에서 읽을 한 줄. 사진으로 찍어 보내는 그 줄이다."""
    if state.error:
        return f"화면을 읽지 못했습니다 ({state.error})"
    if state.queue:
        return state.queue_line() + " · 확인창을 기다립니다"
    if state.ready():
        return "확인창 감지됨 · 선택표 체크 켜짐 · 정각에 [확인] 을 누릅니다"
    if state.modal and not state.asks:
        return "확인창이 떠 있지만 예약 확인창이 아닙니다"
    if state.modal and state.ticked <= 0:
        return "확인창 감지됨 · 선택표 체크가 꺼져 있습니다"
    if state.modal:
        return "확인창 감지됨 · [확인] 버튼을 잡지 못했습니다"
    if state.ticked > 0:
        return "선택표 체크 켜짐 · 확인창 없음 ([예약하기] 를 눌러주세요)"
    return "확인창 없음 · 크롬 창에서 예약 확인창까지 진행해 주세요"


class Watcher:
    """정각까지 화면을 계속 다시 읽으면서 상태를 바깥으로 흘려보낸다.

    누르지 않는다. 읽고, 조준하고, 알려주기만 한다.
    """

    def __init__(self, driver, log=lambda *_: None, on_state=lambda *_: None):
        self.driver = driver
        self.log = log
        self.on_state = on_state
        self.state = LiveState()
        self._last_line = ""
        self._last_log = 0.0
        self._seen_ready = False
        self._seen_queue = False

    def poll(self) -> LiveState:
        st = read_state(self.driver)
        self.state = st
        try:
            self.on_state(st)
        except Exception:
            pass
        self._maybe_log(st)
        return st

    def _maybe_log(self, st: LiveState) -> None:
        line = describe(st)
        now = time.time()
        changed = line != self._last_line
        if not changed and (now - self._last_log) < LOG_EVERY_SECONDS:
            return
        self._last_line, self._last_log = line, now
        if st.queue and not self._seen_queue:
            self._seen_queue = True
            self.log("사이트가 가상대기열을 띄웠습니다. 예약 확인창은 순번이 "
                     "올 때까지 열리지 않습니다. 그대로 기다립니다.")
            self.log("이 화면에서는 새로고침하거나 다시 [예약하기] 를 누르지 "
                     "마세요. 대기열 맨 뒤로 갑니다.")
        if st.ready() and not self._seen_ready:
            self._seen_ready = True
            self.log(f"확인창을 감지했습니다: {(st.modal_text or '')[:60]}")
            self.log(f"선택표 체크 확인: {(st.row_text or '')[:80]}")
        self.log(line)

    def wait_until(self, local_deadline: float, stop_event=None) -> LiveState:
        """로컬 시각 local_deadline 까지 계속 읽는다. 마지막 상태를 돌려준다."""
        while True:
            if stop_event is not None and stop_event.is_set():
                return self.state
            remain = local_deadline - time.time()
            if remain <= 0:
                return self.state
            self.poll()
            remain = local_deadline - time.time()
            if remain <= 0:
                return self.state
            wait = min(POLL_SECONDS, remain)
            if stop_event is not None:
                if stop_event.wait(wait):
                    return self.state
            else:
                time.sleep(wait)


# ---------------------------------------------------------------- 발사

def fire(driver) -> bool:
    """조준해둔 [확인] 을 누른다. 이 프로그램이 이 모드에서 하는 유일한 조작."""
    return booking.fire_confirm(driver)


@dataclass
class HandoverShot:
    attempt: int = 0
    arrival_offset_ms: float = 0.0
    fired: bool = False
    code: str = booking.R_UNKNOWN
    text: str = ""
    blockers: list = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"attempt": self.attempt,
                "arrivalOffsetMs": round(self.arrival_offset_ms, 1),
                "fired": self.fired, "code": self.code,
                "text": (self.text or "")[:300],
                "blockers": list(self.blockers)}


# [확인] 이후 서버 답을 기다리는 시간. 자동 모드는 6초지만 여기서는 재발사
# 간격을 짧게 유지해야 해서 더 짧게 본다. 답이 오면 그 자리에서 돌아온다.
OUTCOME_TIMEOUT = 1.6


class _Reopen:
    """'예약시간전' 을 맞았을 때만 확인창을 되살리는 문(v1.0.9).

    2026-08-27 09:00:00 에 배운 것: 확인창은 [확인] 한 번에 소비된다. 서버가
    "아직 예약 가능한 시간이 아닙니다." 로 답한 뒤에는 확인창이 사라지고,
    v1.0.8 은 그 자리에서 할 수 있는 일이 없었다. 한 발이 전부였다.

    그런데 그 응답만은 특별하다. **자리는 아직 살아 있고 우리가 이르기만 했다.**
    이때에 한해 [예약하기] 를 다시 눌러 확인창을 되살리는 것이 허용된다.

    허용 조건은 전부 참이어야 한다. 하나라도 아니면 누르지 않는다.
      1. 방금 우리가 쏜 한 발의 분류가 정확히 `too_early` 다.
         (정원초과 / 칸 거절 / 미분류 / 아무것도 안 쏜 상태 → 금지)
      2. 실제로 한 발 이상 쐈다.
      3. 확인창이 지금 화면에 없다(있으면 그냥 다시 쏘면 된다).
      4. 아직 예약 화면 위에 있고 선택표 체크가 그대로 켜져 있다.
      5. 가상대기열 레이어가 떠 있지 않다.
      6. 정각을 지났고, 마감(reopen_seconds) 전이다.
      7. 남은 횟수가 있다.
      8. 잠기지 않았다. 한 번이라도 대기열을 보면 영구히 잠근다.

    8번이 이 판의 핵심이다. [예약하기] 는 곧 `NetFunnel_Action`, 즉 대기열
    진입이다(실물 스크립트). 대기열이 떴다면 다시 누르는 것은 순번을 맨 뒤로
    보내는 짓이고, 2026-08-26 에 그것이 72명 → 138명 → 177명을 만들었다.
    """

    def __init__(self, clock, open_epoch: float, max_times: int, seconds: float):
        self.clock = clock
        self.open_epoch = open_epoch
        self.max_times = max(int(max_times), 0)
        self.seconds = max(float(seconds), 0.0)
        self.used = 0
        self.locked = False
        self.lock_reason = ""
        self.pressed = False
        self.last_code = ""

    def lock(self, why: str) -> None:
        if not self.locked:
            self.locked = True
            self.lock_reason = why

    def note_outcome(self, code: str) -> None:
        self.last_code = code or ""
        if code and code != booking.R_TOO_EARLY:
            self.lock(f"결과가 {code} 입니다")

    def allowed(self, st: LiveState) -> bool:
        if self.locked or self.used >= self.max_times:
            return False
        if self.last_code != booking.R_TOO_EARLY:
            return False
        if st.queue or st.modal:
            return False
        if not st.on_reserve_page or st.ticked <= 0:
            return False
        now = self.clock.server_now()
        return self.open_epoch <= now < self.open_epoch + self.seconds

    def why_not(self, st: LiveState) -> str:
        if self.locked:
            return self.lock_reason or "다시 누르지 않기로 잠겼습니다"
        if self.used >= self.max_times:
            return f"확인창 되살리기를 {self.max_times}번 다 썼습니다"
        if self.last_code != booking.R_TOO_EARLY:
            return "'예약시간전' 응답이 아닙니다"
        if st.queue:
            return "가상대기열이 떠 있습니다"
        if not st.on_reserve_page or st.ticked <= 0:
            return "예약 화면/선택표 체크가 그대로가 아닙니다"
        return "되살리기 마감 시각을 지났습니다"

    def do(self, driver, log) -> bool:
        """알림을 닫고 [예약하기] 를 정확히 한 번 다시 누른다."""
        self.used += 1
        self.last_code = ""          # 다음 되살리기는 새 '예약시간전' 이 있어야 한다
        booking.close_result_alert(driver, log)
        ok = booking.repress_reserve_button(driver, log)
        self.pressed = True
        if not ok:
            self.lock("[예약하기] 를 찾지 못했습니다")
            return False
        log(f"확인창 되살리기 {self.used}/{self.max_times}회차. "
            f"대기열이 뜨면 그대로 기다리고 다시 누르지 않습니다.")
        return True

    def as_dict(self) -> dict:
        return {"used": self.used, "max": self.max_times,
                "locked": self.locked, "lockReason": self.lock_reason,
                "pressedReserveAgain": self.pressed}


def burst(driver, clock, open_epoch: float, watcher: Watcher,
          retry_seconds: int = 20, retry_ms: int = 90,
          log=lambda *_: None, diag=None, stop_event=None,
          preflight: "LiveState | None" = None,
          reopen_max: int = 2, reopen_seconds: float = 15.0) -> booking.StepResult:
    """정각에 [확인] 을 쏘고, 필요하면 다시 쏜다. 그 외에는 아무것도 누르지 않는다.

    자동 모드의 `booking.confirm_burst` 와 판정은 같다.
      예약시간전 → 아직 안 열렸다. 자리는 살아 있으니 곧바로 다시 쏜다.
                   그리고 이 응답으로 도착 추정을 보정한다.
      정원초과   → 그 칸은 나갔다. 두들기지 않고 멈춘다.
      칸 거절    → 사이트가 그 칸 자체를 막았다. 멈춘다.

    확인창이 닫혀 버렸을 때가 다르다. 자동 모드는 무조건 [예약하기] 를 다시
    눌러 창을 되살린다. 여기서는 **서버가 '예약시간전' 이라고 답했을 때에만**
    그렇게 한다(`_Reopen` 참고). [예약하기] 는 가상대기열 진입이라, 아무 때나
    다시 누르면 순번이 맨 뒤로 간다(2026-08-26 실측: 72명 → 138명 → 177명).
    되살릴 수 없는 상황이면 사람에게 알리고, 창이 다시 열리는지 읽기만 한다.

    `preflight` 는 발사 직전(수십 ms 전)에 이미 다시 읽어둔 상태다. 첫 발은
    그것을 그대로 쓴다. 첫 발만은 화면을 한 번 더 읽느라 조준 시각을 늦출 수
    없기 때문이다. 그 뒤로는 매 발마다 다시 읽는다.
    """
    shots: list = []
    deadline = open_epoch + max(retry_seconds, 1)
    attempt = 0
    corrected = False
    told_closed = False
    pending = preflight
    reopen = _Reopen(clock, open_epoch, reopen_max, reopen_seconds)

    while clock.server_now() < deadline:
        if stop_event is not None and stop_event.is_set():
            break
        if pending is not None:
            st, pending = pending, None
        else:
            st = watcher.poll()

        if not st.ready():
            if st.queue:
                # 정각을 넘겨 대기열에 잡혀 있을 수도 있다. 기다리는 게 맞다.
                # 우리가 되살리려고 누른 뒤에 뜬 것이라면 여기서 영구히 잠근다.
                if reopen.pressed:
                    reopen.lock("가상대기열에 섰습니다(다시 누르면 맨 뒤로 갑니다)")
                time.sleep(max(retry_ms, 50) / 1000.0)
                continue
            if reopen.allowed(st):
                told_closed = False
                reopen.do(driver, log)
                time.sleep(max(retry_ms, 50) / 1000.0)
                continue
            if not told_closed:
                told_closed = True
                log("[확인] 을 누를 수 없는 상태입니다: " + "; ".join(st.blockers()))
                log("이 모드는 [예약하기] 를 대신 누르지 않습니다(대기열 맨 뒤로 "
                    f"갑니다: {reopen.why_not(st)}). 크롬 창에서 확인창을 다시 "
                    "열어주시면 곧바로 누릅니다.")
            time.sleep(max(retry_ms, 50) / 1000.0)
            continue
        told_closed = False

        attempt += 1
        shot = HandoverShot(attempt=attempt)
        t_fire = time.time()
        shot.fired = fire(driver)
        shot.arrival_offset_ms = (clock.arrival_for_local_fire(t_fire)
                                  - open_epoch) * 1000.0
        if not shot.fired:
            shot.text = "확인 버튼이 사라져 누르지 못했습니다."
            shots.append(shot)
            log(shot.text)
            time.sleep(max(retry_ms, 50) / 1000.0)
            continue

        code, text = booking.read_outcome(driver, timeout=OUTCOME_TIMEOUT)
        shot.code, shot.text = code, text
        shots.append(shot)
        reopen.note_outcome(code)
        log(f"[확인] {attempt}발째 · 도착 추정 정각 {shot.arrival_offset_ms:+.0f}ms "
            f"· 서버: {text or '(문구 없음)'} [{code}]")

        detail = {"shots": [s.as_dict() for s in shots],
                  "confirmAttempts": attempt,
                  "confirmArrivalOffsetMs": round(shot.arrival_offset_ms, 1),
                  "reopen": reopen.as_dict(),
                  "handoverState": st.as_dict()}

        if code == booking.R_OK:
            return booking.StepResult(True, text or "예약이 완료되었습니다.",
                                      "reserved", None, detail)
        if code == booking.R_FULL:
            return booking.StepResult(False, text or "정원이 초과되었습니다.",
                                      "full", None, detail)
        if code == booking.R_NOT_BOOKABLE:
            return booking.StepResult(False, text or "예약할 수 없는 시간대입니다.",
                                      "not_bookable", None, detail)
        if code == booking.R_TOO_EARLY and not corrected:
            delta = clock.note_too_early(shot.arrival_offset_ms / 1000.0)
            if delta:
                corrected = True
                log(f"'예약시간전' 응답으로 도착 추정을 {delta * 1000:+.0f}ms "
                    f"보정했습니다.")
        if code not in (booking.R_TOO_EARLY, booking.R_UNKNOWN):
            try:
                from . import automation
                automation.capture(driver, diag, f"handover_{attempt}_{code}")
            except Exception:
                pass
        time.sleep(max(retry_ms, 20) / 1000.0)

    last = shots[-1] if shots else HandoverShot()
    msg = last.text or "정해진 시간 안에 예약을 마치지 못했습니다."
    return booking.StepResult(
        False, msg, "exhausted" if shots else "never_ready", None,
        {"shots": [s.as_dict() for s in shots], "confirmAttempts": attempt,
         "confirmArrivalOffsetMs": round(last.arrival_offset_ms, 1),
         "reopen": reopen.as_dict(),
         "handoverState": watcher.state.as_dict()})
