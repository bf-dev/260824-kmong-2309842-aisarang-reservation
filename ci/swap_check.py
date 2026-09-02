# -*- coding: utf-8 -*-
"""자동 업데이트 '교체' 를 진짜로 실행해 본다 (윈도우 전용, CI 필수 단계).

왜 이 파일이 있는가
-------------------
2026-09-02, 고객은 "새 버전을 받았습니다 곧 자동으로 재시작합니다" 를 본 뒤
프로그램이 꺼지고 다시 오지 않는 것을 반복해서 겪었다. 09시 예약을 놓칠 뻔했다.

원인은 교체용 배치 안의 **파이프** 한 줄이었다:

    tasklist /FI "PID eq {pid}" 2>NUL | find "{pid}" >NUL

DETACHED_PROCESS 로 띄운 cmd 는 콘솔이 없고, 부모가 os._exit(0) 로 즉시 죽으면서
물려받은 표준 핸들도 닫힌다. 그 상태에서 cmd 가 파이프를 만들려고 하면(파이프는
cmd 가 자기 자신을 두 번 더 띄워 연결하는 구조다) **배치가 그 줄에서 통째로
중단된다.** windows-builder 실측: `echo hello | find "hello" >NUL` 한 줄만으로도
그 다음 줄이 하나도 실행되지 않았다. 그래서 robocopy 도 재실행도 도달하지 못했고,
버전이 그대로였으므로 다음 실행에서 똑같은 일이 반복됐다.

CI 가 이것을 못 잡은 이유는 단순하다. 그때까지 이 저장소의 업데이터 시험은 전부
순수 함수(choose_download / payload_root / zip 구조)만 봤고, **교체 배치는 CI 에서
한 번도 실행된 적이 없었다.** 그래서 이 파일이 생겼다. 여기서는 진짜로 배치를
띄우고, 파일이 정말 바뀌었는지, 프로그램이 정말 다시 떴는지 확인한다.

한글 경로도 같이 본다. 고객은 한국어 윈도우를 쓰고, 배치는 cmd 가 OEM 코드페이지로
읽기 때문에 UTF-8 로 쓴 한글 경로는 깨져서 robocopy 가 조용히 실패한다.

사용법:  python ci/swap_check.py <dist\aisarang-reservation 폴더>
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

EXE_NAME = "aisarang-reservation.exe"
PROOF = "SWAPPROOF.txt"
TIMEOUT_S = 120

DRIVER = r'''# -*- coding: utf-8 -*-
import sys, os
sys.path.insert(0, r"{repo}")
from aisarang import config, updater
config.is_frozen = lambda: True
updater.config.is_frozen = lambda: True
sys.executable = r"{exe}"
updater.UpdaterThread(status_cb=lambda *a: None)._swap_folder_and_restart(r"{zip}")
print("SWAP ABORTED BEFORE SPAWNING THE BATCH")
'''


def _kill_app() -> None:
    subprocess.run(["taskkill", "/f", "/im", EXE_NAME],
                   capture_output=True, text=True)


def run_case(dist: Path, work: Path, label: str, dirname: str) -> bool:
    print(f"\n=== case {label}: install dir = {dirname!r} ===", flush=True)
    root = work / dirname
    if root.exists():
        shutil.rmtree(root, ignore_errors=True)
    install = root / "app"
    shutil.copytree(dist, install)
    exe = install / EXE_NAME
    if not exe.is_file():
        print(f"FAIL: {exe} 가 없다")
        return False
    if (install / PROOF).exists():
        (install / PROOF).unlink()

    # 새 버전 페이로드: 같은 트리 + 교체가 됐는지 알려줄 표식 파일
    payload = work / f"payload-{label}" / "aisarang-reservation-9.9.9"
    if payload.parent.exists():
        shutil.rmtree(payload.parent, ignore_errors=True)
    shutil.copytree(dist, payload)
    (payload / PROOF).write_text("swapped\n", encoding="utf-8")
    zip_path = work / f"payload-{label}.zip"
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_STORED) as zf:
        for p in payload.rglob("*"):
            if p.is_file():
                zf.write(p, str(Path("aisarang-reservation-9.9.9") /
                                p.relative_to(payload)))

    driver_py = work / f"driver-{label}.py"
    driver_py.write_text(
        DRIVER.format(repo=str(REPO), exe=str(exe), zip=str(zip_path)),
        encoding="utf-8")

    _kill_app()
    proc = subprocess.run([sys.executable, str(driver_py)],
                          capture_output=True, text=True, timeout=180)
    print("driver rc:", proc.returncode)
    if proc.stdout.strip():
        print("driver out:", proc.stdout.strip()[-1500:])
    if proc.stderr.strip():
        print("driver err:", proc.stderr.strip()[-1500:])

    deadline = time.time() + TIMEOUT_S
    while time.time() < deadline:
        if (install / PROOF).is_file():
            break
        time.sleep(2)
    swapped = (install / PROOF).is_file()

    tl = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {EXE_NAME}", "/NH", "/FO", "CSV"],
                        capture_output=True, text=True).stdout or ""
    relaunched = EXE_NAME.lower() in tl.lower()
    _kill_app()

    try:
        from aisarang import config as _c
        swap_log = _c.log_dir() / "update-swap.log"
        if swap_log.exists():
            print("--- update-swap.log ---")
            print(swap_log.read_text(encoding="utf-8", errors="replace"))
            swap_log.unlink()
        else:
            print("--- update-swap.log MISSING (batch never ran) ---")
    except Exception as exc:
        print("swap log read failed:", exc)

    print(f"swapped={swapped} relaunched={relaunched}")
    if not swapped:
        print(f"FAIL[{label}]: 교체가 적용되지 않았다. 고객 PC 에서는 이것이 "
              f"'재시작합니다' 후 프로그램이 사라지는 증상으로 나타난다.")
        return False
    if not relaunched:
        print(f"FAIL[{label}]: 교체는 됐는데 프로그램이 다시 뜨지 않았다.")
        return False
    print(f"OK[{label}]")
    return True


def main() -> int:
    if os.name != "nt":
        print("SKIP: 윈도우에서만 의미가 있다")
        return 0
    if len(sys.argv) < 2:
        print("usage: python ci/swap_check.py <dist/aisarang-reservation>")
        return 2
    dist = Path(sys.argv[1]).resolve()
    if not (dist / EXE_NAME).is_file():
        print(f"FAIL: {dist / EXE_NAME} 가 없다")
        return 1
    work = Path(os.environ.get("RUNNER_TEMP") or os.environ.get("TEMP") or ".")
    work = work / "aisarang-swapcheck"
    work.mkdir(parents=True, exist_ok=True)

    ok = run_case(dist, work, "ascii", "plain")
    # 고객은 한국어 윈도우를 쓴다. 경로에 한글이 섞여도 교체가 되어야 한다.
    ok = run_case(dist, work, "korean", "설치폴더 한글") and ok

    print("\nSWAP CHECK:", "OK" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
