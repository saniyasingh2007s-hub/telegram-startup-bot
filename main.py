import os
import asyncio
import threading
import datetime
import pytz
import json
from urllib.parse import urlencode, quote_plus
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from http.server import HTTPServer, BaseHTTPRequestHandler
from google import genai
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# -------------------------------------------------------------------
# 1. Health-Check HTTP Server
# -------------------------------------------------------------------
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Evidence-First Opportunity Scout is active!")

def run_health_server():
    port = int(os.getenv("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    server.serve_forever()

threading.Thread(target=run_health_server, daemon=True).start()

# -------------------------------------------------------------------
# 2. Environment Setup & Prompts (V1 through V7)
# -------------------------------------------------------------------
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
MY_TELEGRAM_CHAT_ID = os.getenv("MY_TELEGRAM_CHAT_ID")

if not TELEGRAM_BOT_TOKEN or not GEMINI_API_KEY:
    raise ValueError("Missing TELEGRAM_BOT_TOKEN or GEMINI_API_KEY environment variable.")

ai_client = genai.Client(api_key=GEMINI_API_KEY)

SYSTEM_PROMPT = """
You are an Evidence-First Startup Opportunity Scout & Founder Discovery Coach.
Your goal is to highlight unvalidated market problems, operational friction, and unaddressed customer pains without treating assumptions as facts.

Strictly categorize all statements into:
🟢 OBSERVED — Confirmed real-world behaviors or existing data.
🟡 HYPOTHESIS — Educated assumptions about pain, workflow loss, or willingness to pay that MIGHT be true.
🔴 UNKNOWN — Critical questions requiring customer discovery.

Return your response following this exact structured format:

🔎 OPPORTUNITY HYPOTHESIS

STATUS: 🔴 UNVALIDATED

### 1. Epistemic Breakdown
🟢 OBSERVED:
- State 1-2 factual, observable market dynamics or current tools in use.

🟡 HYPOTHESIS:
- State 2-3 key hypotheses about the specific friction, impact, or business cost.

🔴 UNKNOWN:
- State 3 critical unanswered questions that require customer discovery.

### 2. Target Profile & Workaround
• Target Persona: Specific role, job title, or business type.
• Current Workaround: How they attempt to cope today (or if they ignore it).

---

🎯 TODAY'S VALIDATION MISSION
Target: 5 specific individuals or businesses fitting the persona.
Objective: Do NOT pitch a solution. Ask non-leading questions to uncover truth.

Questions to Ask:
1. "How do you currently handle [specific workflow/task]?"
2. "What's the hardest part about that process?"
3. "When was the last time this caused a delay, financial loss, or major frustration?"
"""

VALIDATION_PROMPT = """
You are a Lean Customer Discovery Expert.
Opportunity Context:
{idea_context}

Current Status: {current_status}

Provide a concrete Discovery Plan:

🎯 CUSTOMER DISCOVERY ROADMAP

1. TARGET PROFILES & WHERE TO FIND THEM
Exact roles/titles and 3 specific platforms/directories/search queries to find 10 targets today.

2. NON-LEADING DISCOVERY QUESTIONS
3-4 neutral questions designed to extract raw truth without biasing the target toward a solution.

3. SIGNAL EVALUATION MATRIX
• Green Flag (Pain Exists): Specific quotes or behaviors proving real friction.
• Red Flag (Invalidation): Specific responses indicating this is a minor/non-issue.
"""

FIND_CUSTOMERS_PROMPT = """
You are a Lead Generation & Outreach Strategist.
Opportunity Context:
{idea_context}

Provide a customer search blueprint:

👥 FIND POTENTIAL CUSTOMERS

1. TARGET SEARCH QUERIES
Exact search strings to copy/paste into Google, LinkedIn, X, and Reddit.

2. COMMUNITIES & HANGOUTS
Specific subreddits, Slack/Discord groups, forums, or platforms where this target hangs out.

3. UNBIASED OUTREACH SCRIPT
A non-pitch, research-focused cold outreach message asking for 10 minutes of feedback on their workflow.
"""

OUTREACH_PROMPT = """
You are an evidence-first customer discovery outreach assistant.

Startup/problem we are validating:
{idea_context}

Candidate/post/profile:
{candidate}

Analyze ONLY what is actually present in the candidate text.
Do not invent facts.

Return:
🎯 RELEVANCE: HIGH / MEDIUM / LOW
🔎 EVIDENCE: 1-3 concrete reasons from the candidate text.
⚠️ UNKNOWN: What we still don't know.
💬 PUBLIC COMMENT: A short, natural research comment. Do not pitch a product.
📩 RESEARCH DM: A short message asking about their real experience. Do not claim we have a product.
❓ FOLLOW-UP: One non-leading question if they respond.
"""



CHALLENGE_PROMPT = """
You are a Devil's Advocate Startup Investor. Your goal is to ruthlessly attack the assumptions in this hypothesis so the founder doesn't waste time on a non-problem.

Opportunity Context:
{idea_context}

Attack this hypothesis across these 5 questions:

🥊 HYPOTHESIS CHALLENGE

❌ What if this problem is too rare or infrequent to matter?
❌ What if the current workaround is actually "good enough"?
❌ What if the target persona lacks spending authority or budget?
❌ Could this easily be rendered obsolete by a minor update to an existing platform?
❌ What is the simplest zero-code test to prove this hypothesis false in 24 hours?
"""

ANALYZE_FINDINGS_PROMPT = """
You are a Truth-Seeking Lean Startup Coach evaluating real customer discovery findings.

Original Opportunity Context:
{idea_context}

Current Validation Status: {current_status}

Founder's Discovery Findings / Interview Notes:
{user_findings}

Provide an Unbiased Analysis:

📊 DISCOVERY FINDINGS EVALUATION

1. EVIDENCE ANALYSIS
• Confirmed Hypotheses (What findings support real pain):
• Disproved Hypotheses (What assumptions were wrong):

2. TRUTH SIGNAL
Rate the signal: [NO SIGNAL / WEAK SIGNAL / STRONG SIGNAL / PAYMENT SIGNAL]
Explain why based strictly on the user's notes (no wishful thinking).

3. RECOMMENDED ACTION & STATUS UPDATE
• Recommended Status: [🔴 UNVALIDATED / 🟡 SIGNAL FOUND / 🟢 PROBLEM VALIDATED / 💰 PAYMENT SIGNAL / ❌ KILL]
• Next Steps: 2 concrete actions for the next discovery round or pivot.
"""

EXPERIMENT_PROMPT = """
You are a Lean Startup Experiment Designer.
Validated Opportunity:
{idea_context}

Discovery Evidence So Far:
{user_findings}

Design the absolute smallest concierge, manual, or zero-code experiment to test demand before building software:

🧪 LOW-FIDELITY DEMAND EXPERIMENT

1. The Concierge/Wizard-of-Oz Offer
How can the founder deliver this outcome manually (e.g., using spreadsheets, manual processing, or a Google Form) to test if the customer actually cares?

2. Success Metric
What exact commitment proves demand? (e.g., "3 out of 5 targets send us 20 real files to process", or "Target agrees to a 14-day paid pilot").

3. The 24-Hour Pitch / Landing Page Copy
A 3-sentence headline and value proposition to send directly to interviewees.
"""

MVP_PROMPT = """
You are a Technical Product Architect.
Opportunity Context: {idea_context}
Validation Status: {current_status}

Provide a lean MVP build plan:

🛠️ LEAN MVP BUILD BLUEPRINT

1. Core Problem Being Solved (Validated Scope)
The single validated pain point to automate or solve.

2. Fastest Tech Stack
Simplest stack (FastAPI, Supabase, Flutter/Next.js, LLM) to deliver core value in 48 hours.

3. 3-Day Build Sprint
• Day 1: Data Models & Core Trigger
• Day 2: Primary Value Delivery Mechanics
• Day 3: Output Interface & Pilot Access Link
"""

SALES_PROMPT = """
You are a B2B Sales & Customer Acquisition Strategist.
Opportunity Context:
{idea_context}

Validation & Experiment Results:
{user_findings}

Provide a closing strategy to secure your first paying customer:

💼 FIRST CUSTOMER ACQUISITION ROADMAP

1. Pre-Order / Paid Pilot Offer
How to structure a risk-free paid pilot (e.g., 50% discount for design partners, money-back guarantee).

2. Direct Outreach Email / Follow-up Script
A tailored follow-up template for the targets who confirmed pain during your discovery calls.

3. Handling Key Sales Objections
• "We don't have budget for this right now."
• "We need to check with IT / Security first."
• "Can we try it for free for 3 months?"
"""

# -------------------------------------------------------------------
# 3. Dynamic Gemini Generator
# -------------------------------------------------------------------
def generate_gemini_content(prompt: str, system_instruction: str) -> str:
    last_error = None
    try:
        available_models = []
        for m in ai_client.models.list():
            model_id = m.name.replace("models/", "")
            methods = getattr(m, "supported_generation_methods", []) or []
            if "generateContent" in methods or not methods:
                available_models.append(model_id)

        available_models.sort(key=lambda name: ("flash" not in name.lower(), name))
    except Exception as list_err:
        available_models = ["gemini-1.5-flash", "gemini-2.5-flash"]
        last_error = list_err

    for model in available_models:
        try:
            response = ai_client.models.generate_content(
                model=model,
                contents=prompt,
                config={"system_instruction": system_instruction, "temperature": 0.75}
            )
            if response and response.text:
                return response.text
        except Exception as e:
            last_error = e
            continue

    raise Exception(f"Gemini Engine Error: {str(last_error)}")

# -------------------------------------------------------------------
# 4. Telegram UI & Handlers
# -------------------------------------------------------------------
def _fetch_json(url: str, timeout: int = 12):
    """Fetch a public JSON endpoint without using Gemini Search Grounding."""
    req = Request(
        url,
        headers={
            "User-Agent": "SentinelFlow-ProspectScout/1.0 (public research bot)"
        },
    )
    with urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _clean_query(topic: str) -> str:
    """Turn a free-form hunt topic into a compact search query."""
    stop = {
        "sentinelflow", "find", "people", "prospects", "public", "web",
        "real", "actual", "problem", "startup", "project", "operators",
        "who", "that", "experience", "experiencing", "looking", "for",
        "the", "and", "or", "with", "from", "into", "this", "that",
    }
    words = []
    for raw in topic.replace("/", " ").replace(",", " ").split():
        w = raw.strip("'\"()[]{}:;.!?").lower()
        if len(w) > 2 and w not in stop and w not in words:
            words.append(w)
    return " ".join(words[:12])


def _search_reddit(query: str):
    params = urlencode({
        "q": query,
        "sort": "new",
        "t": "year",
        "limit": "12",
        "raw_json": "1",
    })
    url = f"https://www.reddit.com/search.json?{params}"
    data = _fetch_json(url)
    results = []
    for child in data.get("data", {}).get("children", []):
        d = child.get("data", {})
        if not d.get("title") and not d.get("selftext"):
            continue
        author = d.get("author") or "[deleted]"
        permalink = d.get("permalink")
        if permalink and not permalink.startswith("http"):
            permalink = "https://www.reddit.com" + permalink
        results.append({
            "person": f"u/{author}",
            "platform": "Reddit",
            "title": d.get("title", "Untitled"),
            "evidence": (d.get("selftext") or "").replace("\n", " ").strip()[:280],
            "url": permalink or d.get("url", ""),
            "contact": "COMMENT / DM" if author != "[deleted]" else "UNKNOWN",
            "score": d.get("score", 0),
            "created": d.get("created_utc", 0),
        })
    return results


def _search_hackernews(query: str):
    params = urlencode({
        "query": query,
        "tags": "(story,comment)",
        "hitsPerPage": "12",
    })
    url = f"https://hn.algolia.com/api/v1/search_by_date?{params}"
    data = _fetch_json(url)
    results = []
    for hit in data.get("hits", []):
        author = hit.get("author") or "[unknown]"
        object_id = hit.get("objectID", "")
        title = hit.get("title") or hit.get("story_title") or "Hacker News discussion"
        text = hit.get("comment_text") or hit.get("story_text") or ""
        text = " ".join(str(text).replace("<p>", " ").replace("</p>", " ").split())
        url = hit.get("url") or (f"https://news.ycombinator.com/item?id={object_id}" if object_id else "")
        results.append({
            "person": f"@{author}",
            "platform": "Hacker News",
            "title": title,
            "evidence": text[:280],
            "url": url,
            "contact": "PUBLIC PROFILE / COMMENT",
            "score": hit.get("points") or 0,
            "created": hit.get("created_at_i", 0),
        })
    return results


def _search_github(query: str):
    # GitHub's public search endpoint requires no token for small unauthenticated use.
    q = f"{query} in:title,body is:issue"
    params = urlencode({"q": q, "sort": "updated", "order": "desc", "per_page": "10"})
    url = f"https://api.github.com/search/issues?{params}"
    data = _fetch_json(url)
    results = []
    for item in data.get("items", []):
        user = (item.get("user") or {}).get("login") or "[unknown]"
        body = " ".join((item.get("body") or "").split())
        results.append({
            "person": f"@{user}",
            "platform": "GitHub Issues",
            "title": item.get("title", "GitHub issue"),
            "evidence": body[:280],
            "url": item.get("html_url", ""),
            "contact": "ISSUE COMMENT / PROFILE",
            "score": item.get("comments", 0),
            "created": 0,
        })
    return results


def hunt_public_web(topic: str) -> str:
    """Find public prospects directly from public community APIs.

    This deliberately does NOT call Gemini or Gemini Search Grounding.
    Gemini can be used later for qualification/outreach when API quota is available.
    """
    query = _clean_query(topic)
    if not query:
        query = "n8n automation silent workflow failure client"

    searches = [
        ("Reddit", _search_reddit),
        ("Hacker News", _search_hackernews),
        ("GitHub", _search_github),
    ]
    all_results = []
    source_errors = []

    for name, fn in searches:
        try:
            all_results.extend(fn(query))
        except Exception as e:
            source_errors.append(f"{name}: {str(e)[:160]}")

    # Prefer actual evidence-bearing discussions over empty profiles.
    all_results = [r for r in all_results if r.get("url") and (r.get("evidence") or r.get("title"))]
    all_results.sort(key=lambda r: (bool(r.get("evidence")), r.get("score", 0)), reverse=True)

    # Deduplicate by URL and keep a practical Telegram-sized batch.
    seen = set()
    unique = []
    for r in all_results:
        if r["url"] in seen:
            continue
        seen.add(r["url"])
        unique.append(r)
        if len(unique) >= 8:
            break

    if not unique:
        detail = "\n".join(f"• {e}" for e in source_errors) if source_errors else "No matching public discussions found."
        return (
            f"🔎 HUNT RESULTS\n\nNo prospects found for: {query}\n\n"
            f"Source status:\n{detail}\n\n"
            "Try a narrower query such as: n8n client automation silent failure"
        )

    lines = [
        "🔎 HUNT RESULTS — DIRECT PUBLIC SEARCH",
        "",
        f"Query: {query}",
        "Gemini Search Grounding: OFF",
        "",
    ]
    for i, r in enumerate(unique, 1):
        evidence = r.get("evidence") or "No text excerpt available; inspect the post."
        lines.extend([
            f"{i}. {r['person']} — {r['platform']}",
            f"POST: {r['title']}",
            f"EVIDENCE: {evidence}",
            f"URL: {r['url']}",
            f"CONTACT: {r['contact']}",
            "",
        ])

    lines.append("NEXT: Open the strongest 3 posts. Then use /outreach and paste the post text or URL for qualification.")
    if source_errors:
        lines.append("\nSource warnings: " + " | ".join(source_errors))
    return "\n".join(lines)

def get_keyboard(status="🔴 UNVALIDATED"):
    if status in ["🔴 UNVALIDATED", "🟡 SIGNAL FOUND"]:
        return InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🎯 Validate Opportunity", callback_data="btn_validate"),
                InlineKeyboardButton("👥 Find Customers", callback_data="btn_find_customers"),
            ],
            [
                InlineKeyboardButton("🔎 Hunt Prospects", callback_data="btn_hunt"),
                InlineKeyboardButton("💬 Outreach Assistant", callback_data="btn_outreach"),
            ],
            [
                InlineKeyboardButton("📥 Enter Discovery Findings", callback_data="btn_enter_findings"),
                InlineKeyboardButton("🥊 Challenge Idea", callback_data="btn_challenge"),
            ],
            [
                InlineKeyboardButton("🧪 Design Experiment (V5)", callback_data="btn_experiment"),
                InlineKeyboardButton("🔄 Next Opportunity", callback_data="btn_next_opp"),
            ]
        ])
    else:  # 🟢 PROBLEM VALIDATED, 💰 PAYMENT SIGNAL, or 🛠️ BUILD MVP
        return InlineKeyboardMarkup([
            [
                InlineKeyboardButton("📥 Enter Discovery Findings", callback_data="btn_enter_findings"),
                InlineKeyboardButton("🧪 Design Experiment (V5)", callback_data="btn_experiment"),
            ],
            [
                InlineKeyboardButton("🛠️ Plan MVP Sprint (V6)", callback_data="btn_build_mvp"),
                InlineKeyboardButton("💼 Sales & Conversion (V7)", callback_data="btn_sales"),
            ],
            [
                InlineKeyboardButton("🔄 Next Opportunity", callback_data="btn_next_opp"),
            ]
        ])

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    await update.message.reply_text(
        f"👋 Evidence-First Opportunity Scout Active!\n\n"
        f"• Type /pitch to receive today's unvalidated hypothesis.\n"
        f"• Chat ID: `{chat_id}`",
        parse_mode="Markdown"
    )

