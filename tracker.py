import os
import json
import requests
import re
import time
import feedparser
import subprocess
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright
from dotenv import load_dotenv
from groq import Groq

load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_REPO = os.getenv("GITHUB_REPO")

SUBREDDITS = [
    "dubaiclassifieds", "dubai", "abudhabi", "Sharjah", "uaeclassifieds", "UAE_BestDeals", "UAE",
    "BangaloreMarketplace", "bangalorerentals", "bangalore",
    "KeralaBuySell", "Kerala_buysell", "Kerala", "Kochi", "Trivandrum", "KochiClassifieds"
]

DUBIZZLE_URLS = [
    "https://dubai.dubizzle.com/en/free-stuff/"
]

SEEN_POSTS_FILE = "seen_posts.json"

# Stage 1 Keywords
POSITIVE_KEYWORDS = [r"free", r"giveaway", r"moving", r"urgent", r"leaving", r"must go", r"wts", r"clearance", r"sale", r"cheap"]
NEGATIVE_KEYWORDS = [r"\[wtb\]", r"looking for", r"buying", r"wanted"]

def git_pull_memory():
    """Pulls the latest seen_posts.json from GitHub before starting."""
    if not GITHUB_TOKEN or not GITHUB_REPO:
        print("GitHub credentials missing. Skipping Git Pull.")
        return
    try:
        print("Pulling latest memory from Git...")
        subprocess.run(["git", "pull", "origin", "main"], check=False)
    except Exception as e:
        print(f"Git pull failed: {e}")

def git_push_memory():
    """Commits and pushes seen_posts.json back to GitHub before exiting."""
    if not GITHUB_TOKEN or not GITHUB_REPO:
        print("GitHub credentials missing. Skipping Git Push.")
        return
    try:
        print("Committing and pushing memory to Git...")
        subprocess.run(["git", "config", "--global", "user.email", "bot@dealfinder.com"], check=False)
        subprocess.run(["git", "config", "--global", "user.name", "DealFinder Bot"], check=False)
        
        subprocess.run(["git", "add", "SEEN_POSTS_FILE"], check=False)
        subprocess.run(["git", "add", "seen_posts.json"], check=False)
        
        result = subprocess.run(["git", "commit", "-m", "Auto-update memory [skip ci]"], check=False)
        
        if result.returncode == 0:
            remote_url = f"https://x-access-token:{GITHUB_TOKEN}@github.com/{GITHUB_REPO}.git"
            subprocess.run(["git", "push", remote_url, "HEAD:main"], check=False)
            print("Successfully pushed memory to GitHub.")
        else:
            print("No new memory to commit.")
    except Exception as e:
        print(f"Git push failed: {e}")

def load_seen_posts():
    if os.path.exists(SEEN_POSTS_FILE):
        with open(SEEN_POSTS_FILE, 'r') as f:
            return set(json.load(f))
    return set()

def save_seen_posts(seen_posts):
    with open(SEEN_POSTS_FILE, 'w') as f:
        json.dump(list(seen_posts), f)

def send_telegram_message(text):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram credentials missing. Simulating send:")
        print(text)
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML"
    }
    try:
        response = requests.post(url, json=payload)
        response.raise_for_status()
        print("Telegram message sent successfully.")
    except Exception as e:
        print(f"Failed to send Telegram message: {e}")

def stage_1_filter(title, selftext):
    text = (title + " " + selftext).lower()
    for neg in NEGATIVE_KEYWORDS:
        if re.search(neg, text):
            return False
    for pos in POSITIVE_KEYWORDS:
        if re.search(pos, text):
            return True
    return False

def stage_2_groq_analysis(title, selftext, source_name):
    if not GROQ_API_KEY:
        print("Groq API Key missing. Skipping Stage 2.")
        return None

    client = Groq(api_key=GROQ_API_KEY)
    
    prompt = f"""
You are an expert classifieds deal appraiser. I will give you a post from {source_name}. 
You must strictly return a JSON object (no markdown formatting, just raw JSON) analyzing the deal.
Do NOT wrap the response in ```json ``` blocks. Just return the raw JSON object.

Post Title: {title}
Post Body: {selftext}

Output Schema Required:
{{
  "item_category": "electronics | furniture | vehicles | household | other",
  "is_absolutely_free": boolean,
  "seller_motivation_level": "desperate | high | neutral | commercial_dealer",
  "price_stated": "number or null",
  "currency": "string or null",
  "is_negotiable": boolean,
  "deal_score": 0-100,
  "analysis_breakdown": "A concise, objective analysis of the seller's urgency and pricing context."
}}

Scoring Logic (deal_score):
- If the item is absolutely free, score it 100.
- If the seller motivation is desperate (e.g., leaving country tomorrow), give it a very high score (80-100) if a price is mentioned.
- If the seller motivation is commercial_dealer, score it 0.
- If it's highly negotiable, bump the score.
- Base the score on how much of a bargain this appears to be based on the text.
"""
    try:
        chat_completion = client.chat.completions.create(
            messages=[
                {
                    "role": "user",
                    "content": prompt,
                }
            ],
            model="llama-3.1-8b-instant",
            temperature=0.1,
            max_tokens=500
        )
        response_text = chat_completion.choices[0].message.content.strip()
        
        if response_text.startswith("```json"):
            response_text = response_text[7:]
        if response_text.startswith("```"):
            response_text = response_text[3:]
        if response_text.endswith("```"):
            response_text = response_text[:-3]
            
        result = json.loads(response_text)
        return result
    except Exception as e:
        print(f"Error during Groq API call or JSON parsing: {e}")
        return None

