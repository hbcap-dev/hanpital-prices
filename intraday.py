"""한피탈 장중 시세 수집.

평일 장중 1시간마다 GitHub Actions가 돌려 intraday.json 을 만든다.
- 국내 종목(tickers.json stocks): 네이버 증권 모바일 API basic (실패 시 yfinance 1분봉, 약 15~20분 지연)
- 코스피: 네이버 index basic (실패 시 yfinance ^KS11)
- 원/달러: yfinance KRW=X
- 금현물(KRX): 네이버 시장지표 (실패하면 비움)
알림 판단은 하지 않는다. 기준 비교와 카톡은 한피탈 장중 알림 예약 작업이 한다.
"""
import json
import os
import datetime as dt
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
      "Referer": "https://m.stock.naver.com/"}
DEBUG = []


def _get_json(url):
    import requests
    r = requests.get(url, headers=UA, timeout=15)
    r.raise_for_status()
    j = r.json()
    if os.environ.get("HP_DEBUG") and len(DEBUG) < 6:
        DEBUG.append({"url": url, "sample": str(j)[:800]})
    return j


def _num(v):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).replace(",", "").replace("%", "").replace("+", "").strip()
    try:
        return float(s)
    except ValueError:
        return None


def naver_basic(path):
    """path 예: 'stock/005930' 또는 'index/KOSPI'"""
    j = _get_json(f"https://m.stock.naver.com/api/{path}/basic")
    close = _num(j.get("closePrice"))
    diff = _num(j.get("compareToPreviousClosePrice"))
    ratio = _num(j.get("fluctuationsRatio"))
    code = (j.get("compareToPreviousPrice") or {}).get("code")
    # 하락(5)·하한(4)이면 부호를 음수로 맞춘다 (API가 절대값을 줄 때 대비)
    if code in ("4", "5"):
        if diff is not None and diff > 0:
            diff = -diff
        if ratio is not None and ratio > 0:
            ratio = -ratio
    if close is None:
        raise ValueError("closePrice 없음")
    prev = round(close - diff, 2) if diff is not None else None
    return {
        "price": close,
        "prev_close": prev,
        "change_pct": ratio,
        "market_status": j.get("marketStatus"),
        "traded_at": j.get("localTradedAt"),
        "source": "네이버",
    }


def yf_intraday(symbol):
    import yfinance as yf
    t = yf.Ticker(symbol)
    d = t.history(period="5d", interval="1d", auto_adjust=False).dropna(subset=["Close"])
    m = t.history(period="1d", interval="1m", auto_adjust=False).dropna(subset=["Close"])
    price = float(m["Close"].iloc[-1]) if len(m) else float(d["Close"].iloc[-1])
    today = dt.datetime.now(KST).date()
    prev_rows = d[[i.date() < today for i in d.index]] if len(d) else d
    prev = float(prev_rows["Close"].iloc[-1]) if len(prev_rows) else None
    at = m.index[-1].astimezone(KST).isoformat(timespec="minutes") if len(m) else None
    return {
        "price": price,
        "prev_close": prev,
        "change_pct": round((price / prev - 1) * 100, 2) if prev else None,
        "traded_at": at,
        "source": f"야후 ({symbol}, 지연)",
    }


def naver_gold():
    j = _get_json("https://m.stock.naver.com/front-api/marketIndex/prices?category=metals&reutersCode=M04020000&page=1&pageSize=2")
    rows = j.get("result") if isinstance(j, dict) else None
    if not rows:
        raise ValueError("금현물 응답 없음")
    r0 = rows[0]
    price = _num(r0.get("closePrice"))
    ratio = _num(r0.get("fluctuationsRatio"))
    diff = _num(r0.get("fluctuations"))
    return {
        "price": price,
        "prev_close": price - diff if (price is not None and diff is not None) else None,
        "change_pct": ratio,
        "traded_at": r0.get("localTradedAt"),
        "source": "네이버 (KRX 금현물 1g)",
    }


def main():
    cfg = json.load(open("tickers.json", encoding="utf-8"))
    now = dt.datetime.now(KST)
    out = {"updated_at": now.isoformat(timespec="minutes"), "stocks": [], "markets": [], "errors": []}

    for s in cfg["stocks"]:
        row = {"code": s["code"], "name": s["name"]}
        try:
            row.update(naver_basic(f"stock/{s['code']}"))
        except Exception as e1:  # noqa: BLE001
            try:
                row.update(yf_intraday(s["code"] + ".KS"))
                row["fallback"] = f"네이버 실패 → 야후 ({e1})"
            except Exception as e2:  # noqa: BLE001
                out["errors"].append(f"{s['name']}({s['code']}): {e1} / {e2}")
                row["price"] = None
        out["stocks"].append(row)

    # 코스피
    row = {"name": "코스피"}
    try:
        row.update(naver_basic("index/KOSPI"))
    except Exception as e1:  # noqa: BLE001
        try:
            row.update(yf_intraday("^KS11"))
            row["fallback"] = f"네이버 실패 → 야후 ({e1})"
        except Exception as e2:  # noqa: BLE001
            out["errors"].append(f"코스피: {e1} / {e2}")
            row["price"] = None
    out["markets"].append(row)

    # 원/달러
    row = {"name": "원/달러"}
    try:
        row.update(yf_intraday("KRW=X"))
    except Exception as e:  # noqa: BLE001
        out["errors"].append(f"원/달러: {e}")
        row["price"] = None
    out["markets"].append(row)

    # 금현물 (주문표 참고용, 실패해도 무시)
    row = {"name": "KRX 금현물"}
    try:
        row.update(naver_gold())
    except Exception as e:  # noqa: BLE001
        row["price"] = None
        row["note"] = f"조회 실패: {e}"
    out["markets"].append(row)

    if DEBUG:
        out["debug"] = DEBUG
    for line in out["errors"]:
        print(f"::warning::{line}")
    json.dump(out, open("intraday.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
