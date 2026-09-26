import os
import asyncio
import threading
import datetime
import html
import re
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from http.server import HTTPServer, BaseHTTPRequestHandler

import pytz
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
# 1. HEALTH CHECK SERVER
# ================================================================

class HealthCheckHandler(BaseHTTPRequestHandler):

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(
            b"11Hunt Evidence-First Prospect Discovery is active!"
        )

    def log_message(self, format, *args):
        return


def run_health_server():
    port = int(os.getenv("PORT", "8080"))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    server.serve_forever()


threading.Thread(
    target=run_health_server,
    daemon=True
).start()


# ================================================================
# 2. ENVIRONMENT
# ================================================================

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
MY_TELEGRAM_CHAT_ID = os.getenv("MY_TELEGRAM_CHAT_ID")

if not TELEGRAM_BOT_TOKEN:
    raise ValueError("Missing TELEGRAM_BOT_TOKEN environment variable.")

if not GEMINI_API_KEY:
    raise ValueError("Missing GEMINI_API_KEY environment variable.")


ai_client = genai.Client(api_key=GEMINI_API_KEY)


# ================================================================
# 3. CORE 11HUNT PROMPTS
# ================================================================

SYSTEM_PROMPT = """
You are the AI opportunity discovery engine inside 11Hunt.

11Hunt helps beginners, students and freelancers find genuine business
problems and opportunities they can realistically solve and sell.

You MUST distinguish:

🟢 OBSERVED
Something directly supported by evidence.

🟡 HYPOTHESIS
A reasonable interpretation that has not yet been validated.

🔴 UNKNOWN
Something that still requires customer discovery.

Never present an assumption as a fact.

Return:

🎯 OPPORTUNITY HYPOTHESIS

STATUS: 🔴 UNVALIDATED

### 1. EVIDENCE BREAKDOWN

🟢 OBSERVED:
- 1-2 directly observable facts.

🟡 HYPOTHESIS:
- 2-3 possible problems or frictions.

🔴 UNKNOWN:
- 3 important questions that still need validation.

### 2. TARGET PROFILE

• Target Persona:
• Situation:
• Current workaround:

### 3. VALIDATION MISSION

Target 5 relevant people.

Do NOT pitch a solution.

Ask neutral questions that reveal their real workflow,
frustration and previous attempts to solve the problem.
"""


VALIDATION_PROMPT = """
You are a Lean Customer Discovery Expert inside 11Hunt.

Opportunity:
{idea_context}

Current Status:
{current_status}

Create a practical customer discovery plan.

🎯 CUSTOMER DISCOVERY ROADMAP

1. TARGET PROFILE
Who specifically should be interviewed?

2. WHERE TO FIND THEM
Give 3 realistic platforms/search locations.

3. NON-LEADING QUESTIONS
Give 4 questions that uncover actual behavior.

4. SIGNAL EVALUATION

🟢 Strong signal:
What evidence would indicate a meaningful problem?

🔴 Weak signal:
What responses would indicate this is not important?

5. VALIDATION RULE

Explain what evidence is needed before considering the problem validated.
"""


FIND_CUSTOMERS_PROMPT = """
You are a customer discovery and prospect research strategist inside 11Hunt.

Opportunity:
{idea_context}

Create:

👥 FIND POTENTIAL CUSTOMERS

1. EXACT SEARCH QUERIES
Give copy-paste search queries for:
- Google
- Reddit
- LinkedIn
- X
- Communities

2. TARGET PROFILES
Describe exactly who should be contacted.

3. RESEARCH OUTREACH

Write a short, natural message asking about their experience.

Do NOT pitch a product.

Do NOT pretend the problem has already been validated.
"""


OUTREACH_PROMPT = """
You are the evidence-first outreach assistant inside 11Hunt.

11Hunt is helping the founder discover real people experiencing
a problem.

Opportunity context:
{idea_context}

Candidate/post/profile:
{candidate}

IMPORTANT:

Analyze ONLY evidence actually present in the candidate text.

Do not invent:
- problems
- budgets
- business size
- intent
- experience
- willingness to buy

Return exactly:

🎯 RELEVANCE:
HIGH / MEDIUM / LOW

🔎 EVIDENCE:
List 1-3 concrete pieces of evidence.

⚠️ UNKNOWN:
What we still do not know.

💬 PUBLIC COMMENT:
A short natural research-oriented comment.
Do not pitch.

📩 RESEARCH DM:
A short message asking about their actual experience.
Do not claim we already have a solution.

❓ FOLLOW-UP:
One neutral question.
"""


CHALLENGE_PROMPT = """
You are the Devil's Advocate inside 11Hunt.

Opportunity:
{idea_context}

Challenge the opportunity.

🥊 HYPOTHESIS CHALLENGE

1. What if the problem is too rare?

2. What if people already have a good enough workaround?

3. What if the target user has no budget?

4. What if the problem is caused by temporary circumstances?

5. What evidence would prove this opportunity wrong within 24 hours?

6. What is the cheapest experiment to test it?
"""


