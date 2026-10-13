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
    start = end - dt.timedelta(days=14)
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
    return {"close": close, "prev_close": prev, "date": date, "krx_name": name, "source": "pykrx (KRX)"}


def _num(v):
    try:
        f = float(v)
        return None if f != f else f  # NaN → None
    except Exception:  # noqa: BLE001
        return None


def krx_fundamental(code):
    """pykrx 로 최근 거래일 PER·PBR·EPS·BPS·배당수익률."""
    from pykrx import stock
    end = dt.datetime.now(KST).date()
    start = end - dt.timedelta(days=14)
    df = stock.get_market_fundamental(start.strftime("%Y%m%d"), end.strftime("%Y%m%d"), code)
    if df is None or len(df) == 0:
        raise ValueError("no rows")
    r = df.iloc[-1]
    return {
        "date": df.index[-1].strftime("%Y-%m-%d"),
        "per": _num(r.get("PER")), "pbr": _num(r.get("PBR")),
        "eps": _num(r.get("EPS")), "bps": _num(r.get("BPS")),
        "div_yield": _num(r.get("DIV")),
        "source": "pykrx (KRX)",
    }


def krx_flows(code):
    """pykrx 로 투자자별 순매수 금액(원): 최근 거래일과 최근 5거래일 합."""
    from pykrx import stock
    end = dt.datetime.now(KST).date()
    start = end - dt.timedelta(days=20)
    df = stock.get_market_trading_value_by_date(start.strftime("%Y%m%d"), end.strftime("%Y%m%d"), code)
    if df is None or len(df) == 0:
        raise ValueError("no rows")
    cols = {"외국인": "외국인합계", "기관": "기관합계", "개인": "개인"}
    last, last5 = df.iloc[-1], df.tail(5)
    out = {"date": df.index[-1].strftime("%Y-%m-%d"), "source": "pykrx (KRX)"}
    for k, c in cols.items():
        if c in df.columns:
            out[f"{k}_순매수"] = _num(last[c])
            out[f"{k}_5일"] = _num(last5[c].sum())
    return out


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
    h = yf.Ticker(symbol).history(period="10d", auto_adjust=False)
    h = h.dropna(subset=["Close"])
    if len(h) == 0:
        raise ValueError("no rows")
    close = float(h["Close"].iloc[-1])
    prev = float(h["Close"].iloc[-2]) if len(h) > 1 else None
    date = h.index[-1].strftime("%Y-%m-%d")
    return {"close": close, "prev_close": prev, "date": date}


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
                row["fundamental"] = krx_fundamental(s["code"])
            except Exception as e:  # noqa: BLE001
                row["fundamental"] = None
                out["errors"].append(f"{s['name']}({s['code']}): PER·PBR 조회 실패 ({e})")
            try:
                row["flows"] = krx_flows(s["code"])
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

    if out["fallbacks"] or out["errors"]:
        print("⚠️ 자동 대체/실패 항목:")
        for line in out["fallbacks"] + out["errors"]:
            print(" -", line)
            print(f"::warning::{line}")  # 깃허브 Actions 실행 화면에 노란 경고로 표시

    json.dump(out, open("prices.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
