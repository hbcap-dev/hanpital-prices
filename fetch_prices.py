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


UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"}


def _get(url):
    import requests
    r = requests.get(url, headers=UA, timeout=20)
    r.raise_for_status()
    r.encoding = r.apparent_encoding or "euc-kr"
    return r.text


def naver_fundamental(code):
    """네이버 금융 종목 메인에서 PER·PBR·EPS·배당수익률 (최근 실적 기준)."""
    import re
    html = _get(f"https://finance.naver.com/item/main.naver?code={code}")
    import os
    if os.environ.get("HP_DEBUG"):
        i = html.find("_per")
        print("DEBUG main len", len(html), "idx", i, repr(html[max(0, i - 300):i + 300]) if i >= 0 else repr(html[:600]))
    def em(i):
        m = re.search(r'<em id="' + i + r'"[^>]*>\s*([-0-9.,]+)\s*</em>', html)
        return _num(m.group(1).replace(",", "")) if m else None
    out = {"per": em("_per"), "pbr": em("_pbr"), "eps": em("_eps"), "div_yield": em("_dvr"),
           "source": "네이버 금융"}
    if all(out[k] is None for k in ("per", "pbr", "eps")):
        raise ValueError("PER/PBR 값을 찾지 못함")
    return out


def naver_flows(code):
    """네이버 금융 외국인·기관 매매 페이지에서 순매매량(주)과 근사 금액(원)."""
    import io
    import pandas as pd
    html = _get(f"https://finance.naver.com/item/frgn.naver?code={code}")
    tables = pd.read_html(io.StringIO(html))
    tbl = None
    for t in tables:
        flat = [" ".join(map(str, c)) if isinstance(c, tuple) else str(c) for c in t.columns]
        if any("기관" in c for c in flat) and any("외국인" in c for c in flat):
            t.columns = flat
            tbl = t
            break
    if tbl is None:
        raise ValueError("매매 표를 찾지 못함")
    date_col = [c for c in tbl.columns if "날짜" in c][0]
    close_col = [c for c in tbl.columns if "종가" in c][0]
    inst_col = [c for c in tbl.columns if "기관" in c and "순매매" in c][0]
    frgn_col = [c for c in tbl.columns if "외국인" in c and "순매매" in c][0]
    tbl = tbl.dropna(subset=[date_col])
    tbl = tbl[tbl[date_col].astype(str).str.match(r"\d{4}\.\d{2}\.\d{2}")]
    def n(v):
        return _num(str(v).replace(",", "").replace("+", ""))
    rows = [(str(r[date_col]), n(r[close_col]), n(r[inst_col]), n(r[frgn_col])) for _, r in tbl.iterrows()]
    if not rows:
        raise ValueError("행 없음")
    last, last5 = rows[0], rows[:5]
    return {
        "date": last[0].replace(".", "-"),
        "기관_순매수_주": last[2], "외국인_순매수_주": last[3],
        "기관_5일_주": sum(r[2] or 0 for r in last5), "외국인_5일_주": sum(r[3] or 0 for r in last5),
        "기관_순매수_원_근사": (last[2] or 0) * (last[1] or 0),
        "외국인_순매수_원_근사": (last[3] or 0) * (last[1] or 0),
        "기관_5일_원_근사": sum((r[2] or 0) * (r[1] or 0) for r in last5),
        "외국인_5일_원_근사": sum((r[3] or 0) * (r[1] or 0) for r in last5),
        "source": "네이버 금융 (순매매량 × 종가로 금액 근사)",
    }


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

    if out["fallbacks"] or out["errors"]:
        print("⚠️ 자동 대체/실패 항목:")
        for line in out["fallbacks"] + out["errors"]:
            print(" -", line)
            print(f"::warning::{line}")  # 깃허브 Actions 실행 화면에 노란 경고로 표시

    json.dump(out, open("prices.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
