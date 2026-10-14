"""네이버 증권 리서치 목록 수집 → research.json
공개 저장소이므로 제목·증권사·날짜·업종·종목·목표가·의견·링크만 저장한다(요약 본문은 저장하지 않음).
본문에서는 주제 태그(topics)만 뽑는다.
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
PAGE = 30
# 본문은 저장하지 않고, 본문에 나온 주제 키워드만 태그로 남긴다(통계 정보)
TOPICS = {
    "금리": ["금리"], "금리 인하": ["인하"], "금리 인상": ["인상"], "연준": ["연준", "FOMC", "Fed", "파월"],
    "한은": ["한은", "한국은행", "금통위"], "환율": ["환율", "원/달러", "원달러"], "달러": ["달러"],
    "엔화": ["엔화", "엔/달러", "BOJ", "일본은행"], "물가": ["물가", "CPI", "인플레", "PCE"],
    "고용": ["고용", "실업", "비농업"], "경기 둔화": ["둔화", "침체", "리세션", "역성장"],
    "수출": ["수출"], "반도체": ["반도체", "메모리", "HBM", "D램", "DRAM"], "AI": ["AI", "인공지능"],
    "관세·무역": ["관세", "무역", "수출 규제", "제재"], "중국": ["중국", "위안"], "유가": ["유가", "원유", "WTI", "OPEC"],
    "금": ["금 가격", "금값", "금 현물", "골드"], "채권": ["채권", "국채", "국고채", "크레딧", "회사채"],
    "외국인 매도": ["외국인 순매도", "외국인의 대규모 매도", "외국인 매도"], "외국인 매수": ["외국인 순매수", "외국인 매수"],
    "변동성": ["변동성", "사이드카", "서킷브레이커", "VIX", "급락", "폭락"], "반등": ["반등", "반발 매수", "과매도"],
    "실적": ["실적", "영업이익", "컨센서스", "어닝"], "지정학": ["지정학", "전쟁", "분쟁", "중동", "대만"],
    "부동산": ["부동산", "주택"], "정책·세제": ["세제", "밸류업", "ISA", "정부", "예산"],
}


def tags(html):
    import re
    text = re.sub(r"<[^>]+>", " ", html or "")
    return [k for k, words in TOPICS.items() if any(w in text for w in words)]


KEEP = ["nid", "title", "brokerName", "writeDate", "analystName", "industryKoreanName",
        "itemCode", "itemName", "goalPrice", "opinionText", "readCount"]


def get(cat, index, size):
    r = requests.get(f"{API}{cat}?index={index}&size={size}", headers=UA, timeout=20)
    r.raise_for_status()
    return r.json()


def slim(cat, name, it):
    row = {"cat": cat, "category": name}
    row.update({k: it.get(k) for k in KEEP if it.get(k) not in (None, "")})
    row["topics"] = tags(it.get("content"))
    row["page_url"] = f"https://stock.naver.com/research/{cat}"
    return row


def main():
    now = datetime.now(KST)
    cutoff = (now - timedelta(days=DAYS)).strftime("%Y-%m-%d")
    c_cut = (now - timedelta(days=COMPANY_DAYS)).strftime("%Y-%m-%d")
    out = {"updated_at": now.isoformat(timespec="seconds"), "window_days": DAYS,
           "source": "Npay 증권 리서치 (stock.naver.com/research)",
           "note": "목록과 주제 태그만 저장(요약 본문은 저장하지 않음).",
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
        # index가 쪽 번호인지 시작 위치인지 확인
        p0 = get("company", 0, PAGE).get("items", [])
        p1 = get("company", 1, PAGE).get("items", [])
        offset = len(p0) > 1 and p1 and p1[0].get("nid") == p0[1].get("nid")
        out["company_index_mode"] = "offset" if offset else "page"
        steps = range(0, COMPANY_SCAN, PAGE) if offset else range(0, COMPANY_SCAN // PAGE)
        for idx in steps:
            j = get("company", idx, PAGE)
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

    # 주제 집계(경제분석·시황·투자전략)
    from collections import Counter
    cnt = Counter(t for r in out["items"] if r["cat"] in ("economy", "market", "invest") for t in r.get("topics", []))
    out["topic_counts"] = dict(cnt.most_common())

    json.dump(out, open("research.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"리서치 {len(out['items'])}건, 관심 종목 리포트 {len(out['company'])}건(훑은 {seen}건), 오류 {len(out['errors'])}")


if __name__ == "__main__":
    main()
