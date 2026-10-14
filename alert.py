"""한피탈 텔레그램 급변 알림.

장중 시세(intraday.json)를 만든 직후 같은 워크플로에서 돈다.
기준을 '처음' 넘었을 때만 텔레그램으로 보낸다. 같은 날 같은 단계는 다시 보내지 않는다.
판단·매매 권유는 하지 않는다(팀 결론은 매시 22분 장중 감시가 대시보드에 남김).

필요한 깃허브 Secrets: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
기준은 alert_rules.json, 오늘 보낸 기록은 alert_state.json (둘 다 공개 저장소이므로 수량·금액은 넣지 않는다).
"""
import json
import math
import os
import datetime as dt
from zoneinfo import ZoneInfo

import requests

KST = ZoneInfo("Asia/Seoul")


def load(path, default):
    try:
        return json.load(open(path, encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return default


def steps(pct, unit):
    """등락률이 넘은 단계(부호 포함). 예: -6.2%, 단위 5 → -5"""
    if pct is None or unit <= 0:
        return 0
    n = math.floor(abs(pct) / unit)
    return int(math.copysign(n, pct)) if n else 0


def fmt_num(v):
    if v is None:
        return "—"
    return f"{v:,.2f}" if abs(v) < 10000 and v != int(v) else f"{v:,.0f}"


def send(text):
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat:
        print("::warning::TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID 없음 → 보내지 않음")
        return False
    r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                      json={"chat_id": chat, "text": text, "disable_web_page_preview": True}, timeout=15)
    if not r.ok:
        print(f"::warning::텔레그램 전송 실패 {r.status_code}: {r.text[:200]}")
    return r.ok


def main():
    now = dt.datetime.now(KST)
    today = now.date().isoformat()
    rules = load("alert_rules.json", {})
    data = load("intraday.json", {})
    state = load("alert_state.json", {})
    if state.get("date") != today:
        state = {"date": today, "sent": []}
    sent = set(state["sent"])
    already = set(sent)

    upd = data.get("updated_at", "")
    if not upd.startswith(today):
        if os.environ.get("ALERT_TEST"):
            send("🚨 한피탈 급변 · 테스트\n✅ 연결 테스트예요. 장중에 기준을 넘을 때만 이렇게 알려드릴게요.")
        print("intraday.json 이 오늘 것이 아님 → 종료")
        return

    msgs = []
    stock_unit = rules.get("stock_step_pct", 5)
    for s in data.get("stocks", []):
        if s.get("price") is None or not str(s.get("traded_at") or "").startswith(today):
            continue
        k = steps(s.get("change_pct"), stock_unit)
        key = f"{s['code']}:{k}"
        if k and key not in sent:
            sent.add(key)
            msgs.append(f"{'📉' if k < 0 else '📈'} {s['name']} {s['change_pct']:+.2f}% ({fmt_num(s['price'])}원)")
        for lv in rules.get("levels", []):
            if lv.get("code") != s["code"]:
                continue
            p = s["price"]
            hit = (lv["op"] == ">=" and p >= lv["price"]) or (lv["op"] == "<=" and p <= lv["price"])
            key = f"{s['code']}:lv:{lv['op']}{lv['price']}"
            if hit and key not in sent:
                sent.add(key)
                msgs.append(f"🔔 {s['name']} {fmt_num(p)}원 · {lv['label']}")

    market_units = rules.get("market_step_pct", {"코스피": 3, "원/달러": 1.5})
    for m in data.get("markets", []):
        unit = market_units.get(m.get("name"))
        if not unit or m.get("price") is None:
            continue
        k = steps(m.get("change_pct"), unit)
        key = f"{m['name']}:{k}"
        if k and key not in sent:
            sent.add(key)
            msgs.append(f"{'📉' if k < 0 else '📈'} {m['name']} {m['change_pct']:+.2f}% ({fmt_num(m['price'])})")

    def save(keys):
        state["sent"] = sorted(keys)
        json.dump(state, open("alert_state.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    if not msgs and os.environ.get("ALERT_TEST"):
        msgs = ["✅ 연결 테스트예요. 기준을 넘을 때만 이렇게 알려드릴게요."]
    if not msgs:
        save(already)
        print("새 알림 없음")
        return

    t = upd[11:16] if len(upd) >= 16 else now.strftime("%H:%M")
    text = "🚨 한피탈 급변 · " + t + "\n" + "\n".join(msgs) + \
        "\n\n팀 결론은 매시 22분 장중 감시가 대시보드에 남겨요. 급락일 즉흥 매도 금지(원칙 5)."
    print(text)
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat:
        print("::warning::TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID 없음 → 보내지 않음")
        save(already)
        return
    r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                      json={"chat_id": chat, "text": text, "disable_web_page_preview": True}, timeout=15)
    if not r.ok:
        # 토큰이 로그에 남지 않도록 응답 본문만 출력
        print(f"::warning::텔레그램 전송 실패 {r.status_code}: {r.text[:200]}")
        save(already)
    else:
        save(sent)
        print(f"보냄: {len(msgs)}건")


if __name__ == "__main__":
    main()