ANALYZE_FINDINGS_PROMPT = """
You are the evidence evaluator inside 11Hunt.

Original opportunity:
{idea_context}

Current status:
{current_status}

Customer discovery findings:
{user_findings}

Evaluate ONLY what the findings actually support.

Return:

📊 DISCOVERY FINDINGS EVALUATION

1. CONFIRMED EVIDENCE
What was actually supported?

2. DISPROVED ASSUMPTIONS
What was shown to be wrong?

3. UNKNOWN
What remains unanswered?

4. TRUTH SIGNAL

Choose one:

NO SIGNAL
WEAK SIGNAL
STRONG SIGNAL
PAYMENT SIGNAL

Explain using the supplied evidence.

5. STATUS

Choose one:

🔴 UNVALIDATED
🟡 SIGNAL FOUND
🟢 PROBLEM VALIDATED
💰 PAYMENT SIGNAL
❌ KILL

Do not upgrade the status merely because the founder wants it.
"""


EXPERIMENT_PROMPT = """
You are a Lean Startup Experiment Designer inside 11Hunt.

Opportunity:
{idea_context}

Discovery evidence:
{user_findings}

Design the smallest possible experiment.

🧪 LOW-FIDELITY DEMAND EXPERIMENT

1. CONCIERGE TEST
How can this be delivered manually?

2. SUCCESS CRITERION
What exact user behavior would demonstrate demand?

3. FAILURE CRITERION
What result would indicate the idea should be changed or stopped?

4. 24-HOUR TEST
What can be tested within one day?

5. OUTREACH COPY
Write a short test message without making unsupported claims.
"""


MVP_PROMPT = """
You are a technical product architect inside 11Hunt.

Opportunity:
{idea_context}

Validation status:
{current_status}

Create a lean MVP plan.

🛠️ LEAN MVP BUILD BLUEPRINT

1. Validated problem

2. Single core workflow

3. Minimum features

4. Simplest possible technology stack

5. 3-day build plan

6. What should NOT be built yet

Only build after sufficient evidence exists.
"""


SALES_PROMPT = """
You are a B2B customer acquisition strategist inside 11Hunt.

Opportunity:
{idea_context}

Discovery evidence:
{user_findings}

Create:

💼 FIRST CUSTOMER ACQUISITION ROADMAP

1. Who should receive the offer?

2. What evidence-based value proposition can be used?

3. Paid pilot structure

4. Follow-up message

5. Objection handling

Do not invent customer results or testimonials.
"""


# ================================================================
# 4. GEMINI ENGINE
# ================================================================

def generate_gemini_content(prompt: str, system_instruction: str) -> str:

    last_error = None

    try:
        available_models = []

        for model in ai_client.models.list():

            model_id = model.name.replace("models/", "")

            methods = getattr(
                model,
                "supported_generation_methods",
                []
            ) or []

            if (
                "generateContent" in methods
                or not methods
            ):
                available_models.append(model_id)

        available_models.sort(
            key=lambda name: (
                "flash" not in name.lower(),
                name
            )
        )

    except Exception as error:

        last_error = error

        available_models = [
            "gemini-2.5-flash",
            "gemini-1.5-flash"
        ]

    for model in available_models:

        try:

            response = ai_client.models.generate_content(
                model=model,
                contents=prompt,
                config={
                    "system_instruction": system_instruction,
                    "temperature": 0.7
                }
            )

            if response and response.text:
                return response.text

        except Exception as error:

            last_error = error
            continue

    raise Exception(
        f"Gemini Engine Error: {str(last_error)}"
    )


# ================================================================
# 5. PUBLIC WEB HELPERS
# ================================================================

def fetch_json(url: str, timeout: int = 15):

    request = Request(
        url,
        headers={
            "User-Agent":
                "11Hunt-ProspectDiscovery/1.0 "
                "(evidence-first research tool)"
        }
    )

    with urlopen(request, timeout=timeout) as response:

        return response.read().decode("utf-8")


# ================================================================
# 6. REDDIT SEARCH
# ================================================================

def search_reddit(query: str):

    params = urlencode({
        "q": query,
        "sort": "new",
        "t": "year",
        "limit": "25",
        "raw_json": "1"
    })

    url = (
        "https://www.reddit.com/search.json?"
        + params
    )

    raw = fetch_json(url)

    import json

    data = json.loads(raw)

    results = []

    for child in data.get("data", {}).get("children", []):

        item = child.get("data", {})

        title = item.get("title", "")
        body = item.get("selftext", "")

        if not title and not body:
            continue

        author = item.get("author") or "[deleted]"

        permalink = item.get("permalink", "")

        if permalink and not permalink.startswith("http"):

            permalink = (
                "https://www.reddit.com"
                + permalink
            )

        results.append({
            "person": f"u/{author}",
            "platform": "Reddit",
            "title": title,
            "evidence": (
                body.replace("\n", " ")
                .strip()[:500]
            ),
            "url": permalink,
            "contact": (
                "COMMENT / DM"
                if author != "[deleted]"
                else "UNKNOWN"
            )
        })

    return results


