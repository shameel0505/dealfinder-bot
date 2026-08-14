import os
import json
import requests
import re
import time
import feedparser
import subprocess
import calendar
import base64
import urllib3
from dotenv import load_dotenv
from groq import Groq

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

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

SEEN_POSTS_FILE = "seen_posts.json"

# Stage 1 Keywords (Enhanced Regex with Word Boundaries)
POSITIVE_KEYWORDS = [
    r"\bfree\b", r"\bgiveaway\b", r"\bmoving\b", r"\burgent\b", r"\bleaving\b", 
    r"must go", r"\[wts\]", r"\bwts\b", r"\bclearance\b", r"\bsale\b", r"\bcheap\b", 
    r"for sale", r"selling", r"price drop", r"discount", r"take it"
]

NEGATIVE_KEYWORDS = [
    r"\[wtb\]", r"\bwtb\b", r"looking for", r"\bbuying\b", r"\bwanted\b", 
    r"in search of", r"\biso\b", r"where can i", r"where to buy", 
    r"anybody selling", r"anyone selling", r"anyone have", r"anyone has", 
    r"recommendation", r"looking to buy", r"want to buy", 
    r"\bneed a\b", r"\bneed an\b", r"\bneed some\b", r"\bneed to buy\b"
]

GITHUB_FILE_SHA = None

def api_pull_memory():
    """Pulls the latest seen_posts.json directly from GitHub API."""
    global GITHUB_FILE_SHA
    if not GITHUB_TOKEN or not GITHUB_REPO:
        print("GitHub credentials missing. Skipping API Pull.")
        return
        
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{SEEN_POSTS_FILE}"
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }
    try:
        print("Pulling latest memory from GitHub API...")
        response = requests.get(url, headers=headers, verify=False)
        if response.status_code == 200:
            data = response.json()
            GITHUB_FILE_SHA = data['sha']
            content = base64.b64decode(data['content']).decode('utf-8')
            with open(SEEN_POSTS_FILE, 'w') as f:
                f.write(content)
            print("Successfully downloaded memory from GitHub.")
        elif response.status_code == 404:
            print("Memory file not found on GitHub. A new one will be created.")
        else:
            print(f"GitHub API Error: {response.status_code} - {response.text}")
    except Exception as e:
        print(f"API Pull failed: {e}")

def api_push_memory():
    """Pushes seen_posts.json directly to GitHub API."""
    if not GITHUB_TOKEN or not GITHUB_REPO:
        print("GitHub credentials missing. Skipping API Push.")
        return
        
    if not os.path.exists(SEEN_POSTS_FILE):
        print("No memory file to push.")
        return
        
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{SEEN_POSTS_FILE}"
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }
    
    try:
        print("Pushing memory to GitHub API...")
        
        # Get the latest SHA first to prevent 422 errors
        get_response = requests.get(url, headers=headers, verify=False)
        sha = None
        if get_response.status_code == 200:
            sha = get_response.json().get('sha')
            
        with open(SEEN_POSTS_FILE, 'r') as f:
            content = f.read()
            
        encoded_content = base64.b64encode(content.encode('utf-8')).decode('utf-8')
        
        payload = {
            "message": "Auto-update memory [skip ci]",
            "content": encoded_content
        }
        
        if sha:
            payload["sha"] = sha
            
        response = requests.put(url, headers=headers, json=payload, verify=False)
        
        if response.status_code in [200, 201]:
            print("Successfully pushed memory to GitHub.")
        else:
            print(f"GitHub API Error: {response.status_code} - {response.text}")
    except Exception as e:
        print(f"API Push failed: {e}")

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

CRITICAL RULE 1: You are looking for HIGH-VALUE DEALS. This includes physical items (furniture, electronics, cars) AND premium digital services/software that are normally paid but are currently heavily discounted or free. You must STRONGLY REJECT self-promotion, people advertising their own basic free apps/projects, job postings, advice, or news.
CRITICAL RULE 2: You must COMPLETELY REJECT any post where the user is looking to BUY or ACQUIRE an item (e.g., "needed", "wanted", "looking for", "WTB"). You are ONLY looking for people SELLING or GIVING AWAY items.

Post Title: {title}
Post Body: {selftext}

Output Schema Required:
{{
  "is_buy_request": boolean,
  "is_valuable_deal": boolean,
  "item_category": "electronics | furniture | vehicles | household | digital_premium | self_promotion | other",
  "is_absolutely_free": boolean,
  "seller_motivation_level": "desperate | high | neutral | commercial_dealer | self_promoter",
  "price_stated": "number or null",
  "currency": "string or null",
  "is_negotiable": boolean,
  "deal_score": 0-100,
  "analysis_breakdown": "A concise, objective analysis of the seller's urgency and pricing context."
}}

Scoring Logic (deal_score):
- If `is_buy_request` is true (the person wants to buy/acquire something), deal_score MUST be 0.
- If the item is self-promotion, a basic free app, a personal project, or an advertisement (`self_promoter` or `self_promotion`), deal_score MUST be 0 and `is_valuable_deal` MUST be false.
- If it is a premium digital service (normally paid) that is currently free or massively discounted, score it very high (80-100).
- If it is a physical item and is absolutely free, score it 100.
- If the seller motivation is desperate (e.g., leaving country tomorrow), give it a very high score (80-100) if a price is mentioned.
- If the seller motivation is commercial_dealer, score it 0.
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
            model="llama-3.3-70b-versatile",
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
    three_days_ago = time.time() - (3 * 24 * 3600)
    
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
                # Check Post Age (Must be less than 3 days old)
                if hasattr(entry, 'published_parsed'):
                    post_timestamp = calendar.timegm(entry.published_parsed)
                    if post_timestamp < three_days_ago:
                        continue # Skip posts older than 3 days
                
                post_id = entry.id
                title = entry.title
                selftext = entry.summary if hasattr(entry, 'summary') else ''
                post_url = entry.link
                process_item(post_id, title, selftext, post_url, f"r/{sub}", seen_posts)
                
            time.sleep(3) 
        except Exception as e:
            print(f"Error checking {sub}: {e}")
            time.sleep(3)

def main():
    print("Starting Deal Tracker Bot (Reddit Only)...")
    api_pull_memory()
    
    seen_posts = load_seen_posts()
    run_reddit_scraper(seen_posts)
    
    api_push_memory()
            
if __name__ == "__main__":
    main()
