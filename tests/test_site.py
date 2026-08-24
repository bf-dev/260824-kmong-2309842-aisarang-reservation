# -*- coding: utf-8 -*-
"""기관 목록 파서 회귀 테스트.

fixture 는 실제 childcare.go.kr 의 TmpCareSlLAjax 응답을 줄인 것이다.
안쪽의 <ul class="result_info"> 가 닫히는 </ul> 때문에 li 블록이 일찍
잘려 이용대상이 통째로 사라졌던 버그를 붙잡아 둔다.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aisarang import config, site

FIXTURE = """
<p class="amoung_result">총 <b id="emTotCnt">2</b>개가 검색되었습니다.</p>
<ul class="result_list">
    <li class="preschool">
        <div class="result_list_left">
            <span class="badge">어린이집</span>
            <div class="result_title"><a href="#" id="infoMove" data-val="11650000416" title="새창열림">서초구육아종합지원센터(신반포)</a></div>
            <button class="btn_favorite" onclick="javascript:fnStFav('11650000416'); return false;"></button>
            <address>서울특별시 서초구 신반포로19길 26</address>
            <ul class="result_info">
                <li>연락처 : 02-596-9340</li>
                <li>예약 :
                     예약가능
                </li>
            </ul>
        </div>
        <div class="result_btn_group">
            <a href="#none" class="btn on round" id="occasionRes" data-stcode="11650000416" data-unityyn="N" data-unityynall="">시간제보육 예약</a>
            <a href="javascript:" id="viwMap" data-val="11650000416">지도보기</a>
        </div>
        <dl class="result_detail">
            <dt>이용대상</dt>
            <dd>
                    6개월~36개월 미만
            </dd>
            <dt>연락처</dt>
            <dd>02-596-9340</dd>
            <dt>예약</dt>
            <dd> 예약가능 </dd>
        </dl>
    </li>
    <li class="preschool">
        <div class="result_list_left">
            <div class="result_title"><a href="#" id="infoMove" data-val="11650000201">서정어린이집</a></div>
            <address>서울특별시 서초구 방배천로 48</address>
            <ul class="result_info">
                <li>연락처 : 02-581-7227</li>
                <li>예약 : 예약마감 </li>
            </ul>
        </div>
        <dl class="result_detail">
            <dt>이용대상</dt>
            <dd>6개월~36개월 미만</dd>
        </dl>
    </li>
</ul>
"""


def test_parses_every_center_once():
    rows = site.parse_center_list(FIXTURE, "N")
    assert len(rows) == 2
    assert [r["stcode"] for r in rows] == ["11650000416", "11650000201"]


def test_map_link_is_not_a_center():
    rows = site.parse_center_list(FIXTURE, "N")
    assert all(r["name"] != "지도보기" for r in rows)


def test_target_age_survives_inner_ul():
    """이 필드가 비면 li 블록이 안쪽 </ul> 에서 잘린 것이다."""
    rows = site.parse_center_list(FIXTURE, "N")
    assert rows[0]["target"] == "6개월~36개월 미만"
    assert rows[1]["target"] == "6개월~36개월 미만"


def test_fields_are_extracted():
    r = site.parse_center_list(FIXTURE, "N")[0]
    assert r["name"] == "서초구육아종합지원센터(신반포)"
    assert r["address"] == "서울특별시 서초구 신반포로19길 26"
    assert r["tel"] == "02-596-9340"
    assert r["status"] == "예약가능"
    assert r["unityYn"] == "N"


def test_closed_status_is_read():
    rows = site.parse_center_list(FIXTURE, "N")
    assert rows[1]["status"] == "예약마감"


def test_empty_body_is_safe():
    assert site.parse_center_list("", "N") == []
    assert site.parse_center_list("<ul class='result_list'></ul>", "Y") == []


def test_default_center_matches_the_customers_choice():
    """고객이 지정한 기본 센터가 실제 사이트 코드와 맞는지 고정."""
    d = config.DEFAULT_CENTER
    assert d["stcode"] == "11650000416"
    assert d["name"] == "서초구육아종합지원센터(신반포)"
    assert d["signgu"] == "11650" and d["ctprvn"] == "11000"
    assert d["unityYn"] == "N"
