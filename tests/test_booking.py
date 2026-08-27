# -*- coding: utf-8 -*-
"""4·5단계(날짜 표 → 추가 → 체크 → 예약하기 → 확인)의 판정과 불변식.

근거는 고객이 보내준 인증서 세션 화면녹화(docs/site-map/recording/)와
서버 응답이다. 응답 문구의 근거 등급이 서로 다르다:

  예약시간전  **실물**. 2026-08-27 09:00:00 고객 PC 캡처에서 서버가 실제로
              돌려준 원문 "아직 예약 가능한 시간이 아닙니다."
              (`booking.TOO_EARLY_REAL`, InsertOcreqst.html 의 returnmsg)
  정원초과    아직 고객 진술뿐이다. 어떤 캡처에도 한 건도 없다.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aisarang import booking


# ---------------------------------------------------------------- 응답 분류

def test_too_early_is_not_a_failure():
    # 실물 원문이 먼저다. 나머지는 표기 흔들림을 넓게 열어둔 것이다.
    assert booking.TOO_EARLY_REAL == "아직 예약 가능한 시간이 아닙니다."
    assert booking.classify(booking.TOO_EARLY_REAL) == booking.R_TOO_EARLY
    assert booking.classify("알림 아직 예약 가능한 시간이 아닙니다. 확인") \
        == booking.R_TOO_EARLY
    assert booking.classify("예약시간전입니다.") == booking.R_TOO_EARLY
    assert booking.classify("아직 예약시간이 아닙니다.") == booking.R_TOO_EARLY
    assert booking.result_is_retryable(booking.R_TOO_EARLY)


def test_the_real_wording_is_one_character_from_the_sites_own_refusal():
    """실물 두 문구가 '한' 한 글자 차이다. 여기가 섞이면 자리를 버린다.

        예약시간전  "아직 예약 가능한 시간이 아닙니다."   서버 returnmsg (실물)
        칸 거절     "예약 가능 시간이 아닙니다."          selectDay2() (실물)

    앞의 것은 다시 쏘면 되는 상태, 뒤의 것은 다시 쏴봐야 소용없는 상태다.
    """
    assert booking.classify("예약 가능 시간이 아닙니다.") == booking.R_NOT_BOOKABLE
    assert not booking.result_is_retryable(booking.R_NOT_BOOKABLE)
    # 사이트가 언젠가 '아직' 을 붙인 채 '가능' 으로 써도 틀리지 않는다.
    assert booking.classify("아직 예약 가능 시간이 아닙니다.") == booking.R_TOO_EARLY


def test_full_is_terminal():
    assert booking.classify("정원초과") == booking.R_FULL
    assert booking.classify("정원이 초과되었습니다.") == booking.R_FULL
    assert not booking.result_is_retryable(booking.R_FULL)


def test_full_wins_over_generic_failure_words():
    """'정원초과' 안에 '초과' 가 들어 있다. 일반 실패로 떨어지면 안 된다."""
    assert booking.classify("정원초과 입니다") == booking.R_FULL


def test_ok_and_unknown():
    assert booking.classify("예약이 완료되었습니다.") == booking.R_OK
    assert booking.classify("") == booking.R_UNKNOWN
    assert booking.classify("무슨 말인지 모를 문구") == booking.R_UNKNOWN


# ---------------------------------------------------------------- 표 읽기

def _grid():
    """영상 f_016/f_019 의 표 그대로: 09-07 은 전부 0, 09-08 은 전부 2, 09-06 은 X."""
    g = booking.Grid(table_index=0)
    for date, texts in (("20260906", ["X"] * 9),
                        ("20260907", ["0"] * 9),
                        ("20260908", ["2"] * 9)):
        g.rows.append({"date": date, "label": date, "row": len(g.rows) + 1})
        for i, t in enumerate(texts):
            g.cells.append(booking.Cell(date=date, hour=9 + i, text=t,
                                        capacity=booking._parse_cell_text(t),
                                        row=len(g.rows), col=i + 1))
    return g


def test_x_and_zero_are_reported_not_clicked():
    g = _grid()
    cell, why = booking.pick_cell(g, "20260906", [9])
    assert cell is None
    assert "이용불가" in why

    cell, why = booking.pick_cell(g, "20260907", [9])
    assert cell is None
    assert "0명" in why


def test_available_cell_is_picked_by_priority():
    g = _grid()
    cell, why = booking.pick_cell(g, "20260908", [11, 9])
    assert cell is not None and cell.hour == 11
    assert "남은 자리 2명" in why


def test_missing_date_row_is_reported_with_what_is_there():
    g = _grid()
    cell, why = booking.pick_cell(g, "20260915", [9])
    assert cell is None
    assert "20260908" in why


def test_first_open_cell_when_nothing_preferred():
    g = _grid()
    cell, _ = booking.pick_cell(g, "20260908", [])
    assert cell is not None and cell.hour == 9


def test_cell_text_parsing():
    assert booking._parse_cell_text("X") is None
    assert booking._parse_cell_text("×") is None
    assert booking._parse_cell_text("0") == 0
    assert booking._parse_cell_text("2") == 2
    assert booking._parse_cell_text("") is None


# ---------------------------------------------------------------- 불변식

def _ready() -> booking.Prepared:
    return booking.Prepared(target_date="20260908", start_hour=9, hours=9,
                            cell_selected=True, row_ticked=True,
                            row_index=3, modal_open=True, armed=True)


class FakeClock:
    offset = 0.0
    one_way = 0.0
    correction = 0.0
    correction_notes = []

    def __init__(self, now=0.0):
        self._now = now

    def server_now(self):
        return self._now

    def arrival_for_local_fire(self, local_epoch):
        return local_epoch

    def note_too_early(self, est, margin=0.03):
        return 0.0


class FireDriver:
    """__aisarang_fire 만 흉내낸다. 몇 번 눌렸는지 센다."""

    def __init__(self, answers):
        self.answers = list(answers)
        self.fires = 0
        self.page_source = "<html></html>"

    def execute_script(self, script, *a):
        if "__aisarang_fire" in script:
            self.fires += 1
            return True
        if "__aisarang_ok" in script:      # still_armed
            return True
        return None


def test_confirm_never_fires_without_selected_cell(monkeypatch):
    p = _ready()
    p.cell_selected = False
    d = FireDriver([])
    shot = booking.confirm_once(d, p, FakeClock(), 0.0, 1)
    assert d.fires == 0
    assert shot.fired is False
    assert "날짜 칸" in shot.text


def test_confirm_never_fires_without_ticked_row():
    p = _ready()
    p.row_ticked = False
    d = FireDriver([])
    shot = booking.confirm_once(d, p, FakeClock(), 0.0, 1)
    assert d.fires == 0
    assert "체크" in shot.text


def test_confirm_never_fires_without_open_modal():
    p = _ready()
    p.modal_open = False
    d = FireDriver([])
    shot = booking.confirm_once(d, p, FakeClock(), 0.0, 1)
    assert d.fires == 0


def test_open_modal_refuses_when_row_not_ticked(monkeypatch):
    p = _ready()
    p.modal_open = False
    pressed = []
    monkeypatch.setattr(booking, "slot_row_is_ticked", lambda d, i=-1: False)
    monkeypatch.setattr(booking, "press_reserve",
                        lambda d, log=None: pressed.append(1) or True)
    res = booking.open_modal(FireDriver([]), p)
    assert not res.ok
    assert res.reason == "guard_row"
    assert pressed == [], "[예약하기] 를 누르면 안 된다"


def test_open_modal_refuses_when_cell_not_selected(monkeypatch):
    p = _ready()
    p.cell_selected = False
    pressed = []
    monkeypatch.setattr(booking, "press_reserve",
                        lambda d, log=None: pressed.append(1) or True)
    res = booking.open_modal(FireDriver([]), p)
    assert not res.ok
    assert res.reason == "guard_cell"
    assert pressed == []


# ---------------------------------------------------------------- 재시도 규칙

def _burst(monkeypatch, codes, clock=None):
    """read_outcome 을 정해진 순서로 답하게 만들고 confirm_burst 를 돌린다."""
    seq = list(codes)
    calls = {"n": 0}

    def fake_outcome(driver, timeout=6.0):
        i = min(calls["n"], len(seq) - 1)
        calls["n"] += 1
        code = seq[i]
        text = {"too_early": "예약시간전", "full": "정원초과",
                "ok": "예약이 완료되었습니다.", "unknown": "???"}[code]
        return code, text

    monkeypatch.setattr(booking, "read_outcome", fake_outcome)
    monkeypatch.setattr(booking, "redrive_confirm", lambda d, p, log=None: True)
    monkeypatch.setattr(booking.time, "sleep", lambda *_: None)
    d = FireDriver([])
    p = _ready()
    res = booking.confirm_burst(d, p, clock or FakeClock(-0.4), 0.0,
                                retry_seconds=5, retry_ms=1)
    return d, res, calls


def test_burst_retries_on_too_early_then_succeeds(monkeypatch):
    d, res, _ = _burst(monkeypatch, ["too_early", "too_early", "ok"])
    assert res.ok
    assert d.fires == 3
    assert res.detail["confirmAttempts"] == 3
    codes = [s["code"] for s in res.detail["shots"]]
    assert codes == ["too_early", "too_early", "ok"]


def test_burst_stops_immediately_on_full(monkeypatch):
    """정원초과는 이미 나간 자리다. 두들기면 안 된다."""
    d, res, _ = _burst(monkeypatch, ["full", "ok", "ok"])
    assert not res.ok
    assert res.reason == "full"
    assert d.fires == 1


def test_burst_records_arrival_offset_of_each_confirm(monkeypatch):
    d, res, _ = _burst(monkeypatch, ["too_early", "ok"])
    for s in res.detail["shots"]:
        assert "arrivalOffsetMs" in s
        assert s["text"]


def test_burst_stops_when_window_passes(monkeypatch):
    """계속 예약시간전이면 재시도 창이 닫힐 때 끝난다(무한루프 금지)."""
    class Ticking(FakeClock):
        def server_now(self):
            self._now += 1.0
            return self._now

    d, res, _ = _burst(monkeypatch, ["too_early"], clock=Ticking(-2.0))
    assert not res.ok
    assert res.reason == "exhausted"
    assert d.fires <= 8


# ---------------------------------------------------------------- 보정

def test_note_too_early_corrects_only_when_we_thought_we_were_late():
    from aisarang.clock import ClockSync

    c = ClockSync(offset=0.0, rtt_best=0.020, synced=True)
    # 일부러 정각 300ms 전에 겨냥한 발이 '예약시간전' → 배울 게 없다.
    assert c.note_too_early(-0.300) == 0.0
    assert c.correction == 0.0
    # 정각 +80ms 에 도착했다고 믿었는데 서버가 아직 이르다고 했다 → 그만큼 늦춘다.
    added = c.note_too_early(0.080)
    assert added > 0
    assert 0.10 <= c.correction <= 0.12
    # 보정이 실제 발사 시각을 뒤로 미룬다.
    assert c.local_fire_for_arrival(1000.0) > 1000.0 - c.one_way


def test_correction_never_goes_backwards():
    from aisarang.clock import ClockSync

    c = ClockSync(synced=True)
    c.note_too_early(0.200)
    first = c.correction
    assert c.note_too_early(0.050) == 0.0
    assert c.correction == first
