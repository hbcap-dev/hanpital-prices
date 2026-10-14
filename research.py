"""네이버 증권 리서치 목록 수집 → research.json
공개 저장소이므로 제목·증권사·날짜·업종·종목·목표가·의견·링크만 저장한다(요약 본문은 저장하지 않음).
본문은 아침 브리핑이 api_url 로 직접 읽는다.
"""
import json
import time
from datetime import datetime, timedelta, timezone

import requests

KST = timezone(timedelta(hours=9))
API = "https://stock.naver.com/api/stockSecurity/researches/v2/"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
      "Referer": "https://stock.naver.com/research"}
CATS = [  # (키, 이름, 가져올 개수)
    ("economy", "경제분석", 30),
    ("market", "시황정보", 20),
    ("invest", "투자전략", 20),
    ("industry", "산업분석", 40),
]
DAYS = 4           # 카테고리 리포트: 최근 며칠치(주말 포함)
COMPANY_DAYS = 30  # 보유·후보 종목 리포트
COMPANY_SCAN = 600  # 국내종목 최신 몇 건을 훑을지
KEEP = ["nid", "title", "brokerName", "writeDate", "analystName", "industryKoreanName",
        "itemCode", "itemName", "goalPrice", "opinionText", "readCount"]


def get(cat, index, size):
    r = requests.get(f"{API}{cat}?index={index}&size={size}", headers=UA, timeout=20)
    r.raise_for_status()
    return r.json()


def slim(cat, name, it):
    row = {"cat": cat, "category": name}
    row.update({k: it.get(k) for k in KEEP if it.get(k) not in (None, "")})
    row["api_url"] = f"{API}{cat}?index=0&size=40"
    row["page_url"] = f"https://stock.naver.com/research/{cat}"
    return row


def main():
    now = datetime.now(KST)
    cutoff = (now - timedelta(days=DAYS)).strftime("%Y-%m-%d")
    c_cut = (now - timedelta(days=COMPANY_DAYS)).strftime("%Y-%m-%d")
    out = {"updated_at": now.isoformat(timespec="seconds"), "window_days": DAYS,
           "source": "Npay 증권 리서치 (stock.naver.com/research)",
           "note": "목록만 저장. 요약 본문은 api_url(같은 카테고리 최신 40건, nid로 찾기)에서 읽는다.",
           "items": [], "company": [], "errors": []}

    for cat, name, n in CATS:
        try:
            j = get(cat, 0, n)
            out["items"].extend(slim(cat, name, it) for it in j.get("items", [])
                                if (it.get("writeDate") or "") >= cutoff)
        except Exception as e:
            out["errors"].append(f"{name}: {type(e).__name__} {e}"[:200])
        time.sleep(0.5)

    # 관심 종목 코드: 보유 개별주 + 주목 종목 후보(universe_screen)
    codes = {}
    try:
        for t in json.load(open("tickers.json", encoding="utf-8")).get("stocks", []):
            if not t.get("etf"):
                codes[t["code"]] = "보유"
    except Exception as e:
        out["errors"].append(f"tickers.json: {e}"[:200])
    try:
        for t in json.load(open("prices.json", encoding="utf-8")).get("universe_screen", []):
            codes.setdefault(str(t.get("code")), "후보")
    except Exception as e:
        out["errors"].append(f"prices.json: {e}"[:200])

    seen = 0
    try:
        for idx in range(0, COMPANY_SCAN, 100):
            j = get("company", idx, 100)
            items = j.get("items", [])
            for it in items:
                if (it.get("writeDate") or "") < c_cut:
                    continue
                code = str(it.get("itemCode", ""))
                if code in codes:
                    row = slim("company", "종목분석", it)
                    row["group"] = codes[code]
                    out["company"].append(row)
            seen += len(items)
            if not items or (items[-1].get("writeDate") or "") < c_cut or not j.get("hasNext"):
                break
            time.sleep(0.5)
    except Exception as e:
        out["errors"].append(f"종목분석: {type(e).__name__} {e}"[:200])
    out["company_scanned"] = seen

    json.dump(out, open("research.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"리서치 {len(out['items'])}건, 관심 종목 리포트 {len(out['company'])}건(훑은 {seen}건), 오류 {len(out['errors'])}")


if __name__ == "__main__":
    main()
