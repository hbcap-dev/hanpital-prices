import json, requests
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36", "Referer": "https://stock.naver.com/research"}
out = {}
for c in ["economy", "debt", "strategy", "invest", "market", "daily", "industry", "company"]:
    try:
        r = requests.get(f"https://stock.naver.com/api/stockSecurity/researches/v2/{c}?index=0&size=2", headers=UA, timeout=20)
        j = r.json() if r.ok else None
        it = (j or {}).get("items", [{}])[0] if j else {}
        out[c] = {"status": r.status_code, "total": (j or {}).get("totalCount"), "keys": list(it.keys()),
                  "sample": {k: (str(v)[:120]) for k, v in it.items() if k != "content"}, "content_len": len(it.get("content", ""))}
    except Exception as e:
        out[c] = str(e)
try:
    r = requests.get("https://stock.naver.com/api/stockSecurity/researches/v2/company?index=0&size=2&itemCode=005930", headers=UA, timeout=20)
    out["company_005930"] = [{k: str(v)[:80] for k, v in i.items() if k != "content"} for i in r.json().get("items", [])]
except Exception as e:
    out["company_005930"] = str(e)
json.dump(out, open("probe.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
