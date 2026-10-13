# hanpital-prices

한피탈(개인 AI 재무팀) 아침 브리핑용 시세 수집 저장소. 비공개 유지.

- `tickers.json`: 시세를 가져올 국내 종목과 시장 지표 목록
- `fetch_prices.py`: pykrx(KRX) 우선, 실패 시 yfinance로 최근 종가와 전일 대비 등락률 수집
- `prices.json`: 결과. 평일 한국시간 06:40쯤 GitHub Actions가 갱신
- 수동 실행: Actions 탭 → "한피탈 시세 수집" → Run workflow

자동 대체 표시: KRX 조회가 실패해 야후로 대체한 종목은 `prices.json`의 해당 행 `fallback`과 맨 위 `fallbacks` 목록에 적히고, Actions 실행 화면에 노란 경고로 뜬다. 한피탈 브리핑은 이 표시를 대시보드와 카톡에 그대로 옮긴다.

보유 종목이 바뀌면 `tickers.json`에 코드를 추가하거나 빼면 된다.
