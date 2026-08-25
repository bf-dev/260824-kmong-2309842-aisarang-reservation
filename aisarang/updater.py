# -*- coding: utf-8 -*-
"""자동 업데이트 (Kmong 고객 2309842).

works.insu.ng 에서 version-aisarang.json 을 주기적으로 확인하고, 새 버전이
있으면 받아서 자기 자신을 교체한 뒤 재시작한다. 고객이 다시 내려받을 필요가 없다.

    https://works.insu.ng/works/public/2309842/version-aisarang.json
        { "version": "1.0.5",
          "zipUrl": ".../2309842/aisarang-reservation-1.0.5.zip" }

**v1.0.5 부터 배포 형식이 폴더(ZIP) 다.** 예전에는 한 덩어리 exe(--onefile)
였는데, 그 형식은 실행할 때마다 자기 자신을 %TEMP% 에 풀어놓기 때문에 윈도우
디펜더가 이것을 악성코드 동작으로 오탐해 파일을 격리한다(고객 PC 에서 실제로
그렇게 됐다: "지정한 장치, 경로 또는 파일에 액세스할 수 없습니다").
--onedir 폴더 형식은 푸는 동작이 없어서 그 오탐 경로를 아예 지나가지 않는다.

그래서 교체 방식도 달라진다:
  zipUrl  → ZIP 을 받아 임시폴더에 풀고, 프로그램이 종료된 뒤 설치 폴더 위에
            robocopy 로 덮어쓴 다음 다시 실행한다 (폴더 통째 교체).
  exeUrl  → 옛 방식(한 파일 교체). 1.0.4 이하가 설치된 PC 를 위해 남겨둔다.

릴리스 규약: 새 빌드는 항상 버전이 붙은 새 파일명으로 올리고 json 의 URL 만
새 경로를 가리키게 한다. 이미 서빙된 파일명을 덮어쓰면 Cloudflare 엣지 캐시가
낡은 바이트를 몇 시간 동안 계속 내려줘서 업데이트-재시작 루프가 생긴다.

확인이 실패하면(네트워크/404/파싱 오류) 아무것도 하지 않고 하던 일을 계속한다.
업데이트 때문에 프로그램이 멈추는 일은 없어야 한다.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import threading
import zipfile
from pathlib import Path

from . import config

CHECK_SECONDS = 900
MIN_EXE_BYTES = 5_000_000
MIN_ZIP_BYTES = 5_000_000


def version_tuple(v: str) -> tuple:
    try:
        return tuple(int(x) for x in str(v).strip().split("."))
    except Exception:
        return (0,)


def choose_download(manifest: dict, current_version: str) -> tuple | None:
    """매니페스트에서 받을 것을 고른다. (kind, url, version) 또는 None.

    폴더 배포(zipUrl)를 우선한다. 순수 함수라 테스트가 쉽다.
    """
    try:
        latest = str(manifest.get("version", "")).strip()
    except Exception:
        return None
    if not latest:
        return None
    if version_tuple(latest) <= version_tuple(current_version):
        return None
    zip_url = manifest.get("zipUrl")
    if isinstance(zip_url, str) and zip_url.strip():
        return ("zip", zip_url.strip(), latest)
    exe_url = manifest.get("exeUrl")
    if isinstance(exe_url, str) and exe_url.strip():
        return ("exe", exe_url.strip(), latest)
    return None


def payload_root(extracted_dir, exe_name: str):
    """푼 폴더에서 실제 프로그램 폴더를 찾는다.

    ZIP 안에 최상위 폴더가 하나 있는 형태(aisarang-reservation-1.0.5/…)와
    파일이 바로 들어 있는 형태를 모두 받아준다. exe 가 없으면 None 을 돌려
    호출부가 교체를 포기하게 한다(반쯤 덮어쓰는 것이 최악이다).
    """
    root = Path(extracted_dir)
    if (root / exe_name).is_file():
        return root
    entries = [p for p in root.iterdir()] if root.is_dir() else []
    dirs = [p for p in entries if p.is_dir()]
    if len(entries) == 1 and len(dirs) == 1 and (dirs[0] / exe_name).is_file():
        return dirs[0]
    for d in dirs:
        if (d / exe_name).is_file():
            return d
    return None


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

    # -- 확인 --------------------------------------------------------
    def _check_once(self) -> None:
        import requests
        try:
            r = requests.get(config.VERSION_URL, timeout=8,
                             headers={"Cache-Control": "no-cache"})
            if r.status_code != 200:
                return
            data = r.json()
        except Exception:
            return

        picked = choose_download(data if isinstance(data, dict) else {},
                                 config.APP_VERSION)
        if not picked:
            return
        kind, url, latest = picked

        suffix = ".zip" if kind == "zip" else ".exe"
        floor = MIN_ZIP_BYTES if kind == "zip" else MIN_EXE_BYTES
        tmp_path = self._download(url, suffix, floor)
        if not tmp_path:
            return

        try:
            self.status_cb(f"새 버전({latest})을 받았습니다. 곧 자동으로 재시작합니다...")
            if kind == "zip":
                self._swap_folder_and_restart(tmp_path)
            else:
                self._swap_and_restart(tmp_path)
        except Exception:
            pass

    def _download(self, url: str, suffix: str, min_bytes: int):
        """받은 바이트가 온전할 때만 경로를 돌려준다. 아니면 지우고 None."""
        import requests
        tmp_path = None
        try:
            fd, tmp_path = tempfile.mkstemp(suffix=suffix)
            os.close(fd)
            with requests.get(url, timeout=300, stream=True) as resp:
                if resp.status_code != 200:
                    os.unlink(tmp_path)
                    return None
                declared = int(resp.headers.get("Content-Length") or 0)
                total = 0
                with open(tmp_path, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=1 << 16):
                        if chunk:
                            f.write(chunk)
                            total += len(chunk)
            if total < min_bytes or (declared and declared != total):
                os.unlink(tmp_path)
                return None
            return tmp_path
        except Exception:
            try:
                if tmp_path:
                    os.unlink(tmp_path)
            except Exception:
                pass
            return None

    # -- 교체 --------------------------------------------------------
    def _swap_folder_and_restart(self, new_zip: str) -> None:
        """폴더 배포 교체. 풀어서 확인이 끝난 뒤에만 덮어쓰기를 예약한다."""
        if not config.is_frozen():
            return
        current = Path(sys.executable)
        install_dir = current.parent
        exe_name = current.name

        work = tempfile.mkdtemp(prefix="aisarang-update-")
        try:
            with zipfile.ZipFile(new_zip) as zf:
                zf.extractall(work)
        except Exception:
            shutil.rmtree(work, ignore_errors=True)
            return
        try:
            os.unlink(new_zip)
        except Exception:
            pass

        src = payload_root(work, exe_name)
        if src is None:
            shutil.rmtree(work, ignore_errors=True)
            return

        pid = os.getpid()
        # robocopy 는 0~7 을 성공으로 쓴다. 실행 파일이 잠겨 있을 수 있으니
        # 프로세스가 완전히 끝난 뒤에 복사한다.
        script = f"""@echo off
:wait
tasklist /FI "PID eq {pid}" 2>NUL | find "{pid}" >NUL
if not errorlevel 1 (
  timeout /t 1 /nobreak >NUL
  goto wait
)
robocopy "{src}" "{install_dir}" /E /IS /IT /R:2 /W:1 /NFL /NDL /NJH /NJS >NUL
start "" "{current}"
rd /s /q "{work}"
del "%~f0"
"""
        self._spawn_bat(script)

    def _swap_and_restart(self, new_exe: str) -> None:
        """옛 한파일 배포 교체 (1.0.4 이하가 깔린 PC 용)."""
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
        self._spawn_bat(script)

    def _spawn_bat(self, script: str) -> None:
        fd, bat = tempfile.mkstemp(suffix=".bat")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(script)
        flags = 0
        if os.name == "nt":
            flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        subprocess.Popen(["cmd.exe", "/c", bat], creationflags=flags)
        os._exit(0)
