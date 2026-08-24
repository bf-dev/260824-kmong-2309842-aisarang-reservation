# -*- coding: utf-8 -*-
"""러너에서 childcare.go.kr 에 닿는지 확인 (우리 CI 전용).

0 = 닿는다 (아래 단계에서 라이브로 검증)
1 = 못 닿는다 (러너 IP 대역 문제. 고객 PC 와는 무관하므로 빌드를 실패시키지
    않고 녹화된 응답으로 검증한다)
"""
import sys

import requests

URL = "https://www.childcare.go.kr/?menuno=1"

try:
    r = requests.head(URL, timeout=15)
    print(f"reachable: status={r.status_code} date={r.headers.get('Date')}")
    sys.exit(0)
except Exception as exc:  # noqa: BLE001
    print(f"UNREACHABLE from this runner: {type(exc).__name__}: {exc}")
    sys.exit(1)
