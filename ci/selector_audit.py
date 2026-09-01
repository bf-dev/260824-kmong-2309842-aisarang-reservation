"""셀렉터 의존성 전수 감사.

booking.py 가 아이사랑 화면에 대해 세우고 있는 가정 51개를, **실제로 캡처된
HTML** 에 헤드리스 크롬으로 부딪혀 본다. 코드 리뷰가 아니라 실행 결과다.

판정 세 가지
  confirmed      실물 캡처에서 그 요소/문구를 찾았다
  reconstruction 영상 복원본이나 추론에만 근거가 있다 (실물 없음)
  unconfirmed    아무 근거도 없다

  python ci/selector_audit.py            # 요약
  python ci/selector_audit.py --verbose  # 항목별
"""
from __future__ import annotations

import json
import time
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# 이 감사는 항목 이름이 전부 한글이다. 윈도우 러너의 파이썬 stdout 은 기본이
# cp1252 라서 '단계' 를 찍는 순간 UnicodeEncodeError 로 죽는다(실제로 CI 를
# 세웠다). 여기는 콘솔 전용 CI 스크립트라 재설정이 안전하다. 다만 --noconsole
# 로 얼린 제품에서는 stdout 이 None 이므로 같은 코드를 제품에 넣지 말 것.
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

REAL = ROOT / "ci" / "fixtures" / "real"
SITEMAP = ROOT / "docs" / "site-map"

CONFIRMED = "confirmed"
RECON = "reconstruction"
UNCONF = "unconfirmed"


def driver():
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    o = Options()
    for a in ("--headless=new", "--no-sandbox", "--disable-gpu",
              "--window-size=1400,1200",
              # 바깥 네트워크는 완전히 막고 로컬 픽스처 서버만 허용한다.
              "--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1"):
        o.add_argument(a)
    return webdriver.Chrome(options=o)


class Probe:
    """픽스처 하나를 띄우고 그 위에서 자바스크립트를 돌린다.

    file:// 이 아니라 http 로 띄운다. file:// 은 문서마다 오리진이 달라
    CSS 가 제대로 안 붙고, 그러면 `.popup_wrap{display:none}` 이 죽어서
    숨어 있어야 할 확인창 사본까지 '보인다' 로 판정된다.
    """

    def __init__(self, d, base: str):
        self.d = d
        self.base = base.rstrip("/")
        self.loaded = None

    def load(self, path: Path):
        if self.loaded != path:
            rel = path.relative_to(ROOT).as_posix()
            self.d.get(f"{self.base}/{rel}")
            # 스타일시트가 다 붙기 전에 재면 가시성 판정이 흔들린다.
            # (`.popup_wrap{display:none}` 이 아직 안 붙은 순간이 있다.)
            end = time.time() + 10.0
            while time.time() < end:
                try:
                    ready = self.d.execute_script(
                        "return document.readyState === 'complete' && "
                        "document.styleSheets.length > 0;")
                except Exception:  # noqa: BLE001
                    ready = False
                if ready:
                    break
                time.sleep(0.1)
            self.loaded = path
        return self

    def js(self, script, *args):
        try:
            return self.d.execute_script(script, *args)
        except Exception as exc:  # noqa: BLE001
            return {"__error__": str(exc)[:200]}


# 실물이 있는 페이지들
P_GRID = REAL / "grid_ready.html"
P_SEL = REAL / "grid_selected_row_added.html"
P_MODAL = REAL / "modal_open.html"
P_AJAX = REAL / "occasion_time_main_slpl.html"
# 스크립트를 남긴 원본. "사이트가 이 함수를 부르는가" 는 글자로만 확인된다.
P_RAW = REAL / "modal_open.raw.html"
P_AJAX_RAW = REAL / "occasion_time_main_slpl.raw.html"
# 1~3단계는 어제 감사에서 이미 실물로 닫힌 것들 (익명/아이디 세션 캡처)
P_ENTRY = SITEMAP / "01-entry-242.html"
P_CENTERS = SITEMAP / "07-centers-seocho-idsession.html"
P_RESERVE = SITEMAP / "07-reserve-605-idsession.html"
# 2026-08-26 08:57 고객 PC 캡처의 진짜 가상대기열 레이어
P_QUEUE = REAL / "netfunnel_waiting.html"
# 2026-08-27 09:00:00 고객 PC 캡처의 진짜 '예약시간전' 알림
P_TOO_EARLY = REAL / "too_early_alert.html"
# 2026-09-01 09:00:00 고객 PC 캡처의 진짜 '선예약' 알림 (자리를 뺏긴 응답)
P_TAKEN = REAL / "taken_alert.html"