# ================================================================
# 7. HACKER NEWS SEARCH
# ================================================================

def search_hackernews(query: str):

    params = urlencode({
        "query": query,
        "tags": "(story,comment)",
        "hitsPerPage": "20"
    })

    url = (
        "https://hn.algolia.com/api/v1/"
        "search_by_date?"
        + params
    )

    raw = fetch_json(url)

    import json

    data = json.loads(raw)

    results = []

    for hit in data.get("hits", []):

        author = hit.get("author") or "[unknown]"

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

        text = re.sub(
            "<[^>]+>",
            " ",
            str(text)
        )

        text = html.unescape(text)

        text = " ".join(text.split())

        object_id = hit.get("objectID", "")

        url = (
            hit.get("url")
            or (
                f"https://news.ycombinator.com/item?id={object_id}"
                if object_id
                else ""
            )
        )

        results.append({
            "person": f"@{author}",
            "platform": "Hacker News",
            "title": title,
            "evidence": text[:500],
            "url": url,
            "contact": "PUBLIC PROFILE / COMMENT"
        })

    return results


# ================================================================
# 8. GITHUB SEARCH
# ================================================================

def search_github(query: str):

    search_query = (
        f'"{query}" '
        f'in:title,body '
        f'is:issue'
    )

    params = urlencode({
        "q": search_query,
        "sort": "updated",
        "order": "desc",
        "per_page": "20"
    })

    url = (
        "https://api.github.com/search/issues?"
        + params
    )

    raw = fetch_json(url)

    import json

    data = json.loads(raw)

    results = []

    for item in data.get("items", []):

        user = (
            item.get("user") or {}
        ).get("login") or "[unknown]"

        body = " ".join(
            (item.get("body") or "").split()
        )

        results.append({
            "person": f"@{user}",
            "platform": "GitHub",
            "title": item.get(
                "title",
                "GitHub issue"
            ),
            "evidence": body[:500],
            "url": item.get(
                "html_url",
                ""
            ),
            "contact": "ISSUE / PROFILE"
        })

    return results


# ================================================================
# 9. 11HUNT PROSPECT SIGNAL ENGINE
# ================================================================

BEGINNER_TERMS = [

    "beginner",
    "beginner freelancer",
    "new freelancer",
    "new to freelancing",
    "starting freelancing",
    "started freelancing",
    "just started",
    "starting out",
    "first client",
    "first customer",
    "first paying client",
    "first freelance client",
    "no clients",
    "no client",
    "zero clients",
    "can't get clients",
    "cannot get clients",
    "struggling to get clients",
    "getting clients",
    "finding clients",
    "client acquisition",
    "client acquisition problem",
    "how to get clients",
    "how do i get clients",
    "where to find clients",
    "freelance clients"
]


AI_TERMS = [

    "ai freelancer",
    "ai automation",
    "ai agent",
    "ai agents",
    "ai automation freelancer",
    "ai developer",
    "ai developer freelancer",
    "automation freelancer",
    "n8n",
    "make.com",
    "zapier",
    "llm",
    "chatgpt",
    "claude",
    "generative ai",
    "genai",
    "no-code ai",
    "nocode ai",
    "ai services",
    "ai agency"
]


PAIN_TERMS = [

    "struggling",
    "struggle",
    "can't get",
    "cannot get",
    "no clients",
    "no client",
    "zero clients",
    "no response",
    "nobody responds",
    "no one responds",
    "ghosted",
    "ignored",
    "not getting clients",
    "not getting work",
    "hard to find",
    "difficult to find",
    "client acquisition",
    "lead generation",
    "cold outreach",
    "cold dm",
    "cold email",
    "outreach",
    "rejection",
    "rejected",
    "portfolio",
    "pricing",
    "selling",
    "sales"
]


NEGATIVE_TERMS = [

    "10 years freelance",
    "10+ years freelance",
    "15 years freelance",
    "20 years freelance",
    "experienced freelancer",
    "senior freelancer",
    "established agency",
    "large agency",
    "hiring freelancers",
    "who wants to be hired",
    "available for hire"
]


