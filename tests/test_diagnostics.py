# -*- coding: utf-8 -*-
"""진단 수집 용량 (v1.0.10).

왜 이 파일이 생겼나. 2026-09-01 09:00 캡처를 읽고 "가상대기열 티켓이 발급된
적이 없다" 고 고객에게 보고했는데 **틀렸다**. 티켓은 08:42 에 이미 nwait=0 으로
발급돼 있었고(sessionStorage 의 NetFunnel_ID 가 증거다), 그 발급 요청이
network_*.json 의 300건 링버퍼에서 잘려 나갔을 뿐이다.

  network_handover_after.json  = 300건 (정확히 상한)
  가장 이른 항목 id            = 54164.420 (그 앞의 419건은 사라짐)
  티켓 발급(opcode=5002) 위치   = 그 419건 안

그래서 세 가지를 못박는다.
  1. 상한이 실제로 올라갔다.
  2. 잘릴 때 **앞과 뒤**가 같이 남는다(가운데를 버린다).
  3. 예약/대기열 줄은 어디에 있든 남는다.
그리고 예약 POST 의 요청/응답 **본문**을 남기는 훅이 실제로 걸린다.
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aisarang import automation, config


def _rows(n, key_at=()):
    out = []
    for i in range(n):
        url = f"https://www.childcare.go.kr/cms/gen/images/a{i}.png"
        if i in key_at:
            url = "https://www.childcare.go.kr/icms/occasion/InsertOcreqst.html"
        out.append({"id": f"x.{i}", "kind": "request", "method": "GET", "url": url})
    return out


def test_the_limits_actually_went_up():
    """300건이 우리를 틀리게 만들었다. 다시는 그 값이면 안 된다."""
    assert config.NET_DIGEST_LIMIT >= 1000, config.NET_DIGEST_LIMIT
    assert config.NET_RING_MAX >= 10000, config.NET_RING_MAX
    assert automation._NET_RING.maxlen == config.NET_RING_MAX


def test_nothing_is_trimmed_below_the_limit():
    rows = _rows(500)
    assert automation._trim_middle(rows, config.NET_DIGEST_LIMIT) == rows


def test_trimming_keeps_the_head_as_well_as_the_tail():
    """v1.0.9 는 `rows[-limit:]` 이었다. 앞부분이 통째로 사라졌다."""
    rows = _rows(1000)
    out = automation._trim_middle(rows, 100)
    urls = [r.get("url") for r in out if r.get("kind") == "request"]
    assert urls[0] == rows[0]["url"], "앞부분이 남지 않았습니다"
    assert urls[-1] == rows[-1]["url"], "뒷부분이 남지 않았습니다"
    assert len(out) <= 120
    # 버린 만큼을 숫자로 남긴다(조용히 사라지지 않는다).
    elided = [r for r in out if r.get("kind") == "elided"]
    assert elided and sum(r["droppedEntries"] for r in elided) == 1000 - len(urls)


def test_the_booking_and_queue_rows_are_never_dropped():
    """가운데 깊숙이 묻혀 있어도 예약/대기열 줄은 남아야 한다."""
    rows = _rows(2000, key_at=(900,))
    rows[901] = {"id": "x.901", "kind": "request", "method": "GET",
                 "url": "https://nf.childcare.go.kr:8443/ts.wseq?opcode=5002&key=AB"}
    out = automation._trim_middle(rows, 50)
    urls = " ".join(str(r.get("url")) for r in out)
    assert "InsertOcreqst" in urls
    assert "opcode=5002" in urls


def test_the_digest_default_limit_is_the_config_value():
    import inspect
    sig = inspect.signature(automation._network_digest)
    assert sig.parameters["limit"].default == config.NET_DIGEST_LIMIT


# ------------------------------------------------- 예약 POST 본문 기록기

def test_the_recorder_watches_the_booking_post_and_the_queue():
    js = automation._JS_NET_RECORDER
    assert "InsertOcreqst" in js
    assert "ts.wseq" in js
    assert "responseBody" in js and "requestBody" in js
    assert "getAllResponseHeaders" in js


def test_the_recorder_can_never_break_the_customers_page():
    """1순위 규칙: 고객 프로그램을 절대 망가뜨리지 않는다.

      · 원래 핸들러를 교체하지 않는다 (onreadystatechange 를 건드리지 않는다)
      · 응답을 소비하지 않는다 (fetch 는 clone 한다)
      · 모든 갈래가 try/catch 안에 있다
    """
    js = automation._JS_NET_RECORDER
    assert "onreadystatechange" not in js, "페이지의 핸들러를 덮어쓰면 안 됩니다"
    assert "addEventListener('loadend'" in js
    assert "r.clone()" in js, "fetch 응답을 소비하면 페이지가 깨집니다"
    # 원래 구현을 반드시 그대로 호출해 돌려준다.
    assert "_open.apply(this, arguments)" in js
    assert "_send.apply(this, arguments)" in js
    # window 로 고정해야 한다. this 를 넘기면 엄격 모드 호출에서
    # "Illegal invocation" 이 나고 페이지의 fetch 가 죽는다.
    assert "_fetch.apply(window, arguments)" in js
    assert "_fetch.apply(this" not in js
    # 동기 갈래: try 마다 catch 가 있다 = 감싸지 않은 갈래가 없다.
    assert js.count("try {") == js.count("catch (e)") == 10
    # 비동기 갈래: .then 마다 .catch 가 붙어 있다(거부가 새어 나가면 페이지에
    # unhandled rejection 이 뜬다).
    assert js.count(".then(") == js.count(".catch(") == 2


def test_the_recorder_redacts_credentials_and_bounds_its_size():
    js = automation._JS_NET_RECORDER
    assert "REDACTED" in js
    for word in ("pass", "pwd", "password", "aResult", "cert"):
        assert word in js
    assert "MAX_BODY" in js and "MAX_ROWS" in js


def test_the_capture_writes_the_bodies_into_the_zip():
    src = open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "aisarang", "automation.py"),
        encoding="utf-8").read()
    assert "xhr_bodies_" in src
    assert "_page_net_bodies(driver)" in src
    # 그리고 드라이버를 띄울 때 실제로 걸린다.
    assert re.search(r"neutralize_devtool_blocker\(driver, log\)\s*\n\s*"
                     r"install_net_recorder\(driver, log\)", src)


class _FakeDiag:
    def __init__(self):
        self.files = {}

    def add_page(self, *a, **k):
        pass

    def add_json(self, name, data):
        self.files[name] = json.loads(json.dumps(data, ensure_ascii=False))


class _FakeDriver:
    page_source = "<html></html>"
    current_url = "https://www.childcare.go.kr/?menuno=605"

    def get_cookies(self):
        return []

    def get_log(self, *_a):
        return []

    def execute_script(self, script, *a):
        if "__aisarangNet" in script:
            return [{"kind": "xhr", "method": "POST",
                     "url": "https://www.childcare.go.kr/icms/occasion/InsertOcreqst.html",
                     "status": 200,
                     "requestBody": "resdt=20260915&resgb=R",
                     "responseHeaders": "date: Tue, 01 Sep 2026 00:00:00 GMT",
                     "responseBody": '{"returnval":"fail","returnmsg":"..."}'}]
        return {}


def test_capture_lands_the_bodies_file():
    diag = _FakeDiag()
    automation.capture(_FakeDriver(), diag, "handover_after")
    assert "xhr_bodies_handover_after.json" in diag.files, sorted(diag.files)
    row = diag.files["xhr_bodies_handover_after.json"][0]
    assert "InsertOcreqst" in row["url"]
    assert "returnval" in row["responseBody"]


# ------------------------------- 진짜 크롬에서 본문이 실제로 잡히는지 (로컬 전용)
#
# 여기 서버는 100% 로컬이다. childcare.go.kr 로는 한 바이트도 나가지 않는다
# (--host-resolver-rules 로 127.0.0.1 외의 모든 이름을 막는다).

import threading                                            # noqa: E402
from http.server import BaseHTTPRequestHandler, HTTPServer   # noqa: E402

import pytest                                                # noqa: E402

_PAGE = """<!doctype html><meta charset="utf-8"><title>t</title>
<body><script>
window.__done = 0;
function go(){
  var x = new XMLHttpRequest();
  x.open('POST', '/icms/occasion/InsertOcreqst.html', true);
  x.setRequestHeader('Content-Type', 'application/x-www-form-urlencoded');
  x.onreadystatechange = function(){
    if (x.readyState === 4) { window.__pageSawIt = x.responseText; window.__done = 1; }
  };
  x.send('resdt=20260915&resgb=R&certPassword=hunter2');
}
</script></body>"""

_REPLY = ('{"returnval":"fail",'
          '"returnmsg":"1건 예약 중 1건 예약이 선예약으로 인해 예약되지 않았습니다."}')


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        body = _PAGE.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        self.rfile.read(n)
        body = _REPLY.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture(scope="module")
def local_site():
    srv = HTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}/"
    srv.shutdown()


def test_a_real_chrome_records_the_submit_bodies(local_site):
    """v1.0.9 ZIP 에 없던 바로 그것: 예약 POST 의 요청/응답 본문."""
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"selenium 없음: {exc}")
    o = Options()
    for a in ("--headless=new", "--no-sandbox", "--disable-dev-shm-usage",
              "--disable-gpu",
              "--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1"):
        o.add_argument(a)
    try:
        d = webdriver.Chrome(options=o)
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"크롬을 띄우지 못함: {type(exc).__name__}")
    try:
        assert automation.install_net_recorder(d) is True
        d.get(local_site)
        d.execute_script("go();")
        for _ in range(100):
            if d.execute_script("return window.__done;"):
                break
            import time as _t
            _t.sleep(0.05)

        # 1) 페이지 자신의 핸들러가 응답을 그대로 받았다 (기록기가 가로채지 않았다)
        assert "returnmsg" in (d.execute_script("return window.__pageSawIt;") or "")

        rows = automation._page_net_bodies(d)
        assert len(rows) == 1, rows
        row = rows[0]
        assert row["method"] == "POST"
        assert "InsertOcreqst" in row["url"]
        assert row["status"] == 200
        # 2) 응답 본문이 통째로 남는다 -> returnval 을 눈으로 볼 수 있다
        assert '"returnval":"fail"' in row["responseBody"]
        assert "선예약으로 인해" in row["responseBody"]
        # 3) 요청 본문도 남는다 -> 무엇을 보냈는지 확인할 수 있다
        assert "resdt=20260915" in row["requestBody"]
        # 4) 비밀번호는 지워진다
        assert "hunter2" not in row["requestBody"], row["requestBody"]
        assert "REDACTED" in row["requestBody"]
        # 5) 응답 헤더(Date) 도 남는다 -> 실제 도착 초를 사후에 잴 수 있다
        assert "date" in row["responseHeaders"].lower()
    finally:
        try:
            d.quit()
        except Exception:
            pass
