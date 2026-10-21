# Dự án: AI Agent tóm tắt tin tức thị trường (MVP)

Cách dùng nhanh:

1. Tạo file `.env` theo mẫu:

```
OPENAI_API_KEY=sk-...
TELEGRAM_BOT_TOKEN=123456789:...
TELEGRAM_CHAT_ID=@your_chat_id
```

2. Cài dependencies:

```
python -m pip install feedparser requests beautifulsoup4 langchain openai python-telegram-bot apscheduler python-dotenv
```

3. Chạy bot:

```
python main.py
```

Gõ `/start` trong Telegram để xem hướng dẫn, hoặc `/tinmoi` để nhận bản tóm tắt 3 tin mới nhất.

Ghi chú:
- Model dùng qua LangChain: gpt-4o-mini (cần OpenAI API key). Nếu muốn thay model, sửa trong `main.py`.
- Nếu tin nhắn quá dài, bot sẽ chia nhỏ tự động.
