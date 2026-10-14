"""한피탈 텔레그램 전달기.

아침 브리핑·장 마감·주간 리포트·장중 긴급 회의(예약 작업)가 workflow_dispatch로 보낸 짧은 글을
텔레그램으로 그대로 전달한다. 토큰은 깃허브 Secrets에만 있고, 글은 로그에 찍지 않는다.
공개 저장소이므로 보내는 쪽은 수량·금액 없이 짧게 보낸다(자세한 건 대시보드).
"""
import os
import requests

text = (os.environ.get("NOTIFY_TEXT") or "").strip()[:3500]
token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
chat = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
if not text:
    print("보낼 글 없음")
elif not token or not chat:
    print("::warning::텔레그램 Secrets 없음")
else:
    r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                      json={"chat_id": chat, "text": text, "disable_web_page_preview": True}, timeout=15)
    print("보냄" if r.ok else f"::warning::전송 실패 {r.status_code}")
