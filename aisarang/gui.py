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

        # 1. 로그인
        c = card(outer, "1. 로그인 방식", self.compact)
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
        c = card(outer, "2. 지역과 센터", self.compact)
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
        c = card(outer, "3. 예약 조건", self.compact)
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

        # 4. 타이밍 안내 — 이 프로그램이 실제로 무엇을 정각에 하는지.
        c = card(outer, "4. 9시 정각에 하는 일", self.compact)
        tk.Label(c, text="검색 → 센터 → 아동 → 반/이용시간 → 날짜 칸 → 추가 → 체크 → [예약하기] 까지는\n"
                         "9시가 되기 전에 미리 끝내고, 예약 확인창을 열어둔 채 기다립니다.\n"
                         "정각에 누르는 것은 확인창의 [확인] 하나뿐입니다.",
                 bg=CARD, fg=INK, font=("맑은 고딕", 10), anchor="w",
                 justify="left").grid(row=0, column=0, columnspan=4, sticky="w")
        tk.Label(c, text="너무 이르면 사이트가 '예약시간전' 이라고 답합니다. 자리는 남아 있으므로 "
                         "곧바로 다시 누릅니다.\n"
                         "너무 늦으면 '정원초과' 입니다. 그때는 두들기지 않고 결과를 알려드립니다.",
                 bg=CARD, fg=MUTED, font=("맑은 고딕", 9), anchor="w",
                 justify="left").grid(row=1, column=0, columnspan=4, sticky="w",
                                      pady=(8, 0))

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
        self.set_result("실행 중입니다. 창을 닫지 말고 두세요.", "busy")

        self.runner = Runner(status_cb=self.set_status, log_cb=self.log,
                             done_cb=self._on_done, diag=self.diag)
        self.runner.start(self.settings, self.cert_pw.get())
        self.log("실행을 시작했습니다.")

    @safe_handler
    def on_stop(self):
        if self.runner:
            self.runner.stop()
            self.set_status("중지를 요청했습니다...")

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


def run_demo(hold_ms: int = 60000, diag: Diagnostics | None = None):
    """CI 스크린샷용. 진짜 조회를 돌려 결과를 화면에 띄운 뒤 그대로 붙잡고 있는다."""
    root = tk.Tk()
    app = App(root, diag=diag)

    def _work():
        try:
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
            checks = {
                "예약시간전": booking.classify("예약시간전입니다."),
                "정원초과": booking.classify("정원초과 되었습니다."),
                "완료": booking.classify("예약이 완료되었습니다."),
            }
            app.log(f"응답 판정기: {checks}")
            grader_ok = (checks["예약시간전"] == booking.R_TOO_EARLY
                         and checks["정원초과"] == booking.R_FULL
                         and checks["완료"] == booking.R_OK)
            app.log("확인창 흐름: 준비(검색→센터→아동→반/이용시간→칸→추가→체크→예약하기) "
                    "후 [확인] 만 정각 발사")
            ok = (out.get("default_found") and isinstance(out.get("centers"), int)
                  and grader_ok)
            if ok:
                app.set_result(
                    f"점검 완료 · 서초구 센터 {out['centers']}곳 조회, "
                    f"기본 센터(신반포) 확인, 예약시간전/정원초과 판정 정상, "
                    f"{offset_line}", "ok")
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
