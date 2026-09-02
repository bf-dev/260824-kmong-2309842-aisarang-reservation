# -*- coding: utf-8 -*-
"""업데이터와 배포 패키징.

v1.0.5 에서 배포 형식이 한 파일 exe → 폴더(ZIP) 로 바뀌었다. 업데이터가
반쯤 덮어쓰는 일이 절대 없도록, 받은 ZIP 안에 exe 가 확인될 때만 교체하게
되어 있다. 그 판정을 여기서 고정한다.
"""
import os
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aisarang import config, updater  # noqa: E402
from ci import package_zip  # noqa: E402


def test_zip_is_preferred_over_exe():
    picked = updater.choose_download(
        {"version": "1.0.9",
         "zipUrl": "https://x/a.zip",
         "exeUrl": "https://x/a.exe"}, "1.0.5")
    assert picked == ("zip", "https://x/a.zip", "1.0.9")


def test_legacy_exe_manifest_still_updates_an_old_install():
    picked = updater.choose_download(
        {"version": "1.0.5", "exeUrl": "https://x/a.exe"}, "1.0.4")
    assert picked == ("exe", "https://x/a.exe", "1.0.5")


def test_same_or_older_version_does_nothing():
    assert updater.choose_download({"version": "1.0.5", "zipUrl": "u"}, "1.0.5") is None
    assert updater.choose_download({"version": "1.0.4", "zipUrl": "u"}, "1.0.5") is None
    assert updater.choose_download({}, "1.0.5") is None
    assert updater.choose_download({"version": "1.0.9"}, "1.0.5") is None


def test_payload_root_finds_the_program_folder(tmp_path):
    top = tmp_path / "aisarang-reservation-1.0.9"
    (top / "_internal").mkdir(parents=True)
    (top / "aisarang-reservation.exe").write_bytes(b"MZ")
    assert updater.payload_root(tmp_path, "aisarang-reservation.exe") == top
    # exe 가 바로 들어 있는 형태도 받아준다
    flat = tmp_path / "flat"
    flat.mkdir()
    (flat / "aisarang-reservation.exe").write_bytes(b"MZ")
    assert updater.payload_root(flat, "aisarang-reservation.exe") == flat


def test_payload_root_refuses_when_the_exe_is_missing(tmp_path):
    (tmp_path / "something").mkdir()
    assert updater.payload_root(tmp_path, "aisarang-reservation.exe") is None


def test_package_zip_has_one_top_folder_the_exe_and_the_korean_guide(tmp_path):
    dist = tmp_path / "dist" / config.APP_SLUG
    (dist / "_internal").mkdir(parents=True)
    (dist / f"{config.APP_SLUG}.exe").write_bytes(b"MZ" + b"\0" * 64)
    (dist / "_internal" / "python312.dll").write_bytes(b"\0" * 32)

    zip_path = package_zip.build(dist, tmp_path / "out")
    names = zipfile.ZipFile(zip_path).namelist()
    top = f"{config.APP_SLUG}-{config.APP_VERSION}"
    assert zip_path.name == f"{top}.zip"
    assert f"{top}/{config.APP_SLUG}.exe" in names
    assert f"{top}/_internal/python312.dll" in names
    assert f"{top}/{package_zip.README_NAME}" in names
    # 고객이 더블클릭하는 파일 이름은 ASCII 여야 한다 (탐색기 한글 깨짐 사고 방지)
    assert all(n.isascii() for n in names if n.endswith(".exe"))
    assert top.isascii()

    # 그리고 그 ZIP 은 업데이터가 그대로 받아들여야 한다
    work = tmp_path / "work"
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(work)
    root = updater.payload_root(work, f"{config.APP_SLUG}.exe")
    assert root == work / top
    assert (Path(root) / "_internal" / "python312.dll").is_file()


def test_one_point_ten_is_newer_than_one_point_nine():
    """이번 판이 정확히 그 함정이다. 문자열로 비교하면 1.0.10 < 1.0.9 다.

    문자열 비교를 쓰면 v1.0.9 고객은 영원히 갱신을 못 받는다. 실제로 다른
    프로젝트에서 그렇게 고객이 한 판에 묶인 적이 있다.
    """
    assert "1.0.10" < "1.0.9"                       # 문자열로는 이렇다
    assert updater.version_tuple("1.0.10") > updater.version_tuple("1.0.9")

    manifest = {"version": "1.0.10",
                "zipUrl": "https://works.insu.ng/works/public/2309842/"
                          "aisarang-reservation-1.0.10.zip"}
    got = updater.choose_download(manifest, "1.0.9")
    assert got is not None, "1.0.9 -> 1.0.10 갱신 경로가 막혔습니다"
    kind, url, version = got
    assert kind == "zip" and version == "1.0.10"
    assert url.endswith("aisarang-reservation-1.0.10.zip")

    # 이미 최신이면 받지 않는다(재시작 루프 방지).
    assert updater.choose_download(manifest, "1.0.10") is None
    assert updater.choose_download(manifest, "1.0.11") is None
    # 두 자리 이상으로 올라가도 계속 맞아야 한다.
    assert updater.version_tuple("1.1.0") > updater.version_tuple("1.0.99")
    assert updater.version_tuple("1.0.100") > updater.version_tuple("1.0.99")