async def pitch_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    status_msg = await update.message.reply_text("🔎 Scouting market friction & building hypothesis...")
    try:
        pitch_text = await asyncio.to_thread(
            generate_gemini_content,
            prompt="Scout a fresh, unvalidated market opportunity, workflow friction, or customer problem.",
            system_instruction=SYSTEM_PROMPT
        )
        context.user_data['last_idea'] = pitch_text
        context.user_data['validation_status'] = "🔴 UNVALIDATED"
        await status_msg.delete()
        await update.message.reply_text(text=pitch_text, reply_markup=get_keyboard("🔴 UNVALIDATED"))
    except Exception as e:
        await status_msg.delete()
        await update.message.reply_text(f"❌ Error: {str(e)}")

async def scheduled_daily_pitch(context: ContextTypes.DEFAULT_TYPE):
    if not MY_TELEGRAM_CHAT_ID:
        return
    try:
        pitch_text = await asyncio.to_thread(
            generate_gemini_content,
            prompt="Scout a fresh, unvalidated market opportunity, workflow friction, or customer problem.",
            system_instruction=SYSTEM_PROMPT
        )
        await context.bot.send_message(
            chat_id=MY_TELEGRAM_CHAT_ID,
            text=f"☀️ **TODAY'S MARKET OPPORTUNITY HYPOTHESIS**\n\n{pitch_text}",
            reply_markup=get_keyboard("🔴 UNVALIDATED")
        )
    except Exception as e:
        print(f"Daily Scout Push Error: {e}")

