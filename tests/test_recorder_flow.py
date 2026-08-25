# -*- coding: utf-8 -*-
"""진단 기록 모드를 **진짜 크롬 + 진짜 서버**로 돌린다.

이 모드의 약속은 두 개다. 둘 다 여기서 기계적으로 확인한다.

  1. **아무것도 누르지 않는다.** 사람이 손으로 걸어가는 동안 옆에서 받아적기만
     한다. 화면의 클릭 계기(window.__humanClicks)와 예약 계기(window.__reserved)
     로 확인한다. 기록기가 도는 내내 사람이 누른 수 말고는 1도 오르지 않아야
     하고, __reserved 는 끝까지 false 여야 한다.
  2. **우리가 못 본 그 응답을 남긴다.** /icms/occasion/SelectOccasionChild.html
     과 /icms/occasion/OccasionTimeMainSlPL.html 의 **본문**이 진단 ZIP 에
     들어가야 한다. 지금까지 올라온 고객 진단 ZIP 50개에는 network_*.json 이
     단 한 건도 없었다(CDP Network 도메인이 안 켜져 있었다). 그 경로가 정말
     살아났는지도 여기서 본다.

그리고 견고성: 기록 도중 페이지를 넘기고, 레이어를 열었다 닫고, 마지막에는
브라우저를 그냥 닫아버린다. 그 어느 것도 예외로 밖에 나오면 안 된다.

크롬이 없으면 통째로 건너뛴다(우리 개발 환경 사정이지 제품 문제가 아니다).
"""
import json
import os
import socket
import subprocess
import sys
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aisarang import recorder as recmod
from aisarang.reporter import Diagnostics

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER = os.path.join(ROOT, "ci", "fixture_server.py")


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class _CapturedDiag(Diagnostics):
    """업로드만 가로챈다. 나머지(마스킹/ZIP 구성)는 제품 그대로 돈다."""

    def __init__(self):
        super().__init__()
        self.uploads = []

    def upload(self, headline, extra_meta=None, blocking=False):
        self.uploads.append({"headline": headline, "meta": extra_meta or {},
                             "zipBytes": len(self.build_zip(extra_meta))})

    def names(self):
        with self._lock:
            return [n for n, _ in self._entries]

    def entry(self, needle):
        with self._lock:
            for name, data in self._entries:
                if needle in name:
                    return name, data.decode("utf-8", "replace")
        return None, ""


def _driver():
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"selenium 없음: {exc}")
    opts = Options()
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--window-size=1280,1200")
    # 제품(build_driver)과 같은 로그 설정. 이게 없으면 performance 로그가 통째로
    # 없고, 그러면 네트워크 기록도 network_*.json 도 만들어지지 않는다.
    opts.set_capability("goog:loggingPrefs", {"performance": "ALL", "browser": "ALL"})
    opts.add_experimental_option("perfLoggingPrefs", {
        "enableNetwork": True, "enablePage": True})
    try:
        return webdriver.Chrome(options=opts)
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"크롬을 띄우지 못함: {type(exc).__name__}")


