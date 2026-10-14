import json
from playwright.sync_api import sync_playwright
out = []
with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page()
    def on_resp(r):
        if r.request.resource_type in ("xhr", "fetch"):
            try:
                body = r.text()[:600]
            except Exception as e:
                body = str(e)
            out.append({"url": r.url, "status": r.status, "body": body})
    pg.on("response", on_resp)
    for u in ["https://stock.naver.com/research/economy", "https://stock.naver.com/research/company"]:
        pg.goto(u, wait_until="networkidle", timeout=60000)
        pg.wait_for_timeout(3000)
        out.append({"url": "PAGE " + u, "status": 0, "body": pg.inner_text("main")[:1500] if pg.query_selector("main") else pg.inner_text("body")[:1500]})
    b.close()
json.dump(out, open("probe.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