def calculate_prospect_signal(result):

    text = (
        f"{result.get('title', '')} "
        f"{result.get('evidence', '')}"
    ).lower()

    beginner_hits = [
        term
        for term in BEGINNER_TERMS
        if term in text
    ]

    ai_hits = [
        term
        for term in AI_TERMS
        if term in text
    ]

    pain_hits = [
        term
        for term in PAIN_TERMS
        if term in text
    ]

    negative_hits = [
        term
        for term in NEGATIVE_TERMS
        if term in text
    ]

    score = 0

    # AI relevance
    if ai_hits:
        score += 25

    if len(ai_hits) >= 2:
        score += 10

    # Beginner / first-client relevance
    if beginner_hits:
        score += 30

    if len(beginner_hits) >= 2:
        score += 15

    # Actual acquisition pain
    if pain_hits:
        score += 20

    if len(pain_hits) >= 2:
        score += 15

    # Remove clearly experienced / irrelevant profiles
    if negative_hits:
        score -= 40

    # Explicit first-client language gets strong evidence
    if "first client" in text:
        score += 20

    if "no clients" in text:
        score += 20

    if "can't get clients" in text:
        score += 20

    if "cannot get clients" in text:
        score += 20

    # Classification
    if score >= 90:
        signal = "🔥 HIGH"

    elif score >= 60:
        signal = "🟡 MEDIUM"

    else:
        signal = "🔴 LOW"

    return signal, score


# ================================================================
# 10. HUNT ENGINE
# ================================================================

def hunt_public_prospects(topic: str):

    """
    11Hunt prospect discovery.

    Goal:
    Find beginner AI freelancers who show public evidence
    of struggling with client acquisition / first clients.

    Automatic DMs: OFF
    Automatic comments: OFF
    """

    if not topic:

        topic = (
            "beginner AI freelancer "
            "first client client acquisition"
        )

    # ------------------------------------------------------------
    # Search queries specifically designed for the 11Hunt target
    # ------------------------------------------------------------

    queries = [

        "AI freelancer first client",

        "AI freelancer no clients",

        "AI freelancer struggling to get clients",

        "AI automation freelancer first client",

        "AI automation freelancer no clients",

        "starting AI freelancing",

        "how to get first AI freelance client",

        "beginner AI freelancer client acquisition",

        "AI freelancer cold outreach",

        "AI freelancer finding clients",

        "student AI freelancer clients",

        "new freelancer AI clients",

        "AI services no clients",

        "AI agency first client",

        "n8n freelancer clients"
    ]


    all_results = []

    source_warnings = []


    # ============================================================
    # REDDIT
    # ============================================================

    for query in queries[:8]:

        try:

            results = search_reddit(query)

            all_results.extend(results)

        except Exception as error:

            message = str(error)

            if "Reddit" not in " ".join(
                source_warnings
            ):

                source_warnings.append(
                    f"• Reddit: {message[:180]}"
                )

            break


    # ============================================================
    # HACKER NEWS
    # ============================================================

    for query in queries:

        try:

            results = search_hackernews(query)

            all_results.extend(results)

        except Exception as error:

            message = str(error)

            if "Hacker News" not in " ".join(
                source_warnings
            ):

                source_warnings.append(
                    f"• Hacker News: {message[:180]}"
                )

            break


    # ============================================================
    # GITHUB
    # ============================================================

    for query in queries[:8]:

        try:

            results = search_github(query)

            all_results.extend(results)

        except Exception as error:

            message = str(error)

            if "GitHub" not in " ".join(
                source_warnings
            ):

                source_warnings.append(
                    f"• GitHub: {message[:180]}"
                )

            break


    # ============================================================
    # SCORE RESULTS
    # ============================================================

    scored = []

    seen_urls = set()

    for result in all_results:

        url = (
            result.get("url") or ""
        ).strip()

        if not url:
            continue

        if url in seen_urls:
            continue

        seen_urls.add(url)

        signal, score = calculate_prospect_signal(
            result
        )

        if signal == "🔴 LOW":
            continue

        result["signal"] = signal
        result["signal_score"] = score

        scored.append(result)


    # Highest evidence first
    scored.sort(
        key=lambda item: (
            item.get("signal_score", 0)
        ),
        reverse=True
    )


    # ============================================================
    # REMOVE DUPLICATE PEOPLE / POSTS
    # ============================================================

    unique = []

    seen_people_posts = set()

    for result in scored:

        identity = (
            result.get("person", ""),
            result.get("title", "")
        )

        if identity in seen_people_posts:
            continue

        seen_people_posts.add(identity)

        unique.append(result)

        if len(unique) >= 10:
            break


    # ============================================================
    # NO RESULTS
    # ============================================================

    if not unique:

        warning_text = (
            "\n".join(source_warnings)
            if source_warnings
            else "No source errors reported."
        )

        return (
            "🎯 11HUNT PROSPECT DISCOVERY\n\n"

            "Mode: Evidence-first public discovery\n\n"

            "Automatic DMs: OFF\n"
            "Automatic comments: OFF\n\n"

            "TARGET:\n"
            "Beginner AI freelancers struggling to get "
            "their first clients.\n\n"

            "────────────────────\n\n"

            "No medium/high prospect signals were found.\n\n"

            "This does NOT mean there are no prospects.\n\n"

            "It means the current public search did not "
            "find enough evidence matching the target.\n\n"

            "Try:\n\n"

            "/hunt AI freelancers looking for clients\n\n"

            "/hunt beginner AI freelancers\n\n"

            "/hunt people struggling to get first clients\n\n"

            "/hunt students doing AI freelancing\n\n"

            "SOURCE WARNINGS:\n"
            f"{warning_text}"
        )


    # ============================================================
    # BUILD OUTPUT
    # ============================================================

    lines = [

        "🎯 11HUNT PROSPECT DISCOVERY",

        "",

        "Mode: Evidence-first public discovery",

        "",

        "Automatic DMs: OFF",
        "Automatic comments: OFF",

        "",

        "TARGET:",

        "Beginner AI freelancers struggling "
        "to get their first clients.",

        "",

        "────────────────────",

        ""
    ]


    for index, result in enumerate(
        unique,
        start=1
    ):

        evidence = (
            result.get("evidence")
            or "No text excerpt available."
        )

        evidence = (
            evidence
            .replace("\n", " ")
            .strip()
        )

        lines.extend([

            f"{index}. "
            f"{result['signal']} "
            f"— {result['person']} "
            f"({result['platform']})",

            f"POST: {result['title']}",

            f"EVIDENCE: {evidence}",

            f"URL: {result['url']}",

            f"CONTACT: {result['contact']}",

            f"SIGNAL SCORE: "
            f"{result['signal_score']}",

            ""
        ])


    lines.extend([

        "────────────────────",

        "",

        "NEXT STEP:",

        "Open the strongest 3 candidates.",

        "Read their full post/profile.",

        "",

        "Then use:",

        "/outreach",

        "",

        "Paste the actual post/profile text.",

        "",

        "11Hunt will analyze the evidence and prepare:",

        "• relevance",
        "• evidence",
        "• unknowns",
        "• research comment",
        "• research DM",
        "• follow-up question",

        "",

        "You approve and send everything yourself.",

        "No automatic messages are sent."
    ])


    if source_warnings:

        lines.extend([

            "",

            "SOURCE WARNINGS:",

            "\n".join(source_warnings)

        ])


    return "\n".join(lines)


