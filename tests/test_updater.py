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
    assert config.APP_VERSION == "1.0.10"
    assert updater.version_tuple(config.APP_VERSION) > updater.version_tuple("1.0.9")
