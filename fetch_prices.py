"""한피탈 시세 수집 스크립트.

tickers.json 의 종목(국내)과 시장 지표의 최근 종가를 가져와 prices.json 으로 저장한다.
국내 종목: pykrx(KRX) 우선, 실패하면 yfinance(.KS / .KQ) 로 대체.
시장 지표: yfinance.
"""
import json
import datetime as dt
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")


def pct(close, prev):
    if close is None or prev in (None, 0):
        return None
    return round((close / prev - 1) * 100, 2)


def krx_price(code):
    """pykrx 로 최근 2거래일 종가."""
    from pykrx import stock
    end = dt.datetime.now(KST).date()
    start = end - dt.timedelta(days=45)
    df = stock.get_market_ohlcv(start.strftime("%Y%m%d"), end.strftime("%Y%m%d"), code)
    df = df[df["종가"] > 0]
    if len(df) == 0:
        raise ValueError("no rows")
    close = float(df["종가"].iloc[-1])
    prev = float(df["종가"].iloc[-2]) if len(df) > 1 else None
    date = df.index[-1].strftime("%Y-%m-%d")
    try:
        name = stock.get_market_ticker_name(code)
        if not isinstance(name, str):
            name = stock.get_etf_ticker_name(code)
    except Exception:
        name = None
    ma20 = round(float(df["종가"].iloc[-20:].mean()), 1) if len(df) >= 20 else None
    return {"close": close, "prev_close": prev, "date": date, "krx_name": name, "ma20": ma20, "source": "pykrx (KRX)"}


def _num(v):
    try:
        f = float(v)
        return None if f != f else f  # NaN → None
    except Exception:  # noqa: BLE001
        return None


UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"}


DEBUG_NOTES = []


def _get(url):
    import os
    import re
    import requests
    r = requests.get(url, headers=UA, timeout=20)
    r.raise_for_status()
    r.encoding = r.apparent_encoding or "euc-kr"
    if os.environ.get("HP_DEBUG"):
        t = r.text
        title = re.search(r"<title>(.*?)</title>", t, re.S)
        i = t.find("_per")
        j = t.find("순매매")
        DEBUG_NOTES.append({"url": url, "final": r.url, "status": r.status_code, "len": len(t),
                            "title": title.group(1).strip()[:80] if title else None,
                            "per_ctx": t[max(0, i - 200):i + 200] if i >= 0 else None,
                            "flow_ctx": t[max(0, j - 300):j + 300] if j >= 0 else None,
                            "head": t[:300]})
    return r.text


def _get_json(url):
    import os
    import requests
    r = requests.get(url, headers={**UA, "Referer": "https://m.stock.naver.com/"}, timeout=20)
    r.raise_for_status()
    j = r.json()
    if os.environ.get("HP_DEBUG"):
        DEBUG_NOTES.append({"url": url, "status": r.status_code,
                            "keys": list(j.keys())[:30] if isinstance(j, dict) else type(j).__name__,
                            "sample": str(j)[:1200]})
    return j


def _parse_num(v):
    if v is None:
        return None
    s = str(v).replace(",", "").replace("+", "").replace("배", "").replace("%", "").replace("원", "").strip()
    return _num(s)


_naver_cache = {}


def _naver_integration(code):
    if code not in _naver_cache:
        _naver_cache[code] = _get_json(f"https://m.stock.naver.com/api/stock/{code}/integration")
    return _naver_cache[code]


def naver_fundamental(code):
    """네이버 증권(모바일 API)에서 PER·PBR·EPS·BPS·배당수익률."""
    j = _naver_integration(code)
    infos = j.get("totalInfos") or []
    by = {}
    for it in infos:
        k = (it.get("code") or "").lower()
        by[k] = it.get("value")
        if it.get("key"):
            by[it["key"]] = it.get("value")
    def pick(*names):
        for n in names:
            if n in by and by[n] not in (None, "", "N/A"):
                return _parse_num(by[n])
        return None
    out = {"per": pick("per", "PER"), "pbr": pick("pbr", "PBR"), "eps": pick("eps", "EPS"),
           "bps": pick("bps", "BPS"), "div_yield": pick("dividendyieldratio", "배당수익률"),
           "high_52w": pick("highpriceof52weeks", "52주 최고"), "low_52w": pick("lowpriceof52weeks", "52주 최저"),
           "foreign_rate": pick("foreignrate", "외인소진율"),
           "source": "네이버 증권"}
    c = j.get("consensusInfo")
    if isinstance(c, dict):
        out["consensus"] = {k: c.get(k) for k in list(c.keys())[:8]}
    if all(out[k] is None for k in ("per", "pbr", "eps")):
        raise ValueError("PER/PBR 값을 찾지 못함 (항목: " + ",".join(list(by.keys())[:20]) + ")")
    return out