async def outreach_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    last_idea = context.user_data.get('last_idea')
    if not last_idea:
        await update.message.reply_text(
            "🛑 No active opportunity yet.\n\nUse /pitch first, then open 🎯 Outreach Assistant."
        )
        return

    context.user_data['awaiting_candidate'] = True
    await update.message.reply_text(
        "🎯 **OUTREACH ASSISTANT**\n\n"
        "Paste a Reddit/X post, comment, profile text, or candidate description here.\n\n"
        "I'll tell you:\n"
        "• whether they're relevant\n"
        "• what evidence they gave\n"
        "• what to comment\n"
        "• what DM to send\n"
        "• the best follow-up question\n\n"
        "⚠️ I won't automatically send messages."
    )

async def outreach_analysis(update: Update, context: ContextTypes.DEFAULT_TYPE):
    candidate = update.message.text
    last_idea = context.user_data.get('last_idea', 'Market Opportunity Hypothesis')

    status_msg = await update.message.reply_text("🔎 Evaluating prospect...")
    try:
        prompt = OUTREACH_PROMPT.format(
            idea_context=last_idea,
            candidate=candidate
        )
        res = await asyncio.to_thread(
            generate_gemini_content,
            prompt=prompt,
            system_instruction="You are an evidence-first customer discovery and outreach assistant."
        )

        # Keep a lightweight local outreach log in Telegram user state.
        prospects = context.user_data.setdefault('outreach_prospects', [])
        prospects.append({
            "candidate": candidate,
            "analysis": res,
            "status": "prepared"
        })
        context.user_data['last_candidate'] = candidate
        context.user_data['awaiting_candidate'] = False

        await status_msg.delete()
        await update.message.reply_text(
            f"🎯 **PROSPECT ANALYSIS**\n\n{res}\n\n"
            f"📌 Saved as prospect #{len(prospects)} in this Telegram session."
        )
    except Exception as e:
        context.user_data['awaiting_candidate'] = False
        await status_msg.delete()
        await update.message.reply_text(f"❌ Error: {str(e)}")


