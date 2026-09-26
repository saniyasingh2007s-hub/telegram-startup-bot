import os
import asyncio
import threading
import datetime
import pytz
import json
import re
from urllib.parse import urlencode
from urllib.request import Request, urlopen
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


# ================================================================
# 1. HEALTH CHECK
# ================================================================

class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"11Hunt Prospect Discovery is active!")

    def log_message(self, format, *args):
        return


def run_health_server():
    port = int(os.getenv("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    server.serve_forever()


threading.Thread(target=run_health_server, daemon=True).start()


# ================================================================
# 2. ENVIRONMENT
# ================================================================

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
MY_TELEGRAM_CHAT_ID = os.getenv("MY_TELEGRAM_CHAT_ID")

if not TELEGRAM_BOT_TOKEN or not GEMINI_API_KEY:
    raise ValueError(
        "Missing TELEGRAM_BOT_TOKEN or GEMINI_API_KEY environment variable."
    )

ai_client = genai.Client(api_key=GEMINI_API_KEY)


# ================================================================
# 3. 11HUNT SYSTEM PROMPT
# ================================================================

SYSTEM_PROMPT = """
You are 11Hunt, an evidence-first opportunity discovery assistant.

Your purpose is to help beginners, students and freelancers discover
real business/client-acquisition problems they may be able to solve.

Never present assumptions as facts.

Strictly separate:

🟢 OBSERVED
Directly supported by the provided evidence.

🟡 HYPOTHESIS
A reasonable interpretation that still needs validation.

🔴 UNKNOWN
Something we do not know yet.

A missing feature or generic complaint is NOT automatically a real problem.

Always prioritize evidence over speculation.
"""


VALIDATION_PROMPT = """
You are a Lean Customer Discovery Expert.

Opportunity Context:
{idea_context}

Current Status:
{current_status}

Provide:

🎯 CUSTOMER DISCOVERY ROADMAP

1. TARGET PROFILES & WHERE TO FIND THEM
Exact roles/titles and 3 specific platforms/directories/search queries.

2. NON-LEADING DISCOVERY QUESTIONS
3-4 neutral questions.

3. SIGNAL EVALUATION
Green flags proving real pain.
Red flags showing the problem may be weak or irrelevant.
"""


FIND_CUSTOMERS_PROMPT = """
You are a Lead Generation & Customer Discovery Strategist.

Opportunity Context:
{idea_context}

Provide:

👥 FIND POTENTIAL CUSTOMERS

1. Exact search queries
2. Communities/platforms
3. Unbiased research outreach message

Do not invent customer problems.
"""


OUTREACH_PROMPT = """
You are an evidence-first customer discovery outreach assistant.

Startup/problem being investigated:
{idea_context}

Candidate/post/profile:
{candidate}

Analyze ONLY what is actually present.

Do not invent facts.
Do not assume the candidate has a problem unless their text supports it.

Return:

🎯 RELEVANCE: HIGH / MEDIUM / LOW

🟢 OBSERVED EVIDENCE:
Concrete facts from the candidate text.

🟡 HYPOTHESES:
Possible problems that still need validation.

🔴 UNKNOWN:
What we do not know.

💬 PUBLIC COMMENT:
Short natural research-oriented comment.
Do not pitch a product.

📩 RESEARCH DM:
Short human message asking about their actual experience.
Do not pretend we already know their problem.

❓ FOLLOW-UP:
One non-leading question.
"""


CHALLENGE_PROMPT = """
You are a Devil's Advocate Startup Investor.

Opportunity Context:
{idea_context}

Attack the hypothesis:

1. What if the problem is too rare?
2. What if the current workaround is good enough?
3. Does the target actually have budget?
4. Could an existing platform already solve this?
5. What zero-code experiment could disprove the hypothesis in 24 hours?
"""


ANALYZE_FINDINGS_PROMPT = """
You are a truth-seeking customer discovery evaluator.

Original Opportunity:
{idea_context}

Current Status:
{current_status}

Discovery Findings:
{user_findings}

Return:

📊 DISCOVERY FINDINGS EVALUATION

1. EVIDENCE ANALYSIS
• Confirmed hypotheses
• Disproved hypotheses

2. TRUTH SIGNAL
[NO SIGNAL / WEAK SIGNAL / STRONG SIGNAL / PAYMENT SIGNAL]

3. RECOMMENDED STATUS
[🔴 UNVALIDATED / 🟡 SIGNAL FOUND / 🟢 PROBLEM VALIDATED / 💰 PAYMENT SIGNAL / ❌ KILL]

4. NEXT STEPS
Two concrete actions.
"""


EXPERIMENT_PROMPT = """
You are a Lean Startup Experiment Designer.

Opportunity:
{idea_context}

Discovery Evidence:
{user_findings}

Design the smallest manual or zero-code experiment.

Include:

🧪 LOW-FIDELITY DEMAND EXPERIMENT

1. Concierge/manual offer
2. Exact success metric
3. 24-hour test/pitch
"""


MVP_PROMPT = """
You are a Technical Product Architect.

Opportunity:
{idea_context}

Validation Status:
{current_status}

Create:

🛠️ LEAN MVP BUILD BLUEPRINT

1. Validated problem
2. Simplest technology stack
3. Three-day build sprint
"""


SALES_PROMPT = """
You are a B2B Sales Strategist.

Opportunity:
{idea_context}

Evidence:
{user_findings}

Create:

💼 FIRST CUSTOMER ACQUISITION ROADMAP

1. Paid pilot
2. Follow-up message
3. Key objection handling
"""


# ================================================================
# 4. GEMINI
# ================================================================

GEMINI_MODELS = [
    "gemini-2.5-flash",
    "gemini-2.0-flash",
    "gemini-1.5-flash",
]


def generate_gemini_content(prompt: str, system_instruction: str) -> str:
    last_error = None

    for model in GEMINI_MODELS:
        try:
            response = ai_client.models.generate_content(
                model=model,
                contents=prompt,
                config={
                    "system_instruction": system_instruction,
                    "temperature": 0.5,
                },
            )

            if response and response.text:
                return response.text

        except Exception as error:
            last_error = error

    raise Exception(f"Gemini Engine Error: {str(last_error)}")


# ================================================================
# 5. PUBLIC WEB HELPERS
# ================================================================

def _fetch_json(url: str, timeout: int = 8):
    req = Request(
        url,
        headers={
            "User-Agent": "11Hunt-ProspectDiscovery/1.0"
        },
    )

    with urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


# ================================================================
# 6. REDDIT
# ================================================================

def _search_reddit(query: str):
    params = urlencode({
        "q": query,
        "sort": "new",
        "t": "year",
        "limit": "20",
        "raw_json": "1",
    })

    url = f"https://www.reddit.com/search.json?{params}"

    try:
        data = _fetch_json(url)

    except Exception as e:
        raise Exception(f"Reddit unavailable: {str(e)}")

    results = []

    for child in data.get("data", {}).get("children", []):
        d = child.get("data", {})

        title = d.get("title") or ""
        body = d.get("selftext") or ""

        if not title and not body:
            continue

        author = d.get("author") or "[deleted]"

        permalink = d.get("permalink")

        if permalink and not permalink.startswith("http"):
            permalink = "https://www.reddit.com" + permalink

        results.append({
            "person": f"u/{author}",
            "platform": "Reddit",
            "title": title,
            "evidence": " ".join(body.split())[:700],
            "url": permalink or d.get("url", ""),
            "contact": "COMMENT / DM",
            "score": d.get("score", 0),
        })

    return results


# ================================================================
# 7. HACKER NEWS
# ================================================================

def _search_hackernews(query: str):

    params = urlencode({
        "query": query,
        "tags": "(story,comment)",
        "hitsPerPage": "20",
    })

    url = f"https://hn.algolia.com/api/v1/search_by_date?{params}"

    data = _fetch_json(url)

    results = []

    for hit in data.get("hits", []):

        author = hit.get("author") or "[unknown]"
        object_id = hit.get("objectID", "")

        title = (
            hit.get("title")
            or hit.get("story_title")
            or "Hacker News discussion"
        )

        text = (
            hit.get("comment_text")
            or hit.get("story_text")
            or ""
        )

        text = re.sub("<[^>]+>", " ", text)
        text = " ".join(text.split())

        item_url = hit.get("url")

        if not item_url and object_id:
            item_url = (
                f"https://news.ycombinator.com/item?id={object_id}"
            )

        results.append({
            "person": f"@{author}",
            "platform": "Hacker News",
            "title": title,
            "evidence": text[:700],
            "url": item_url or "",
            "contact": "PUBLIC PROFILE / COMMENT",
            "score": hit.get("points") or 0,
        })

    return results


# ================================================================
# 8. GITHUB
# ================================================================

def _search_github(query: str):

    github_query = f"{query} in:title,body is:issue"

    params = urlencode({
        "q": github_query,
        "sort": "updated",
        "order": "desc",
        "per_page": "15",
    })

    url = f"https://api.github.com/search/issues?{params}"

    data = _fetch_json(url)

    results = []

    for item in data.get("items", []):

        user = (
            (item.get("user") or {}).get("login")
            or "[unknown]"
        )

        body = " ".join(
            (item.get("body") or "").split()
        )

        results.append({
            "person": f"@{user}",
            "platform": "GitHub",
            "title": item.get("title", "GitHub issue"),
            "evidence": body[:700],
            "url": item.get("html_url", ""),
            "contact": "ISSUE / PROFILE",
            "score": item.get("comments", 0),
        })

    return results


# ================================================================
# 9. STRICT 11HUNT SIGNAL DETECTION
# ================================================================

DIRECT_SIGNALS = [

    "first client",
    "first customer",
    "get my first client",
    "get my first customer",
    "finding my first client",
    "finding clients",
    "find clients",
    "find freelance clients",
    "get clients",
    "getting clients",
    "getting freelance clients",
    "how to get clients",
    "how do i get clients",
    "how do i find clients",
    "struggling to get clients",
    "struggling to find clients",
    "struggling with client acquisition",
    "can't get clients",
    "cant get clients",
    "cannot get clients",
    "no clients",
    "zero clients",
    "no freelance clients",
    "not getting clients",
    "clients aren't responding",
    "clients are not responding",
    "clients don't respond",
    "clients do not respond",
    "no one responds",
    "no response from clients",
    "sent proposals",
    "sent proposals and",
    "cold outreach",
    "cold dm",
    "cold dms",
    "freelance outreach",
    "proposal response",
    "proposal responses",
    "upwork proposals",
    "fiverr clients",
    "how to land clients",
    "landing clients",
    "land my first client",
    "close my first client",
    "freelancing with no clients",
]


BEGINNER_SIGNALS = [

    "beginner",
    "new freelancer",
    "new to freelancing",
    "starting freelancing",
    "started freelancing",
    "first freelance",
    "first client",
    "first customer",
    "new freelancer",
    "student",
    "college student",
    "recent graduate",
    "junior",
    "entry level",
    "entry-level",
    "no experience",
    "little experience",
    "early career",
]


AI_SIGNALS = [

    "ai freelancer",
    "ai automation",
    "ai agent",
    "ai agents",
    "ai development",
    "ai developer",
    "automation freelancer",
    "automation agency",
    "llm",
    "openai",
    "chatgpt",
    "claude",
    "gemini",
    "n8n",
    "make.com",
    "zapier",
    "ai engineer",
    "ai engineer freelancer",
]


JOB_ONLY_SIGNALS = [

    "first software job",
    "first engineering job",
    "software engineer job",
    "software job",
    "looking for a job",
    "looking for jobs",
    "looking for employment",
    "job search",
    "job hunting",
    "get hired",
    "getting hired",
    "hiring manager",
    "resume",
    "cv",
    "interview preparation",
    "interviews",
    "leetcode",
    "coding interview",
]


def contains_any(text, phrases):
    return any(
        phrase in text
        for phrase in phrases
    )


def classify_candidate(result):

    title = result.get("title", "")
    evidence = result.get("evidence", "")

    text = f"{title} {evidence}".lower()

    direct_hits = [
        phrase
        for phrase in DIRECT_SIGNALS
        if phrase in text
    ]

    beginner_hits = [
        phrase
        for phrase in BEGINNER_SIGNALS
        if phrase in text
    ]

    ai_hits = [
        phrase
        for phrase in AI_SIGNALS
        if phrase in text
    ]

    job_only_hits = [
        phrase
        for phrase in JOB_ONLY_SIGNALS
        if phrase in text
    ]

    # ------------------------------------------------------------
    # HARD REJECTION
    # ------------------------------------------------------------

    # If the post is primarily about finding a software/job role
    # and has no direct client-acquisition signal, reject it.

    if job_only_hits and not direct_hits:
        return None

    # Generic freelancer without acquisition evidence = reject.

    if not direct_hits:
        return None

    # ------------------------------------------------------------
    # SCORE
    # ------------------------------------------------------------

    score = 40

    score += min(len(direct_hits) * 12, 36)

    if beginner_hits:
        score += min(len(beginner_hits) * 5, 15)

    if ai_hits:
        score += min(len(ai_hits) * 5, 15)

    # Explicit AI + client acquisition = strongest combination.

    if direct_hits and ai_hits:
        score += 10

    # ------------------------------------------------------------
    # SIGNAL TYPE
    # ------------------------------------------------------------

    if len(direct_hits) >= 2 and (beginner_hits or ai_hits):
        signal_type = "🟢 DIRECT"

    elif len(direct_hits) >= 1:
        signal_type = "🟡 DIRECT"

    else:
        signal_type = "🟡 INDIRECT"

    if score >= 90:
        signal = "🔥 HIGH"
    elif score >= 65:
        signal = "🟡 MEDIUM"
    else:
        signal = "🟡 LOW"

    result["signal"] = signal
    result["signal_type"] = signal_type
    result["signal_score"] = min(score, 100)

    result["why_matched"] = []

    if direct_hits:
        result["why_matched"].append(
            "Explicit client-acquisition language"
        )

    if beginner_hits:
        result["why_matched"].append(
            "Beginner/early-stage signal"
        )

    if ai_hits:
        result["why_matched"].append(
            "AI/automation-related skill or work"
        )

    return result


# ================================================================
# 10. DEDUPLICATION
# ================================================================

def deduplicate_candidates(candidates):

    people = {}

    for candidate in candidates:

        person = candidate.get("person", "").lower().strip()

        if not person:
            continue

        key = (
            candidate.get("platform", ""),
            person
        )

        if key not in people:
            people[key] = candidate

        else:
            existing = people[key]

            # Keep the strongest evidence.

            if (
                candidate.get("signal_score", 0)
                >
                existing.get("signal_score", 0)
            ):
                people[key] = candidate

    return list(people.values())


# ================================================================
# 11. SEARCH BLUEPRINT
# ================================================================

def hunt_public_web(topic: str) -> str:
    """
    Evidence-first public prospect discovery.

    No automatic DMs/comments.
    No Gemini Search Grounding.
    Uses targeted public searches and runs them concurrently so /hunt
    does not sit waiting on one blocked source.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    topic = " ".join((topic or "").split())

    queries = [
        '"first client" freelancer',
        '"how to get clients" freelancer',
        '"struggling to get clients" freelancer',
        '"finding clients" freelancer',
        '"freelance outreach" clients',
        '"cold outreach" freelancer',
        '"AI freelancer" clients',
        '"AI freelancer" "first client"',
        '"AI automation" "first client"',
        '"no clients" freelancer',
        '"first customer" freelancer',
        '"client acquisition" freelancer',
    ]

    if topic and topic.lower() not in {
        "beginner ai freelancers struggling to get first clients",
        "beginner ai freelancers struggling to get their first clients",
    }:
        queries.append(f'"{topic}" freelancer clients')

    queries = list(dict.fromkeys(queries))

    searches = [
        ("Reddit", _search_reddit),
        ("Hacker News", _search_hackernews),
        ("GitHub", _search_github),
    ]

    jobs = [
        (source_name, search_function, query)
        for query in queries
        for source_name, search_function in searches
    ]

    all_results = []
    source_errors = []

    def run_search(job):
        source_name, search_function, query = job
        try:
            return source_name, query, search_function(query), None
        except Exception as error:
            return source_name, query, [], str(error)[:180]

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(run_search, job) for job in jobs]

        for future in as_completed(futures):
            source_name, query, results, error = future.result()

            if error:
                warning = f"{source_name}: {error}"
                if warning not in source_errors:
                    source_errors.append(warning)
            else:
                all_results.extend(results)

    classified = []
    seen_urls = set()

    for result in all_results:
        url = (result.get("url") or "").strip()

        if not url or url in seen_urls:
            continue

        seen_urls.add(url)

        candidate = classify_candidate(result)

        if candidate:
            classified.append(candidate)

    classified = deduplicate_candidates(classified)

    classified.sort(
        key=lambda item: (
            item.get("signal_score", 0),
            item.get("score", 0),
        ),
        reverse=True,
    )

    candidates = classified[:10]

    if not candidates:
        warning_text = (
            "\n".join(f"• {warning}" for warning in source_errors)
            if source_errors
            else "No source errors reported."
        )

        return (
            "🎯 11HUNT PROSPECT DISCOVERY\n\n"
            "Mode: Evidence-first public discovery\n\n"
            "Automatic DMs: OFF\n"
            "Automatic comments: OFF\n\n"
            "TARGET:\n"
            "Beginner AI freelancers struggling to get their first clients\n\n"
            "────────────────────\n\n"
            "No direct client-acquisition signals were found.\n\n"
            "This does NOT mean there are no prospects.\n"
            "It means the current public search did not find enough "
            "explicit evidence.\n\n"
            "Try:\n\n"
            "/hunt first client freelancer\n"
            "/hunt AI freelancer clients\n"
            "/hunt freelancer outreach\n"
            "/hunt struggling to get clients\n\n"
            "SOURCE WARNINGS:\n"
            f"{warning_text}"
        )

    lines = [
        "🎯 11HUNT PROSPECT DISCOVERY",
        "",
        "Mode: Evidence-first public discovery",
        "",
        "Automatic DMs: OFF",
        "",
        "Automatic comments: OFF",
        "",
        "TARGET:",
        "Beginner AI freelancers struggling to get their first clients",
        "",
        "────────────────────",
        "",
        "Found candidates with explicit client-acquisition signals.",
        "",
    ]

    for index, candidate in enumerate(candidates, 1):
        evidence = candidate.get("evidence") or "No excerpt available."
        why = candidate.get("why_matched", [])

        lines.extend([
            f"{index}. {candidate['signal']} {candidate['signal_type']} — "
            f"{candidate['person']} ({candidate['platform']})",
            f"POST: {candidate['title']}",
            "",
            "EVIDENCE:",
            evidence,
            "",
            "WHY IT MATCHED:",
        ])

        for reason in why:
            lines.append(f"• {reason}")

        lines.extend([
            "",
            f"URL: {candidate['url']}",
            f"CONTACT: {candidate['contact']}",
            f"SIGNAL SCORE: {candidate['signal_score']}",
            "",
            "────────────────────",
            "",
        ])

    lines.extend([
        "NEXT STEP:",
        "",
        "Open the strongest 3 candidates.",
        "",
        "Read their full post/profile.",
        "",
        "Then use:",
        "",
        "/outreach",
        "",
        "Paste the actual post/profile text.",
        "",
        "11Hunt will analyze:",
        "",
        "• relevance",
        "• observed evidence",
        "• hypotheses",
        "• unknowns",
        "• research comment",
        "• research DM",
        "• follow-up question",
        "",
        "You approve and send everything yourself.",
        "",
        "No automatic messages are sent.",
    ])

    if source_errors:
        lines.extend(["", "SOURCE WARNINGS:", ""])
        for warning in source_errors:
            lines.append(f"• {warning}")

    return "\n".join(lines)


# ================================================================
# 12. TELEGRAM KEYBOARD
# ================================================================

def get_keyboard(status="🔴 UNVALIDATED"):

    if status in [
        "🔴 UNVALIDATED",
        "🟡 SIGNAL FOUND"
    ]:

        return InlineKeyboardMarkup([

            [
                InlineKeyboardButton(
                    "🎯 Validate Opportunity",
                    callback_data="btn_validate"
                ),

                InlineKeyboardButton(
                    "👥 Find Customers",
                    callback_data="btn_find_customers"
                ),
            ],

            [
                InlineKeyboardButton(
                    "🔎 Hunt Prospects",
                    callback_data="btn_hunt"
                ),

                InlineKeyboardButton(
                    "💬 Outreach Assistant",
                    callback_data="btn_outreach"
                ),
            ],

            [
                InlineKeyboardButton(
                    "📥 Enter Discovery Findings",
                    callback_data="btn_enter_findings"
                ),

                InlineKeyboardButton(
                    "🥊 Challenge Idea",
                    callback_data="btn_challenge"
                ),
            ],

            [
                InlineKeyboardButton(
                    "🧪 Design Experiment",
                    callback_data="btn_experiment"
                ),

                InlineKeyboardButton(
                    "🔄 Next Opportunity",
                    callback_data="btn_next_opp"
                ),
            ],
        ])

    return InlineKeyboardMarkup([

        [
            InlineKeyboardButton(
                "📥 Enter Discovery Findings",
                callback_data="btn_enter_findings"
            ),

            InlineKeyboardButton(
                "🧪 Design Experiment",
                callback_data="btn_experiment"
            ),
        ],

        [
            InlineKeyboardButton(
                "🛠️ Plan MVP Sprint",
                callback_data="btn_build_mvp"
            ),

            InlineKeyboardButton(
                "💼 Sales & Conversion",
                callback_data="btn_sales"
            ),
        ],

        [
            InlineKeyboardButton(
                "🔄 Next Opportunity",
                callback_data="btn_next_opp"
            ),
        ],
    ])


# ================================================================
# 13. START
# ================================================================

async def start_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    chat_id = update.effective_chat.id

    await update.message.reply_text(

        "👋 11Hunt Prospect Discovery Active!\n\n"

        "🎯 Target:\n"
        "Beginner AI freelancers struggling to get their first clients.\n\n"

        "Commands:\n"
        "/hunt — find public prospects\n"
        "/outreach — analyze a prospect\n"
        "/pitch — generate opportunity\n\n"

        f"Chat ID: `{chat_id}`",

        parse_mode="Markdown"
    )


# ================================================================
# 14. PITCH
# ================================================================

async def pitch_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    status_msg = await update.message.reply_text(
        "🔎 Scouting market friction..."
    )

    try:

        pitch_text = await asyncio.to_thread(
            generate_gemini_content,
            prompt=(
                "Scout a fresh, unvalidated market opportunity, "
                "workflow friction, or customer problem."
            ),
            system_instruction=SYSTEM_PROMPT,
        )

        context.user_data["last_idea"] = pitch_text
        context.user_data["validation_status"] = "🔴 UNVALIDATED"

        await status_msg.delete()

        await update.message.reply_text(
            pitch_text,
            reply_markup=get_keyboard("🔴 UNVALIDATED"),
        )

    except Exception as error:

        await status_msg.delete()

        await update.message.reply_text(
            f"❌ Error: {str(error)}"
        )


# ================================================================
# 15. OUTREACH COMMAND
# ================================================================

async def outreach_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    last_idea = context.user_data.get("last_idea")

    if not last_idea:

        last_idea = (
            "Beginner AI freelancers struggling "
            "to acquire their first clients."
        )

        context.user_data["last_idea"] = last_idea

    context.user_data["awaiting_candidate"] = True

    await update.message.reply_text(

        "🎯 OUTREACH ASSISTANT\n\n"

        "Paste the actual Reddit/Hacker News/X post, "
        "profile text, or candidate description.\n\n"

        "I'll analyze:\n"

        "• relevance\n"
        "• observed evidence\n"
        "• hypotheses\n"
        "• unknowns\n"
        "• research comment\n"
        "• research DM\n"
        "• follow-up question\n\n"

        "⚠️ I will NOT automatically send anything."
    )


# ================================================================
# 16. OUTREACH ANALYSIS
# ================================================================

async def outreach_analysis(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    candidate = update.message.text

    last_idea = context.user_data.get(
        "last_idea",
        "Beginner AI freelancers struggling to acquire clients."
    )

    status_msg = await update.message.reply_text(
        "🔎 Evaluating prospect evidence..."
    )

    try:

        prompt = OUTREACH_PROMPT.format(
            idea_context=last_idea,
            candidate=candidate,
        )

        result = await asyncio.to_thread(
            generate_gemini_content,
            prompt=prompt,
            system_instruction=SYSTEM_PROMPT,
        )

        prospects = context.user_data.setdefault(
            "outreach_prospects",
            []
        )

        prospects.append({
            "candidate": candidate,
            "analysis": result,
            "status": "prepared",
        })

        context.user_data["last_candidate"] = candidate
        context.user_data["awaiting_candidate"] = False

        await status_msg.delete()

        await update.message.reply_text(
            "🎯 PROSPECT ANALYSIS\n\n"
            f"{result}\n\n"
            f"📌 Saved as prospect #{len(prospects)} "
            "in this Telegram session."
        )

    except Exception as error:

        context.user_data["awaiting_candidate"] = False

        await status_msg.delete()

        await update.message.reply_text(
            f"❌ Error: {str(error)}"
        )


# ================================================================
# 17. HUNT COMMAND
# ================================================================

async def hunt_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    topic = " ".join(context.args).strip()

    if not topic:

        topic = (
            "beginner AI freelancers "
            "struggling to get first clients"
        )

    status_msg = await update.message.reply_text(

        "🔎 11Hunt is searching public sources...\n\n"

        "Target:\n"
        "Beginner AI freelancers struggling "
        "to get their first clients.\n\n"

        "Filtering for explicit client-acquisition evidence.\n"
        "Automatic DMs/comments: OFF."
    )

    try:

        result = await asyncio.to_thread(
            hunt_public_web,
            topic
        )

        await status_msg.delete()

        # Telegram max message size is around 4096 chars.
        chunks = [
            result[i:i + 3800]
            for i in range(
                0,
                len(result),
                3800
            )
        ]

        for chunk in chunks:

            await update.message.reply_text(
                chunk
            )

    except Exception as error:

        await status_msg.delete()

        await update.message.reply_text(
            f"❌ Hunt failed:\n{str(error)}"
        )


# ================================================================
# 18. BUTTON HANDLER
# ================================================================

async def button_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.callback_query

    try:
        await query.answer()
    except Exception:
        pass

    last_idea = context.user_data.get(
        "last_idea",
        "Beginner AI freelancers struggling to get clients."
    )

    current_status = context.user_data.get(
        "validation_status",
        "🔴 UNVALIDATED"
    )

    # ------------------------------------------------------------
    # HUNT
    # ------------------------------------------------------------

    if query.data == "btn_hunt":

        await query.message.reply_text(

            "🔎 11HUNT PROSPECT DISCOVERY\n\n"

            "Target:\n"
            "Beginner AI freelancers struggling "
            "to get their first clients.\n\n"

            "Use:\n"
            "`/hunt`\n\n"

            "Or:\n"
            "`/hunt AI freelancer first client`\n\n"

            "Automatic DMs/comments: OFF.",

            parse_mode="Markdown"
        )

    # ------------------------------------------------------------
    # OUTREACH
    # ------------------------------------------------------------

    elif query.data == "btn_outreach":

        context.user_data["awaiting_candidate"] = True

        await query.message.reply_text(

            "🎯 OUTREACH ASSISTANT\n\n"

            "Paste the actual candidate post/profile.\n\n"

            "I'll analyze:\n"
            "• relevance\n"
            "• evidence\n"
            "• hypotheses\n"
            "• unknowns\n"
            "• research comment\n"
            "• research DM\n"
            "• follow-up question\n\n"

            "⚠️ You approve and send everything yourself."
        )

    # ------------------------------------------------------------
    # VALIDATE
    # ------------------------------------------------------------

    elif query.data == "btn_validate":

        status_msg = await query.message.reply_text(
            "🎯 Building customer discovery plan..."
        )

        try:

            prompt = VALIDATION_PROMPT.format(
                idea_context=last_idea,
                current_status=current_status,
            )

            result = await asyncio.to_thread(
                generate_gemini_content,
                prompt=prompt,
                system_instruction=SYSTEM_PROMPT,
            )

            await status_msg.delete()

            await query.message.reply_text(
                result
            )

        except Exception as error:

            await status_msg.delete()

            await query.message.reply_text(
                f"❌ Error: {str(error)}"
            )

    # ------------------------------------------------------------
    # FIND CUSTOMERS
    # ------------------------------------------------------------

    elif query.data == "btn_find_customers":

        status_msg = await query.message.reply_text(
            "👥 Building customer search strategy..."
        )

        try:

            prompt = FIND_CUSTOMERS_PROMPT.format(
                idea_context=last_idea
            )

            result = await asyncio.to_thread(
                generate_gemini_content,
                prompt=prompt,
                system_instruction=SYSTEM_PROMPT,
            )

            await status_msg.delete()

            await query.message.reply_text(
                result
            )

        except Exception as error:

            await status_msg.delete()

            await query.message.reply_text(
                f"❌ Error: {str(error)}"
            )

    # ------------------------------------------------------------
    # ENTER FINDINGS
    # ------------------------------------------------------------

    elif query.data == "btn_enter_findings":

        context.user_data["awaiting_findings"] = True

        await query.message.reply_text(

            "📥 DISCOVERY FINDINGS INPUT\n\n"

            "Send your interview/customer notes.\n\n"

            "Include:\n"
            "1. Number of people contacted\n"
            "2. What they said\n"
            "3. Their current workaround\n"
            "4. Any pricing/willingness-to-pay signal"
        )

    # ------------------------------------------------------------
    # CHALLENGE
    # ------------------------------------------------------------

    elif query.data == "btn_challenge":

        status_msg = await query.message.reply_text(
            "🥊 Challenging the hypothesis..."
        )

        try:

            prompt = CHALLENGE_PROMPT.format(
                idea_context=last_idea
            )

            result = await asyncio.to_thread(
                generate_gemini_content,
                prompt=prompt,
                system_instruction=SYSTEM_PROMPT,
            )

            await status_msg.delete()

            await query.message.reply_text(
                result
            )

        except Exception as error:

            await status_msg.delete()

            await query.message.reply_text(
                f"❌ Error: {str(error)}"
            )

    # ------------------------------------------------------------
    # EXPERIMENT
    # ------------------------------------------------------------

    elif query.data == "btn_experiment":

        status_msg = await query.message.reply_text(
            "🧪 Designing demand experiment..."
        )

        try:

            findings = context.user_data.get(
                "last_findings",
                "No interview findings recorded yet."
            )

            prompt = EXPERIMENT_PROMPT.format(
                idea_context=last_idea,
                user_findings=findings,
            )

            result = await asyncio.to_thread(
                generate_gemini_content,
                prompt=prompt,
                system_instruction=SYSTEM_PROMPT,
            )

            await status_msg.delete()

            await query.message.reply_text(
                result
            )

        except Exception as error:

            await status_msg.delete()

            await query.message.reply_text(
                f"❌ Error: {str(error)}"
            )

    # ------------------------------------------------------------
    # BUILD MVP
    # ------------------------------------------------------------

    elif query.data == "btn_build_mvp":

        if current_status in [
            "🔴 UNVALIDATED",
            "🟡 SIGNAL FOUND",
        ]:

            await query.message.reply_text(

                f"🛑 BUILD LOCKED\n\n"
                f"Current status: {current_status}\n\n"
                "Collect customer evidence before building."
            )

            return

        status_msg = await query.message.reply_text(
            "⚙️ Building lean MVP blueprint..."
        )

        try:

            prompt = MVP_PROMPT.format(
                idea_context=last_idea,
                current_status=current_status,
            )

            result = await asyncio.to_thread(
                generate_gemini_content,
                prompt=prompt,
                system_instruction=SYSTEM_PROMPT,
            )

            await status_msg.delete()

            await query.message.reply_text(
                result
            )

        except Exception as error:

            await status_msg.delete()

            await query.message.reply_text(
                f"❌ Error: {str(error)}"
            )

    # ------------------------------------------------------------
    # SALES
    # ------------------------------------------------------------

    elif query.data == "btn_sales":

        if current_status in [
            "🔴 UNVALIDATED",
            "🟡 SIGNAL FOUND",
        ]:

            await query.message.reply_text(
                "🛑 SALES LOCKED\n\n"
                "Validate the problem first."
            )

            return

        status_msg = await query.message.reply_text(
            "💼 Building first-customer acquisition strategy..."
        )

        try:

            findings = context.user_data.get(
                "last_findings",
                "Validated customer problem."
            )

            prompt = SALES_PROMPT.format(
                idea_context=last_idea,
                user_findings=findings,
            )

            result = await asyncio.to_thread(
                generate_gemini_content,
                prompt,
                SYSTEM_PROMPT,
            )

            await status_msg.delete()

            await query.message.reply_text(
                result
            )

        except Exception as error:

            await status_msg.delete()

            await query.message.reply_text(
                f"❌ Error: {str(error)}"
            )

    # ------------------------------------------------------------
    # NEXT OPPORTUNITY
    # ------------------------------------------------------------

    elif query.data == "btn_next_opp":

        status_msg = await query.message.reply_text(
            "🔄 Scouting next opportunity..."
        )

        try:

            pitch_text = await asyncio.to_thread(
                generate_gemini_content,
                prompt=(
                    "Scout a fresh unvalidated market "
                    "opportunity or workflow friction."
                ),
                system_instruction=SYSTEM_PROMPT,
            )

            context.user_data["last_idea"] = pitch_text
            context.user_data["validation_status"] = "🔴 UNVALIDATED"

            await status_msg.delete()

            await query.message.reply_text(
                pitch_text,
                reply_markup=get_keyboard(
                    "🔴 UNVALIDATED"
                ),
            )

        except Exception as error:

            await status_msg.delete()

            await query.message.reply_text(
                f"❌ Error: {str(error)}"
            )


# ================================================================
# 19. REPLY HANDLER
# ================================================================

async def reply_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    # ------------------------------------------------------------
    # OUTREACH
    # ------------------------------------------------------------

    if context.user_data.get(
        "awaiting_candidate"
    ):

        await outreach_analysis(
            update,
            context
        )

        return

    # ------------------------------------------------------------
    # FINDINGS
    # ------------------------------------------------------------

    if context.user_data.get(
        "awaiting_findings"
    ):

        context.user_data[
            "awaiting_findings"
        ] = False

        user_findings = update.message.text

        context.user_data[
            "last_findings"
        ] = user_findings

        last_idea = context.user_data.get(
            "last_idea",
            "Market Opportunity"
        )

        current_status = context.user_data.get(
            "validation_status",
            "🔴 UNVALIDATED"
        )

        status_msg = await update.message.reply_text(
            "🧐 Evaluating evidence..."
        )

        try:

            prompt = ANALYZE_FINDINGS_PROMPT.format(
                idea_context=last_idea,
                current_status=current_status,
                user_findings=user_findings,
            )

            evaluation = await asyncio.to_thread(
                generate_gemini_content,
                prompt=prompt,
                system_instruction=SYSTEM_PROMPT,
            )

            new_status = current_status

            if "💰 PAYMENT SIGNAL" in evaluation:
                new_status = "💰 PAYMENT SIGNAL"

            elif "🟢 PROBLEM VALIDATED" in evaluation:
                new_status = "🟢 PROBLEM VALIDATED"

            elif "🟡 SIGNAL FOUND" in evaluation:
                new_status = "🟡 SIGNAL FOUND"

            elif "❌ KILL" in evaluation:
                new_status = "❌ KILLED"

            context.user_data[
                "validation_status"
            ] = new_status

            await status_msg.delete()

            await update.message.reply_text(

                "📋 EVALUATION & STATUS UPDATE\n\n"

                f"Updated Status: {new_status}\n\n"

                f"{evaluation}",

                reply_markup=get_keyboard(
                    new_status
                ),
            )

        except Exception as error:

            await status_msg.delete()

            await update.message.reply_text(
                f"❌ Error: {str(error)}"
            )


# ================================================================
# 20. TELEGRAM ERROR HANDLER
# ================================================================

async def telegram_error_handler(
    update: object,
    context: ContextTypes.DEFAULT_TYPE
):
    print(
        "❌ Telegram update error:",
        repr(context.error),
        flush=True,
    )


# ================================================================
# 21. APPLICATION STARTUP
# ================================================================

def main():

    app = (
        Application
        .builder()
        .token(TELEGRAM_BOT_TOKEN)
        .build()
    )

    app.add_handler(
        CommandHandler(
            "start",
            start_command
        )
    )

    app.add_handler(
        CommandHandler(
            "pitch",
            pitch_command
        )
    )

    app.add_handler(
        CommandHandler(
            "hunt",
            hunt_command
        )
    )

    app.add_handler(
        CommandHandler(
            "outreach",
            outreach_command
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            button_handler
        )
    )

    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            reply_handler
        )
    )

    app.add_error_handler(telegram_error_handler)

    print(
        "🚀 11Hunt Prospect Discovery running...",
        flush=True
    )

    print(
        "✅ Commands: "
        "/start /pitch /hunt /outreach"
    )

    app.run_polling(
        drop_pending_updates=False,
        allowed_updates=Update.ALL_TYPES,
        timeout=30,
        poll_interval=0.5,
    )


# ================================================================
# 22. RUN
# ================================================================

if __name__ == "__main__":
    main()
