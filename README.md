# hanpital-prices

한피탈(개인 AI 재무팀) 아침 브리핑용 시세 수집 저장소. 비공개 유지.

- `tickers.json`: 시세를 가져올 국내 종목과 시장 지표 목록
- `fetch_prices.py`: pykrx(KRX) 우선, 실패 시 yfinance로 최근 종가와 전일 대비 등락률 수집
- `prices.json`: 결과. 평일 한국시간 06:40쯤 GitHub Actions가 갱신
- 수동 실행: Actions 탭 → "한피탈 시세 수집" → Run workflow

자동 대체 표시: KRX 조회가 실패해 야후로 대체한 종목은 `prices.json`의 해당 행 `fallback`과 맨 위 `fallbacks` 목록에 적히고, Actions 실행 화면에 노란 경고로 뜬다. 한피탈 브리핑은 이 표시를 대시보드와 카톡에 그대로 옮긴다.

보유 종목이 바뀌면 `tickers.json`에 코드를 추가하거나 빼면 된다.

`universe.json`: 코스피 시총 상위 100 + 코스닥 상위 50의 PER·PBR·52주 위치·목표가 괴리·5일 수급. `prices.json`의 `universe_screen`은 보유·적자·우선주를 뺀 목표가 괴리 상위 20개로, 한피탈 애널리스트의 주목 종목 후보다.

`intraday.py` / `intraday.json`: 평일 장중(09~15시 매시) 보유·예정 종목, 코스피, 원/달러, KRX 금현물 현재가. 한피탈 장중 알림이 읽는다. 알림 기준 판단은 하지 않는다.

## DART 공시 (disclosures.json)
- 평일 아침 시세 수집 직후 `dart.py`가 보유 개별주 + 주목 종목 후보(universe_screen 상위 20)의 최근 7일 공시 목록을 만든다.
- 깃허브 저장소 Settings → Secrets and variables → Actions 에 `DART_API_KEY`(OpenDART 인증키)를 등록해야 동작한다. 키가 없으면 errors에 이유만 남기고 넘어간다.
- 제목에 주요사항보고·유상증자·실적·공급계약 등이 있으면 `important: true`.
