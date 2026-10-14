"""네이버 증권 리서치 목록 수집 → research.json
제목·증권사·날짜·링크만 저장한다(리포트 본문은 저장하지 않음).
"""
import json
import re
import time
from datetime import datetime, timedelta, timezone

import requests
from bs4 import BeautifulSoup

KST = timezone(timedelta(hours=9))
BASE = "https://finance.naver.com/research/"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
      "Referer": "https://finance.naver.com/research/"}
CATS = [  # (키, 이름, 목록 페이지, 페이지 수)
    ("economy", "경제분석", "economy_list.naver", 2),
    ("market", "시황정보", "market_info_list.naver", 1),
    ("debt", "채권분석", "debt_list.naver", 1),
    ("invest", "투자정보", "invest_list.naver", 1),
]
DAYS = 4  # 최근 며칠치(주말 포함)
DATE_RE = re.compile(r"^\d{2}\.\d{2}\.\d{2}$")


def fetch(url):
    r = requests.get(url, headers=UA, timeout=20)
    r.raise_for_status()
    r.encoding = "euc-kr"
    return r.text


def parse(html, cat_key, cat_name, page_url):
    soup = BeautifulSoup(html, "html.parser")
    rows = []
    for tr in soup.select("table.type_1 tr"):
        tds = tr.find_all("td")
        if len(tds) < 4:
            continue
        a = tr.find("a", href=re.compile(r"_read\.naver"))
        if not a:
            continue
        texts = [td.get_text(" ", strip=True) for td in tds]
        date = next((t for t in texts if DATE_RE.match(t)), "")
        if not date:
            continue
        # 제목 칸 다음 칸이 증권사
        ti = next(i for i, td in enumerate(tds) if td.find("a", href=re.compile(r"_read\.naver")))
        broker = texts[ti + 1] if ti + 1 < len(texts) else ""
        item = ""
        if ti > 0:  # 종목분석 목록: 앞 칸이 종목명
            item = texts[ti - 1]
        pdf = tr.find("a", href=re.compile(r"\.pdf", re.I))
        nid = re.search(r"nid=(\d+)", a["href"])
        rows.append({
            "cat": cat_key, "category": cat_name,
            "title": a.get_text(strip=True), "broker": broker, "item": item,
            "date": "20" + date.replace(".", "-"),
            "nid": nid.group(1) if nid else "",
            "url": requests.compat.urljoin(page_url, a["href"]),
            "pdf": pdf["href"] if pdf else "",
        })
    return rows


def main():
    now = datetime.now(KST)
    cutoff = (now - timedelta(days=DAYS)).strftime("%Y-%m-%d")
    out = {"updated_at": now.isoformat(timespec="seconds"), "window_days": DAYS,
           "source": "finance.naver.com/research", "note": "목록만 저장. 본문은 pdf 링크에서 확인.",
           "items": [], "holdings_reports": [], "errors": []}

    for key, name, path, pages in CATS:
        for p in range(1, pages + 1):
            url = f"{BASE}{path}?page={p}"
            try:
                html = fetch(url)
                rows = parse(html, key, name, url)
                if not rows and p == 1:
                    sp = BeautifulSoup(html, "html.parser")
                    tbls = [(t.get("class"), len(t.find_all("tr"))) for t in sp.find_all("table")][:6]
                    trs = [str(tr)[:400] for tr in sp.find_all("tr") if tr.find("a")][:2]
                    out.setdefault("debug", []).append({"cat": name, "len": len(html), "title": sp.title.string if sp.title else "", "tables": str(tbls), "trs": trs})
                out["items"].extend(r for r in rows if r["date"] >= cutoff)
            except Exception as e:
                out["errors"].append(f"{name} p{p}: {type(e).__name__} {e}"[:200])
            time.sleep(0.6)

    # 보유 개별주 종목분석 리포트(최근 30일)
    try:
        tickers = json.load(open("tickers.json", encoding="utf-8"))
        stocks = [t for t in tickers.get("stocks", []) if not t.get("etf")]
    except Exception as e:
        stocks = []
        out["errors"].append(f"tickers.json: {e}"[:200])
    c30 = (now - timedelta(days=30)).strftime("%Y-%m-%d")
    for t in stocks:
        url = f"{BASE}company_list.naver?searchType=itemCode&itemCode={t['code']}&page=1"
        try:
            rows = parse(fetch(url), "company", "종목분석", url)
            for r in rows:
                if r["date"] >= c30:
                    r["code"] = t["code"]
                    r["item"] = r["item"] or t.get("name", "")
                    out["holdings_reports"].append(r)
        except Exception as e:
            out["errors"].append(f"종목분석 {t['code']}: {type(e).__name__} {e}"[:200])
        time.sleep(0.6)

    json.dump(out, open("research.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"리서치 {len(out['items'])}건, 보유 종목 리포트 {len(out['holdings_reports'])}건, 오류 {len(out['errors'])}")


if __name__ == "__main__":
    main()
