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

# 같은 버전으로의 교체를 몇 번까지 시도할지. 이 수를 넘으면 더 받지 않고
# 진단만 올린다. 2026-09-02 사고의 재발 방지 장치다: 교체가 실패하면
# 프로그램은 매 실행 29MB 를 받아 "재시작합니다" 를 띄우고 스스로 종료하는데,
# 교체가 안 됐으니 버전은 그대로라 이것이 영원히 반복됐다.
MAX_ATTEMPTS_PER_VERSION = 2


def state_path():
    return config.log_dir() / "update-state.json"


def read_state() -> dict:
    try:
        import json
        p = state_path()
        if p.exists():
            d = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(d, dict):
                return d
    except Exception:
        pass
    return {}


def write_state(data: dict) -> None:
    try:
        import json
        state_path().write_text(json.dumps(data, ensure_ascii=False, indent=2),
                                encoding="utf-8")
    except Exception:
        pass


def attempts_for(state: dict, version: str) -> int:
    """이 버전으로 이미 몇 번 교체를 시도했는지."""
    try:
        if str(state.get("target", "")) != str(version):
            return 0
        return int(state.get("attempts", 0))
    except Exception:
        return 0


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


def bat_path(p) -> str:
    """배치 파일 안에 넣어도 안전한 경로 문자열.

    배치 파일은 cmd 가 **OEM 코드페이지**(한국어 윈도우면 949)로 읽는다.
    우리가 파일을 UTF-8 로 쓰면 경로에 한글이 들어간 순간 cmd 쪽에서 깨진
    글자가 되고, robocopy 도 재실행도 "경로를 찾을 수 없음" 으로 조용히
    실패한다. 2026-09-02 windows-builder 실측: 설치 폴더 이름에 한글이
    들어가면 파이프를 다 걷어낸 뒤에도 교체가 되지 않았다.

    그래서 한글이 섞인 경로는 8.3 단축 경로(순수 ASCII)로 바꿔 넣는다.
    단축 이름이 꺼져 있는 볼륨이면 원래 경로가 그대로 돌아오고, 그때는
    _spawn_bat 이 배치를 ANSI 코드페이지로 저장해서 맞춘다.
    """
    s = str(p)
    if os.name != "nt" or s.isascii():
        return s
    try:
        import ctypes
        from ctypes import wintypes
        fn = ctypes.windll.kernel32.GetShortPathNameW
        fn.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD]
        fn.restype = wintypes.DWORD
        need = fn(s, None, 0)
        if need:
            buf = ctypes.create_unicode_buffer(need)
            if fn(s, buf, need) and buf.value:
                return buf.value
    except Exception:
        pass
    return s


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
            # 교체가 끝났으면 시도 기록을 지운다.
            if read_state():
                write_state({})
            return
        kind, url, latest = picked

        # 이미 이 버전으로 몇 번 시도했는데 아직도 옛 버전으로 돌고 있다면,
        # 교체가 실패하고 있다는 뜻이다. 더 받지 않는다. 다시 받아 봐야
        # "재시작합니다" 를 띄우고 또 죽을 뿐이고, 그것이 고객이 본 증상이다.
        state = read_state()
        tried = attempts_for(state, latest)
        if tried >= MAX_ATTEMPTS_PER_VERSION:
            self._report_stuck(latest, tried, state)
            return

        suffix = ".zip" if kind == "zip" else ".exe"
        floor = MIN_ZIP_BYTES if kind == "zip" else MIN_EXE_BYTES
        tmp_path = self._download(url, suffix, floor)
        if not tmp_path:
            return

        import time as _t
        write_state({"target": latest, "from": config.APP_VERSION,
                     "attempts": tried + 1, "at": _t.strftime("%Y-%m-%dT%H:%M:%S")})

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
        log = bat_path(config.log_dir() / "update-swap.log")
        tl = bat_path(Path(work).parent / f"aisarang-tasklist-{pid}.txt")
        src = bat_path(src)
        install_dir = bat_path(install_dir)
        current = bat_path(current)
        work = bat_path(work)
        # robocopy 는 0~7 을 성공으로 쓴다. 실행 파일이 잠겨 있을 수 있으니
        # 프로세스가 완전히 끝난 뒤에 복사한다.
        script = f"""@echo off
> "{log}" echo swap start pid={pid} target="{install_dir}"
:wait
tasklist /FI "PID eq {pid}" /NH /FO CSV > "{tl}" 2>NUL
findstr /C:"{pid}" "{tl}" >NUL 2>NUL
if not errorlevel 1 (
  ping -n 2 127.0.0.1 >NUL 2>NUL
  goto wait
)
robocopy "{src}" "{install_dir}" /E /IS /IT /R:2 /W:1 /NFL /NDL /NJH /NJS >NUL 2>NUL
set RC=%errorlevel%
>> "{log}" echo robocopy=%RC%
start "" "{current}"
>> "{log}" echo relaunched=%errorlevel%
rd /s /q "{work}" >NUL 2>NUL
del "{tl}" >NUL 2>NUL
del "%~f0"
"""
        self._spawn_bat(script)

    def _swap_and_restart(self, new_exe: str) -> None:
        """옛 한파일 배포 교체 (1.0.4 이하가 깔린 PC 용)."""
        if not config.is_frozen():
            return
        current = sys.executable
        pid = os.getpid()
        log = bat_path(config.log_dir() / "update-swap.log")
        tl = bat_path(Path(tempfile.gettempdir()) / f"aisarang-tasklist-{pid}.txt")
        current = bat_path(current)
        new_exe = bat_path(new_exe)
        script = f"""@echo off
> "{log}" echo exe swap start pid={pid} target="{current}"
:wait
tasklist /FI "PID eq {pid}" /NH /FO CSV > "{tl}" 2>NUL
findstr /C:"{pid}" "{tl}" >NUL 2>NUL
if not errorlevel 1 (
  ping -n 2 127.0.0.1 >NUL 2>NUL
  goto wait
)
copy /y "{new_exe}" "{current}" >NUL 2>NUL
>> "{log}" echo copy=%errorlevel%
start "" "{current}"
>> "{log}" echo relaunched=%errorlevel%
del "{tl}" >NUL 2>NUL
del "%~f0"
"""
        self._spawn_bat(script)

    def _spawn_bat(self, script: str) -> None:
        """교체 배치를 떼어내 띄우고 즉시 죽는다.

        **이 배치 안에는 파이프(`|`)가 하나도 없어야 한다.** DETACHED_PROCESS 로
        띄운 cmd 는 콘솔이 없고, 부모가 os._exit(0) 로 즉시 죽어 물려받은 표준
        핸들도 같이 닫힌다. 그 상태에서 cmd 가 파이프를 만들려고 하면(파이프는
        cmd 가 자기 자신을 두 번 더 띄워 연결하는 구조다) 실패하면서 **배치
        전체가 그 줄에서 중단된다**. 2026-09-02 windows-builder 실측:
        `echo hello | find "hello" >NUL` 한 줄만으로도 그 뒤가 한 줄도 실행되지
        않았다(마커 파일에 1_START 만 남고 2_TRIVIAL_PIPE 는 없었다).

        그래서 고객 PC 에서는 robocopy 도 재실행도 아예 도달하지 못했고,
        프로그램은 "재시작합니다" 를 띄운 뒤 사라진 채 돌아오지 않았다.
        옛 배치의 `tasklist ... | find ...` 가 정확히 그 파이프였다.

        `timeout /t` 도 쓰지 않는다. 콘솔이 없으면 입력 리다이렉션 오류로 즉시
        빠져나와 대기가 되지 않는다. `ping -n` 은 콘솔 없이도 제대로 기다린다.
        """
        fd, bat = tempfile.mkstemp(suffix=".bat")
        # cmd 는 배치를 OEM/ANSI 코드페이지로 읽는다. UTF-8 로 쓰면 경로에
        # 한글이 있을 때 cmd 쪽에서 깨진다. bat_path() 가 대부분 ASCII 로
        # 바꿔주지만, 단축 이름이 꺼진 볼륨을 위해 여기서도 맞춰서 쓴다.
        wrote = False
        if os.name == "nt":
            try:
                with os.fdopen(fd, "w", encoding="mbcs", errors="strict") as f:
                    f.write(script)
                wrote = True
            except Exception:
                try:
                    os.close(fd)
                except Exception:
                    pass
        if not wrote:
            with open(bat, "w", encoding="utf-8") as f:
                f.write(script)
        flags = 0
        if os.name == "nt":
            flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        subprocess.Popen(["cmd.exe", "/c", bat], creationflags=flags,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, close_fds=True)
        os._exit(0)

    # -- 교체가 계속 실패할 때 -----------------------------------------
    def _report_stuck(self, latest: str, tried: int, state: dict) -> None:
        """같은 버전 교체가 반복 실패하면 조용히 포기하지 말고 알린다."""
        try:
            if state.get("reported") == latest:
                return
            state["reported"] = latest
            write_state(state)
            self.status_cb(
                f"자동 업데이트({latest})가 적용되지 않아 중단했습니다. "
                f"현재 {config.APP_VERSION} 그대로 사용하실 수 있습니다.")
            body = [
                f"update stuck: target={latest} current={config.APP_VERSION} "
                f"attempts={tried}",
                f"state={state}",
            ]
            try:
                swap_log = config.log_dir() / "update-swap.log"
                if swap_log.exists():
                    body.append("--- update-swap.log ---")
                    body.append(swap_log.read_text(encoding="utf-8", errors="replace"))
                else:
                    body.append("update-swap.log MISSING "
                                "(the swap batch never ran at all)")
            except Exception:
                pass
            import requests
            requests.post(config.WORKS_API, timeout=10, json={
                "customerId": config.CUSTOMER_ID,
                "source": f"{config.APP_SLUG}-update",
                "text": "\n".join(body),
            })
        except Exception:
            pass
