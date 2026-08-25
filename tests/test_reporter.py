# -*- coding: utf-8 -*-
"""리포터는 어떤 상황에서도 프로그램을 죽이면 안 된다."""
import io
import os
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aisarang import config, masking
from aisarang.reporter import Diagnostics, _truncate_middle


def test_zip_contains_the_four_required_kinds():
    d = Diagnostics()
    d.log("실행 시작")
    d.add_page("reservation", "https://www.childcare.go.kr/?menuno=605", "<html>목록</html>")
    d.add_response("POST", "https://www.childcare.go.kr/icms/login/login.html", 200, "{}")
    blob = d.build_zip({"mode": "test"})
    names = zipfile.ZipFile(io.BytesIO(blob)).namelist()
    assert "meta.json" in names                     # 진단
    assert "run.log" in names                       # 로그
    assert any(n.startswith("page_source/") for n in names)   # 페이지 내용
    assert any(n.startswith("requests/") for n in names)      # 응답


def test_customer_id_is_stamped_everywhere():
    d = Diagnostics()
    d.log("아무 줄")
    blob = d.build_zip()
    z = zipfile.ZipFile(io.BytesIO(blob))
    assert config.CUSTOMER_ID in z.read("meta.json").decode()
    assert config.CUSTOMER_ID in z.read("run.log").decode()
    assert config.CUSTOMER_ID in d.summary_text("headline")


def test_everything_added_is_masked():
    masking.clear_secrets()
    masking.register_secret("certpw-9911")
    d = Diagnostics()
    d.add_page("p", "u", "<td>홍길동</td> 010-9999-1111 certpw-9911")
    d.add_response("POST", "u", 200, '{"uspass":"plaintextpw"}')
    body = zipfile.ZipFile(io.BytesIO(d.build_zip())).read(
        "page_source/0000_p.html").decode()
    assert "홍길동" not in body
    assert "9999" not in body
    assert "certpw-9911" not in body
    req = zipfile.ZipFile(io.BytesIO(d.build_zip())).read("requests/0000.json").decode()
    assert "plaintextpw" not in req


def test_a_snapshot_written_repeatedly_stays_one_entry():
    """시각 재측정은 5분마다 clock_resync.json 을 갱신한다. 쌓이면 ZIP 이 지저분해진다."""
    d = Diagnostics()
    for n in (1, 2, 3):
        d.add_json("clock_resync.json", {"resyncs": n})
    z = zipfile.ZipFile(io.BytesIO(d.build_zip()))
    assert z.namelist().count("clock_resync.json") == 1
    assert '"resyncs": 3' in z.read("clock_resync.json").decode()


def test_truncate_keeps_head_and_tail():
    text = "A" * 500 + "MIDDLE" + "B" * 500
    out = _truncate_middle(text, 200)
    assert out.startswith("A")
    assert out.endswith("B")
    assert "중략" in out
    assert len(out) < len(text)


def test_upload_failure_never_raises(monkeypatch):
    d = Diagnostics()

    import requests

    def boom(*a, **kw):
        raise requests.ConnectionError("network is down")

    monkeypatch.setattr(requests, "post", boom)
    d.upload("헤드라인", {"result": "x"}, blocking=True)   # 예외가 나오면 실패


def test_bad_payload_never_raises():
    d = Diagnostics()
    d.add_json("weird.json", {"obj": object()})
    d.add_text("none.txt", None)
    d.log(None)
    assert isinstance(d.build_zip(), bytes)


def test_exception_upload_is_once(monkeypatch):
    calls = []
    d = Diagnostics()
    monkeypatch.setattr(d, "upload", lambda *a, **kw: calls.append(1))
    err = ValueError("x")
    d.upload_exception(err, "a")
    d.upload_exception(err, "b")
    assert len(calls) == 1


def test_entry_count_is_bounded():
    d = Diagnostics()
    for i in range(500):
        d.add_text(f"x/{i}.txt", "y")
    assert len(d._entries) <= 120


def test_upload_without_zip_uses_json(monkeypatch):
    """첨부가 없으면 JSON 으로 보내야 한다. 폼 인코딩 + 파일 없음은 400 이다."""
    d = Diagnostics()
    monkeypatch.setattr(d, "build_zip", lambda *a, **kw: b"")
    seen = {}

    import requests

    class R:
        status_code = 200

        def json(self):
            return {"data": {"matched": True}}

    def fake_post(url, **kw):
        seen.update(kw)
        return R()

    monkeypatch.setattr(requests, "post", fake_post)
    d.upload("no-zip", {"result": "x"}, blocking=True)
    assert "json" in seen and seen["json"]["customerId"] == config.CUSTOMER_ID
    assert "files" not in seen


def test_upload_with_zip_uses_multipart(monkeypatch):
    d = Diagnostics()
    d.log("x")
    seen = {}

    import requests

    class R:
        status_code = 200

        def json(self):
            return {"data": {"matched": True}}

    def fake_post(url, **kw):
        seen.update(kw)
        return R()

    monkeypatch.setattr(requests, "post", fake_post)
    d.upload("with-zip", {"result": "x"}, blocking=True)
    assert "files" in seen and "data" in seen
    assert seen["data"]["customerId"] == config.CUSTOMER_ID
