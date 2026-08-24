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
from http.server import BaseHTTPRequestHandler, HTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
FIX = os.path.join(HERE, "fixtures")


def _read(name: str) -> bytes:
    with open(os.path.join(FIX, name), "rb") as f:
        return f.read()


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
        return self._send(b"{}", "application/json; charset=UTF-8")


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 18642
    HTTPServer(("127.0.0.1", port), Handler).serve_forever()
