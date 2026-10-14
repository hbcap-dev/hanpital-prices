"""한피탈 DART 공시 수집.

평일 아침 시세 수집 직후 GitHub Actions가 돌려 disclosures.json 을 만든다.
- 대상: tickers.json 의 개별주(보유) + prices.json universe_screen(주목 종목 후보 상위 20)
- 기간: 최근 7일 접수분
- API 키: 환경 변수 DART_API_KEY (깃허브 Secrets). 없으면 이유만 적고 정상 종료.
공시 자체는 공개 정보이고, 키는 파일에 남기지 않는다.
"""
import io
import json
import os
import zipfile
import datetime as dt
import xml.etree.ElementTree as ET
from zoneinfo import ZoneInfo

import requests

KST = ZoneInfo("Asia/Seoul")
API = "https://opendart.fss.or.kr/api"
LOOKBACK_DAYS = 7
# 제목에 이 말이 있으면 '중요'로 표시 (브리핑이 먼저 본다)
IMPORTANT = [
    "주요사항보고", "유상증자", "무상증자", "감자", "합병", "분할", "자기주식", "자사주",
    "단일판매", "공급계약", "잠정", "실적", "최대주주", "소송", "배당", "횡령", "배임",
    "영업정지", "거래정지", "상장폐지", "관리종목", "불성실공시", "전환사채", "신주인수권",
    "교환사채", "타법인주식", "유형자산", "투자판단",
]


def write(out):
    json.dump(out, open("disclosures.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(json.dumps({k: v for k, v in out.items() if k != "items"}, ensure_ascii=False, indent=2))
    print(f"items: {len(out.get('items', []))}")


def corp_codes(key):
    """종목코드(6자리) → DART 고유번호(8자리)"""
    r = requests.get(f"{API}/corpCode.xml", params={"crtfc_key": key}, timeout=60)
    r.raise_for_status()
    if not r.content.startswith(b"PK"):
        raise ValueError("corpCode 응답이 zip이 아님: " + r.text[:200])
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        root = ET.fromstring(z.read(z.namelist()[0]))
    m = {}
    for el in root.iter("list"):
        sc = (el.findtext("stock_code") or "").strip()
        if sc:
            m[sc] = el.findtext("corp_code").strip()
    return m


def targets():
    t = []
    cfg = json.load(open("tickers.json", encoding="utf-8"))
    for s in cfg["stocks"]:
        if not s.get("etf"):
            t.append({"code": s["code"], "name": s["name"], "group": "보유"})
    try:
        p = json.load(open("prices.json", encoding="utf-8"))
        for r in p.get("universe_screen") or []:
            if r.get("code") and all(x["code"] != r["code"] for x in t):
                t.append({"code": r["code"], "name": r.get("name", ""), "group": "후보"})
    except Exception as e:  # noqa: BLE001
        print(f"::warning::universe_screen 못 읽음: {e}")
    return t


def main():
    now = dt.datetime.now(KST)
    bgn = (now - dt.timedelta(days=LOOKBACK_DAYS)).strftime("%Y%m%d")
    end = now.strftime("%Y%m%d")
    out = {"updated_at": now.isoformat(timespec="minutes"), "window": f"{bgn}~{end}",
           "items": [], "errors": [], "targets": []}

    key = os.environ.get("DART_API_KEY", "").strip()
    if not key:
        out["errors"].append("DART_API_KEY 없음 (깃허브 Secrets에 등록 필요)")
        write(out)
        return

    try:
        cmap = corp_codes(key)
    except Exception as e:  # noqa: BLE001
        out["errors"].append(f"고유번호 목록 실패: {e}")
        write(out)
        return

    for t in targets():
        cc = cmap.get(t["code"])
        out["targets"].append({**t, "corp_code": cc})
        if not cc:
            out["errors"].append(f"{t['name']}({t['code']}): DART 고유번호 없음")
            continue
        try:
            r = requests.get(f"{API}/list.json", params={
                "crtfc_key": key, "corp_code": cc, "bgn_de": bgn, "end_de": end, "page_count": 100,
            }, timeout=20)
            j = r.json()
            st = j.get("status")
            if st == "013":  # 조회된 데이터 없음
                continue
            if st != "000":
                out["errors"].append(f"{t['name']}: {st} {j.get('message')}")
                continue
            for d in j.get("list", []):
                nm = (d.get("report_nm") or "").strip()
                out["items"].append({
                    "code": t["code"], "name": t["name"], "group": t["group"],
                    "rcept_dt": d.get("rcept_dt"), "report_nm": nm, "flr_nm": d.get("flr_nm"),
                    "rcept_no": d.get("rcept_no"), "rm": d.get("rm", ""),
                    "important": any(k in nm for k in IMPORTANT),
                    "url": f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={d.get('rcept_no')}",
                })
        except Exception as e:  # noqa: BLE001
            out["errors"].append(f"{t['name']}: {e}")

    # 같은 그룹·중요도 안에서는 최신순
    out["items"].sort(key=lambda x: x["rcept_dt"] or "", reverse=True)
    out["items"].sort(key=lambda x: (x["group"] != "보유", not x["important"]))
    for line in out["errors"]:
        print(f"::warning::{line}")
    write(out)


if __name__ == "__main__":
    main()