def test_the_shipped_version_matches_what_the_manifest_will_say():
    assert config.APP_VERSION == "1.0.11"
    assert updater.version_tuple(config.APP_VERSION) > updater.version_tuple("1.0.10")


# ---------------------------------------------------------------- 2026-09-02
#
# 이 아래는 2026-09-02 사고의 회귀 시험이다.
#
# 그날 고객은 "새 버전을 받았습니다 곧 자동으로 재시작합니다" 를 본 뒤 프로그램이
# 꺼지고 다시 오지 않는 것을 반복해서 겪었다. 원인은 교체용 배치 안의 **파이프**
# 였다. `tasklist ... | find ...` 한 줄. DETACHED_PROCESS 로 띄운 cmd 는 콘솔이
# 없고, 부모가 os._exit(0) 로 즉시 죽어 표준 핸들도 닫힌다. 그 상태에서 cmd 가
# 파이프를 만들려 하면 배치가 그 줄에서 통째로 중단된다(windows-builder 실측:
# `echo hello | find "hello" >NUL` 만으로도 그 뒤가 한 줄도 실행되지 않았다).
# 그래서 robocopy 도 재실행도 도달하지 못했고, 버전이 그대로라 매 실행 반복됐다.
#
# CI 가 이것을 못 잡은 이유는 단순하다: 아래 세 개가 생기기 전까지 이 저장소의
# 업데이터 시험은 전부 순수 함수(choose_download/payload_root/zip 구조)만 봤고,
# 교체 배치는 CI 에서도 windows-builder 에서도 **한 번도 실행된 적이 없다**.

def _swap_script(tmp_path, monkeypatch):
    """실제 교체 배치 문자열을 만들어 돌려준다(스폰은 하지 않는다)."""
    import sys as _s
    install = tmp_path / "install"
    install.mkdir()
    exe = install / "aisarang-reservation.exe"
    exe.write_bytes(b"old")
    payload = tmp_path / "payload"
    (payload / "aisarang-reservation-9.9.9").mkdir(parents=True)
    (payload / "aisarang-reservation-9.9.9" / "aisarang-reservation.exe").write_bytes(b"new")
    zip_path = tmp_path / "new.zip"
    import zipfile as _z
    with _z.ZipFile(zip_path, "w") as zf:
        for p in (payload / "aisarang-reservation-9.9.9").iterdir():
            zf.write(p, f"aisarang-reservation-9.9.9/{p.name}")

    monkeypatch.setattr(config, "is_frozen", lambda: True)
    monkeypatch.setattr(updater.config, "is_frozen", lambda: True)
    monkeypatch.setattr(_s, "executable", str(exe))
    captured = {}
    monkeypatch.setattr(updater.UpdaterThread, "_spawn_bat",
                        lambda self, script: captured.setdefault("script", script))
    updater.UpdaterThread()._swap_folder_and_restart(str(zip_path))
    return captured.get("script", "")


def test_the_swap_batch_contains_no_pipe(tmp_path, monkeypatch):
    """배치에 파이프가 있으면 고객 PC 에서 교체가 통째로 중단된다."""
    script = _swap_script(tmp_path, monkeypatch)
    assert script, "교체 배치가 만들어지지 않았다"
    assert "|" not in script, (
        "교체 배치에 파이프가 있다. DETACHED_PROCESS + 콘솔 없음 상태에서는 "
        "그 줄에서 배치가 죽고 robocopy/재실행에 도달하지 못한다:\n" + script)


def test_the_swap_batch_does_not_use_timeout_command(tmp_path, monkeypatch):
    """timeout 은 콘솔이 없으면 즉시 실패해서 대기가 되지 않는다."""
    script = _swap_script(tmp_path, monkeypatch)
    assert "timeout /t" not in script
    assert "ping -n" in script, "프로세스 종료 대기 수단이 없다"


def test_the_swap_batch_records_what_it_did(tmp_path, monkeypatch):
    """교체가 실패해도 서버에서 보이도록 robocopy 결과를 남겨야 한다."""
    script = _swap_script(tmp_path, monkeypatch)
    assert "robocopy=" in script
    assert "update-swap.log" in script


def test_bat_path_is_ascii_for_a_korean_install_dir():
    """한글 경로는 배치에 그대로 넣으면 cmd 가 깨뜨린다(8.3 또는 ANSI 로 처리)."""
    # 리눅스에서는 변환이 없다(윈도우 전용 문제). 반환값이 문자열이면 된다.
    assert isinstance(updater.bat_path("/tmp/한글"), str)
    assert updater.bat_path("/tmp/ascii") == "/tmp/ascii"


def test_repeated_failed_updates_stop_instead_of_looping(tmp_path, monkeypatch):
    """같은 버전 교체가 계속 실패하면 다운로드를 멈춘다(무한 재시작 방지)."""
    state = {"target": "1.0.10", "from": "1.0.9", "attempts": 2}
    assert updater.attempts_for(state, "1.0.10") == 2
    assert updater.attempts_for(state, "1.0.11") == 0
    assert updater.attempts_for({}, "1.0.10") == 0
    assert updater.MAX_ATTEMPTS_PER_VERSION == 2