# ================================================================
# 11. KEYBOARD
# ================================================================

def get_keyboard(
    status="🔴 UNVALIDATED"
):

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
                )
            ],

            [
                InlineKeyboardButton(
                    "🔎 Hunt Prospects",
                    callback_data="btn_hunt"
                ),

                InlineKeyboardButton(
                    "💬 Outreach Assistant",
                    callback_data="btn_outreach"
                )
            ],

            [
                InlineKeyboardButton(
                    "📥 Enter Discovery Findings",
                    callback_data="btn_enter_findings"
                ),

                InlineKeyboardButton(
                    "🥊 Challenge Idea",
                    callback_data="btn_challenge"
                )
            ],

            [
                InlineKeyboardButton(
                    "🧪 Design Experiment",
                    callback_data="btn_experiment"
                ),

                InlineKeyboardButton(
                    "🔄 Next Opportunity",
                    callback_data="btn_next_opp"
                )
            ]

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
            )
        ],

        [
            InlineKeyboardButton(
                "🛠️ Plan MVP Sprint",
                callback_data="btn_build_mvp"
            ),

            InlineKeyboardButton(
                "💼 Sales & Conversion",
                callback_data="btn_sales"
            )
        ],

        [
            InlineKeyboardButton(
                "🔄 Next Opportunity",
                callback_data="btn_next_opp"
            )
        ]

    ])


# ================================================================
# 12. /START
# ================================================================

async def start_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    chat_id = update.effective_chat.id

    await update.message.reply_text(

        "👋 11Hunt Prospect Discovery is active!\n\n"

        "Find real people experiencing problems "
        "you may be able to solve.\n\n"

        "Commands:\n\n"

        "/pitch — discover an opportunity\n"
        "/hunt — find potential prospects\n"
        "/outreach — analyze a prospect\n\n"

        f"Chat ID: `{chat_id}`",

        parse_mode="Markdown"
    )


# ================================================================
# 13. /PITCH
# ================================================================

async def pitch_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    status = await update.message.reply_text(
        "🔎 Discovering an evidence-first opportunity..."
    )

    try:

        pitch = await asyncio.to_thread(

            generate_gemini_content,

            "Scout a fresh unvalidated opportunity "
            "that a beginner freelancer or student "
            "could realistically investigate.",

            SYSTEM_PROMPT
        )

        context.user_data["last_idea"] = pitch

        context.user_data[
            "validation_status"
        ] = "🔴 UNVALIDATED"

        await status.delete()

        await update.message.reply_text(
            pitch,
            reply_markup=get_keyboard(
                "🔴 UNVALIDATED"
            )
        )

    except Exception as error:

        await status.delete()

        await update.message.reply_text(
            f"❌ Error: {str(error)}"
        )