def exists(p: Probe, page: Path, script, *args):
    """스크립트가 참/비어있지 않은 값을 돌려주면 confirmed."""
    if not page.exists():
        return UNCONF, f"픽스처 없음: {page.name}"
    got = p.load(page).js(script, *args)
    if isinstance(got, dict) and "__error__" in got:
        return UNCONF, got["__error__"]
    ok = bool(got) and got != 0
    return (CONFIRMED if ok else UNCONF), json.dumps(got, ensure_ascii=False)[:220]


def build_checks(p: Probe):
    """(번호, 단계, 이름, 판정, 근거) 51개."""
    C = []

    def add(step, name, verdict, note):
        C.append({"n": len(C) + 1, "step": step, "name": name,
                  "verdict": verdict, "note": str(note)[:220]})

    def probe(step, name, page, script, *args):
        v, note = exists(p, page, script, *args)
        add(step, name, v, note)

    # ---------------- 1단계: 지역 선택 / 조회 (공개 페이지, 어제 확인됨)
    probe("1", "구분 라디오 #aUnityN", P_ENTRY,
          "return document.getElementById('aUnityN') ? 'aUnityN' : null;")
    probe("1", "지역선택 열기 #addressDesc", P_ENTRY,
          "return document.getElementById('addressDesc') ? 'addressDesc' : null;")
    probe("1", "시/도 목록 항목(서울특별시)", P_ENTRY, r"""
      var n=document.querySelectorAll('a,li,option');
      for(var i=0;i<n.length;i++){var t=(n[i].textContent||'').trim();
        if(t==='서울특별시') return n[i].tagName;} return null;""")
    probe("1", "시/군/구 목록 항목", P_ENTRY, r"""
      var n=document.querySelectorAll('#gugunList,[id*=gugun],[id*=signgu]');
      return n.length ? n[0].id : null;""")
    probe("1", "조회 버튼 #btnSearch", P_ENTRY,
          "return document.getElementById('btnSearch') ? 'btnSearch' : null;")
    probe("1", "결과 목록 센터 행", P_CENTERS, r"""
      var n=document.querySelectorAll('a#occasionRes,a[id^=occasionRes],.btn_preschool');
      return n.length || null;""")

    # ---------------- 2단계: 센터의 [시간제보육 예약] 열기
    probe("2", "a#occasionRes[data-stcode]", P_CENTERS,
          "var e=document.querySelector('a[data-stcode]');return e?e.getAttribute('data-stcode'):null;")
    probe("2", "data-unityyn 속성", P_CENTERS,
          "var e=document.querySelector('a[data-unityyn]');return e?e.getAttribute('data-unityyn'):null;")
    probe("2", "gotoOccasionRes 함수 존재", P_CENTERS,
          "return document.documentElement.innerHTML.indexOf('gotoOccasionRes')>=0;")
    probe("2", "form[name=pfrm] 폴백", P_CENTERS,
          "return document.querySelector('form[name=pfrm]')?'pfrm':null;")

    # ---------------- 3단계: 아동 선택 -> 이용정보 화면
    # 고객의 진짜 인증서 세션 캡처(?menuno=605)로 본다. docs/site-map 의
    # 아이디 세션 저장본에는 아동 목록이 아예 안 그려져 있어서 근거가 못 된다.
    probe("3", "아동 라디오 name=occasionChk", P_GRID,
          "return document.querySelectorAll('input[type=radio][name=occasionChk]').length||null;")
    probe("3", "라디오 onclick listChildSelect()", P_GRID, r"""
      var e=document.querySelector('input[type=radio][name=occasionChk]');
      return e?e.getAttribute('onclick'):null;""")
    probe("3", "#unityyn 히든", P_GRID,
          "var e=document.getElementById('unityyn');return e?(e.value||'(빈값)'):null;")
    probe("3", "[data-tab=divOccasionTimeSlPL]", P_GRID,
          "return document.querySelector('[data-tab=divOccasionTimeSlPL]')?'slpl':null;")
    probe("3", "[data-tab=divOccasionTimePils] (통합반)", P_GRID,
          "return document.querySelector('[data-tab=divOccasionTimePils]')?'pils':null;")
    probe("3", "fnChildInfo 함수", P_RAW,
          "return document.documentElement.innerHTML.indexOf('fnChildInfo')>=0;")
    probe("3", "이용정보 렌더 완료 판정", P_GRID, r"""
      var s=document.querySelectorAll('select');
      for(var i=0;i<s.length;i++){var r=s[i].closest('tr,div,li');
        var l=r?(r.innerText||''):''; if(l.indexOf('이용시간')>=0||l.indexOf('반명')>=0) return true;}
      return (document.body.innerText||'').indexOf('날짜/시간')>=0;""")
    # listChildSelect 의 alert 경로는 신청서 없는 계정에서만 뜬다. 캡처 없음.
    add("3", "이용신청서 없음 네이티브 alert 문구", RECON,
        "고객 설명에만 근거. 캡처에 alert 문구 없음(자동 accept 는 구현됨)")

    # ---------------- 4단계: 반명
    probe("4", "반명 select#clname", P_AJAX,
          "var e=document.getElementById('clname');return e?e.name:null;")
    probe("4", "반명 select 이 '반명' 행 안에 있음", P_AJAX, r"""
      var e=document.getElementById('clname'); if(!e) return null;
      var r=e.closest('tr'); return r?(r.innerText||'').replace(/\s+/g,' ').trim().slice(0,20):null;""")
    probe("4", "반명 onchange fnSerChange()", P_AJAX,
          "var e=document.getElementById('clname');return e?e.getAttribute('onchange'):null;")
    probe("4", "반명 option 이 ajax(selectOcTaClList)로 채워짐", P_MODAL, r"""
      var e=document.getElementById('clname'); if(!e) return null;
      var o=[]; for(var i=0;i<e.options.length;i++) o.push(e.options[i].text);
      return o.length>1 ? o : null;""")
    # selectedIndex 는 저장된 HTML 에 직렬화되지 않는다(프로퍼티라서).
    # 그래서 '자동 선택' 은 사이트 JS 의 규칙과 그 결과물로 확인한다.
    probe("4", "반 1개면 자동 선택 (fnSetCl 의 clList.length==1 분기)", P_AJAX_RAW, r"""
      var h=document.documentElement.innerHTML;
      return (h.indexOf('clList.length == 1')>=0 &&
              h.indexOf('#clname option:eq(1)')>=0) ? '자동선택 분기 있음' : null;""")

    # ---------------- 5단계: 이용시간
    probe("5", "이용시간 select#rtm", P_AJAX,
          "var e=document.getElementById('rtm');return e?e.name:null;")
    probe("5", "이용시간 option 값 1~9", P_AJAX, r"""
      var e=document.getElementById('rtm'); if(!e) return null;
      var v=[]; for(var i=0;i<e.options.length;i++){var t=e.options[i].value; if(t) v.push(t);}
      return v.join(',')==='1,2,3,4,5,6,7,8,9' ? v.join(',') : null;""")
    probe("5", "이용시간 onchange fnTimeReset()", P_AJAX,
          "var e=document.getElementById('rtm');return e?e.getAttribute('onchange'):null;")

    # ---------------- 6단계: 날짜 x 시간 표
    probe("6", "표 컨테이너 #crtminfo", P_GRID,
          "return document.getElementById('crtminfo')?'crtminfo':null;")
    probe("6", "표가 #crtminfo 안의 table", P_GRID,
          "var e=document.querySelector('#crtminfo table');return e?e.querySelectorAll('tr').length:null;")
    probe("6", "날짜 행머리 th#day_N", P_GRID,
          "return document.querySelectorAll('#crtminfo th[id^=day_]').length||null;")
    probe("6", "날짜 표기 YYYY-MM-DD(요일)", P_GRID, r"""
      var e=document.getElementById('day_0'); if(!e) return null;
      var t=(e.textContent||'').trim();
      return /^20\d\d-\d{2}-\d{2}\([월화수목금토일]\)/.test(t) ? t.slice(0,14) : null;""")
    probe("6", "날짜 머신값 input[name=resdt]", P_GRID, r"""
      var e=document.getElementById('day_0'); if(!e) return null;
      var i=e.querySelector('input[name=resdt]');
      return (i && /^20\d{6}$/.test(i.value)) ? i.value : null;""")
    probe("6", "헤더 시각 형식(09..17, 0채움)", P_GRID, r"""
      var th=document.querySelectorAll('#crtminfo thead th'); if(!th.length) return null;
      var v=[]; for(var i=1;i<th.length;i++) v.push((th[i].textContent||'').trim());
      return v.join(',')==='09,10,11,12,13,14,15,16,17' ? v.join(',') : null;""")
    probe("6", "클릭 대상 a.time-option#tm_H_R", P_GRID, r"""
      var e=document.getElementById('tm_9_0');
      return (e && e.tagName==='A' && e.className.indexOf('time-option')>=0) ? e.outerHTML.slice(0,90) : null;""")
    probe("6", "셀 id 의 시각은 0채움 아님(tm_9_ vs tm_09_)", P_GRID,
          "return (document.getElementById('tm_9_0') && !document.getElementById('tm_09_0'))?'unpadded':null;")
    probe("6", "onclick selectDay2(this,'H',R)", P_GRID, r"""
      var e=document.getElementById('tm_9_0'); if(!e) return null;
      var a=e.getAttribute('onclick');
      return /selectDay2\(this,'9',0\)/.test(a) ? a : null;""")
    probe("6", "잔여 인원 i.count 텍스트", P_GRID, r"""
      var e=document.querySelector('#tm_9_0 i.count'); if(!e) return null;
      return {text:(e.textContent||'').trim(), title:e.getAttribute('title')};""")
    probe("6", "이용불가 표시 i.count.not = 'X'", P_GRID, r"""
      var n=document.querySelectorAll('#crtminfo i.count.not'); if(!n.length) return null;
      return {count:n.length, text:(n[0].textContent||'').trim(), title:n[0].getAttribute('title')};""")
    probe("6", "선택 표시 = a.on + title='선택됨'", P_SEL, r"""
      var e=document.querySelector('#crtminfo a.time-option.on'); if(!e) return null;
      return {id:e.id, title:e.getAttribute('title'), inner:!!e.querySelector('i.count.on')};""")
    probe("6", "숨은 열 pp_/bm_/nsc_ 가 같은 tr 안에 있음", P_GRID, r"""
      var r=document.getElementById('day_0'); if(!r) return null;
      var tr=r.closest('tr'); var tds=tr.querySelectorAll('td');
      var hidden=[]; for(var i=0;i<tds.length;i++){ if(tds[i].id && /^(pp|bm|nsc)_/.test(tds[i].id)) hidden.push(tds[i].id); }
      return hidden.length ? {tds:tds.length, hidden:hidden} : null;""")

    # ---------------- 7단계: 추가
    probe("7", "추가 버튼 #timecareTableAddBtn", P_GRID, r"""
      var e=document.getElementById('timecareTableAddBtn');
      return e?{text:(e.textContent||'').trim(), onclick:e.getAttribute('onclick')}:null;""")
    probe("7", "추가 onclick f_AddQualRow()", P_GRID,
          "var e=document.getElementById('timecareTableAddBtn');return (e&&/f_AddQualRow/.test(e.getAttribute('onclick')||''))?'f_AddQualRow':null;")

    # ---------------- 8단계: 선택표
    probe("8", "선택표 table#INFOQUALF", P_SEL,
          "return document.getElementById('INFOQUALF')?'INFOQUALF':null;")
    probe("8", "추가된 행 tr#tId_N", P_SEL,
          "return document.querySelectorAll('#INFOQUALF tbody tr[id^=tId_]').length||null;")
    probe("8", "행 체크박스 #rowSchChkNoN[name=rowQualChkNo]", P_SEL, r"""
      var e=document.querySelector('#INFOQUALF input[name=rowQualChkNo]');
      return e?{id:e.id, type:e.type, cls:e.className}:null;""")
    probe("8", "이용일 값이 input.value 에 있음(텍스트 아님)", P_SEL, r"""
      var tr=document.querySelector('#INFOQUALF tbody tr'); if(!tr) return null;
      var txt=(tr.innerText||tr.textContent||'').trim();
      var i=tr.querySelector('input[id^=resdt]');
      return i ? {rowText:txt, resdt:i.value} : null;""")
    probe("8", "이용시간 값 input#restimeN", P_SEL, r"""
      var e=document.querySelector('#INFOQUALF input[id^=restime]');return e?e.value:null;""")
    probe("8", "반명 값 input#resclnameN", P_SEL, r"""
      var e=document.querySelector('#INFOQUALF input[id^=resclname]');return e?e.value:null;""")

    # ---------------- 9단계: 예약하기 -> 확인 모달
    probe("9", "예약하기 #timecareConfirm (onclick fnSave)", P_SEL, r"""
      var e=document.getElementById('timecareConfirm');
      return e?{text:(e.textContent||'').trim(), onclick:e.getAttribute('onclick')}:null;""")
    probe("9", "모달 컨테이너: 보이는 #layer-confirm-popup2 (중복 id 주의)", P_MODAL, r"""
      var all=document.querySelectorAll('[id=layer-confirm-popup2]');
      var vis=[]; for(var i=0;i<all.length;i++){var r=all[i].getBoundingClientRect();
        if(r.width>0&&r.height>0) vis.push(i);}
      return all.length ? {total:all.length, visibleIndexes:vis} : null;""")
    probe("9", "모달 본문 문구 '예약하시겠습니까?'", P_MODAL, r"""
      var n=document.querySelectorAll('[id=layer-confirm-popup-contents2]');
      for(var i=0;i<n.length;i++){var t=(n[i].innerText||n[i].textContent||'').trim();
        if(t.indexOf('예약하시겠습니까')>=0) return t.slice(-40);}
      return null;""")
    probe("9", "최종 확인 #layer-confirm-popup-confirm2 (보이는 쪽)", P_MODAL, r"""
      var all=document.querySelectorAll('[id=layer-confirm-popup-confirm2]');
      var out=[]; for(var i=0;i<all.length;i++){var r=all[i].getBoundingClientRect();
        out.push({i:i, text:(all[i].textContent||'').trim(), vis:(r.width>0&&r.height>0)});}
      return out.length?out:null;""")

    # 결과가 도착하는 자리. 캡처된 fnSave 콜백이 서버 답(data.returnmsg)을
    # icmsLayerPopup.alert2 로 띄우고, layerpopup.js 의 open('type-alert2') 는
    # #layer-alert-popup-contents2 를 채우고 #layer-alert-popup2 를 편다.
    # 확인창과 똑같이 이 껍데기도 페이지에 두 벌이다.
    probe("9", "결과 안내 껍데기 #layer-alert-popup2 (두 벌)", P_MODAL, r"""
      var s=document.querySelectorAll('[id=layer-alert-popup2]');
      var c=document.querySelectorAll('[id=layer-alert-popup-contents2]');
      return s.length ? {shells:s.length, contents:c.length} : null;""")

    # 서버가 실제로 돌려주는 결과 **문구**. 근거 등급이 둘로 갈렸다.
    #   예약시간전: 2026-08-27 09:00:00 실물. InsertOcreqst.html 의 returnmsg 를
    #               사이트가 alert2 로 찍은 것이 캡처에 그대로 남았다.
    #   선예약    : 2026-08-28 / 2026-09-01 실물 2회. 자리를 뺏긴 응답.
    #   정원초과  : 아직 실물 없음. 위 선예약이 이 사이트의 '자리 없음' 응답인
    #               것이 밝혀졌으므로, 사이트가 아예 안 쓰는 문구일 가능성이 높다.
    add("9", "서버 결과 문구: 예약시간전 (아직 예약 가능한 시간이 아닙니다.)", CONFIRMED,
        "2026-08-27 09:00:00 캡처 page_source/0002_handover_after.html "
        "#layer-alert-popup-contents2 (= InsertOcreqst.html 의 returnmsg)")
    probe("9", "서버 결과 문구: 선예약 (자리를 뺏김)", P_TAKEN, r"""
      var e=document.querySelectorAll('[id=layer-alert-popup-contents2]');
      for (var i=0;i<e.length;i++) {
        var t=(e[i].innerText||e[i].textContent||'').trim();
        if (t) return {text: t};
      }
      return null;""")
    add("9", "서버 결과 문구(정원초과)", UNCONF,
        "2026-08-25 ~ 2026-09-01 어떤 캡처에도 없음. 자리 없음은 '선예약' 으로 "
        "온다는 것이 확인됐으므로 사이트가 안 쓰는 문구로 보인다(지우지는 않음)")

    # ---------------- 대기열: 2026-08-26 실물. 확인창 자리에 뜬 것이 이것이다.
    probe("Q", "대기열 레이어 #NetFunnel_Loading_Popup", P_QUEUE, r"""
      var e=document.querySelectorAll('[id=NetFunnel_Loading_Popup]')[0];
      if(!e) return null;
      var r=e.getBoundingClientRect();
      return {visible: r.width>0 && r.height>0,
              style: (e.getAttribute('style')||'').slice(0,60)};""")
    probe("Q", "대기 인원 #..._Count / #..._NextCnt", P_QUEUE, r"""
      var a=document.querySelectorAll('[id=NetFunnel_Loading_Popup_Count]')[0];
      var b=document.querySelectorAll('[id=NetFunnel_Loading_Popup_NextCnt]')[0];
      if(!a||!b) return null;
      return {ahead:(a.textContent||'').trim(), behind:(b.textContent||'').trim()};""")
    probe("Q", "예상 대기시간 #..._TimeLeft", P_QUEUE, r"""
      var t=document.querySelectorAll('[id=NetFunnel_Loading_Popup_TimeLeft]')[0];
      return t ? (t.textContent||'').replace(/\s+/g,' ').trim() : null;""")
    probe("Q", "레이어 경고문 '재접속하시면 대기시간이 더 길어집니다'", P_QUEUE, r"""
      var e=document.querySelectorAll('[id=NetFunnel_Loading_Popup]')[0];
      if(!e) return null;
      var s=(e.innerText||e.textContent||'').replace(/\s+/g,' ');
      return s.indexOf('재접속하시면 대기시간이 더 길어집니다') >= 0 ? '있음' : null;""")
    probe("Q", "대기 중에는 확인창이 없다", P_QUEUE, r"""
      var sh=document.querySelectorAll("[id='layer-confirm-popup2']");
      for (var i=0;i<sh.length;i++){
        var r=sh[i].getBoundingClientRect();
        if (r.width>0 && r.height>0) return null;
      }
      return '확인창 없음 확인';""")

    return C


