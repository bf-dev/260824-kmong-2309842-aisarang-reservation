# -*- coding: utf-8 -*-
"""프로그램 화면 (tkinter).

원칙
  - 고객이 손으로 고칠 설정 파일은 없다. 모든 설정은 이 화면 안에 있다.
  - 켜짐/꺼짐은 글자로 보여준다. tkinter 기본 체크박스는 켜진 상태가 X 로
    보여서 꺼진 것처럼 읽히므로 쓰지 않는다.
  - 버튼 핸들러는 전부 safe_handler 로 감싼다. --noconsole 로 빌드된 exe 는
    stdout 이 None 이라, 처리 안 된 예외 하나에 창이 그냥 사라진다.
"""
from __future__ import annotations

import datetime as dt
import functools
import threading
import tkinter as tk
from tkinter import messagebox, ttk

from . import config, site
from .reporter import Diagnostics
from .runner import Runner
from .updater import UpdaterThread

BG = "#f4f6fa"
CARD = "#ffffff"
INK = "#1c2430"
MUTED = "#6b7684"
ACCENT = "#1b64da"
ACCENT_DK = "#154fae"
OK = "#0b8a4b"
BAD = "#c3352b"
LINE = "#dfe3ea"

SLOT_HOURS = [f"{h:02d}:00" for h in range(9, 18)]


def safe_handler(fn):
    """버튼에서 터진 예외가 창을 죽이지 않게 한다."""
    @functools.wraps(fn)
    def wrapper(self, *a, **kw):
        try:
            return fn(self, *a, **kw)
        except Exception as exc:  # noqa: BLE001
            try:
                self.diag.upload_exception(exc, fn.__name__)
            except Exception:
                pass
            try:
                messagebox.showerror("오류", f"{fn.__name__} 처리 중 문제가 생겼습니다.\n\n"
                                             f"{type(exc).__name__}: {exc}")
            except Exception:
                pass
    return wrapper


class WordToggle(tk.Frame):
    """켜짐/꺼짐을 글자로 보여주는 토글."""

    def __init__(self, master, on_text="사용", off_text="사용 안 함",
                 value=False, command=None, width=12):
        super().__init__(master, bg=CARD)
        self.on_text, self.off_text = on_text, off_text
        self._value = bool(value)
        self._command = command
        self.btn = tk.Button(self, text="", width=width, relief="flat", bd=0,
                             font=("맑은 고딕", 10, "bold"), cursor="hand2",
                             command=self._toggle, padx=10, pady=6)
        self.btn.pack()
        self._paint()

    def _paint(self):
        if self._value:
            self.btn.config(text=self.on_text, bg=ACCENT, fg="white",
                            activebackground=ACCENT_DK, activeforeground="white")
        else:
            self.btn.config(text=self.off_text, bg="#e8ebf0", fg=MUTED,
                            activebackground="#dde1e8", activeforeground=MUTED)

    def _toggle(self):
        self._value = not self._value
        self._paint()
        if self._command:
            try:
                self._command(self._value)
            except Exception:
                pass

    def get(self) -> bool:
        return self._value

    def set(self, v: bool):
        self._value = bool(v)
        self._paint()


class SegmentedChoice(tk.Frame):
    """여러 선택지 중 하나. 선택된 것이 글자와 색으로 드러난다."""

    def __init__(self, master, options, value=None, command=None):
        super().__init__(master, bg=CARD)
        self.options = options            # [(key, label), ...]
        self._value = value or options[0][0]
        self._command = command
        self._buttons = {}
        for key, label in options:
            b = tk.Button(self, text=label, relief="flat", bd=0, cursor="hand2",
                          font=("맑은 고딕", 10, "bold"), padx=14, pady=7,
                          command=lambda k=key: self._pick(k))
            b.pack(side="left", padx=(0, 6))
            self._buttons[key] = b
        self._paint()

    def _paint(self):
        for key, b in self._buttons.items():
            if key == self._value:
                b.config(bg=ACCENT, fg="white", activebackground=ACCENT_DK,
                         activeforeground="white")
            else:
                b.config(bg="#e8ebf0", fg=MUTED, activebackground="#dde1e8",
                         activeforeground=MUTED)

    def _pick(self, key):
        self._value = key
        self._paint()
        if self._command:
            try:
                self._command(key)
            except Exception:
                pass

    def get(self):
        return self._value

    def set(self, key):
        if key in self._buttons:
            self._value = key
            self._paint()