# ================================================================
# 14. DAILY PITCH
# ================================================================

async def scheduled_daily_pitch(
    context: ContextTypes.DEFAULT_TYPE
):

    if not MY_TELEGRAM_CHAT_ID:
        return

    try:

        pitch = await asyncio.to_thread(

            generate_gemini_content,

            "Scout a fresh unvalidated market "
            "opportunity or workflow problem.",

            SYSTEM_PROMPT
        )

        await context.bot.send_message(

            chat_id=MY_TELEGRAM_CHAT_ID,

            text=(
                "☀️ TODAY'S 11HUNT OPPORTUNITY\n\n"
                + pitch
            ),

            reply_markup=get_keyboard(
                "🔴 UNVALIDATED"
            )
        )

    except Exception as error:

        print(
            f"Daily Scout Push Error: {error}"
        )


# ================================================================
# 15. /HUNT
# ================================================================

async def hunt_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    topic = " ".join(
        context.args
    ).strip()

    if not topic:

        topic = (
            "beginner AI freelancers "
            "struggling to get first clients"
        )

    status = await update.message.reply_text(

        "🔎 11Hunt is searching public sources...\n\n"

        "Target:\n"
        "Beginner AI freelancers struggling "
        "to get clients.\n\n"

        "Automatic DMs: OFF\n"
        "Automatic comments: OFF"
    )

    try:

        result = await asyncio.to_thread(

            hunt_public_prospects,

            topic
        )

        await status.delete()

        # Telegram message size protection
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

        await status.delete()

        await update.message.reply_text(

            "❌ Hunt failed:\n\n"
            + str(error)
        )


# ================================================================
# 16. /OUTREACH
# ================================================================

async def outreach_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    last_idea = context.user_data.get(
        "last_idea"
    )

    if not last_idea:

        last_idea = (
            "Beginner AI freelancers "
            "struggling to acquire their first clients."
        )

    context.user_data[
        "awaiting_candidate"
    ] = True

    await update.message.reply_text(

        "🎯 OUTREACH ASSISTANT\n\n"

        "Paste the actual public post/profile "
        "text of a candidate.\n\n"

        "I will analyze:\n\n"

        "• Relevance\n"
        "• Evidence\n"
        "• Unknowns\n"
        "• Public research comment\n"
        "• Research DM\n"
        "• Follow-up question\n\n"

        "⚠️ Automatic messages are OFF.\n"
        "You approve and send everything yourself."
    )


# ================================================================
# 17. OUTREACH ANALYSIS
# ================================================================