def process_item(item_id, title, selftext, post_url, source_name, seen_posts):
    if item_id in seen_posts:
        return
        
    seen_posts.add(item_id)
    save_seen_posts(seen_posts)
    
    if not stage_1_filter(title, selftext):
        return
        
    print(f"Post passed Stage 1: {title}")
    
    time.sleep(1.5) 
    analysis = stage_2_groq_analysis(title, selftext, source_name)
    
    if not analysis:
        return
        
    score = analysis.get("deal_score", 0)
    is_free = analysis.get("is_absolutely_free", False)
    motivation = analysis.get("seller_motivation_level", "neutral")
    
    print(f"Stage 2 Results - Score: {score}, Free: {is_free}, Motivation: {motivation}")
    
    should_alert = False
    if is_free:
        should_alert = True
    elif score >= 80 and motivation != "commercial_dealer":
        should_alert = True
        
    if should_alert:
        message = (
            f"🚨 <b>HIGH VALUE DEAL DETECTED!</b> 🚨\n\n"
            f"<b>Source:</b> {source_name}\n"
            f"<b>Title:</b> {title}\n"
            f"<b>Score:</b> {score}/100\n"
            f"<b>Category:</b> {analysis.get('item_category', 'Unknown')}\n"
            f"<b>Price:</b> {analysis.get('price_stated', 'N/A')} {analysis.get('currency', '')}\n"
            f"<b>Motivation:</b> {motivation}\n\n"
            f"<b>AI Analysis:</b> {analysis.get('analysis_breakdown', 'No analysis provided.')}\n\n"
            f"<a href='{post_url}'>👉 View Post Here</a>"
        )
        send_telegram_message(message)

def run_reddit_scraper(seen_posts):
    headers = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
    for sub in SUBREDDITS:
        print(f"Checking r/{sub} via RSS...")
        url = f"https://www.reddit.com/r/{sub}/new.rss"
        try:
            response = requests.get(url, headers=headers)
            if response.status_code != 200:
                time.sleep(3) 
                continue
                
            feed = feedparser.parse(response.content)
            for entry in feed.entries:
                post_id = entry.id
                title = entry.title
                selftext = entry.summary if hasattr(entry, 'summary') else ''
                post_url = entry.link
                process_item(post_id, title, selftext, post_url, f"r/{sub}", seen_posts)
                
            time.sleep(3) 
        except Exception as e:
            print(f"Error checking {sub}: {e}")
            time.sleep(3)

def run_dubizzle_scraper(seen_posts):
    print("Launching Headless Chrome for Dubizzle...")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            viewport={'width': 1280, 'height': 800}
        )
        page = context.new_page()
        
        for dub_url in DUBIZZLE_URLS:
            try:
                print(f"Checking Dubizzle: {dub_url}")
                page.goto(dub_url, wait_until="networkidle", timeout=60000)
                page.wait_for_timeout(3000) 
                
                html = page.content()
                soup = BeautifulSoup(html, "html.parser")
                
                links = soup.find_all('a', href=True)
                for link in links:
                    href = link['href']
                    if "/en/free-stuff/" in href and len(href) > 30:
                        full_url = href if href.startswith("http") else "https://dubai.dubizzle.com" + href
                        title = link.get_text(strip=True)
                        if not title or len(title) < 5:
                            continue
                            
                        process_item(full_url, title, "Dubizzle Listing", full_url, "Dubizzle", seen_posts)
            except Exception as e:
                print(f"Error checking Dubizzle {dub_url}: {e}")
                
        browser.close()

def main():
    print("Starting Deal Tracker Bot (RSS + Dubizzle Headless Mode)...")
    git_pull_memory()
    
    seen_posts = load_seen_posts()
    run_reddit_scraper(seen_posts)
    run_dubizzle_scraper(seen_posts)
    
    git_push_memory()
            
if __name__ == "__main__":
    main()
