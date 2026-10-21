import os
import asyncio
import feedparser
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from google import genai
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from telegram.request import HTTPXRequest
from apscheduler.schedulers.asyncio import AsyncIOScheduler

load_dotenv()

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

RSS_URL = "https://cafef.vn/thi-truong-chung-khoan.rss"
CATEGORIES = {
    "Kinh tế số": (
        "công nghệ", "kỹ thuật số", "digital", "ai ", "trí tuệ nhân tạo",
        "fintech", "thương mại điện tử", "startup", "game", "phần mềm",
        "nền tảng", "đổi mới sáng tạo",
    ),
    "Doanh nghiệp": (
        "doanh nghiệp", "công ty", "tập đoàn", "cổ phiếu", "doanh thu",
        "lợi nhuận", "m&a", "đầu tư", "tài trợ", "bảo hiểm", "ngân hàng",
    ),
}

# Configure Gemini client
gemini_client = genai.Client(api_key=GOOGLE_API_KEY) if GOOGLE_API_KEY else None


def fetch_latest_entries(limit=3):
    feed = feedparser.parse(RSS_URL)
    return feed.entries[:limit]


def classify_article(title, content):
    text = f"{title} {content}".lower()
    for category, keywords in CATEGORIES.items():
        if any(keyword in text for keyword in keywords):
            return category
    return "Thị trường chứng khoán"


def extract_article_text(url):
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.content, "html.parser")
        # Heuristics: try article tag, else join all <p> text
        article = soup.find("article")
        if article:
            texts = [p.get_text(strip=True) for p in article.find_all("p")]
        else:
            paragraphs = soup.find_all("p")
            texts = [p.get_text(strip=True) for p in paragraphs]
        # Keep reasonable length
        joined = "\n\n".join([t for t in texts if t])
        return joined[:3000]  # limit chars to avoid huge prompts
    except Exception as e:
        return ""


def summarize_article(title, link, content):
    category = classify_article(title, content)
    prompt = (
        f"You are a helpful assistant.\n"
        f"Category: {category}\n"
        f"Summarize the article titled:\n{title}\nURL: {link}\n\n"
        "Output format (MARKDOWN):\n"
        "- Title with link\n"
        "- Two-sentence summary\n"
        "- Sentiment: Positive / Negative / Neutral\n"
        "Be concise and produce a neat Markdown block.\n\n"
        "Article content:\n" + content
    )
    try:
        if gemini_client is None:
            raise RuntimeError("GOOGLE_API_KEY is missing from .env")
        resp = gemini_client.models.generate_content(
            model="gemini-3.6-flash",
            contents=prompt,
        )
        return (resp.text or "").strip()
    except Exception as e:
        if "RESOURCE_EXHAUSTED" in str(e) or "quota" in str(e).lower():
            return "Chưa thể tóm tắt bằng Gemini: API đã hết hạn mức miễn phí. Vui lòng thử lại sau khi quota được reset hoặc nâng cấp billing."
        return f"**Error generating summary**: {e}"


def generate_digest():
    # Keep each digest within the free Gemini request quota.
    entries = fetch_latest_entries(limit=3)
    grouped = {category: [] for category in ("Thị trường chứng khoán", *CATEGORIES)}
    for e in entries:
        title = e.get("title", "(No title)")
        link = e.get("link", "")
        published = e.get("published", "")
        content = extract_article_text(link)
        summary = summarize_article(title, link, content)
        category = classify_article(title, content)
        block = f"{title}\n{link}\n{published}\n\n{summary}\n\n---\n"
        grouped[category].append(block)

    sections = ["# Bản tóm tắt tin tức thị trường\n"]
    for category, blocks in grouped.items():
        if blocks:
            sections.append(f"\n## {category}\n\n" + "\n".join(blocks))
    return "\n".join(sections)

def split_message(text, chunk_size=3900):
    # Telegram message limit ~4096, reserve some margin
    return [text[i:i+chunk_size] for i in range(0, len(text), chunk_size)]


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Xin chào! Gõ /tinmoi để nhận bản tóm tắt 3 tin mới nhất về thị trường chứng khoán."
    )


async def tinmoi(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Đang tổng hợp... Vui lòng chờ vài giây.")
    loop = asyncio.get_event_loop()
    digest = await loop.run_in_executor(None, generate_digest)
    parts = split_message(digest)
    for p in parts:
        await update.message.reply_text(p)


def main():
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Please set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env")
        return

    telegram_request = HTTPXRequest(
        connect_timeout=30,
        read_timeout=30,
        write_timeout=30,
        pool_timeout=30,
    )
    app = (
        ApplicationBuilder()
        .token(TELEGRAM_BOT_TOKEN)
        .request(telegram_request)
        .build()
    )
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("tinmoi", tinmoi))

    # Background sender: periodically call generate_digest and send via Telegram HTTP API
    import threading, time

    def periodic_sender(interval_minutes=60):
        while True:
            try:
                digest = generate_digest()
                parts = split_message(digest)
                for p in parts:
                    # Use Telegram HTTP API to send messages synchronously from this thread
                    try:
                        response = requests.post(
                            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                            data={"chat_id": TELEGRAM_CHAT_ID, "text": p},
                            timeout=15,
                        )
                        response.raise_for_status()
                    except Exception as e:
                        print("Failed to send periodic message:", e)
            except Exception as e:
                print("Periodic sender error:", e)
            time.sleep(interval_minutes * 60)

    sender_thread = threading.Thread(target=periodic_sender, args=(60,), daemon=True)
    sender_thread.start()

    print("Bot started. Listening for commands. Press Ctrl+C to stop.")
    # Run polling synchronously; Application will manage the event loop
    app.run_polling()


if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, SystemExit):
        print("Shutting down...")
