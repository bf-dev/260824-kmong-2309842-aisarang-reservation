# -*- coding: utf-8 -*-
"""ci/fixtures/real/ 을 http 로 내주는 아주 작은 정적 서버.

왜 file:// 이 아니라 http 인가:
크롬은 file:// 문서마다 오리진을 따로 준다. 그래서 <link> 로 불러온 CSS 의
cssRules 접근이 SecurityError 로 막히고, 실제로 **스타일이 붙지 않은 것처럼**
보이는 상황이 생긴다. 이 프로젝트에서는 그게 치명적이다.
사이트의 팝업 껍데기는 `.popup_wrap { display: none }` (sub.css) 하나로만
숨겨져 있고, 그게 안 먹으면 숨어 있어야 할 확인창 두 번째 사본까지
"보인다" 로 판정되기 때문이다. 실제 브라우저에서의 가시성 판정을 그대로
재현하려면 같은 오리진의 http 로 띄워야 한다.
"""
from __future__ import annotations

import functools
import os
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
REAL = os.path.join(HERE, "fixtures", "real")


class _Quiet(SimpleHTTPRequestHandler):
    def log_message(self, *args):  # 조용히
        pass


class RealFixtureServer:
    """with 문으로 쓴다. .url('modal_open.html') 로 주소를 얻는다."""

    def __init__(self, root: str = REAL):
        self.root = root
        self.httpd = None
        self.thread = None

    def __enter__(self):
        handler = functools.partial(_Quiet, directory=self.root)
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *exc):
        if self.httpd:
            self.httpd.shutdown()
            self.httpd.server_close()
        return False

    def url(self, name: str) -> str:
        return f"http://127.0.0.1:{self.port}/{name}"