class SlotPicker(tk.Frame):
    """시간대 선택 칩. 선택 여부를 색과 글자로 보여준다."""

    def __init__(self, master, hours=SLOT_HOURS, per_row=5):
        super().__init__(master, bg=CARD)
        self.per_row = per_row
        self._state = {}
        self._buttons = {}
        for i, h in enumerate(hours):
            b = tk.Button(self, text=h, relief="flat", bd=0, cursor="hand2",
                          font=("맑은 고딕", 10), width=6, padx=2, pady=6,
                          command=lambda k=h: self._toggle(k))
            b.grid(row=i // self.per_row, column=i % self.per_row, padx=3, pady=2)
            self._state[h] = False
            self._buttons[h] = b
        self._paint()

    def _paint(self):
        for h, b in self._buttons.items():
            if self._state[h]:
                b.config(bg=ACCENT, fg="white", font=("맑은 고딕", 10, "bold"))
            else:
                b.config(bg="#eef1f5", fg=MUTED, font=("맑은 고딕", 10))

    def _toggle(self, h):
        self._state[h] = not self._state[h]
        self._paint()

    def get(self) -> list:
        return [h for h in self._buttons if self._state[h]]

    def set(self, slots):
        for h in self._state:
            self._state[h] = h in (slots or [])
        self._paint()


def card(parent, title, compact=False):
    wrap = tk.Frame(parent, bg=BG)
    wrap.pack(fill="x", pady=(0, 7 if compact else 12))
    head = tk.Label(wrap, text=title, bg=BG, fg=INK,
                    font=("맑은 고딕", 11, "bold"), anchor="w")
    head.pack(fill="x", pady=(0, 4 if compact else 6))
    box = tk.Frame(wrap, bg=CARD, highlightthickness=1,
                   highlightbackground=LINE, highlightcolor=LINE)
    box.pack(fill="x")
    inner = tk.Frame(box, bg=CARD)
    inner.pack(fill="x", padx=16, pady=8 if compact else 14)
    return inner


class App:
    def __init__(self, root: tk.Tk, diag: Diagnostics | None = None):
        self.root = root
        self.diag = diag or Diagnostics()
        self.settings = config.load_settings()
        self.centers: list[dict] = []
        self.sido: list[dict] = []
        self.gugun: list[dict] = []
        self.runner: Runner | None = None
        self.recorder = None
        self._updater = None

        root.title(f"{config.APP_NAME}  v{config.APP_VERSION}")
        root.configure(bg=BG)
        # 화면이 낮은 PC(1366x768 노트북, CI 러너 등)에서는 창이 잘려서
        # 결과 표시줄과 로그가 안 보인다. 화면 높이에 맞춰 여백을 줄인다.
        try:
            screen_h = root.winfo_screenheight()
        except Exception:
            screen_h = 1080
        self.compact = screen_h < 900
        height = max(620, min(900, screen_h - 90))
        root.geometry(f"880x{height}")
        root.minsize(820, 600)

        self._build()
        self._apply_settings()
        self._start_updater()

    # ------------------------------------------------------------ 화면
    def _build(self):
        shell = tk.Frame(self.root, bg=BG)
        shell.pack(fill="both", expand=True, padx=18, pady=8 if self.compact else 14)

        # 실행 버튼 / 결과 / 상태 / 로그를 먼저 바닥에 붙여 자리를 확보한다.
        # 위쪽 카드들이 먼저 자리를 다 먹으면 화면이 낮은 PC 에서 결과 표시줄이
        # 통째로 잘려 나간다(실제로 CI 스크린샷에서 두 번 잘렸다).
        # side="bottom" 으로 먼저 pack 한 것이 가장 아래를 차지한다.
        self._build_bottom(shell)

        # 설정 영역은 스크롤된다. 화면이 낮아도 카드가 찌그러지지 않고,
        # 아래 실행/결과/로그는 언제나 제자리에 남는다.
        mid = tk.Frame(shell, bg=BG)
        mid.pack(side="top", fill="both", expand=True)
        canvas = tk.Canvas(mid, bg=BG, highlightthickness=0, bd=0)
        vsb = ttk.Scrollbar(mid, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        canvas.pack(side="left", fill="both", expand=True)
        self._canvas = canvas          # 스크린샷용: 아래쪽 카드를 보여줄 때 쓴다
        outer = tk.Frame(canvas, bg=BG)
        win = canvas.create_window((0, 0), window=outer, anchor="nw")

        def _on_content(_=None):
            try:
                canvas.configure(scrollregion=canvas.bbox("all"))
                need = outer.winfo_reqheight() > canvas.winfo_height()
                if need and not vsb.winfo_ismapped():
                    vsb.pack(side="right", fill="y")
                elif not need and vsb.winfo_ismapped():
                    vsb.pack_forget()
            except Exception:
                pass

        outer.bind("<Configure>", _on_content)
        canvas.bind("<Configure>",
                    lambda e: (canvas.itemconfigure(win, width=e.width), _on_content()))
        canvas.bind_all(
            "<MouseWheel>",
            lambda e: canvas.yview_scroll(int(-1 * (e.delta / 120)), "units"))

        # 머리말
        head = tk.Frame(outer, bg=BG)
        head.pack(fill="x", pady=(0, 7 if self.compact else 14))
        tk.Label(head, text="아이사랑 시간제보육 예약", bg=BG, fg=INK,
                 font=("맑은 고딕", 18, "bold")).pack(side="left")
        tk.Label(head, text=f"  v{config.APP_VERSION}", bg=BG, fg=MUTED,
                 font=("맑은 고딕", 10)).pack(side="left", pady=(8, 0))
        tk.Label(head, text="매일 오전 9시 오픈분을 서버 시각에 맞춰 신청합니다",
                 bg=BG, fg=MUTED, font=("맑은 고딕", 10)).pack(side="right", pady=(8, 0))

        # 0. 실행 방식. 2026-08-26 부터 인계 모드가 기본이다.
        c = card(outer, "1. 실행 방식", self.compact)
        self.mode_choice = SegmentedChoice(
            c,
            [(config.MODE_HANDOVER, "인계 모드 · 제가 확인창까지 만들어 둡니다"),
             (config.MODE_AUTO, "자동 모드 · 프로그램이 처음부터 진행")],
            value=config.MODE_HANDOVER, command=self._on_run_mode)
        self.mode_choice.grid(row=0, column=0, columnspan=4, sticky="w")
        self.lbl_mode = tk.Label(
            c, text="", bg=CARD, fg=INK, font=("맑은 고딕", 10),
            anchor="w", justify="left")
        self.lbl_mode.grid(row=1, column=0, columnspan=4, sticky="w", pady=(10, 0))

        # 1. 로그인
        c = card(outer, "2. 로그인 방식", self.compact)
        self.login_choice = SegmentedChoice(
            c,
            [("manual", "크롬에서 직접 로그인"), ("cert", "공동인증서 자동 로그인")],
            value="manual", command=self._on_login_mode)
        self.login_choice.grid(row=0, column=0, columnspan=3, sticky="w")
        tk.Label(c, text="인증서는 이 PC 에만 있고, 비밀번호는 이 화면 밖으로 나가지 않습니다.",
                 bg=CARD, fg=MUTED, font=("맑은 고딕", 9)).grid(
            row=1, column=0, columnspan=3, sticky="w", pady=(8, 0))
        tk.Label(c, text="시간제보육 신청 화면은 공동인증서(또는 간편인증) 로그인에서만 열립니다. "
                         "아이디 로그인으로는 화면이 비어서 나옵니다.",
                 bg=CARD, fg=BAD, font=("맑은 고딕", 9), anchor="w", justify="left").grid(
            row=5, column=0, columnspan=3, sticky="w", pady=(10, 0))
        tk.Label(c, text="로그인 세션은 60분이면 끊깁니다. 프로그램이 9시까지 세션을 살려 둡니다.",
                 bg=CARD, fg=MUTED, font=("맑은 고딕", 9)).grid(
            row=6, column=0, columnspan=3, sticky="w", pady=(4, 0))
        tk.Label(c, text="인증서 비밀번호", bg=CARD, fg=INK,
                 font=("맑은 고딕", 10)).grid(row=2, column=0, sticky="w", pady=(10, 0))
        self.cert_pw = tk.Entry(c, show="●", width=26, font=("맑은 고딕", 11),
                                relief="flat", bg="#f0f2f6", disabledbackground="#f0f2f6")
        self.cert_pw.grid(row=2, column=1, sticky="w", padx=(12, 0), pady=(10, 0),
                          ipady=6, ipadx=8)
        self.cert_hint = tk.Label(c, text="(직접 로그인 방식에서는 필요 없습니다)",
                                  bg=CARD, fg=MUTED, font=("맑은 고딕", 9))
        self.cert_hint.grid(row=2, column=2, sticky="w", padx=(10, 0), pady=(10, 0))

        # 2. 센터
        c = card(outer, "3. 지역과 센터", self.compact)
        tk.Label(c, text="시/도", bg=CARD, fg=INK, font=("맑은 고딕", 10)).grid(
            row=0, column=0, sticky="w")
        self.cb_sido = ttk.Combobox(c, width=18, state="readonly", font=("맑은 고딕", 10))
        self.cb_sido.grid(row=0, column=1, sticky="w", padx=(10, 16))
        self.cb_sido.bind("<<ComboboxSelected>>", lambda e: self.on_sido())

        tk.Label(c, text="시/군/구", bg=CARD, fg=INK, font=("맑은 고딕", 10)).grid(
            row=0, column=2, sticky="w")
        self.cb_gugun = ttk.Combobox(c, width=16, state="readonly", font=("맑은 고딕", 10))
        self.cb_gugun.grid(row=0, column=3, sticky="w", padx=(10, 16))

        self.btn_load = tk.Button(c, text="센터 불러오기", command=self.on_load_centers,
                                  bg=ACCENT, fg="white", relief="flat", bd=0,
                                  font=("맑은 고딕", 10, "bold"), padx=14, pady=7,
                                  cursor="hand2", activebackground=ACCENT_DK,
                                  activeforeground="white")
        self.btn_load.grid(row=0, column=4, sticky="w")

        tk.Label(c, text="센터", bg=CARD, fg=INK, font=("맑은 고딕", 10)).grid(
            row=1, column=0, sticky="w", pady=(12, 0))
        self.cb_center = ttk.Combobox(c, width=54, state="readonly", font=("맑은 고딕", 10))
        self.cb_center.grid(row=1, column=1, columnspan=4, sticky="w",
                            padx=(10, 0), pady=(12, 0))
        self.lbl_center = tk.Label(c, text="", bg=CARD, fg=MUTED,
                                   font=("맑은 고딕", 9), anchor="w", justify="left")
        self.lbl_center.grid(row=2, column=0, columnspan=5, sticky="w", pady=(8, 0))
        self.cb_center.bind("<<ComboboxSelected>>", lambda e: self._show_center())

        # 3. 예약 조건
        c = card(outer, "4. 예약 조건", self.compact)
        tk.Label(c, text="이용일", bg=CARD, fg=INK, font=("맑은 고딕", 10)).grid(
            row=0, column=0, sticky="w")
        self.date_choice = SegmentedChoice(
            c, [("auto", "2주 뒤 자동"), ("fixed", "날짜 직접 지정")],
            value="auto", command=lambda k: self._on_date_mode(k))
        self.date_choice.grid(row=0, column=1, sticky="w", padx=(10, 0))
        self.ent_date = tk.Entry(c, width=14, font=("맑은 고딕", 11), relief="flat",
                                 bg="#f0f2f6", justify="center")
        self.ent_date.grid(row=0, column=2, sticky="w", padx=(12, 0), ipady=6)
        self.lbl_date = tk.Label(c, text="", bg=CARD, fg=MUTED, font=("맑은 고딕", 9))
        self.lbl_date.grid(row=1, column=1, columnspan=3, sticky="w", pady=(6, 0))

        tk.Label(c, text="아동 이름", bg=CARD, fg=INK, font=("맑은 고딕", 10)).grid(
            row=2, column=0, sticky="w", pady=(14, 0))
        self.ent_child = tk.Entry(c, width=14, font=("맑은 고딕", 11), relief="flat",
                                  bg="#f0f2f6")
        self.ent_child.grid(row=2, column=1, sticky="w", padx=(10, 0), pady=(14, 0),
                            ipady=6, ipadx=6)
        tk.Label(c, text="반명", bg=CARD, fg=INK, font=("맑은 고딕", 10)).grid(
            row=2, column=2, sticky="e", pady=(14, 0))
        self.ent_class = tk.Entry(c, width=14, font=("맑은 고딕", 11), relief="flat",
                                  bg="#f0f2f6")
        self.ent_class.grid(row=2, column=3, sticky="w", padx=(10, 0), pady=(14, 0),
                            ipady=6, ipadx=6)
        tk.Label(c, text="비워두면 화면에 나온 첫 번째 아동/반을 그대로 씁니다.",
                 bg=CARD, fg=MUTED, font=("맑은 고딕", 9)).grid(
            row=3, column=0, columnspan=5, sticky="w", pady=(6, 0))

        tk.Label(c, text="이용시간", bg=CARD, fg=INK, font=("맑은 고딕", 10)).grid(
            row=4, column=0, sticky="w", pady=(14, 0))
        self.cb_hours = ttk.Combobox(c, width=6, state="readonly",
                                     font=("맑은 고딕", 10),
                                     values=[str(h) for h in range(1, 10)])
        self.cb_hours.grid(row=4, column=1, sticky="w", padx=(10, 0), pady=(14, 0))
        tk.Label(c, text="시간 (사이트의 '이용시간' 선택칸과 같은 값입니다. 9 = 09:00~18:00)",
                 bg=CARD, fg=MUTED, font=("맑은 고딕", 9)).grid(
            row=4, column=2, columnspan=3, sticky="w", padx=(10, 0), pady=(14, 0))

        tk.Label(c, text="시작 시간대", bg=CARD, fg=INK,
                 font=("맑은 고딕", 10)).grid(row=5, column=0, sticky="nw", pady=(14, 0))
        self.slots = SlotPicker(c, per_row=9 if self.compact else 5)
        self.slots.grid(row=5, column=1, columnspan=4, sticky="w",
                        padx=(10, 0), pady=(14, 0))
        tk.Label(c, text="고른 순서가 우선순위입니다. 첫 번째가 정원초과면 다음 것으로 한 번 더 갑니다. "
                         "아무것도 고르지 않으면 그 날 열려 있는 첫 칸으로 갑니다.",
                 bg=CARD, fg=MUTED, font=("맑은 고딕", 9), anchor="w",
                 justify="left").grid(row=6, column=0, columnspan=5, sticky="w",
                                      pady=(8, 0))

        tk.Label(c, text="연습 모드", bg=CARD, fg=INK, font=("맑은 고딕", 10)).grid(
            row=7, column=0, sticky="w", pady=(14, 0))
        self.tg_dry = WordToggle(c, on_text="연습 (예약 안 함)", off_text="실제 예약",
                                 value=False, width=16)
        self.tg_dry.grid(row=7, column=1, sticky="w", padx=(10, 0), pady=(14, 0))
        tk.Label(c, text="연습 모드는 예약 확인창까지만 열고 [확인] 을 누르지 않습니다.",
                 bg=CARD, fg=MUTED, font=("맑은 고딕", 9)).grid(
            row=7, column=2, columnspan=3, sticky="w", padx=(10, 0), pady=(14, 0))

        # 4. 타이밍 안내. 이 프로그램이 실제로 무엇을 정각에 하는지.
        c = card(outer, "5. 9시 정각에 하는 일", self.compact)
        tk.Label(c, text="어느 방식이든 정각에 누르는 것은 예약 확인창의 [확인] 하나뿐입니다.\n"
                         "인계 모드에서는 확인창을 만드는 일까지 직접 하시고, 프로그램은\n"
                         "화면을 계속 지켜보다가 그 [확인] 만 정각에 맞춰 누릅니다.\n"
                         "확인창이 없으면 누르지 않습니다 (잘못 누르는 것보다 안전합니다).",
                 bg=CARD, fg=INK, font=("맑은 고딕", 10), anchor="w",
                 justify="left").grid(row=0, column=0, columnspan=4, sticky="w")
        tk.Label(c, text="정각보다 먼저 도착한 요청은 사이트가 그냥 버립니다"
                         " ('아직 예약 가능한 시간이 아닙니다').\n"
                         "그래서 9시 정각을 아주 조금 지나서 도착하도록 맞춥니다. "
                         "그래도 이르면 확인창을 되살려 다시 누릅니다.\n"
                         "'정원초과' 라면 자리가 나간 것이라 두들기지 않고 결과를 알려드립니다.",
                 bg=CARD, fg=MUTED, font=("맑은 고딕", 9), anchor="w",
                 justify="left").grid(row=1, column=0, columnspan=4, sticky="w",
                                      pady=(8, 0))
        tk.Label(c, text=f"기준 시계는 PC 시계가 아니라 아이사랑 서버 시계입니다. 프로그램이 켜져 있는 "
                         f"동안 {config.RESYNC_SECONDS // 60}분마다 다시 맞추고,\n"
                         f"다시 맞출 때마다 아래 기록에 한 줄씩 남습니다. 정각 "
                         f"{config.RESYNC_QUIET_SECONDS}초 전부터는 발사에 방해되지 않도록 멈춥니다.",
                 bg=CARD, fg=MUTED, font=("맑은 고딕", 9), anchor="w",
                 justify="left").grid(row=2, column=0, columnspan=4, sticky="w",
                                      pady=(8, 0))

        # 5. 진단 기록. 사람이 손으로 걸어가는 동안 우리는 받아적기만 한다.
        c = card(outer, "6. 진단 기록 (예약이 잘 안 될 때만)", self.compact)
        self.btn_rec = tk.Button(c, text="진단 기록 시작", command=self.on_record_start,
                                 bg="#1f8a70", fg="white", relief="flat", bd=0,
                                 font=("맑은 고딕", 11, "bold"), padx=20,
                                 pady=6 if self.compact else 9, cursor="hand2",
                                 activebackground="#186a56", activeforeground="white")
        self.btn_rec.grid(row=0, column=0, sticky="w")
        self.btn_rec_stop = tk.Button(c, text="기록 중지", command=self.on_record_stop,
                                      bg="#e8ebf0", fg=MUTED, relief="flat", bd=0,
                                      font=("맑은 고딕", 11), padx=18,
                                      pady=6 if self.compact else 9,
                                      cursor="hand2", state="disabled")
        self.btn_rec_stop.grid(row=0, column=1, sticky="w", padx=(10, 0))
        tk.Label(c, text="크롬을 열어 드립니다. 공동인증서로 로그인하시고, 예약 확인창이 뜨는 곳까지\n"
                         "평소처럼 손으로 진행해 주세요. 프로그램은 아무것도 누르지 않고 화면과 통신만\n"
                         "받아적습니다. 다 되시면 [기록 중지] 를 눌러주세요. 예약은 만들어지지 않습니다.",
                 bg=CARD, fg=MUTED, font=("맑은 고딕", 9), anchor="w",
                 justify="left").grid(row=1, column=0, columnspan=4, sticky="w",
                                      pady=(10, 0))

    def _build_bottom(self, shell):
        """항상 보여야 하는 것들. 바닥부터 역순으로 붙인다."""
        logwrap = tk.Frame(shell, bg=CARD, highlightthickness=1,
                           highlightbackground=LINE)
        logwrap.pack(side="bottom", fill="both", expand=True)
        self.logbox = tk.Text(logwrap, height=4 if self.compact else 9,
                              bg=CARD, fg=INK, relief="flat",
                              font=("맑은 고딕", 9), wrap="word", padx=12, pady=10)
        self.logbox.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(logwrap, command=self.logbox.yview)
        sb.pack(side="right", fill="y")
        self.logbox.config(yscrollcommand=sb.set, state="disabled")

        self.status = tk.Label(shell, text="설정을 확인하고 [예약 시작] 을 눌러주세요.",
                               bg=BG, fg=MUTED, font=("맑은 고딕", 10), anchor="w")
        self.status.pack(side="bottom", fill="x",
                         pady=(4, 5) if self.compact else (6, 8))

        self.result = tk.Label(shell, text="대기 중", bg="#e8ecf4", fg=INK,
                               font=("맑은 고딕", 12, "bold"), anchor="w",
                               padx=16, pady=9 if self.compact else 12)
        self.result.pack(side="bottom", fill="x")

        # 인계 모드 상태판. 고객이 9시 직전에 이 화면을 사진으로 찍어 보낸다.
        # 그래서 모드 / 확인창 감지 여부 / 체크 여부 / 남은 시간이 한눈에
        # 읽혀야 한다. 실행 전에는 접혀 있고, 시작하면 펼쳐진다.
        self.panel = tk.Frame(shell, bg="#101a2b")
        row = tk.Frame(self.panel, bg="#101a2b")
        row.pack(fill="x", padx=16, pady=(10, 2))
        self.pl_mode = tk.Label(row, text="", bg="#2b3a55", fg="white",
                                font=("맑은 고딕", 11, "bold"), padx=12, pady=5)
        self.pl_mode.pack(side="left")
        self.pl_modal = tk.Label(row, text="확인창 확인 중", bg="#3a3f4b",
                                 fg="white", font=("맑은 고딕", 11, "bold"),
                                 padx=12, pady=5)
        self.pl_modal.pack(side="left", padx=(8, 0))
        self.pl_tick = tk.Label(row, text="선택표 확인 중", bg="#3a3f4b",
                                fg="white", font=("맑은 고딕", 11, "bold"),
                                padx=12, pady=5)
        self.pl_tick.pack(side="left", padx=(8, 0))
        self.pl_count = tk.Label(row, text="", bg="#101a2b", fg="#8fb4ff",
                                 font=("맑은 고딕", 15, "bold"))
        self.pl_count.pack(side="right")
        self.pl_line = tk.Label(self.panel, text="", bg="#101a2b", fg="#cfd8e6",
                                font=("맑은 고딕", 10), anchor="w", justify="left")
        self.pl_line.pack(fill="x", padx=16, pady=(0, 10))

        run = tk.Frame(shell, bg=BG)
        run.pack(side="bottom", fill="x", pady=(2, 7 if self.compact else 12))
        self.btn_start = tk.Button(run, text="예약 시작", command=self.on_start,
                                   bg=ACCENT, fg="white", relief="flat", bd=0,
                                   font=("맑은 고딕", 14, "bold"), padx=40, pady=10 if self.compact else 14,
                                   cursor="hand2", activebackground=ACCENT_DK,
                                   activeforeground="white")
        self.btn_start.pack(side="left")
        self.btn_stop = tk.Button(run, text="중지", command=self.on_stop,
                                  bg="#e8ebf0", fg=MUTED, relief="flat", bd=0,
                                  font=("맑은 고딕", 12), padx=26, pady=10 if self.compact else 14,
                                  cursor="hand2", state="disabled")
        self.btn_stop.pack(side="left", padx=(10, 0))
        self.btn_save = tk.Button(run, text="설정 저장", command=self.on_save,
                                  bg="#e8ebf0", fg=INK, relief="flat", bd=0,
                                  font=("맑은 고딕", 12), padx=22, pady=10 if self.compact else 14,
                                  cursor="hand2")
        self.btn_save.pack(side="right")

    # ------------------------------------------------------ 상태 표시
    def log(self, line: str):
        def _do():
            try:
                self.logbox.config(state="normal")
                self.logbox.insert("end", f"{dt.datetime.now():%H:%M:%S}  {line}\n")
                self.logbox.see("end")
                self.logbox.config(state="disabled")
            except Exception:
                pass
        try:
            self.root.after(0, _do)
        except Exception:
            pass

    def set_status(self, line: str):
        try:
            self.root.after(0, lambda: self.status.config(text=line))
        except Exception:
            pass

    # ------------------------------------------------------ 인계 상태판
    def show_panel(self, mode_label: str):
        def _do():
            try:
                self.pl_mode.config(text=mode_label)
                if not self.panel.winfo_ismapped():
                    self.panel.pack(side="bottom", fill="x", pady=(0, 6),
                                    before=self.result)
            except Exception:
                pass
        try:
            self.root.after(0, _do)
        except Exception:
            pass

    def set_state(self, st: dict):
        """runner 가 화면을 다시 읽을 때마다 부른다. 여기가 고객이 보는 곳이다."""
        def _do():
            try:
                self.pl_mode.config(text=st.get("modeLabel") or "")
                if st.get("queue"):
                    self.pl_modal.config(text="가상대기열 대기 중", bg="#8a5a10")
                elif st.get("modal"):
                    self.pl_modal.config(text="확인창 감지됨", bg="#0b6b3a")
                else:
                    self.pl_modal.config(text="확인창 없음", bg="#8c2a22")
                if st.get("ticked"):
                    self.pl_tick.config(text="선택표 체크 켜짐", bg="#0b6b3a")
                else:
                    self.pl_tick.config(text="선택표 체크 꺼짐", bg="#8c2a22")
                secs = float(st.get("secondsToFire") or 0.0)
                m, s = divmod(int(secs), 60)
                h, m = divmod(m, 60)
                clockstr = (f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}")
                self.pl_count.config(
                    text=("[확인] 까지 " + clockstr) if secs > 0 else "지금 누릅니다",
                    fg="#8fb4ff" if st.get("ready") else "#ffb4a8")
                self.pl_line.config(text=st.get("line") or "")
                if not self.panel.winfo_ismapped():
                    self.panel.pack(side="bottom", fill="x", pady=(0, 6),
                                    before=self.result)
            except Exception:
                pass
        try:
            self.root.after(0, _do)
        except Exception:
            pass

    def set_result(self, text: str, kind: str = "info"):
        colors = {"info": ("#e8ecf4", INK), "ok": ("#e3f5eb", OK),
                  "bad": ("#fdeceb", BAD), "busy": ("#fff4e0", "#a8620a")}
        bg, fg = colors.get(kind, colors["info"])
        try:
            self.root.after(0, lambda: self.result.config(text=text, bg=bg, fg=fg))
        except Exception:
            pass

    # ------------------------------------------------------ 설정 반영
    def _apply_settings(self):
        s = self.settings
        mode = config.normalize_run_mode(s.get("run_mode"))
        self.mode_choice.set(mode)
        self._on_run_mode(mode)
        self.login_choice.set(s.get("login_mode", "manual"))
        self._on_login_mode(s.get("login_mode", "manual"))
        self.slots.set(s.get("time_slots") or [])
        self.ent_child.insert(0, s.get("child_name") or "")
        self.ent_class.insert(0, s.get("class_name") or "")
        try:
            self.cb_hours.set(str(int(s.get("use_hours", 9) or 9)))
        except Exception:
            self.cb_hours.set("9")
        self.tg_dry.set(bool(s.get("dry_run")))
        center = s.get("center") or dict(config.DEFAULT_CENTER)
        self.centers = [center]
        self.cb_center["values"] = [self._center_label(center)]
        self.cb_center.current(0)
        self._show_center()
        self.cb_sido["values"] = [center.get("ctprvnName", "서울특별시")]
        self.cb_sido.current(0)
        self.cb_gugun["values"] = [center.get("signguName", "서초구")]
        self.cb_gugun.current(0)
        if s.get("target_date"):
            self.date_choice.set("fixed")
            self.ent_date.insert(0, s["target_date"])
            self._on_date_mode("fixed")
        else:
            self._on_date_mode("auto")
        self.log(f"기본 센터: {center.get('name')} ({center.get('stcode')})")
        threading.Thread(target=self._load_regions, daemon=True).start()

    def _center_label(self, c: dict) -> str:
        kind = "통합반" if c.get("unityYn") == "Y" else "독립반"
        return f"{c.get('name')}  [{kind}]"

    def _show_center(self):
        c = self._current_center()
        if not c:
            return
        bits = [f"기관코드 {c.get('stcode')}"]
        if c.get("address"):
            bits.append(c["address"])
        if c.get("tel"):
            bits.append(f"☎ {c['tel']}")
        if c.get("target"):
            bits.append(f"이용대상 {c['target']}")
        if c.get("status"):
            bits.append(c["status"])
        self.lbl_center.config(text="   ·   ".join(bits))

    def _current_center(self) -> dict | None:
        i = self.cb_center.current()
        if 0 <= i < len(self.centers):
            return self.centers[i]
        return self.centers[0] if self.centers else None

    HANDOVER_HELP = (
        "크롬 창에서 아동 선택 → 반/이용시간 → 날짜 칸 → [추가] → 선택표 체크 →\n"
        "[예약하기] 까지 직접 해서 예약 확인창을 띄워 두세요.\n"
        "프로그램은 그 확인창의 [확인] 만 9시 정각에 맞춰 누릅니다.\n"
        "화면을 옮기거나 다시 진행하는 일은 하지 않습니다.")
    AUTO_HELP = (
        "프로그램이 검색부터 [예약하기] 까지 스스로 진행하고 확인창을 열어 둡니다.\n"
        "9시 직전에는 사이트가 가상대기열을 띄워 확인창이 늦게 열릴 수 있습니다.\n"
        "그때는 기다립니다. 처음부터 다시 하지 않습니다(대기열 맨 뒤로 갑니다).")

    def _on_run_mode(self, key):
        handover = (key == config.MODE_HANDOVER)
        self.lbl_mode.config(
            text=self.HANDOVER_HELP if handover else self.AUTO_HELP,
            fg=INK if handover else MUTED)
        try:
            self.btn_start.config(
                text="[확인] 대기 시작" if handover else "예약 시작")
        except Exception:
            pass

    def _on_login_mode(self, key):
        if key == "cert":
            self.cert_pw.config(state="normal")
            self.cert_hint.config(text="인증서 창이 뜨면 이 비밀번호를 자동으로 넣습니다.")
        else:
            self.cert_pw.config(state="disabled")
            self.cert_hint.config(text="(직접 로그인 방식에서는 필요 없습니다)")

    def _on_date_mode(self, key):
        if key == "fixed":
            self.ent_date.config(state="normal")
            self.lbl_date.config(text="예: 20260908 (YYYYMMDD)")
        else:
            self.ent_date.config(state="disabled")
            nxt = (dt.datetime.now() + dt.timedelta(days=config.OPEN_LEAD_DAYS))
            self.lbl_date.config(
                text=f"오전 9시에 열리는 2주 뒤 날짜를 서버 시각 기준으로 자동 계산합니다 "
                     f"(오늘 기준 {nxt:%Y-%m-%d} 쯤).")

    # ------------------------------------------------------ 지역/센터
    def _load_regions(self):
        try:
            sess = site.make_session()
            self.sido = site.list_sido(sess, self.diag)
            if not self.sido:
                return
            names = [x["name"] for x in self.sido]
            cur = (self.settings.get("center") or {}).get("ctprvnName", "서울특별시")

            def _fill():
                self.cb_sido["values"] = names
                if cur in names:
                    self.cb_sido.current(names.index(cur))
                self.on_sido(select=(self.settings.get("center") or {}).get("signguName"))
            self.root.after(0, _fill)
        except Exception as exc:  # noqa: BLE001
            self.log(f"지역 목록을 불러오지 못했습니다: {exc}")

    @safe_handler
    def on_sido(self, select=None):
        i = self.cb_sido.current()
        if i < 0 or i >= len(self.sido):
            return
        code = self.sido[i]["code"]

        def _work():
            try:
                sess = site.make_session()
                rows = site.list_gugun(sess, code, self.diag)
                self.gugun = rows
                names = [r["name"] for r in rows]

                def _fill():
                    self.cb_gugun["values"] = names
                    if select and select in names:
                        self.cb_gugun.current(names.index(select))
                    elif names:
                        self.cb_gugun.current(0)
                self.root.after(0, _fill)
            except Exception as exc:  # noqa: BLE001
                self.log(f"시군구를 불러오지 못했습니다: {exc}")
        threading.Thread(target=_work, daemon=True).start()

    @safe_handler
    def on_load_centers(self):
        si, gi = self.cb_sido.current(), self.cb_gugun.current()
        if si < 0 or gi < 0 or si >= len(self.sido) or gi >= len(self.gugun):
            messagebox.showinfo("안내", "시/도와 시/군/구를 먼저 골라주세요.")
            return
        sido, gugun = self.sido[si], self.gugun[gi]
        self.btn_load.config(state="disabled", text="불러오는 중...")
        self.set_status(f"{sido['name']} {gugun['name']} 시간제보육 센터를 조회합니다...")

        def _work():
            rows = []
            try:
                sess = site.make_session()
                rows = site.search_centers_both(
                    sess, sido["code"], sido["name"], gugun["code"], gugun["name"],
                    diag=self.diag)
            except Exception as exc:  # noqa: BLE001
                self.log(f"센터 조회 실패: {exc}")

            def _fill():
                self.btn_load.config(state="normal", text="센터 불러오기")
                if not rows:
                    self.set_status("해당 지역에서 시간제보육 센터를 찾지 못했습니다.")
                    return
                self.centers = rows
                self.cb_center["values"] = [self._center_label(r) for r in rows]
                keep = (self.settings.get("center") or {}).get("stcode")
                idx = next((n for n, r in enumerate(rows) if r["stcode"] == keep), 0)
                self.cb_center.current(idx)
                self._show_center()
                self.set_status(f"{len(rows)}개 센터를 불러왔습니다.")
                self.log(f"{sido['name']} {gugun['name']}: {len(rows)}개 센터")
            self.root.after(0, _fill)
        threading.Thread(target=_work, daemon=True).start()

    # ------------------------------------------------------ 실행
    def _collect(self) -> dict:
        s = dict(self.settings)
        c = self._current_center()
        if c:
            s["center"] = {
                "stcode": c["stcode"], "name": c.get("name", ""),
                "unityYn": c.get("unityYn", "N"),
                "ctprvn": c.get("ctprvn", ""), "ctprvnName": c.get("ctprvnName", ""),
                "signgu": c.get("signgu", ""), "signguName": c.get("signguName", ""),
            }
        s["run_mode"] = config.normalize_run_mode(self.mode_choice.get())
        s["login_mode"] = self.login_choice.get()
        s["time_slots"] = self.slots.get()
        s["child_name"] = self.ent_child.get().strip()
        s["class_name"] = self.ent_class.get().strip()
        try:
            s["use_hours"] = int(self.cb_hours.get() or 9)
        except Exception:
            s["use_hours"] = 9
        s["dry_run"] = self.tg_dry.get()
        s["target_date"] = (self.ent_date.get().strip()
                            if self.date_choice.get() == "fixed" else "")
        return s

    @safe_handler
    def on_save(self):
        self.settings = self._collect()
        if config.save_settings(self.settings):
            self.set_status("설정을 저장했습니다. 다음 실행에도 그대로 쓰입니다.")
            self.log("설정 저장 완료")
        else:
            messagebox.showwarning("안내", "설정을 저장하지 못했습니다.")

    @safe_handler
    def on_start(self):
        if self.runner and self.runner.is_running():
            return
        self.settings = self._collect()
        config.save_settings(self.settings)

        if self.settings["login_mode"] == "cert" and not self.cert_pw.get().strip():
            messagebox.showinfo("안내", "공동인증서 자동 로그인을 고르셨습니다.\n"
                                        "인증서 비밀번호를 입력해 주세요.")
            return
        if self.settings["target_date"]:
            d = self.settings["target_date"]
            if not (len(d) == 8 and d.isdigit()):
                messagebox.showinfo("안내", "이용일은 20260908 처럼 8자리 숫자로 넣어주세요.")
                return

        self.btn_start.config(state="disabled", bg="#b9c6de")
        self.btn_stop.config(state="normal", bg="#ffd9d6", fg=BAD)
        mode = config.normalize_run_mode(self.settings.get("run_mode"))
        self.show_panel(config.RUN_MODE_LABELS[mode])
        if mode == config.MODE_HANDOVER:
            self.set_result("인계 모드 · 크롬 창에서 예약 확인창까지 진행해 주세요.",
                            "busy")
        else:
            self.set_result("실행 중입니다. 창을 닫지 말고 두세요.", "busy")

        self.runner = Runner(status_cb=self.set_status, log_cb=self.log,
                             done_cb=self._on_done, diag=self.diag,
                             state_cb=self.set_state)
        self.runner.start(self.settings, self.cert_pw.get())
        self.log(f"실행을 시작했습니다. ({config.RUN_MODE_LABELS[mode]})")

    @safe_handler
    def on_stop(self):
        if self.runner:
            self.runner.stop()
            self.set_status("중지를 요청했습니다...")

    # ------------------------------------------------------ 진단 기록
    @safe_handler
    def on_record_start(self):
        """크롬을 열고 받아적기 시작. 이 모드는 아무것도 누르지 않는다."""
        if self.recorder is not None and self.recorder.is_running():
            return
        if self.runner and self.runner.is_running():
            messagebox.showinfo("안내", "예약이 실행 중입니다. 먼저 [중지] 를 눌러주세요.")
            return
        from .recorder import DiagRecorder
        self.btn_rec.config(state="disabled", bg="#a8c9bf")
        self.btn_rec_stop.config(state="normal", bg="#ffd9d6", fg=BAD)
        self.set_result("진단 기록 중입니다. 크롬 창에서 손으로 진행해 주세요.", "busy")
        if self.recorder is None:
            self.recorder = DiagRecorder(log=self.log, status=self.set_status,
                                         diag=self.diag)

        def _work():
            ok = False
            try:
                ok = self.recorder.start()
            except Exception as exc:  # noqa: BLE001
                self.log(f"진단 기록 시작 실패: {type(exc).__name__}: {exc}")
            if not ok:
                self.root.after(0, self._record_buttons_idle)
                self.set_result("진단 기록을 시작하지 못했습니다.", "bad")

        threading.Thread(target=_work, daemon=True).start()

    @safe_handler
    def on_record_stop(self):
        if self.recorder is None:
            return
        self.btn_rec_stop.config(state="disabled", bg="#e8ebf0", fg=MUTED)
        self.set_status("진단 기록을 마무리하는 중입니다...")

        def _work():
            try:
                s = self.recorder.stop()
                self.set_result(
                    f"진단 기록 완료 · 화면 {s.get('pages')}장, 통신 {s.get('requests')}건, "
                    f"찾던 응답 {len(s.get('wanted') or [])}건을 보냈습니다.", "ok")
            except Exception as exc:  # noqa: BLE001
                self.log(f"진단 기록 마무리 중 오류(무시): {type(exc).__name__}: {exc}")
                self.set_result("진단 기록을 마쳤습니다(일부 항목은 빠졌을 수 있습니다).", "ok")
            self.root.after(0, self._record_buttons_idle)

        threading.Thread(target=_work, daemon=True).start()

    def _record_buttons_idle(self):
        try:
            self.btn_rec.config(state="normal", bg="#1f8a70")
            self.btn_rec_stop.config(state="disabled", bg="#e8ebf0", fg=MUTED)
        except Exception:
            pass

    def _on_done(self, result: dict):
        def _do():
            self.btn_start.config(state="normal", bg=ACCENT)
            self.btn_stop.config(state="disabled", bg="#e8ebf0", fg=MUTED)
            if result.get("ok"):
                self.set_result("성공 · " + result.get("message", ""), "ok")
            else:
                self.set_result("실패 · " + result.get("message", ""), "bad")
        try:
            self.root.after(0, _do)
        except Exception:
            pass

    def _start_updater(self):
        try:
            self._updater = UpdaterThread(status_cb=self.set_status)
            self._updater.start()
        except Exception:
            pass


# ---------------------------------------------------------------- 진입점

def run_gui(diag: Diagnostics | None = None):
    root = tk.Tk()
    app = App(root, diag=diag)
    root.mainloop()
    return app


def run_demo(hold_ms: int = 60000, diag: Diagnostics | None = None,
             show_record: bool = False):
    """CI 스크린샷용. 진짜 조회를 돌려 결과를 화면에 띄운 뒤 그대로 붙잡고 있는다.

    show_record=True 면 설정 영역을 끝까지 내려 '6. 진단 기록' 카드가 화면에
    보이게 한다. 새 버튼이 실제로 창에 있다는 것을 스크린샷으로 증명하기 위한
    것이다(설정 영역은 스크롤되므로 기본 화면에서는 접혀 있다).
    """
    root = tk.Tk()
    app = App(root, diag=diag)
    if show_record:
        def _scroll():
            try:
                app._canvas.update_idletasks()
                app._canvas.yview_moveto(1.0)
            except Exception:
                pass
        root.after(2500, _scroll)
        root.after(9000, _scroll)

    def _work():
        import time as _t
        try:
            app.show_panel(config.RUN_MODE_LABELS[config.MODE_HANDOVER])
            app.set_result("실행 중입니다. 창을 닫지 말고 두세요.", "busy")
            app.set_status("서버 시각을 맞추는 중입니다...")
            r = Runner(status_cb=app.set_status, log_cb=app.log, diag=app.diag)
            out = r.selfcheck()
            app.log(f"시간제보육 센터 조회: {out.get('centers')}개")
            app.log(f"기본 센터 확인: {out.get('default_found')}")
            offset_line = out.get("clock", "")
            app.set_status(offset_line)
            app.root.after(0, lambda: app.slots.set(["09:00", "10:00"]))
            app.root.after(0, lambda: app.date_choice.set("auto"))
            app.root.after(0, lambda: app.cb_hours.set("9"))
            # 4·5단계 판정기도 같이 돌려 화면에 남긴다. 정각에 쓰이는 바로 그 함수다.
            from . import booking
            # 실측 확인창 본문. 여기에 '불가' 와 '초과합니다' 가 같이 들어
            # 있어서, 예전 판정기는 성공한 예약을 '실패' 로 읽을 수 있었다.
            real_modal = ("월 이용 시간이 60시간을 초과할 경우 바우처 지원이 "
                          "불가합니다. 8월 현재 예약 시간 포함하여 60시간을 "
                          "초과합니다. 예약하시겠습니까?")
            checks = {
                # 실물 서버 원문(2026-08-27 09:00:00 캡처). 지어낸 글자가 아니다.
                "예약시간전": booking.classify(booking.TOO_EARLY_REAL),
                "정원초과": booking.classify("정원초과 되었습니다."),
                # 실물 서버 원문(2026-08-28 / 2026-09-01 캡처). 자리를 뺏긴 응답.
                "선예약": booking.classify(booking.TAKEN_REAL),
                "완료": booking.classify("예약이 완료되었습니다."),
                "확인창본문": booking.classify(real_modal),
                "칸거절": booking.classify("예약 가능 시간이 아닙니다."),
            }
            app.log(f"응답 판정기: {checks}")
            grader_ok = (checks["예약시간전"] == booking.R_TOO_EARLY
                         and checks["정원초과"] == booking.R_FULL
                         and checks["선예약"] == booking.R_TAKEN
                         and not booking.result_is_retryable(booking.R_TAKEN)
                         and checks["완료"] == booking.R_OK
                         # 확인창 문구는 결과가 아니다(실패로 읽으면 안 된다)
                         and checks["확인창본문"] != booking.R_FAIL
                         # 사이트가 막는 문구는 재시도 대상이 아니다
                         and checks["칸거절"] == booking.R_NOT_BOOKABLE
                         and not booking.result_is_retryable(booking.R_NOT_BOOKABLE))
            app.log("확인창 흐름: 인계 모드는 사람이 만든 확인창의 [확인] 만 정각 발사")

            # 인계 모드 상태판을 실제 판정기로 채운다. 아래 세 상태는 전부
            # handover.LiveState 를 그대로 통과시킨 것이고, 화면에 그리는
            # 경로도 실행 중과 똑같은 App.set_state 다.
            from . import handover
            queue_state = handover.LiveState(
                on_reserve_page=True, ticked=1,
                row_text="해솔아이 2026-09-09(수) 09 : 00 ~ 18 : 00 (9시간)",
                queue=True, queue_ahead=72, queue_behind=26,
                queue_eta="2분  10초")
            ready_state = handover.LiveState(
                modal=True, modal_text=real_modal, modal_how="layer-confirm-popup2",
                confirm=True, confirm_id="layer-confirm-popup-confirm2",
                armed=True, rows=1, ticked=1, on_reserve_page=True,
                row_text="해솔아이 2026-09-09(수) 09 : 00 ~ 18 : 00 (9시간)")
            blank_state = handover.LiveState(on_reserve_page=True)
            label = config.RUN_MODE_LABELS[config.MODE_HANDOVER]
            handover_ok = (blank_state.ready() is False
                           and queue_state.ready() is False
                           and ready_state.ready() is True)
            app.log(f"인계 모드 판정: 확인창 없음 → 발사 안 함 / "
                    f"대기열 → 발사 안 함 / 확인창+체크 → 발사")
            app.log("대기열 실측(2026-08-26 08:57): " + queue_state.queue_line())
            for st, secs in ((blank_state, 214.0), (queue_state, 126.0),
                             (ready_state, 41.0)):
                app.set_state({
                    "mode": config.MODE_HANDOVER, "modeLabel": label,
                    "line": handover.describe(st), "ready": st.ready(),
                    "modal": st.modal, "ticked": st.ticked > 0,
                    "queue": st.queue, "secondsToFire": secs})
                _t.sleep(2.0)

            resyncs = out.get("clock_resyncs", 0)
            ok = (out.get("default_found") and isinstance(out.get("centers"), int)
                  and grader_ok and handover_ok and resyncs >= 2)
            if ok:
                app.set_result(
                    f"점검 완료 · 서초구 센터 {out['centers']}곳 조회, "
                    f"기본 센터(신반포) 확인, 인계 모드 판정 정상"
                    f"(확인창 없음/대기열이면 누르지 않음), "
                    f"서버 시각 {config.RESYNC_SECONDS // 60}분 주기 재측정 {resyncs}회 확인, "
                    f"{out.get('clock_after_resync', offset_line)}", "ok")
            else:
                app.set_result(f"점검 결과: {out}", "bad")
        except Exception as exc:  # noqa: BLE001
            app.set_result(f"점검 실패: {exc}", "bad")

    root.after(1200, lambda: threading.Thread(target=_work, daemon=True).start())
    root.after(hold_ms, root.destroy)
    root.mainloop()
    return app


def run_construct_selftest() -> int:
    """창을 만들고 바로 닫는다. tkinter 번들 확인용."""
    root = tk.Tk()
    App(root, diag=Diagnostics())
    root.after(1500, root.destroy)
    root.mainloop()
    return 0
