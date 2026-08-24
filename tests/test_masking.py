# -*- coding: utf-8 -*-
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aisarang import masking


def setup_function(_):
    masking.clear_secrets()


def test_rrn_is_masked():
    out = masking.mask("주민번호 900101-1234567 입니다")
    assert "1234567" not in out
    assert "900101-1******" in out


def test_phone_is_masked():
    out = masking.mask("연락처 : 010-1234-5678")
    assert "1234" not in out
    assert "5678" not in out


def test_landline_is_masked():
    out = masking.mask("<li>연락처 : 02-596-9340</li>")
    assert "9340" not in out


def test_card_is_masked():
    out = masking.mask("카드 5327-1234-5678-9012")
    assert "1234-5678" not in out
    assert out.endswith("9012")


def test_cert_password_never_leaks():
    masking.register_secret("SuperSecret!2026")
    out = masking.mask("certpw=SuperSecret!2026 and again SuperSecret!2026")
    assert "SuperSecret" not in out


def test_password_field_value_masked():
    out = masking.mask('{"uspass":"hunter2xyz","mbrid":"abc"}')
    assert "hunter2xyz" not in out


def test_signed_blob_masked():
    out = masking.mask('<input name="aResult" value="MIIFAKESIGNEDBLOB123456">')
    assert "MIIFAKESIGNEDBLOB123456" not in out


def test_name_field_masked():
    out = masking.mask('mbrNm="홍길동"')
    assert "홍길동" not in out
    assert "홍**" in out


def test_name_in_table_cell_masked():
    out = masking.mask("<td>김민수</td>")
    assert "김민수" not in out


def test_ui_words_are_not_mangled():
    out = masking.mask("<td>예약가능</td><td>어린이집</td><td>통합반</td>")
    assert "어린이집" in out
    assert "통합반" in out


def test_mask_never_raises():
    assert masking.mask(None) == ""
    assert isinstance(masking.mask(12345), str)
    assert isinstance(masking.mask(object()), str)


def test_email_masked():
    out = masking.mask("parent@example.com")
    assert "parent@" not in out
    assert "example.com" in out