def naver_flows(code):
    """네이버 증권(모바일 API)에서 외국인·기관·개인 순매수량(주)과 근사 금액(원)."""
    j = _naver_integration(code)
    trend = j.get("dealTrendInfos") or []
    if not trend:
        raise ValueError("수급 데이터 없음 (키: " + ",".join(list(j.keys())[:20]) + ")")
    def f(row, *names):
        for n in names:
            if n in row:
                return _parse_num(row[n])
        return None
    rows = []
    for t in trend:
        rows.append({
            "date": str(t.get("bizdate") or t.get("localTradedAt") or "")[:10],
            "close": f(t, "closePrice"),
            "frgn": f(t, "foreignerPureBuyQuant"),
            "inst": f(t, "organPureBuyQuant"),
            "indiv": f(t, "individualPureBuyQuant"),
        })
    last, last5 = rows[0], rows[:5]
    d = last["date"]
    if len(d) == 8 and d.isdigit():
        d = f"{d[:4]}-{d[4:6]}-{d[6:]}"
    amt = lambda r, k: (r[k] or 0) * (r["close"] or 0)
    return {
        "date": d,
        "외국인_순매수_주": last["frgn"], "기관_순매수_주": last["inst"], "개인_순매수_주": last["indiv"],
        "외국인_5일_주": sum(r["frgn"] or 0 for r in last5), "기관_5일_주": sum(r["inst"] or 0 for r in last5),
        "외국인_순매수_원_근사": amt(last, "frgn"), "기관_순매수_원_근사": amt(last, "inst"),
        "외국인_5일_원_근사": sum(amt(r, "frgn") for r in last5), "기관_5일_원_근사": sum(amt(r, "inst") for r in last5),
        "source": "네이버 증권 (순매수량 × 종가로 금액 근사)",
    }


def naver_market_list(market, size=100):
    """네이버 증권 시가총액 상위 종목 목록 (market: KOSPI | KOSDAQ)."""
    j = _get_json(f"https://m.stock.naver.com/api/stocks/marketValue/{market}?page=1&pageSize={size}")
    items = j.get("stocks") if isinstance(j, dict) else j
    out = []
    for it in items or []:
        if it.get("stockEndType") not in (None, "stock"):
            continue
        out.append({"code": it.get("itemCode"), "name": it.get("stockName"), "market": market,
                    "close": _parse_num(it.get("closePrice")),
                    "change_pct": _parse_num(it.get("fluctuationsRatio")),
                    "market_cap": it.get("marketValueHangeul") or it.get("marketValue")})
    return out


def build_universe(held_codes):
    """시총 상위 종목의 밸류에이션·수급을 모으고 간단한 관찰 후보 스크린을 만든다."""
    import time
    uni, errs = [], []
    for mkt, n in (("KOSPI", 100), ("KOSDAQ", 50)):
        try:
            uni.extend(naver_market_list(mkt, n))
        except Exception as e:  # noqa: BLE001
            errs.append(f"{mkt} 목록 조회 실패 ({e})")
    for row in uni:
        try:
            f = naver_fundamental(row["code"])
            row.update({k: f.get(k) for k in ("per", "pbr", "div_yield", "high_52w", "low_52w", "foreign_rate")})
            cons = (f.get("consensus") or {})
            tgt = _parse_num(cons.get("priceTargetMean"))
            row["target_mean"] = tgt
            row["recomm_mean"] = _parse_num(cons.get("recommMean"))
            c, hi, lo = row.get("close"), row.get("high_52w"), row.get("low_52w")
            row["pos_52w"] = round((c - lo) / (hi - lo), 4) if c and hi and lo and hi > lo else None
            row["target_gap"] = round(tgt / c - 1, 4) if tgt and c else None
        except Exception as e:  # noqa: BLE001
            row["fund_error"] = str(e)[:80]
        try:
            fl = naver_flows(row["code"])
            row["foreign_5d_won"] = fl.get("외국인_5일_원_근사")
            row["inst_5d_won"] = fl.get("기관_5일_원_근사")
        except Exception:  # noqa: BLE001
            pass
        time.sleep(0.15)
    cand = [r for r in uni if r["code"] not in held_codes and r.get("per") and r["per"] > 0
            and r.get("target_gap") is not None
            # 우선주는 보통주 목표주가가 그대로 붙어 괴리율이 부풀려지므로 제외
            and r["code"].endswith("0") and not r["name"].rstrip("B").endswith("우")]
    cand.sort(key=lambda r: r["target_gap"], reverse=True)
    screen = cand[:20]
    return uni, screen, errs


