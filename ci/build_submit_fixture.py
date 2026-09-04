# -*- coding: utf-8 -*-
"""2026-09-04 09:00:00 캡처에서 **예약 제출의 서버 응답 본문** 픽스처를 만든다.

이것이 이 저장소가 처음 손에 넣은 InsertOcreqst.html 의 응답 본문이다.
(v1.0.9 까지는 훅이 없었고, v1.0.10 에서 훅이 붙었지만 그 뒤 첫 실패가 09-04 다.)

무슨 일이 있었나 (고객 진단 ZIP `…-20260904-090037.zip`, v1.0.11, 인계 모드):

  09:00:00  조준 확정: 도착 목표 정각 +350ms (시각 오차 ±24ms + 여유 250ms)
  09:00:01  지금 [확인] 을 누릅니다!
  09:00:02  [확인] 1발째 · 도착 추정 정각 +352ms · 서버: (문구 없음) [unknown]

고객은 자기 화면에서 '선예약' 을 읽었는데 우리 로그는 아무것도 못 적었다.
그런데 같은 실행의 `xhr_bodies_handover_after.json` 안에 답이 그대로 있었다:

    {"returnmsg":"1건 예약 중 1건 예약이 선예약으로 인해 예약되지 않았습니다.",
     "returnval":""}

    date: Fri, 04 Sep 2026 00:00:00 GMT      (= 09:00:00 KST, 서버가 받은 초)
    t0 = 1788480001289 → t1 = 1788480004707  (왕복 3,418ms)

왕복이 3.4초인데 화면 판정 창은 1.6초였다. 즉 우리는 서버 답이 오는 도중에
포기하고 [unknown] 을 적었다. v1.0.12 는 이 본문을 1순위 근거로 삼는다.

이 스크립트는 그 본문을 **바이트 그대로** 픽스처로 떨어뜨린다. 우리가 지어낸
글자가 한 자도 섞이지 않도록, 분류기 테스트는 이 파일에서 문구를 읽어
booking.TAKEN_REAL 과 대조한다.

응답 본문에는 개인정보가 없다(returnmsg / returnval 두 칸뿐이다). 그래도
떨어뜨리기 전에 모양 검사를 한 번 더 통과시키고, 실패하면 0 이 아닌 코드로 끝난다.
"""
from __future__ import annotations

import json
import re
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "fixtures" / "real"
TARGET = OUT / "insert_ocreqst_taken.json"

MEMBER = "xhr_bodies_handover_after.json"
URL_MARK = "InsertOcreqst"
REAL_MARK = "선예약으로 인해 예약되지 않았습니다."

PII_SHAPES = (
    r"(?<!\d)\d{18}(?!\d)",
    r"\d{6}\s*-\s*[1-4]\d{6}",
    r"[\w.+-]+@[\w-]+\.[\w.]+",
    r"01[016789][-\s.]?\d{3,4}[-\s.]?\d{4}",
)


def main(zip_path: str) -> int:
    src = Path(zip_path)
    if not src.exists():
        print(f"ZIP 이 없습니다: {src}", file=sys.stderr)
        return 2

    zf = zipfile.ZipFile(src)
    member = next((n for n in zf.namelist() if n.endswith(MEMBER)), "")
    if not member:
        print(f"ZIP 안에 {MEMBER} 가 없습니다.", file=sys.stderr)
        return 2

    try:
        blob = json.loads(zf.read(member).decode("utf-8", "replace"))
    except Exception as exc:  # noqa: BLE001
        # 2026-09-03 ZIP 이 이렇게 깨져 있었다(마스킹이 13자리 epoch 을
        # 주민번호로 보고 "178839-3******" 로 바꿨다). v1.0.12 에서 고쳤다.
        print(f"{MEMBER} 를 읽을 수 없습니다: {exc}", file=sys.stderr)
        return 1

    rows = [r for r in (blob.get("rows") or [])
            if URL_MARK in str(r.get("url", ""))]
    if not rows:
        print(f"{MEMBER} 안에 {URL_MARK} 행이 없습니다.", file=sys.stderr)
        return 1
    row = rows[-1]

    body = str(row.get("responseBody") or "")
    if REAL_MARK not in body:
        print(f"응답 본문에 '{REAL_MARK}' 가 없습니다.", file=sys.stderr)
        return 1

    leaks = []
    for pat in PII_SHAPES:
        for hit in re.findall(pat, body):
            leaks.append((pat, str(hit)[:24]))
    if leaks:
        print("응답 본문에 개인정보 모양이 남아 있습니다:", leaks[:5], file=sys.stderr)
        return 1

    def header(name: str) -> str:
        for line in str(row.get("responseHeaders") or "").replace("\r\n", "\n").split("\n"):
            if line.lower().startswith(name + ":"):
                return line.split(":", 1)[1].strip()
        return ""

    t0, t1 = int(row.get("t0") or 0), int(row.get("t1") or 0)
    out = {
        "_source": ("2026-09-04 09:00:00 KST, 고객 2309842 PC, v1.0.11 인계 모드, "
                    f"{MEMBER} 의 {URL_MARK} 행. 요청 본문은 아동 주민번호가 "
                    "들어 있어 일부러 담지 않는다."),
        "_note": ("그날 로그는 '서버: (문구 없음) [unknown]' 이었다. 답은 여기 "
                  "있었고 우리가 3.4초를 못 기다린 것뿐이다."),
        "url": str(row.get("url") or ""),
        "status": int(row.get("status") or 0),
        "date": header("date"),
        "contentType": header("content-type"),
        "elapsedMs": (t1 - t0) if (t0 and t1) else 0,
        # 서버가 돌려준 바이트 그대로. 여기에 우리가 지어낸 글자는 없다.
        "responseBody": body,
    }
    TARGET.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8")
    print(f"{TARGET.name:32s} <- {MEMBER} 의 {URL_MARK} "
          f"(HTTP {out['status']}, 왕복 {out['elapsedMs']}ms, "
          f"본문 {len(body)}바이트)")
    return 0


if __name__ == "__main__":
    default = ("/home/bfdev/neoworks/apps/gateway/artifacts/private/"
               "05788f12-b025-48ba-bb01-7c45121013d8/"
               "1788480037493-aisarang-reservation-2309842-20260904-090037.zip")
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else default))