def product_checks(p: Probe) -> list:
    """제품의 _JS_* 상수를 실물 캡처에 그대로 돌린다.

    위의 51+1 은 '사이트에 그 요소가 있는가' 를 본다. 여기는 '우리 코드가
    그것을 실제로 맞히는가' 를 본다. 둘은 다른 질문이고, 예전 감사에서
    번번이 갈렸다.
    """
    from aisarang import booking
    out = []

    def add(name, ok, note):
        out.append({"name": name, "ok": bool(ok), "note": str(note)[:200]})

    d = p.load(P_GRID).d
    raw = p.js(booking._JS_SCAN_GRID)
    ok = (isinstance(raw, dict) and raw.get("how") == "crtminfo"
          and len(raw.get("cells") or []) == 126
          and len(raw.get("rows") or []) == 14)
    hours = sorted({c["hour"] for c in (raw.get("cells") or [])}) if isinstance(raw, dict) else []
    add("_JS_SCAN_GRID 가 실물 표를 정확히 126칸으로 읽는다", ok,
        f"how={raw.get('how') if isinstance(raw, dict) else raw} "
        f"cells={len(raw.get('cells') or []) if isinstance(raw, dict) else 0} hours={hours}")
    add("유령 시간대(숨은 벌점/개월 칸)가 없다",
        hours == [9, 10, 11, 12, 13, 14, 15, 16, 17], f"hours={hours}")

    g = booking.read_grid(d)
    cell, why = booking.pick_cell(g, "20260826", [10, 11])
    add("0 인 칸은 고르지 않는다", cell is None, why)
    cell2, why2 = booking.pick_cell(g, "20260828", [9])
    add("자리가 있는 칸은 id 까지 짚어 고른다",
        cell2 is not None and cell2.el_id == "tm_9_2",
        f"{why2} el_id={getattr(cell2, 'el_id', None)}")

    p.load(P_SEL)
    sr = p.js(booking._JS_SCAN_SLOT_ROWS)
    rows = sr.get("rows") or [] if isinstance(sr, dict) else []
    add("_JS_SCAN_SLOT_ROWS 가 #INFOQUALF 를 고른다",
        isinstance(sr, dict) and sr.get("how") == "INFOQUALF",
        f"how={sr.get('how') if isinstance(sr, dict) else sr}")
    add("선택표 행의 이용일을 input value 에서 읽는다",
        bool(rows) and rows[0].get("date") == "20260828",
        f"date={rows[0].get('date') if rows else None} "
        f"text={(rows[0].get('text') if rows else '')[:60]}")
    add("_JS_CELL_IS_ON 이 선택 표시를 본다",
        (p.js(booking._JS_CELL_IS_ON, "tm_9_2") or {}).get("title") == "선택됨",
        p.js(booking._JS_CELL_IS_ON, "tm_9_2"))

    p.load(P_MODAL)
    m = p.js(booking._JS_MODAL)
    add("_JS_MODAL 이 보이는 #layer-confirm-popup2 를 잡는다",
        isinstance(m, dict) and m.get("how") == "layer-confirm-popup2",
        m if not isinstance(m, dict) else
        f"how={m.get('how')} shells={m.get('shells')} okId={m.get('okId')}")
    armed = p.js(booking._JS_ARM)
    okid = p.js("return window.__aisarang_ok ? window.__aisarang_ok.id : null;")
    add("_JS_ARM 이 -confirm2 를 (열린 껍데기 안에서) 조준한다",
        armed is True and okid == "layer-confirm-popup-confirm2", f"armed={armed} id={okid}")
    body = p.js("var q=document.querySelectorAll(\"[id='layer-confirm-popup-contents2']\");"
                "for(var i=0;i<q.length;i++){var t=(q[i].innerText||'').trim();"
                "if(t) return t;} return '';")
    code = booking.classify(body if isinstance(body, str) else "")
    add("확인창 본문을 '실패' 로 오분류하지 않는다",
        code != booking.R_FAIL, f"classify -> {code}")
    add("사이트가 막는 문구는 재시도하지 않는다",
        booking.classify("예약 가능 시간이 아닙니다.") == booking.R_NOT_BOOKABLE
        and not booking.result_is_retryable(booking.R_NOT_BOOKABLE),
        booking.classify("예약 가능 시간이 아닙니다."))

    # [확인] 이후 서버 답이 오는 자리를 실물에서 열어 보고 읽는다.
    # layerpopup.js 의 open('type-alert2') 가 하는 두 줄만 그대로 재현한다.
    p.js("var c=document.querySelectorAll(\"[id='layer-confirm-popup2']\");"
         "for(var i=0;i<c.length;i++) c[i].style.display='none';"
         "document.querySelectorAll(\"[id='layer-alert-popup-contents2']\")[0]"
         "  .innerHTML='예약이 완료되었습니다.';"
         "document.querySelectorAll(\"[id='layer-alert-popup2']\")[0]"
         "  .style.display='block';")
    notices = [str(t) for t in (p.js(booking._JS_READ_NOTICE) or [])]
    hit = [t for t in notices if "예약이 완료되었습니다." in t]
    add("_JS_READ_NOTICE 가 결과 안내(alert2)를 읽는다",
        bool(hit) and booking.classify(hit[-1]) == booking.R_OK,
        f"notices={len(notices)} classify={booking.classify(hit[-1]) if hit else None}")
    add("결과가 뜬 뒤에는 조준이 풀려 있다(두 번 쏘지 않는다)",
        p.js(booking._JS_STILL_ARMED) is False, p.js(booking._JS_STILL_ARMED))

    # ---- v1.0.8: 인계 모드와 대기열 판정기
    from aisarang import handover

    d = p.load(P_QUEUE).d
    q = p.js(booking._JS_QUEUE)
    add("_JS_QUEUE 가 실물 대기열을 순번까지 읽는다",
        isinstance(q, dict) and q.get("queue") is True and q.get("ahead") == 72
        and q.get("behind") == 26,
        json.dumps(q, ensure_ascii=False)[:200])
    st = handover.read_state(d)
    add("인계 모드는 대기열 화면에서 발사 조건을 만족하지 않는다",
        st.queue is True and st.ready() is False and st.modal is False,
        f"queue={st.queue} modal={st.modal} ready={st.ready()}")
    add("대기열 화면에서 fire 가 실제로 거부된다",
        handover.fire(d) is False, "fire() -> False")

    d = p.load(P_MODAL).d
    d.execute_script("var b=document.getElementById('rowSchChkNo0');"
                     "if(b){b.checked=true;}")
    st = handover.read_state(d)
    add("사람이 만든 확인창에서 인계 모드가 발사 조건을 만족한다",
        st.ready() is True and st.confirm_id == "layer-confirm-popup-confirm2",
        f"ready={st.ready()} confirmId={st.confirm_id} ticked={st.ticked} "
        f"blockers={st.blockers()}")
    add("그 화면에서 fire 가 실제로 눌린다", handover.fire(d) is True,
        f"firedAt={d.execute_script('return window.__aisarang_fired_at;')}")

    d.execute_script("var b=document.getElementById('rowSchChkNo0');"
                     "if(b){b.checked=false;}")
    st = handover.read_state(d)
    add("체크가 꺼지면 같은 화면에서도 발사하지 않는다",
        st.ready() is False and st.ticked == 0, f"blockers={st.blockers()}")

    # ---- 2026-08-27 09:00:00 의 그 화면. 서버 원문과 되살리기 문. -------------
    d = p.load(P_TOO_EARLY).d
    d.execute_script("var b=document.getElementById('rowSchChkNo0');"
                     "if(b){b.checked=true;}")
    notices = [str(t) for t in (p.js(booking._JS_READ_NOTICE) or [])]
    hit = [n for n in notices if booking.TOO_EARLY_REAL in n]
    add("서버 원문 '아직 예약 가능한 시간이 아닙니다.' 를 실물 알림에서 읽는다",
        bool(hit) and booking.classify(hit[0]) == booking.R_TOO_EARLY,
        f"notices={len(notices)} classify="
        f"{booking.classify(hit[0]) if hit else 'no_text'}")

    st = handover.read_state(d)
    add("확인창이 소비된 그 화면에서는 발사 조건을 만족하지 않는다",
        st.modal is False and st.ready() is False and st.ticked == 1,
        f"modal={st.modal} ticked={st.ticked} queue={st.queue}")

    d.execute_script(
        "window.__fnSave = 0; window.fnSave = function(){ window.__fnSave++; };"
        "window.__alertClose = 0; window.__confirmClick = 0;"
        "document.querySelectorAll(\"[id^='layer-popup-close']\").forEach("
        "  function(a){ a.addEventListener('click', function(){"
        "    window.__alertClose++; }); });"
        "document.querySelectorAll(\"[id='layer-confirm-popup-confirm2']\").forEach("
        "  function(a){ a.addEventListener('click', function(){"
        "    window.__confirmClick++; }); });")

    class _Now:
        def server_now(self):
            return 1001.0

    gate = handover._Reopen(_Now(), 1000.0, 2, 15.0)
    gate.note_outcome(booking.R_TOO_EARLY)
    allowed = gate.allowed(st)
    if allowed:
        gate.do(d, lambda *_: None)
    got = d.execute_script(
        "return {save: window.__fnSave, alert: window.__alertClose,"
        "        confirm: window.__confirmClick};") or {}
    add("'예약시간전' 뒤 되살리기가 [예약하기] 를 정확히 한 번 누른다",
        allowed is True and got.get("save") == 1 and got.get("alert") == 1
        and got.get("confirm") == 0,
        f"allowed={allowed} fnSave={got.get('save')} "
        f"alertClosed={got.get('alert')} confirmClicked={got.get('confirm')}")

    gate2 = handover._Reopen(_Now(), 1000.0, 2, 15.0)
    gate2.note_outcome(booking.R_FULL)
    add("'정원초과' 뒤에는 되살리기 문이 열리지 않는다",
        gate2.allowed(st) is False, gate2.why_not(st))

    gate3 = handover._Reopen(_Now(), 1000.0, 2, 15.0)
    gate3.note_outcome(booking.R_TAKEN)
    add("'선예약' 뒤에도 되살리기 문이 열리지 않는다 (대기열 재진입 금지)",
        gate3.allowed(st) is False and gate3.locked is True, gate3.why_not(st))

    add("'선예약' 실물 문구가 R_TAKEN 으로 분류된다",
        booking.classify(booking.TAKEN_REAL) == booking.R_TAKEN
        and not booking.result_is_retryable(booking.R_TAKEN),
        f"{booking.TAKEN_REAL} -> {booking.classify(booking.TAKEN_REAL)}")

    add("2026-08-31 성공 문구는 그대로 성공이다 (선예약 규칙에 안 걸린다)",
        booking.classify("1건 예약 중 1건 예약되었습니다.") == booking.R_OK,
        "1건 예약 중 1건 예약되었습니다.")
    return out


