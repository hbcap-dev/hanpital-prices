"""미국 거시 지표(FRED 공개 CSV, 키 불필요) → macro.json"""
import csv
import io
import json
from datetime import datetime, timedelta, timezone

import requests

KST = timezone(timedelta(hours=9))
UA = {"User-Agent": "Mozilla/5.0 hanpital-bot"}
# (id, 이름, 단위, 계산) 계산: level | yoy(전년 대비 %) | mom_diff(전월 대비 차이)
SERIES = [
    ("CPIAUCSL", "미국 CPI", "% YoY", "yoy"),
    ("CPILFESL", "미국 근원 CPI", "% YoY", "yoy"),
    ("PCEPILFE", "미국 근원 PCE", "% YoY", "yoy"),
    ("UNRATE", "미국 실업률", "%", "level"),
    ("PAYEMS", "미국 비농업 고용 증감", "천 명", "mom_diff"),
    ("DFEDTARU", "연준 기준금리 상단", "%", "level"),
    ("DGS2", "미국 2년물", "%", "level"),
    ("DGS10", "미국 10년물", "%", "level"),
    ("T10Y2Y", "장단기 금리차(10년-2년)", "%p", "level"),
    ("BAMLH0A0HYM2", "미국 하이일드 스프레드", "%p", "level"),
    ("VIXCLS", "VIX", "pt", "level"),
    ("DTWEXBGS", "달러 지수(광의)", "pt", "level"),
    ("DCOILWTICO", "WTI 유가", "$", "level"),
]


def load(sid):
    start = (datetime.now(KST) - timedelta(days=800)).strftime("%Y-%m-%d")
    r = requests.get(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}&cosd={start}",
                     headers=UA, timeout=30)
    r.raise_for_status()
    obs = []
    for row in csv.reader(io.StringIO(r.text)):
        if len(row) < 2 or not row[0][:4].isdigit():
            continue
        try:
            obs.append((row[0], float(row[1])))
        except ValueError:
            pass
    return obs


def calc(obs, how):
    if how == "level":
        (d, v), (pd, pv) = obs[-1], obs[-2]
        return d, round(v, 3), pd, round(pv, 3)
    if how == "mom_diff":
        return obs[-1][0], round(obs[-1][1] - obs[-2][1], 1), obs[-2][0], round(obs[-2][1] - obs[-3][1], 1)

    def yoy(i):
        d, v = obs[i]
        y = str(int(d[:4]) - 1) + d[4:]
        base = dict(obs).get(y)
        return d, (round((v / base - 1) * 100, 2) if base else None)
    d, v = yoy(-1)
    pd, pv = yoy(-2)
    return d, v, pd, pv


def main():
    out = {"updated_at": datetime.now(KST).isoformat(timespec="seconds"),
           "source": "FRED (St. Louis Fed)", "items": [], "errors": []}
    for sid, name, unit, how in SERIES:
        try:
            d, v, pd, pv = calc(load(sid), how)
            out["items"].append({"id": sid, "name": name, "unit": unit, "date": d, "value": v,
                                 "prev_date": pd, "prev": pv,
                                 "url": f"https://fred.stlouisfed.org/series/{sid}"})
        except Exception as e:
            out["errors"].append(f"{sid}: {type(e).__name__} {e}"[:200])
    json.dump(out, open("macro.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"거시 {len(out['items'])}개, 오류 {len(out['errors'])}")


if __name__ == "__main__":
    main()
