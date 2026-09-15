# -*- coding: utf-8 -*-
"""게시한 매니페스트의 사본을 리포에 남긴다 (`deploy/manifests/`).

왜 있나. 매니페스트 파일은 리포에 없고 gateway artifacts 아래 한 곳에만 있다:
`/home/bfdev/neoworks/apps/gateway/artifacts/public/2309842/version-aisarang.json`
게시할 때마다 직전 판을 `~/workspace/kmong/tmp/` 에 떠 뒀는데, **tmp 는 14일 뒤
청소된다.** ZIP 은 계속 서빙되므로 되돌리기가 불가능해지지는 않지만,
`notes` 의 한국어 본문(= 그 판을 왜 냈는지의 기록)은 어디에도 안 남아 사라진다.
에러 하나 없이 조용히 없어지는 종류의 손실이라 리포로 옮겼다.

매니페스트에는 비밀이 없다: 버전, URL, sha256, 크기, 안내문뿐이다.

이 파일은 '다음 게시 때 사본 남기는 것을 기억하기' 를 시험으로 바꾼다.
기억에 의존하면 언젠가 빠진다.
"""
import glob
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
ARCHIVE = os.path.join(ROOT, "deploy", "manifests")

_NAME = re.compile(r"^version-aisarang-(\d+\.\d+\.\d+)\.json$")


def _files():
    return sorted(glob.glob(os.path.join(ARCHIVE, "version-aisarang-*.json")))


def test_the_archive_exists_and_is_not_empty():
    assert os.path.isdir(ARCHIVE), f"{ARCHIVE} 가 없습니다"
    assert _files(), "보관된 매니페스트가 하나도 없습니다"


def test_every_archived_manifest_is_valid_and_matches_its_filename():
    for path in _files():
        name = os.path.basename(path)
        m = _NAME.match(name)
        assert m, f"이름 규칙이 아닙니다: {name}"
        with open(path, encoding="utf-8") as fh:
            d = json.load(fh)                       # 깨진 JSON 이면 여기서 터진다
        assert d["version"] == m.group(1), (name, d["version"])


def test_no_archived_manifest_carries_an_exeUrl():
    """1.0.4 이하의 옛 업데이터는 exeUrl 이 있으면 ZIP 을 exe 자리에 덮어쓴다.

    되돌릴 때 쓰는 사본이므로, 사본에 exeUrl 이 섞여 있으면 되돌리는 순간
    그 사고가 재현된다.
    """
    for path in _files():
        with open(path, encoding="utf-8") as fh:
            d = json.load(fh)
        assert "exeUrl" not in d, os.path.basename(path)
        assert d.get("zipUrl", "").endswith(".zip"), os.path.basename(path)


def test_each_archived_manifest_keeps_its_notes_body():
    """`notes` 가 이 사본의 존재 이유다. 비어 있으면 보관할 가치가 없다."""
    for path in _files():
        with open(path, encoding="utf-8") as fh:
            d = json.load(fh)
        assert d.get("notes", "").strip(), os.path.basename(path)


def test_the_archived_values_are_internally_consistent():
    for path in _files():
        with open(path, encoding="utf-8") as fh:
            d = json.load(fh)
        name = os.path.basename(path)
        assert isinstance(d["size"], int) and d["size"] > 5_000_000, name
        assert re.fullmatch(r"[0-9a-f]{64}", d["sha256"]), name
        # zipUrl 의 파일명에도 같은 판 번호가 박혀 있어야 한다. 파일명을
        # 재사용하면 Cloudflare 캐시가 옛 바이트를 계속 내려준다.
        assert f"-{d['version']}.zip" in d["zipUrl"], name
        assert d["supersedes"] != d["version"], name
