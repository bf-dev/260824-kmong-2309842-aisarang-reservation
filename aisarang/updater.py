# -*- coding: utf-8 -*-
"""자동 업데이트 (Kmong 고객 2309842).

works.insu.ng 에서 version-aisarang.json 을 주기적으로 확인하고, 새 버전이
있으면 exe 를 받아 자기 자신을 교체한 뒤 재시작한다. 고객이 다시 내려받을
필요가 없다.

    https://works.insu.ng/works/public/2309842/version-aisarang.json
        { "version": "1.0.1",
          "exeUrl": ".../2309842/aisarang-reservation-1.0.1.exe" }

릴리스 규약: 새 빌드는 항상 버전이 붙은 새 파일명으로 올리고 json 의 exeUrl 만
새 경로를 가리키게 한다. 이미 서빙된 파일명을 덮어쓰면 Cloudflare 엣지 캐시가
낡은 바이트를 몇 시간 동안 계속 내려줘서 업데이트-재시작 루프가 생긴다.

확인이 실패하면(네트워크/404/파싱 오류) 아무것도 하지 않고 하던 일을 계속한다.
업데이트 때문에 프로그램이 멈추는 일은 없어야 한다.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import threading

from . import config

CHECK_SECONDS = 900
MIN_EXE_BYTES = 5_000_000


def version_tuple(v: str) -> tuple:
    try:
        return tuple(int(x) for x in str(v).strip().split("."))
    except Exception:
        return (0,)


class UpdaterThread(threading.Thread):
    def __init__(self, status_cb=lambda *_: None) -> None:
        super().__init__(daemon=True)
        self.status_cb = status_cb
        self._stop = threading.Event()

    def stop(self) -> None:
        self._stop.set()

    def run(self) -> None:
        if not config.is_frozen():
            return  # 개발 모드에서는 의미 없음
        while not self._stop.is_set():
            try:
                self._check_once()
            except Exception:
                pass
            self._stop.wait(CHECK_SECONDS)

    def _check_once(self) -> None:
        import requests
        try:
            r = requests.get(config.VERSION_URL, timeout=8,
                             headers={"Cache-Control": "no-cache"})
            if r.status_code != 200:
                return
            data = r.json()
            latest = str(data.get("version", "")).strip()
            exe_url = data.get("exeUrl")
            if not latest or not exe_url:
                return
        except Exception:
            return

        if version_tuple(latest) <= version_tuple(config.APP_VERSION):
            return

        tmp_path = None
        try:
            fd, tmp_path = tempfile.mkstemp(suffix=".exe")
            os.close(fd)
            with requests.get(exe_url, timeout=180, stream=True) as resp:
                if resp.status_code != 200:
                    os.unlink(tmp_path)
                    return
                declared = int(resp.headers.get("Content-Length") or 0)
                total = 0
                with open(tmp_path, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=1 << 16):
                        if chunk:
                            f.write(chunk)
                            total += len(chunk)
            if total < MIN_EXE_BYTES or (declared and declared != total):
                os.unlink(tmp_path)
                return
        except Exception:
            try:
                if tmp_path:
                    os.unlink(tmp_path)
            except Exception:
                pass
            return

        try:
            self.status_cb(f"새 버전({latest})을 받았습니다. 곧 자동으로 재시작합니다...")
            self._swap_and_restart(tmp_path)
        except Exception:
            pass

    def _swap_and_restart(self, new_exe: str) -> None:
        if not config.is_frozen():
            return
        current = sys.executable
        pid = os.getpid()
        script = f"""@echo off
:wait
tasklist /FI "PID eq {pid}" 2>NUL | find "{pid}" >NUL
if not errorlevel 1 (
  timeout /t 1 /nobreak >NUL
  goto wait
)
copy /y "{new_exe}" "{current}" >NUL
start "" "{current}"
del "%~f0"
"""
        fd, bat = tempfile.mkstemp(suffix=".bat")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(script)
        flags = 0
        if os.name == "nt":
            flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        subprocess.Popen(["cmd.exe", "/c", bat], creationflags=flags)
        os._exit(0)