async def hunt_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Find public prospects without Gemini Search Grounding."""
    topic = " ".join(context.args).strip()
    if not topic:
        topic = (
            "SentinelFlow n8n Make Zapier client automation silent failures "
            "missed leads broken workflows"
        )

    status_msg = await update.message.reply_text(
        "🔎 Hunting directly across public community sources...\n\n"
        "Gemini Search Grounding is OFF for this step."
    )

    try:
        result = await asyncio.to_thread(hunt_public_web, topic)
        await status_msg.delete()

        # Telegram messages have a practical 4096-character limit.
        chunks = [result[i:i + 3800] for i in range(0, len(result), 3800)]
        for chunk in chunks:
            await update.message.reply_text(chunk)
    except Exception as e:
        await status_msg.delete()
        await update.message.reply_text(f"❌ Hunt failed:\n{str(e)}")

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    
    try:
        await query.answer()
    except Exception:
        pass

    last_idea = context.user_data.get('last_idea', 'Market Opportunity Hypothesis')
    current_status = context.user_data.get('validation_status', '🔴 UNVALIDATED')

    if query.data == "btn_hunt":
        await query.message.reply_text(
            "🔎 **SENTINELFLOW PROSPECT HUNT**\n\n"
            "Use /hunt to search the public web for real automation operators discussing silent failures.\n\n"
            "Example:\n`/hunt n8n client workflow silent failure`"
        )

    elif query.data == "btn_outreach":
        if not last_idea:
            await query.message.reply_text("🛑 Generate an opportunity first with /pitch.")
            return
        context.user_data['awaiting_candidate'] = True
        await query.message.reply_text(
            "🎯 **OUTREACH ASSISTANT**\n\n"
            "Paste a Reddit/X post, comment, profile text, or candidate description.\n\n"
            "I'll qualify it and create:\n"
            "• a public comment\n"
            "• a private research DM\n"
            "• one follow-up question\n\n"
            "⚠️ You approve and send the message yourself."
        )

    elif query.data == "btn_validate":
        status_msg = await query.message.reply_text("🎯 Architecting Unbiased Customer Discovery Plan...")
        try:
            prompt = VALIDATION_PROMPT.format(idea_context=last_idea, current_status=current_status)
            res = await asyncio.to_thread(
                generate_gemini_content,
                prompt=prompt,
                system_instruction="You are a Customer Discovery Expert."
            )
            await status_msg.delete()
            await query.message.reply_text(text=res)
        except Exception as e:
            await status_msg.delete()
            await update.message.reply_text(f"❌ Error: {str(e)}")

    elif query.data == "btn_find_customers":
        status_msg = await query.message.reply_text("👥 Generating customer search strategy...")
        try:
            prompt = FIND_CUSTOMERS_PROMPT.format(idea_context=last_idea)
            res = await asyncio.to_thread(
                generate_gemini_content,
                prompt=prompt,
                system_instruction="You are a Lead Generation Specialist."
            )
            await status_msg.delete()
            await query.message.reply_text(text=res)
        except Exception as e:
            await status_msg.delete()
            await update.message.reply_text(f"❌ Error: {str(e)}")

    elif query.data == "btn_enter_findings":
        context.user_data['awaiting_findings'] = True
        await query.message.reply_text(
            "📥 **DISCOVERY FINDINGS INPUT**\n\n"
            "Reply directly to this message with your notes or quotes from talking to target customers.\n\n"
            "Include:\n"
            "1. How many people you talked to\n"
            "2. What they said about their current workflow\n"
            "3. Any pricing or willingness-to-pay quotes"
        )

    elif query.data == "btn_challenge":
        status_msg = await query.message.reply_text("🥊 Attacking hypothesis assumptions...")
        try:
            prompt = CHALLENGE_PROMPT.format(idea_context=last_idea)
            res = await asyncio.to_thread(
                generate_gemini_content,
                prompt=prompt,
                system_instruction="You are a Devil's Advocate Investor."
            )
            await status_msg.delete()
            await query.message.reply_text(text=res)
        except Exception as e:
            await status_msg.delete()
            await update.message.reply_text(f"❌ Error: {str(e)}")

    elif query.data == "btn_experiment":
        status_msg = await query.message.reply_text("🧪 Designing zero-code demand experiment...")
        try:
            user_findings = context.user_data.get('last_findings', 'No interview findings recorded yet.')
            prompt = EXPERIMENT_PROMPT.format(idea_context=last_idea, user_findings=user_findings)
            res = await asyncio.to_thread(
                generate_gemini_content,
                prompt=prompt,
                system_instruction="You are a Lean Startup Experiment Designer."
            )
            await status_msg.delete()
            await query.message.reply_text(text=res)
        except Exception as e:
            await status_msg.delete()
            await update.message.reply_text(f"❌ Error: {str(e)}")

    elif query.data == "btn_build_mvp":
        if current_status in ["🔴 UNVALIDATED", "🟡 SIGNAL FOUND"]:
            await query.message.reply_text(
                f"🛑 **BUILD LOCKED (Current Status: {current_status})**\n\n"
                "You have not collected enough evidence yet!\n"
                "Talk to at least 5 target customers and enter your findings to promote the status to **🟢 PROBLEM VALIDATED** or **💰 PAYMENT SIGNAL** before building."
            )
            return

        status_msg = await query.message.reply_text("⚙️ Compiling Lean MVP Blueprint for Validated Problem...")
        try:
            prompt = MVP_PROMPT.format(idea_context=last_idea, current_status=current_status)
            res = await asyncio.to_thread(
                generate_gemini_content,
                prompt=prompt,
                system_instruction="You are a Technical Product Architect."
            )
            await status_msg.delete()
            await query.message.reply_text(text=res)
        except Exception as e:
            await status_msg.delete()
            await update.message.reply_text(f"❌ Error: {str(e)}")

    elif query.data == "btn_sales":
        if current_status in ["🔴 UNVALIDATED", "🟡 SIGNAL FOUND"]:
            await query.message.reply_text(
                f"🛑 **SALES STRATEGY LOCKED (Current Status: {current_status})**\n\n"
                "Validate the problem and conduct an experiment before crafting sales offers!"
            )
            return

        status_msg = await query.message.reply_text("💼 Compiling customer acquisition & closing blueprint...")
        try:
            user_findings = context.user_data.get('last_findings', 'Customer validated problem and workflow pain.')
            prompt = SALES_PROMPT.format(idea_context=last_idea, user_findings=user_findings)
            res = await asyncio.to_thread(
                generate_gemini_content,
                prompt=prompt,
                system_instruction="You are a B2B Sales Strategist."
            )
            await status_msg.delete()
            await query.message.reply_text(text=res)
        except Exception as e:
            await status_msg.delete()
            await update.message.reply_text(f"❌ Error: {str(e)}")

    elif query.data == "btn_next_opp":
        status_msg = await query.message.reply_text("🔄 Scouting next unvalidated opportunity hypothesis...")
        try:
            pitch_text = await asyncio.to_thread(
                generate_gemini_content,
                prompt="Scout a fresh, unvalidated market opportunity, workflow friction, or customer problem.",
                system_instruction=SYSTEM_PROMPT
            )
            context.user_data['last_idea'] = pitch_text
            context.user_data['validation_status'] = "🔴 UNVALIDATED"
            await status_msg.delete()
            await query.message.reply_text(text=pitch_text, reply_markup=get_keyboard("🔴 UNVALIDATED"))
        except Exception as e:
            await status_msg.delete()
            await update.message.reply_text(f"❌ Error: {str(e)}")

async def reply_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get('awaiting_candidate'):
        await outreach_analysis(update, context)
        return

    if context.user_data.get('awaiting_findings'):
        context.user_data['awaiting_findings'] = False
        user_findings = update.message.text
        
        # Store user interview notes for V5 & V7 prompts
        context.user_data['last_findings'] = user_findings

        last_idea = context.user_data.get('last_idea', 'Market Opportunity Hypothesis')
        current_status = context.user_data.get('validation_status', '🔴 UNVALIDATED')

        status_msg = await update.message.reply_text("🧐 Analyzing discovery notes for objective truth signals...")
        try:
            prompt = ANALYZE_FINDINGS_PROMPT.format(
                idea_context=last_idea,
                current_status=current_status,
                user_findings=user_findings
            )
            evaluation = await asyncio.to_thread(
                generate_gemini_content,
                prompt=prompt,
                system_instruction="You are a Truth-Seeking Startup Evaluator."
            )
            
            # Auto-promote or update status based on key phrase presence
            new_status = current_status
            if "🟢 PROBLEM VALIDATED" in evaluation:
                new_status = "🟢 PROBLEM VALIDATED"
            elif "💰 PAYMENT SIGNAL" in evaluation:
                new_status = "💰 PAYMENT SIGNAL"
            elif "🟡 SIGNAL FOUND" in evaluation:
                new_status = "🟡 SIGNAL FOUND"
            elif "❌ KILL" in evaluation:
                new_status = "❌ KILLED"

            context.user_data['validation_status'] = new_status

            await status_msg.delete()
            await update.message.reply_text(
                f"📋 **EVALUATION & STATUS UPDATE**\n"
                f"**Updated Status:** {new_status}\n\n"
                f"{evaluation}",
                reply_markup=get_keyboard(new_status)
            )
        except Exception as e:
            await status_msg.delete()
            await update.message.reply_text(f"❌ Error: {str(e)}")

# -------------------------------------------------------------------
# 5. Application Startup
# -------------------------------------------------------------------
def main():
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("pitch", pitch_command))
    app.add_handler(CommandHandler("hunt", hunt_command))
    app.add_handler(CommandHandler("outreach", outreach_command))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, reply_handler))

    if MY_TELEGRAM_CHAT_ID:
        target_time = datetime.time(hour=8, minute=0, second=0, tzinfo=pytz.timezone("Asia/Kolkata"))
        app.job_queue.run_daily(scheduled_daily_pitch, time=target_time)

    print("🚀 Evidence-First Opportunity Scout running...")
    print("✅ Commands registered: /start /pitch /hunt /outreach")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