async def outreach_analysis(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    candidate = update.message.text

    last_idea = context.user_data.get(

        "last_idea",

        "Beginner AI freelancers struggling "
        "to acquire their first clients."
    )

    status = await update.message.reply_text(
        "🔎 Analyzing candidate evidence..."
    )

    try:

        prompt = OUTREACH_PROMPT.format(

            idea_context=last_idea,

            candidate=candidate
        )

        result = await asyncio.to_thread(

            generate_gemini_content,

            prompt,

            "You are the evidence-first "
            "outreach assistant for 11Hunt."
        )

        prospects = context.user_data.setdefault(
            "outreach_prospects",
            []
        )

        prospects.append({

            "candidate": candidate,

            "analysis": result,

            "status": "prepared"
        })

        context.user_data[
            "last_candidate"
        ] = candidate

        context.user_data[
            "awaiting_candidate"
        ] = False

        await status.delete()

        await update.message.reply_text(

            "🎯 PROSPECT ANALYSIS\n\n"

            + result

            + "\n\n"

            f"📌 Prospect #{len(prospects)} "
            "saved in this Telegram session."
        )

    except Exception as error:

        context.user_data[
            "awaiting_candidate"
        ] = False

        await status.delete()

        await update.message.reply_text(
            f"❌ Error: {str(error)}"
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

        "Beginner AI freelancers struggling "
        "to acquire their first clients."
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

            "Try:\n\n"

            "/hunt AI freelancers looking for clients\n\n"

            "/hunt beginner AI freelancers\n\n"

            "/hunt people struggling to get first clients\n\n"

            "Automatic DMs: OFF\n"
            "Automatic comments: OFF"
        )

        return


    # ------------------------------------------------------------
    # OUTREACH
    # ------------------------------------------------------------

    if query.data == "btn_outreach":

        context.user_data[
            "awaiting_candidate"
        ] = True

        await query.message.reply_text(

            "🎯 OUTREACH ASSISTANT\n\n"

            "Paste the actual post/profile text.\n\n"

            "11Hunt will prepare:\n"

            "• Evidence\n"
            "• Relevance\n"
            "• Unknowns\n"
            "• Research comment\n"
            "• Research DM\n"
            "• Follow-up question\n\n"

            "You approve and send it yourself."
        )

        return


    # ------------------------------------------------------------
    # VALIDATE
    # ------------------------------------------------------------

    if query.data == "btn_validate":

        status = await query.message.reply_text(

            "🎯 Building customer discovery plan..."
        )

        try:

            prompt = VALIDATION_PROMPT.format(

                idea_context=last_idea,

                current_status=current_status
            )

            result = await asyncio.to_thread(

                generate_gemini_content,

                prompt,

                "You are a Customer Discovery Expert."
            )

            await status.delete()

            await query.message.reply_text(
                result
            )

        except Exception as error:

            await status.delete()

            await query.message.reply_text(
                f"❌ Error: {str(error)}"
            )

        return


    # ------------------------------------------------------------
    # FIND CUSTOMERS
    # ------------------------------------------------------------

    if query.data == "btn_find_customers":

        status = await query.message.reply_text(

            "👥 Finding customer search strategies..."
        )

        try:

            prompt = FIND_CUSTOMERS_PROMPT.format(

                idea_context=last_idea
            )

            result = await asyncio.to_thread(

                generate_gemini_content,

                prompt,

                "You are a Lead Generation Specialist."
            )

            await status.delete()

            await query.message.reply_text(
                result
            )

        except Exception as error:

            await status.delete()

            await query.message.reply_text(
                f"❌ Error: {str(error)}"
            )

        return


    # ------------------------------------------------------------
    # ENTER FINDINGS
    # ------------------------------------------------------------

    if query.data == "btn_enter_findings":

        context.user_data[
            "awaiting_findings"
        ] = True

        await query.message.reply_text(

            "📥 DISCOVERY FINDINGS\n\n"

            "Send your interview notes.\n\n"

            "Include:\n"

            "1. Number of people interviewed\n"

            "2. What they currently do\n"

            "3. Problems they described\n"

            "4. Exact quotes if possible\n"

            "5. Any willingness-to-pay evidence"
        )

        return


    # ------------------------------------------------------------
    # CHALLENGE
    # ------------------------------------------------------------

    if query.data == "btn_challenge":

        status = await query.message.reply_text(

            "🥊 Stress-testing the opportunity..."
        )

        try:

            prompt = CHALLENGE_PROMPT.format(

                idea_context=last_idea
            )

            result = await asyncio.to_thread(

                generate_gemini_content,

                prompt,

                "You are the Devil's Advocate "
                "inside 11Hunt."
            )

            await status.delete()

            await query.message.reply_text(
                result
            )

        except Exception as error:

            await status.delete()

            await query.message.reply_text(
                f"❌ Error: {str(error)}"
            )

        return


    # ------------------------------------------------------------
    # EXPERIMENT
    # ------------------------------------------------------------

    if query.data == "btn_experiment":

        status = await query.message.reply_text(

            "🧪 Designing smallest demand experiment..."
        )

        try:

            findings = context.user_data.get(

                "last_findings",

                "No customer findings recorded yet."
            )

            prompt = EXPERIMENT_PROMPT.format(

                idea_context=last_idea,

                user_findings=findings
            )

            result = await asyncio.to_thread(

                generate_gemini_content,

                prompt,

                "You are a Lean Startup "
                "Experiment Designer."
            )

            await status.delete()

            await query.message.reply_text(
                result
            )

        except Exception as error:

            await status.delete()

            await query.message.reply_text(
                f"❌ Error: {str(error)}"
            )

        return


    # ------------------------------------------------------------
    # BUILD MVP
    # ------------------------------------------------------------

    if query.data == "btn_build_mvp":

        if current_status in [

            "🔴 UNVALIDATED",

            "🟡 SIGNAL FOUND"
        ]:

            await query.message.reply_text(

                "🛑 BUILD LOCKED\n\n"

                f"Current status: {current_status}\n\n"

                "Collect stronger customer evidence "
                "before building."
            )

            return


        status = await query.message.reply_text(

            "🛠️ Creating lean MVP blueprint..."
        )

        try:

            prompt = MVP_PROMPT.format(

                idea_context=last_idea,

                current_status=current_status
            )

            result = await asyncio.to_thread(

                generate_gemini_content,

                prompt,

                "You are a Technical Product Architect."
            )

            await status.delete()

            await query.message.reply_text(
                result
            )

        except Exception as error:

            await status.delete()

            await query.message.reply_text(
                f"❌ Error: {str(error)}"
            )

        return


    # ------------------------------------------------------------
    # SALES
    # ------------------------------------------------------------

    if query.data == "btn_sales":

        if current_status in [

            "🔴 UNVALIDATED",

            "🟡 SIGNAL FOUND"
        ]:

            await query.message.reply_text(

                "🛑 SALES LOCKED\n\n"

                "Validate the problem and test demand "
                "before building a sales strategy."
            )

            return


        status = await query.message.reply_text(

            "💼 Creating first-customer strategy..."
        )

        try:

            findings = context.user_data.get(

                "last_findings",

                "Customer discovery completed."
            )

            prompt = SALES_PROMPT.format(

                idea_context=last_idea,

                user_findings=findings
            )

            result = await asyncio.to_thread(

                generate_gemini_content,

                prompt,

                "You are a B2B Sales Strategist."
            )

            await status.delete()

            await query.message.reply_text(
                result
            )

        except Exception as error:

            await status.delete()

            await query.message.reply_text(
                f"❌ Error: {str(error)}"
            )

        return


    # ------------------------------------------------------------
    # NEXT OPPORTUNITY
    # ------------------------------------------------------------

    if query.data == "btn_next_opp":

        status = await query.message.reply_text(

            "🔄 Finding the next opportunity..."
        )

        try:

            pitch = await asyncio.to_thread(

                generate_gemini_content,

                "Scout a fresh unvalidated market "
                "opportunity that a beginner freelancer "
                "could investigate.",

                SYSTEM_PROMPT
            )

            context.user_data[
                "last_idea"
            ] = pitch

            context.user_data[
                "validation_status"
            ] = "🔴 UNVALIDATED"

            await status.delete()

            await query.message.reply_text(

                pitch,

                reply_markup=get_keyboard(
                    "🔴 UNVALIDATED"
                )
            )

        except Exception as error:

            await status.delete()

            await query.message.reply_text(
                f"❌ Error: {str(error)}"
            )

        return


# ================================================================
# 19. NORMAL TEXT REPLY HANDLER
# ================================================================

async def reply_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    # ------------------------------------------------------------
    # Candidate waiting for outreach analysis
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
    # Discovery findings
    # ------------------------------------------------------------

    if context.user_data.get(
        "awaiting_findings"
    ):

        context.user_data[
            "awaiting_findings"
        ] = False

        findings = update.message.text

        context.user_data[
            "last_findings"
        ] = findings

        last_idea = context.user_data.get(

            "last_idea",

            "Market Opportunity Hypothesis"
        )

        current_status = context.user_data.get(

            "validation_status",

            "🔴 UNVALIDATED"
        )

        status = await update.message.reply_text(

            "🧐 Evaluating evidence..."
        )

        try:

            prompt = ANALYZE_FINDINGS_PROMPT.format(

                idea_context=last_idea,

                current_status=current_status,

                user_findings=findings
            )

            evaluation = await asyncio.to_thread(

                generate_gemini_content,

                prompt,

                "You are an objective evidence evaluator."
            )


            # ----------------------------------------------------
            # Status extraction
            # ----------------------------------------------------

            new_status = current_status

            if "💰 PAYMENT SIGNAL" in evaluation:

                new_status = "💰 PAYMENT SIGNAL"

            elif "🟢 PROBLEM VALIDATED" in evaluation:

                new_status = "🟢 PROBLEM VALIDATED"

            elif "🟡 SIGNAL FOUND" in evaluation:

                new_status = "🟡 SIGNAL FOUND"

            elif "❌ KILL" in evaluation:

                new_status = "❌ KILL"


            context.user_data[
                "validation_status"
            ] = new_status


            await status.delete()

            await update.message.reply_text(

                "📋 EVIDENCE EVALUATION\n\n"

                f"STATUS: {new_status}\n\n"

                + evaluation,

                reply_markup=get_keyboard(
                    new_status
                )
            )

        except Exception as error:

            await status.delete()

            await update.message.reply_text(
                f"❌ Error: {str(error)}"
            )

        return


# ================================================================
# 20. APPLICATION STARTUP
# ================================================================

def main():

    app = (
        Application
        .builder()
        .token(TELEGRAM_BOT_TOKEN)
        .build()
    )


    # Commands

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


    # Buttons

    app.add_handler(
        CallbackQueryHandler(
            button_handler
        )
    )


    # Text

    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            reply_handler
        )
    )


    # Daily opportunity

    if MY_TELEGRAM_CHAT_ID:

        india = pytz.timezone(
            "Asia/Kolkata"
        )

        target_time = datetime.time(
            hour=8,
            minute=0,
            second=0,
            tzinfo=india
        )

        app.job_queue.run_daily(
            scheduled_daily_pitch,
            time=target_time
        )


    print(
        "🚀 11Hunt Evidence-First "
        "Prospect Discovery running..."
    )

    print(
        "✅ Commands:"
        " /start /pitch /hunt /outreach"
    )

    print(
        "✅ Automatic DMs: OFF"
    )

    print(
        "✅ Automatic comments: OFF"
    )

    app.run_polling(
        drop_pending_updates=True
    )


# ================================================================
# 21. RUN
# ================================================================

if __name__ == "__main__":
    main()