def main() -> int:
    verbose = "--verbose" in sys.argv
    sys.path.insert(0, str(ROOT / "ci"))
    from real_fixture_server import RealFixtureServer

    with RealFixtureServer(str(ROOT)) as srv:
        d = driver()
        try:
            probe = Probe(d, srv.url(""))
            checks = build_checks(probe)
            prod = product_checks(probe)
        finally:
            d.quit()

    n = len(checks)
    tally = {CONFIRMED: 0, RECON: 0, UNCONF: 0}
    for c in checks:
        tally[c["verdict"]] += 1

    if verbose:
        cur = None
        for c in checks:
            if c["step"] != cur:
                cur = c["step"]
                print(f"\n--- {cur}단계 ---")
            mark = {CONFIRMED: "OK  ", RECON: "RECON", UNCONF: "NONE"}[c["verdict"]]
            print(f"{c['n']:2d} [{mark:5s}] {c['name']}")
            if c["verdict"] != CONFIRMED or verbose:
                print(f"          {c['note']}")

    print("\n--- 제품의 _JS_* 를 실물에 직접 돌린 결과 ---")
    for c in prod:
        print(f"{'OK  ' if c['ok'] else 'FAIL'}  {c['name']}")
        if verbose or not c["ok"]:
            print(f"        {c['note']}")
    prod_ok = sum(1 for c in prod if c["ok"])

    print(f"\n의존성 {n}개: 확인 {tally[CONFIRMED]} / "
          f"영상복원본만 {tally[RECON]} / 미확인 {tally[UNCONF]}")
    print(f"제품 동작 검증 {len(prod)}개 중 {prod_ok}개 통과")
    out = ROOT / "out" / "selector-audit.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps({"total": n, "tally": tally, "checks": checks,
                               "product": prod}, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    print(f"상세: {out}")
    return 0 if (tally[UNCONF] <= 1 and prod_ok == len(prod)) else 1


if __name__ == "__main__":
    raise SystemExit(main())