def krx_index(ticker):
    """국내 지수(예: KS11 코스피) 최근 2거래일 종가. FinanceDataReader 사용."""
    import FinanceDataReader as fdr
    start = (dt.datetime.now(KST).date() - dt.timedelta(days=14)).strftime("%Y-%m-%d")
    df = fdr.DataReader(ticker, start)
    df = df.dropna(subset=["Close"])
    df = df[df["Close"] > 0]
    if len(df) == 0:
        raise ValueError("no rows")
    close = float(df["Close"].iloc[-1])
    prev = float(df["Close"].iloc[-2]) if len(df) > 1 else None
    return {"close": close, "prev_close": prev, "date": df.index[-1].strftime("%Y-%m-%d"), "source": f"FinanceDataReader ({ticker})"}


def yf_history(symbol):
    import yfinance as yf
    h = yf.Ticker(symbol).history(period="45d", auto_adjust=False)
    h = h.dropna(subset=["Close"])
    if len(h) == 0:
        raise ValueError("no rows")
    close = float(h["Close"].iloc[-1])
    prev = float(h["Close"].iloc[-2]) if len(h) > 1 else None
    date = h.index[-1].strftime("%Y-%m-%d")
    ma20 = round(float(h["Close"].iloc[-20:].mean()), 2) if len(h) >= 20 else None
    return {"close": close, "prev_close": prev, "date": date, "ma20": ma20}


def yf_kr_price(code):
    last_err = None
    for suffix in (".KS", ".KQ"):
        try:
            r = yf_history(code + suffix)
            r["source"] = f"yfinance ({code}{suffix})"
            return r
        except Exception as e:  # noqa: BLE001
            last_err = e
    raise last_err


def main():
    cfg = json.load(open("tickers.json", encoding="utf-8"))
    out = {
        "updated_at": dt.datetime.now(KST).isoformat(timespec="minutes"),
        "stocks": [],
        "markets": [],
        "fallbacks": [],  # 자동 대체가 일어난 항목 (사람이 읽는 문장)
        "errors": [],     # 끝내 조회 못 한 항목
    }

    for s in cfg["stocks"]:
        row = {"code": s["code"], "name": s["name"]}
        try:
            r = krx_price(s["code"])
            row["fallback"] = None
        except Exception as e1:  # noqa: BLE001
            try:
                r = yf_kr_price(s["code"])
                row["fallback"] = "KRX 조회 실패 → 야후로 대체"
                out["fallbacks"].append(f"{s['name']}({s['code']}): KRX 조회 실패 → 야후로 대체 ({e1})")
            except Exception as e2:  # noqa: BLE001
                out["errors"].append(f"{s['name']}({s['code']}): 조회 실패 (KRX {e1} / 야후 {e2})")
                out["stocks"].append({**row, "close": None, "fallback": None})
                continue
        row.update(r)
        row["change_pct"] = pct(r["close"], r.get("prev_close"))
        if not s.get("etf"):
            try:
                row["fundamental"] = naver_fundamental(s["code"])
            except Exception as e:  # noqa: BLE001
                row["fundamental"] = None
                out["errors"].append(f"{s['name']}({s['code']}): PER·PBR 조회 실패 ({e})")
            try:
                row["flows"] = naver_flows(s["code"])
            except Exception as e:  # noqa: BLE001
                row["flows"] = None
                out["errors"].append(f"{s['name']}({s['code']}): 수급 조회 실패 ({e})")
        out["stocks"].append(row)

    for m in cfg["markets"]:
        row = {"name": m["name"], "symbol": m["symbol"], "fallback": None}
        r = None
        if m.get("krx_index"):
            try:
                r = krx_index(m["krx_index"])
            except Exception as e0:  # noqa: BLE001
                row["fallback"] = "KRX 조회 실패 → 야후로 대체"
                out["fallbacks"].append(f"{m['name']}: KRX 조회 실패 → 야후로 대체 ({e0})")
        if r is None:
            try:
                r = yf_history(m["symbol"])
                r["source"] = f"yfinance ({m['symbol']})"
            except Exception as e:  # noqa: BLE001
                out["errors"].append(f"{m['name']}({m['symbol']}): 조회 실패 ({e})")
                row["close"] = None
                out["markets"].append(row)
                continue
        row.update(r)
        row["change_pct"] = pct(r["close"], r.get("prev_close"))
        out["markets"].append(row)

    held = {s["code"] for s in cfg["stocks"]}
    try:
        uni, screen, uerrs = build_universe(held)
        out["universe_screen"] = screen
        out["errors"].extend(uerrs)
        json.dump({"updated_at": out["updated_at"], "count": len(uni), "stocks": uni},
                  open("universe.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    except Exception as e:  # noqa: BLE001
        out["errors"].append(f"관찰 후보 수집 실패 ({e})")

    if DEBUG_NOTES:
        out["debug"] = DEBUG_NOTES[:4]
    if out["fallbacks"] or out["errors"]:
        print("⚠️ 자동 대체/실패 항목:")
        for line in out["fallbacks"] + out["errors"]:
            print(" -", line)
            print(f"::warning::{line}")  # 깃허브 Actions 실행 화면에 노란 경고로 표시

    json.dump(out, open("prices.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
