# ⚡ DealFinder Bot: Automated Real-Time Deal Tracker

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Automation](https://img.shields.io/badge/Pipeline-Automated%20Scraper-green.svg)](#)

An automated deal scraping and price anomaly detection bot. Continuously monitors targeted regional classifieds and marketplaces, applies regex keyword heuristics and Groq LLM validation, and delivers instant notifications to Telegram.

---

## 🏛️ How It Works

```
┌────────────────────┐     ┌─────────────────────┐     ┌─────────────────────┐
│ 1. Stream Monitor  │────►│ 2. Heuristic Filter │────►│ 3. LLM Verification │
│ Regional Feeds     │     │ Regex Boundary Match│     │ Groq (Llama 3 8B)   │
└────────────────────┘     └─────────────────────┘     └──────────┬──────────┘
                                                                  │
                                                                  ▼
                                                       ┌─────────────────────┐
                                                       │ 4. Instant Dispatch │
                                                       │ Telegram Webhook    │
                                                       └─────────────────────┘
```

1. **Stream Polling:** Monitors high-velocity community classified feeds across the UAE and India (Dubai, Abu Dhabi, Bangalore, Kerala).
2. **Two-Stage Filtering:**
   - **Stage 1 (Regex Filtering):** Uses compiled boundary regex patterns to match buyer intent and distress sale keywords (`[WTS]`, `moving out`, `urgent`, `clearance`) while eliminating noise (`[WTB]`, `recommendation`).
   - **Stage 2 (LLM Validation):** Uses low-latency Groq LLM inference to confirm deal legitimacy and extract structured pricing and item metadata.
3. **Alerting:** Formats verified deals and sends immediate push alerts via Telegram Bot API.

---

## 🛠️ Setup & Configuration

### 1. Installation
```bash
git clone https://github.com/shameel0505/dealfinder-bot.git
cd dealfinder-bot

python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Environment Variables
Copy `.env.example` to `.env` and fill in credentials:
```bash
GROQ_API_KEY=your_groq_api_key
TELEGRAM_BOT_TOKEN=your_telegram_bot_token
TELEGRAM_CHAT_ID=your_chat_id
```

### 3. Execution
```bash
python tracker.py
```

---

## 📄 License
Licensed under the [MIT License](LICENSE).