@pytest.fixture(scope="module")
def server():
    port = _free_port()
    proc = subprocess.Popen([sys.executable, SERVER, str(port)],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f"http://127.0.0.1:{port}"
    for _ in range(60):
        try:
            import urllib.request
            urllib.request.urlopen(base + "/rec", timeout=1).read()
            break
        except Exception:
            time.sleep(0.2)
    else:
        proc.kill()
        pytest.skip("fixture 서버가 뜨지 않음")
    yield base
    proc.kill()


@pytest.fixture(scope="module")
def session(server):
    """기록기 하나를 띄워 시나리오를 순서대로 걸어간다(테스트가 '사람' 역할)."""
    drv = _driver()
    diag = _CapturedDiag()
    rec = recmod.DiagRecorder(log=lambda *_: None, status=lambda *_: None, diag=diag)
    rec.driver = drv
    assert rec.start(start_url=server + "/rec") is True
    yield rec, diag, drv, server
    try:
        rec.running = False
    except Exception:
        pass
    try:
        drv.quit()
    except Exception:
        pass


def _wait(pred, seconds=20.0):
    end = time.time() + seconds
    while time.time() < end:
        if pred():
            return True
        time.sleep(0.25)
    return False


def _clicks(drv):
    return drv.execute_script("return window.__humanClicks || 0;")


def test_recorder_does_not_touch_the_page_at_all(session):
    """기록기가 도는 동안 사람이 안 누르면 클릭 수는 0 이어야 한다."""
    rec, _diag, drv, _base = session
    assert _wait(lambda: drv.execute_script(
        "return !!document.querySelector('input[name=occasionChk]');"), 20)
    time.sleep(3.0)                     # 펌프가 여러 바퀴 돌 시간
    assert rec.pages >= 1
    assert _clicks(drv) == 0
    assert drv.execute_script("return window.__reserved;") is False


def test_the_never_seen_ajax_responses_are_recorded(session):
    """사람이 아동 라디오를 누르면 그 ajax 응답 본문이 그대로 남아야 한다."""
    rec, diag, drv, _base = session
    before = _clicks(drv)
    drv.find_element("css selector", "input[name=occasionChk]").click()   # 사람 역할
    assert _wait(lambda: len(rec.wanted_seen) >= 2, 25), rec.wanted_seen
    urls = " ".join(w["url"] for w in rec.wanted_seen)
    assert "SelectOccasionChild.html" in urls
    assert "OccasionTimeMainSlPL.html" in urls
    name, body = diag.entry("OccasionTimeMainSlPL")
    assert name.startswith("record/wanted/"), diag.names()
    assert "날짜/시간" in body and "예약하기" in body
    # 우리가 만든 클릭은 없다. 방금 하나 는 것은 테스트(=사람)가 누른 것뿐이다.
    assert _clicks(drv) == before + 1


def test_meaningful_screen_changes_are_snapshotted(session):
    """사람이 [추가] → [예약하기] 로 걸어가면 그 화면들이 남아야 한다."""
    rec, diag, drv, _base = session
    assert _wait(lambda: drv.execute_script(
        "return !!document.getElementById('btnAdd');"), 20)
    drv.find_element("css selector", "#btnAdd").click()
    assert _wait(lambda: rec.pages >= 2, 15)
    drv.find_element("css selector", "#btnReserve").click()
    assert _wait(lambda: any("modal_open" in n for n in diag.names()), 15), diag.names()
    # 확인창까지 왔지만 예약은 만들어지지 않았다. 이것이 이 모드의 존재 이유다.
    assert drv.execute_script("return window.__reserved;") is False


def test_layers_opening_and_closing_do_not_break_anything(session):
    rec, _diag, drv, _base = session
    skipped_before = len(rec.skipped)
    for _ in range(3):
        drv.execute_script("openLayer();")
        time.sleep(0.4)
        drv.execute_script("closeLayer();")
        time.sleep(0.4)
    assert rec.is_running()
    # 레이어를 여닫는 것만으로 실패가 쌓이면 안 된다.
    assert len(rec.skipped) == skipped_before, rec.skipped[-3:]


def test_navigating_away_mid_capture_keeps_recording(session):
    rec, _diag, drv, base = session
    drv.get(base + "/other")
    assert _wait(lambda: any("/other" in u for u in rec.visited), 15), rec.visited
    drv.get(base + "/rec")
    assert _wait(lambda: len(rec.wanted_seen) >= 3, 25), rec.wanted_seen
    assert rec.is_running()


def test_network_rows_carry_status_and_headers_but_no_cookie_values(session):
    rec, _diag, _drv, _base = session
    rows = rec._network_rows()
    posts = [r for r in rows if r.get("url", "") and "Occasion" in r["url"]]
    assert posts, [r.get("url") for r in rows][:10]
    assert any(r.get("status") == 200 for r in posts), posts[:3]
    assert any(r.get("method") == "POST" for r in posts), posts[:3]
    assert any(r.get("respHeaders") for r in posts), posts[:3]
    blob = json.dumps(rows, ensure_ascii=False)
    for row in rows:
        for headers in (row.get("reqHeaders") or {}, row.get("respHeaders") or {}):
            for key, value in headers.items():
                if key.lower() in ("cookie", "set-cookie"):
                    assert str(value).startswith("<값 제거됨")
    assert "JSESSIONID=" not in blob


def test_periodic_flush_uploads_without_stopping(session):
    rec, diag, _drv, _base = session
    before = len(diag.uploads)
    rec._last_flush = 0.0                 # 다음 펌프에서 주기 업로드가 걸리도록
    assert _wait(lambda: len(diag.uploads) > before, 15)
    assert rec.is_running()
    assert diag.uploads[-1]["meta"]["result"] == "periodic"
    assert diag.uploads[-1]["zipBytes"] > 2000


def test_closing_the_browser_ends_the_session_quietly(session):
    """사람이 크롬을 그냥 닫아도 오류창은 없고, 모은 것은 올라간다."""
    rec, diag, drv, _base = session
    before = len(diag.uploads)
    drv.quit()
    assert _wait(lambda: not rec.is_running(), 60)
    # running 은 마지막 업로드 **전에** 내려간다. 업로드가 실제로 끝날 때까지 본다.
    assert _wait(lambda: len(diag.uploads) > before, 30), diag.uploads[-1:]
    assert diag.uploads[-1]["meta"]["result"] == "browser_closed"
    # 그리고 stop() 을 눌러도(고객이 그럴 것이다) 예외가 밖으로 나오지 않는다.
    s = rec.stop()
    assert s["pages"] >= 2 and s["requests"] > 0
    assert any(row["where"] for row in rec.skipped)


def test_restarting_after_the_browser_closed_builds_a_fresh_one(monkeypatch):
    """창을 닫고 다시 [진단 기록 시작] 을 누르는 것은 자연스러운 순서다.

    죽은 드라이버를 그대로 재사용하면 시작하자마자 또 끊긴다. 살아 있는지
    찔러보고 죽었으면 새로 띄워야 한다.
    """
    class _DeadDriver:
        def execute_script(self, *_a, **_k):
            raise RuntimeError("invalid session id")

    built = []

    class _NewDriver(_DeadDriver):
        def execute_script(self, *_a, **_k):
            return 1

        def execute_cdp_cmd(self, *_a, **_k):
            return {}

        def get(self, url):
            built.append(url)

        def get_log(self, _kind):
            return []

    from aisarang import automation
    fresh = _NewDriver()
    monkeypatch.setattr(automation, "build_driver", lambda *a, **k: fresh)
    rec = recmod.DiagRecorder(diag=_CapturedDiag())
    rec.driver = _DeadDriver()
    assert rec.start(start_url="http://127.0.0.1:1/rec") is True
    try:
        assert rec.driver is fresh
        assert built == ["http://127.0.0.1:1/rec"]
    finally:
        rec.running = False


def test_cookie_values_are_never_collected():
    """쿠키는 이름/길이만 담는다. 값은 어디에도 남지 않아야 한다."""
    class _FakeDriver:
        def get_cookies(self):
            return [{"name": "JSESSIONID", "value": "SECRET-SESSION-VALUE",
                     "domain": ".childcare.go.kr", "path": "/",
                     "httpOnly": True, "secure": True}]

    rec = recmod.DiagRecorder()
    rec.driver = _FakeDriver()
    rows = rec._cookie_names()
    assert rows and rows[0]["name"] == "JSESSIONID"
    assert rows[0]["valueLength"] == len("SECRET-SESSION-VALUE")
    assert "SECRET-SESSION-VALUE" not in json.dumps(rows)


def test_the_products_own_chrome_options_actually_launch_chrome(tmp_path,
                                                                monkeypatch):
    """제품이 쓰는 옵션 그대로 크롬이 **뜨는지**, 그리고 네트워크 로그가 오는지.

    v1.0.6 작업 중에 perfLoggingPrefs 에 `traceCategories: ""` 를 넣었다가
    chromedriver 가 "cannot be empty" 로 **크롬을 아예 안 띄우는** 상태였다.
    옵션 한 줄이 09시에 프로그램을 통째로 못 쓰게 만들 수 있으므로, 여기서
    실제로 띄워서 확인한다.
    """
    from aisarang import automation, config
    monkeypatch.setattr(config, "profile_dir", lambda: tmp_path / "profile")
    try:
        drv = automation.build_driver(headless=True)
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"크롬을 띄우지 못함: {type(exc).__name__}: {str(exc)[:120]}")
    try:
        drv.get("data:text/html,<h1>ok</h1>")
        time.sleep(1.0)
        msgs = automation.drain_network(drv)
        assert msgs, "performance 로그가 비었다 = 네트워크 기록이 안 켜졌다"
        assert any(str(m.get("method", "")).startswith("Network.") for m in msgs)
        diag = _CapturedDiag()
        automation.capture(drv, diag, "probe")
        assert any(n == "network_probe.json" for n in diag.names()), diag.names()
        _name, body = diag.entry("network_probe.json")
        assert json.loads(body), "network_probe.json 이 비었다"
    finally:
        try:
            drv.quit()
        except Exception:
            pass


def test_the_recorder_has_no_way_to_click_anything():
    """이 모듈에 클릭/제출 경로가 존재하지 않는다는 것을 소스로 못박는다.

    나중에 누군가 '자동으로 한 번만 눌러주자' 를 넣으면 여기서 걸린다.
    """
    src = open(os.path.join(ROOT, "aisarang", "recorder.py"), encoding="utf-8").read()
    for banned in (".click()", "click()", ".submit()", "send_keys",
                   "ActionChains", "dispatchEvent"):
        assert banned not in src, banned
