import os
import asyncio
import threading
import datetime
import pytz
import json
import re
import html
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from http.server import HTTPServer, BaseHTTPRequestHandler

from google import genai

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)

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
    raise ValueError(
        "Missing TELEGRAM_BOT_TOKEN environment variable."
    )

if not GEMINI_API_KEY:
    raise ValueError(
        "Missing GEMINI_API_KEY environment variable."
    )


ai_client = genai.Client(api_key=GEMINI_API_KEY)


# ================================================================
# 3. 11HUNT PRODUCT POSITIONING
# ================================================================

TARGET_PROFILE = """
BEGINNER AI FREELANCERS STRUGGLING TO GET THEIR FIRST CLIENTS

Examples:

- students learning AI freelancing
- beginners offering AI automation services
- beginner no-code/AI builders
- people who recently started freelancing
- people who have skills but cannot get clients
- people asking how to find their first client
- people sending cold DMs but getting no replies
- people struggling with outreach
- people who have built demos but have no customers
- people unsure what service to sell
- people asking where freelancers find clients
- people frustrated by competition
- people getting ignored by prospects
- people doing free work to get testimonials
- beginner AI agencies with no clients
"""


# ================================================================
# 4. SYSTEM PROMPTS
# ================================================================

SYSTEM_PROMPT = """
You are the AI engine inside 11Hunt.

11Hunt helps beginners, students and early-stage freelancers
discover genuine opportunities and turn them into client conversations.

Core principle:

BUSINESS / PERSON
        ↓
EVIDENCE
        ↓
PROBLEM
        ↓
OPPORTUNITY
        ↓
SOLUTION
        ↓
PERSONALIZED OUTREACH
        ↓
CLIENT

You MUST distinguish:

🟢 OBSERVED
Directly supported by the supplied information.

🟡 HYPOTHESIS
A reasonable interpretation that still requires validation.

🔴 UNKNOWN
Something that cannot be concluded from the available evidence.

Never invent pain.

Never assume someone needs a product merely because they belong to a target category.
"""


OUTREACH_PROMPT = """
You are the 11Hunt Evidence-First Outreach Assistant.

TARGET:
Beginner AI freelancers struggling to acquire their first clients.

11Hunt's purpose:
Help the founder discover genuine client-acquisition problems and start
human conversations.

Candidate information:
{candidate}

Analyze ONLY the information actually present.

Do NOT invent:
- income
- number of clients
- skill level
- business size
- motivation
- willingness to pay
- problems that were not stated

Return:

🎯 RELEVANCE
HIGH / MEDIUM / LOW

🔎 OBSERVED EVIDENCE
List concrete evidence from the candidate.

🟡 HYPOTHESES
Possible problems suggested by the evidence.

🔴 UNKNOWN
Important things we still need to learn.

💬 RESEARCH COMMENT
A natural public comment.
Do not pitch 11Hunt.
Do not pretend to be an expert.

📩 RESEARCH DM
A short human message asking about their actual experience.

❓ FOLLOW-UP
One non-leading question.

IMPORTANT:
The purpose is discovery, not selling.
Do not automatically send anything.
"""


# ================================================================
# 5. GEMINI GENERATOR
# ================================================================

def generate_gemini_content(
    prompt: str,
    system_instruction: str
) -> str:

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
        available_models = [
            "gemini-2.5-flash",
            "gemini-1.5-flash"
        ]

        last_error = error

    for model in available_models:

        try:

            response = ai_client.models.generate_content(
                model=model,
                contents=prompt,
                config={
                    "system_instruction": system_instruction,
                    "temperature": 0.45
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
# 6. GENERIC PUBLIC JSON FETCHER
# ================================================================

def fetch_json(
    url: str,
    timeout: int = 15
):

    request = Request(
        url,
        headers={
            "User-Agent":
                "11Hunt-ProspectDiscovery/1.0"
        }
    )

    with urlopen(
        request,
        timeout=timeout
    ) as response:

        raw = response.read().decode(
            "utf-8",
            errors="ignore"
        )

        return json.loads(raw)


# ================================================================
# 7. TEXT CLEANING
# ================================================================

def clean_text(text):

    if not text:
        return ""

    text = html.unescape(str(text))

    text = re.sub(
        r"<[^>]+>",
        " ",
        text
    )

    text = re.sub(
        r"\s+",
        " ",
        text
    )

    return text.strip()


# ================================================================
# 8. HACKER NEWS SEARCH
# ================================================================

def search_hackernews(query):

    params = urlencode({
        "query": query,
        "tags": "(story,comment)",
        "hitsPerPage": 20
    })

    url = (
        "https://hn.algolia.com/api/v1/"
        f"search_by_date?{params}"
    )

    data = fetch_json(url)

    results = []

    for hit in data.get("hits", []):

        author = (
            hit.get("author")
            or "[unknown]"
        )

        object_id = (
            hit.get("objectID")
            or ""
        )

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

        title = clean_text(title)
        text = clean_text(text)

        if not title and not text:
            continue

        if object_id:

            item_url = (
                "https://news.ycombinator.com/"
                f"item?id={object_id}"
            )

        else:

            item_url = hit.get(
                "url",
                ""
            )

        results.append({

            "person":
                f"@{author}",

            "platform":
                "Hacker News",

            "title":
                title,

            "evidence":
                text[:700],

            "url":
                item_url,

            "contact":
                "PUBLIC PROFILE / COMMENT",

            "score":
                hit.get("points") or 0,

            "created":
                hit.get("created_at_i") or 0

        })

    return results


# ================================================================
# 9. GITHUB ISSUE SEARCH
# ================================================================

def search_github(query):

    github_query = (
        f"{query} "
        "in:title,body "
        "is:issue"
    )

    params = urlencode({
        "q": github_query,
        "sort": "updated",
        "order": "desc",
        "per_page": 20
    })

    url = (
        "https://api.github.com/search/issues?"
        f"{params}"
    )

    data = fetch_json(url)

    results = []

    for item in data.get("items", []):

        user = (
            item.get("user") or {}
        ).get(
            "login"
        ) or "[unknown]"

        title = clean_text(
            item.get(
                "title",
                "GitHub issue"
            )
        )

        body = clean_text(
            item.get(
                "body",
                ""
            )
        )

        results.append({

            "person":
                f"@{user}",

            "platform":
                "GitHub",

            "title":
                title,

            "evidence":
                body[:700],

            "url":
                item.get(
                    "html_url",
                    ""
                ),

            "contact":
                "ISSUE COMMENT / PROFILE",

            "score":
                item.get(
                    "comments",
                    0
                ),

            "created":
                0

        })

    return results


# ================================================================
# 10. PROBLEM DISCOVERY SEARCH QUERIES
# ================================================================

DISCOVERY_QUERIES = [

    # First-client intent
    "first freelance client",
    "first AI freelance client",
    "how to get first client",
    "struggling to get clients",
    "can't get freelance clients",

    # Client acquisition
    "freelance client acquisition",
    "freelancer finding clients",
    "AI freelancer finding clients",
    "how do AI freelancers get clients",
    "where to find AI clients",

    # Outreach pain
    "cold outreach freelancers no replies",
    "freelance outreach no response",
    "sent DMs no clients",
    "cold email freelance clients",
    "freelancer DMs no response",

    # Beginner struggles
    "new freelancer no clients",
    "beginner freelancer no clients",
    "starting AI freelancing",
    "new AI freelancer",
    "AI automation freelancer beginner",

    # Service positioning
    "don't know what freelance service to sell",
    "AI freelancer what service to offer",
    "AI automation freelance niche",
    "freelancer has skills but no clients",

    # Portfolio / proof
    "freelancer portfolio no clients",
    "AI freelancer portfolio clients",
    "built projects no clients",
    "AI automation demos no clients",

    # General frustration
    "freelancing competition clients",
    "freelancers struggling to find work",
    "freelancing getting clients difficult"
]


# ================================================================
# 11. TARGET SIGNAL VOCABULARY
# ================================================================

FIRST_CLIENT_TERMS = [

    "first client",
    "first customer",
    "first paying client",
    "first paying customer",
    "first freelance client",
    "first project",
    "land my first",
    "get my first",
    "finding my first"
]


CLIENT_ACQUISITION_TERMS = [

    "get clients",
    "getting clients",
    "find clients",
    "finding clients",
    "client acquisition",
    "customer acquisition",
    "lead generation",
    "generate leads",
    "prospects",
    "prospecting",
    "outreach",
    "cold outreach",
    "cold dm",
    "cold email",
    "client hunting",
    "book clients"
]


PAIN_TERMS = [

    "struggling",
    "can't get",
    "cannot get",
    "no clients",
    "no client",
    "zero clients",
    "no response",
    "no replies",
    "ignored",
    "nobody replies",
    "not getting clients",
    "not getting work",
    "hard to find",
    "difficult to find",
    "competition",
    "rejected",
    "ghosted",
    "unsuccessful",
    "failed",
    "nothing works",
    "don't know how",
    "do not know how",
    "confused",
    "stuck"
]


BEGINNER_TERMS = [

    "beginner",
    "new freelancer",
    "new to freelancing",
    "starting freelancing",
    "started freelancing",
    "just started",
    "student",
    "learning",
    "learning ai",
    "learning automation",
    "new to ai",
    "new to automation",
    "beginner ai",
    "beginner freelancer",
    "junior"
]


AI_FREELANCE_TERMS = [

    "ai freelancer",
    "ai automation",
    "ai automation freelancer",
    "ai agent",
    "ai agents",
    "automation freelancer",
    "automation agency",
    "no-code",
    "nocode",
    "make.com",
    "n8n",
    "zapier",
    "llm",
    "chatgpt",
    "claude",
    "ai services"
]


SENIOR_TERMS = [

    "10 years",
    "15 years",
    "20 years",
    "senior",
    "principal",
    "lead engineer",
    "staff engineer",
    "enterprise",
    "large corporations",
    "worked with google",
    "worked with microsoft",
    "worked with amazon",
    "worked with meta",
    "acquired by",
    "million users",
    "years of experience"
]


IRRELEVANT_TERMS = [

    "hiring",
    "job opening",
    "looking to hire",
    "we are hiring",
    "salary",
    "resume",
    "cv",
    "recruiter"
]


# ================================================================
# 12. SIGNAL SCORING
# ================================================================

def count_matches(
    text,
    terms
):

    text = text.lower()

    return sum(
        1
        for term in terms
        if term in text
    )


def score_prospect(result):

    title = result.get(
        "title",
        ""
    )

    evidence = result.get(
        "evidence",
        ""
    )

    person = result.get(
        "person",
        ""
    )

    blob = (
        f"{title} "
        f"{evidence} "
        f"{person}"
    ).lower()

    first_client = count_matches(
        blob,
        FIRST_CLIENT_TERMS
    )

    acquisition = count_matches(
        blob,
        CLIENT_ACQUISITION_TERMS
    )

    pain = count_matches(
        blob,
        PAIN_TERMS
    )

    beginner = count_matches(
        blob,
        BEGINNER_TERMS
    )

    ai_freelance = count_matches(
        blob,
        AI_FREELANCE_TERMS
    )

    senior = count_matches(
        blob,
        SENIOR_TERMS
    )

    irrelevant = count_matches(
        blob,
        IRRELEVANT_TERMS
    )


    # ------------------------------------------------------------
    # HARD EXCLUSIONS
    # ------------------------------------------------------------

    if irrelevant >= 2:
        return (
            "🔴 LOW",
            0,
            ["Likely hiring/job-seeking content"]
        )


    # Experienced freelancers are not automatically invalid,
    # but strong senior signals reduce their score significantly.

    score = 0
    reasons = []


    # ------------------------------------------------------------
    # CLIENT ACQUISITION SIGNAL
    # ------------------------------------------------------------

    if first_client:

        score += 40

        reasons.append(
            "Mentions first-client/first-customer intent"
        )

    elif acquisition >= 2:

        score += 30

        reasons.append(
            "Clearly discusses finding/acquiring clients"
        )

    elif acquisition == 1:

        score += 15

        reasons.append(
            "Mentions client acquisition"
        )


    # ------------------------------------------------------------
    # PAIN SIGNAL
    # ------------------------------------------------------------

    if pain >= 3:

        score += 30

        reasons.append(
            "Contains multiple concrete acquisition pain signals"
        )

    elif pain == 2:

        score += 20

        reasons.append(
            "Contains clear client-acquisition frustration"
        )

    elif pain == 1:

        score += 8

        reasons.append(
            "Contains one possible pain signal"
        )


    # ------------------------------------------------------------
    # BEGINNER SIGNAL
    # ------------------------------------------------------------

    if beginner >= 2:

        score += 25

        reasons.append(
            "Strong beginner/early-stage signal"
        )

    elif beginner == 1:

        score += 15

        reasons.append(
            "Some beginner/early-stage signal"
        )


    # ------------------------------------------------------------
    # AI FREELANCING SIGNAL
    # ------------------------------------------------------------

    if ai_freelance >= 2:

        score += 20

        reasons.append(
            "Strong AI/automation freelancing signal"
        )

    elif ai_freelance == 1:

        score += 10

        reasons.append(
            "AI/automation freelancing signal"
        )


    # ------------------------------------------------------------
    # SENIORITY PENALTY
    # ------------------------------------------------------------

    if senior >= 3:

        score -= 40

        reasons.append(
            "Strong established/senior freelancer signal"
        )

    elif senior == 2:

        score -= 25

        reasons.append(
            "Some established freelancer signal"
        )

    elif senior == 1:

        score -= 10

        reasons.append(
            "Possible established freelancer signal"
        )


    # ------------------------------------------------------------
    # FINAL SIGNAL
    # ------------------------------------------------------------

    if score >= 85:

        signal = "🔥 HIGH"

    elif score >= 55:

        signal = "🟡 MEDIUM"

    else:

        signal = "🔴 LOW"


    return (
        signal,
        max(score, 0),
        reasons
    )


# ================================================================
# 13. MAIN HUNT ENGINE
# ================================================================

def hunt_public_web(
    topic: str = ""
):

    all_results = []

    source_errors = []

    seen_urls = set()


    # ------------------------------------------------------------
    # Search HN
    # ------------------------------------------------------------

    for query in DISCOVERY_QUERIES:

        try:

            results = search_hackernews(
                query
            )

            all_results.extend(
                results
            )

        except Exception as error:

            if not any(
                "Hacker News" in x
                for x in source_errors
            ):

                source_errors.append(
                    "Hacker News: "
                    + str(error)[:180]
                )


    # ------------------------------------------------------------
    # Search GitHub
    # ------------------------------------------------------------

    github_queries = [

        "first client freelancer",

        "freelance clients",

        "client acquisition",

        "getting clients",

        "AI freelancer",

        "automation freelancer"

    ]

    for query in github_queries:

        try:

            results = search_github(
                query
            )

            all_results.extend(
                results
            )

        except Exception as error:

            if not any(
                "GitHub" in x
                for x in source_errors
            ):

                source_errors.append(
                    "GitHub: "
                    + str(error)[:180]
                )


    # ------------------------------------------------------------
    # NOTE:
    # Reddit is deliberately NOT used here.
    #
    # Reddit currently returns HTTP 403 for unauthenticated
    # requests from this bot.
    #
    # We do not want the entire discovery engine to depend on it.
    # ------------------------------------------------------------


    scored = []

    for result in all_results:

        url = (
            result.get(
                "url",
                ""
            )
            .strip()
        )

        if not url:
            continue

        if url in seen_urls:
            continue

        seen_urls.add(url)


        signal, score, reasons = score_prospect(
            result
        )

        if signal == "🔴 LOW":
            continue


        result["signal"] = signal
        result["signal_score"] = score
        result["match_reasons"] = reasons

        scored.append(
            result
        )


    # ------------------------------------------------------------
    # REMOVE DUPLICATE PEOPLE + SAME POSTS
    # ------------------------------------------------------------

    unique = []

    seen_people_titles = set()

    for result in sorted(
        scored,
        key=lambda item: (
            item.get(
                "signal_score",
                0
            ),
            item.get(
                "score",
                0
            )
        ),
        reverse=True
    ):

        person = result.get(
            "person",
            ""
        ).lower()

        title = result.get(
            "title",
            ""
        ).lower()

        key = (
            person,
            title
        )

        if key in seen_people_titles:
            continue

        seen_people_titles.add(
            key
        )

        unique.append(
            result
        )

        if len(unique) >= 12:
            break


    # ============================================================
    # NO RESULTS
    # ============================================================

    if not unique:

        warning_text = ""

        if source_errors:

            warning_text = (
                "\n\nSOURCE WARNINGS:\n"
                + "\n".join(
                    "• " + error
                    for error in source_errors
                )
            )

        return (
            "🎯 11HUNT PROSPECT DISCOVERY\n\n"

            "Mode: Evidence-first public discovery\n\n"

            "Automatic DMs: OFF\n"
            "Automatic comments: OFF\n\n"

            "TARGET:\n"
            "Beginner AI freelancers struggling "
            "to get their first clients\n\n"

            "────────────────────\n\n"

            "No medium/high prospect signals were found.\n\n"

            "This does NOT mean there are no prospects.\n\n"

            "It means the current public search did not "
            "find enough explicit evidence.\n\n"

            "Try:\n\n"

            "/hunt first client\n"
            "/hunt AI freelancer clients\n"
            "/hunt freelance outreach\n"
            "/hunt no clients\n"
            "/hunt beginner AI freelancer"

            + warning_text
        )


    # ============================================================
    # BUILD OUTPUT
    # ============================================================

    lines = [

        "🎯 11HUNT PROSPECT DISCOVERY",

        "",

        "Mode: Evidence-first public discovery",

        "Automatic DMs: OFF",

        "Automatic comments: OFF",

        "",

        "TARGET:",

        "Beginner AI freelancers struggling "
        "to get their first clients",

        "",

        "────────────────────",

        "",

        "Found candidates with explicit "
        "client-acquisition signals.",

        "",

    ]


    for index, result in enumerate(
        unique,
        1
    ):

        evidence = (
            result.get(
                "evidence"
            )
            or
            "No text excerpt available."
        )

        reasons = result.get(
            "match_reasons",
            []
        )


        lines.extend([

            f"{index}. "
            f"{result['signal']} "
            f"— {result['person']} "
            f"({result['platform']})",

            "",

            f"POST: {result['title']}",

            "",

            "EVIDENCE:",

            evidence[:500],

            "",

            "WHY IT MATCHED:",

        ])


        for reason in reasons[:4]:

            lines.append(
                f"• {reason}"
            )


        lines.extend([

            "",

            f"URL: {result['url']}",

            f"CONTACT: {result['contact']}",

            f"SIGNAL SCORE: "
            f"{result['signal_score']}",

            "",

            "────────────────────",

            ""

        ])


    lines.extend([

        "NEXT STEP:",

        "",

        "Open the strongest 3 candidates.",

        "Read their full post/profile.",

        "",

        "Then use:",

        "/outreach",

        "",

        "Paste the actual post/profile text.",

        "",

        "11Hunt will analyze:",

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

        "No automatic messages are sent."

    ])


    if source_errors:

        lines.extend([

            "",

            "SOURCE WARNINGS:",

            *[
                "• " + error
                for error in source_errors
            ]

        ])


    return "\n".join(lines)


# ================================================================
# 14. TELEGRAM KEYBOARD
# ================================================================

def get_keyboard(
    status="🔴 UNVALIDATED"
):

    return InlineKeyboardMarkup([

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
                "🎯 Validate",
                callback_data="btn_validate"
            ),

            InlineKeyboardButton(
                "👥 Find Customers",
                callback_data="btn_find_customers"
            )

        ],

        [

            InlineKeyboardButton(
                "🥊 Challenge",
                callback_data="btn_challenge"
            ),

            InlineKeyboardButton(
                "🔄 Next Opportunity",
                callback_data="btn_next_opp"
            )

        ]

    ])


# ================================================================
# 15. /START
# ================================================================

async def start_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    chat_id = update.effective_chat.id

    await update.message.reply_text(

        "👋 11Hunt Prospect Discovery is active!\n\n"

        "🎯 Target:\n"
        "Beginner AI freelancers struggling "
        "to get their first clients.\n\n"

        "Commands:\n\n"

        "/hunt — discover public prospects\n"
        "/outreach — analyze a candidate\n"
        "/pitch — generate an opportunity hypothesis\n\n"

        "Human approval:\n"
        "✅ Required before every message\n"
        "❌ No automatic DMs\n"
        "❌ No automatic comments\n\n"

        f"Chat ID: `{chat_id}`",

        parse_mode="Markdown"
    )


# ================================================================
# 16. /PITCH
# ================================================================

async def pitch_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    status_msg = await update.message.reply_text(
        "🔎 Building evidence-first opportunity hypothesis..."
    )

    try:

        pitch_text = await asyncio.to_thread(

            generate_gemini_content,

            prompt=(
                "Generate one fresh, unvalidated business "
                "problem that could realistically be solved "
                "by a beginner freelancer or AI builder."
            ),

            system_instruction=SYSTEM_PROMPT

        )

        context.user_data[
            "last_idea"
        ] = pitch_text

        context.user_data[
            "validation_status"
        ] = "🔴 UNVALIDATED"

        await status_msg.delete()

        await update.message.reply_text(

            pitch_text,

            reply_markup=get_keyboard(
                "🔴 UNVALIDATED"
            )

        )

    except Exception as error:

        await status_msg.delete()

        await update.message.reply_text(
            f"❌ Error: {str(error)}"
        )


# ================================================================
# 17. /HUNT
# ================================================================

async def hunt_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    topic = " ".join(
        context.args
    ).strip()


    status_msg = await update.message.reply_text(

        "🔎 11Hunt is searching public sources...\n\n"

        "Target:\n"
        "Beginner AI freelancers struggling "
        "to get clients.\n\n"

        "Automatic outreach: OFF"

    )


    try:

        result = await asyncio.to_thread(

            hunt_public_web,

            topic

        )

        await status_msg.delete()


        # Telegram message size safety

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

            "❌ Hunt failed:\n\n"
            + str(error)

        )


# ================================================================
# 18. /OUTREACH
# ================================================================

async def outreach_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    context.user_data[
        "awaiting_candidate"
    ] = True


    await update.message.reply_text(

        "🎯 11HUNT OUTREACH ASSISTANT\n\n"

        "Paste the actual Reddit/X/HN/GitHub "
        "post, profile text, or candidate description.\n\n"

        "I will analyze:\n\n"

        "• relevance\n"
        "• observed evidence\n"
        "• hypotheses\n"
        "• unknowns\n"
        "• research comment\n"
        "• research DM\n"
        "• follow-up question\n\n"

        "⚠️ Nothing will be sent automatically.\n"
        "You approve and send it yourself."

    )


# ================================================================
# 19. OUTREACH ANALYSIS
# ================================================================

async def outreach_analysis(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    candidate = update.message.text

    context.user_data[
        "awaiting_candidate"
    ] = False


    status_msg = await update.message.reply_text(

        "🔎 Analyzing candidate evidence..."

    )


    try:

        prompt = OUTREACH_PROMPT.format(

            candidate=candidate

        )


        result = await asyncio.to_thread(

            generate_gemini_content,

            prompt=prompt,

            system_instruction=SYSTEM_PROMPT

        )


        prospects = context.user_data.setdefault(

            "outreach_prospects",

            []

        )


        prospects.append({

            "candidate":
                candidate,

            "analysis":
                result,

            "status":
                "prepared",

            "created_at":
                datetime.datetime.now(
                    datetime.timezone.utc
                ).isoformat()

        })


        context.user_data[
            "last_candidate"
        ] = candidate


        await status_msg.delete()


        await update.message.reply_text(

            "🎯 **11HUNT PROSPECT ANALYSIS**\n\n"

            + result

            + "\n\n"

            + "📌 Prospect saved locally in "
              "this Telegram session.\n\n"

            + "⚠️ No message was sent."

        )


    except Exception as error:

        await status_msg.delete()

        await update.message.reply_text(

            f"❌ Error: {str(error)}"

        )


# ================================================================
# 20. BUTTON HANDLER
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


    if query.data == "btn_hunt":

        await query.message.reply_text(

            "🔎 **11HUNT PROSPECT DISCOVERY**\n\n"

            "Target:\n"
            "Beginner AI freelancers struggling "
            "to get their first clients.\n\n"

            "Try:\n\n"

            "`/hunt first client`\n"
            "`/hunt AI freelancer clients`\n"
            "`/hunt freelance outreach`\n"
            "`/hunt no clients`\n\n"

            "The system looks for explicit evidence "
            "of client-acquisition pain.\n\n"

            "Automatic DMs: OFF\n"
            "Automatic comments: OFF"

        )

        return


    if query.data == "btn_outreach":

        context.user_data[
            "awaiting_candidate"
        ] = True

        await query.message.reply_text(

            "🎯 **OUTREACH ASSISTANT**\n\n"

            "Paste the actual post/profile text.\n\n"

            "I will prepare a research comment "
            "and DM for your approval.\n\n"

            "⚠️ Nothing is sent automatically."

        )

        return


    if query.data == "btn_validate":

        last_idea = context.user_data.get(

            "last_idea",

            "No opportunity generated yet."

        )


        status_msg = await query.message.reply_text(

            "🎯 Building customer discovery plan..."

        )


        try:

            prompt = f"""

Opportunity:

{last_idea}

Create an evidence-first customer discovery plan.

Target:
People directly experiencing this problem.

Give:

1. Exact target profile
2. Where to find them
3. 5 non-leading interview questions
4. What evidence would validate the problem
5. What evidence would invalidate it

Do not invent evidence.
"""

            result = await asyncio.to_thread(

                generate_gemini_content,

                prompt,

                SYSTEM_PROMPT

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

        return


    if query.data == "btn_find_customers":

        last_idea = context.user_data.get(

            "last_idea",

            "No opportunity generated yet."

        )


        status_msg = await query.message.reply_text(

            "👥 Finding customer discovery channels..."

        )


        try:

            prompt = f"""

Opportunity:

{last_idea}

Identify:

- exact target customers
- search queries
- communities
- forums
- social platforms
- places where these people publicly discuss the problem

Do not suggest spam.
Do not suggest automatic messaging.

Focus on discovery.
"""


            result = await asyncio.to_thread(

                generate_gemini_content,

                prompt,

                SYSTEM_PROMPT

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

        return


    if query.data == "btn_challenge":

        last_idea = context.user_data.get(

            "last_idea",

            "No opportunity generated yet."

        )


        status_msg = await query.message.reply_text(

            "🥊 Stress-testing the opportunity..."

        )


        try:

            prompt = f"""

Opportunity:

{last_idea}

Challenge this idea.

Ask:

1. Is the problem frequent?
2. Is the problem painful?
3. Are people already solving it?
4. Would they pay?
5. Can a beginner realistically solve it?
6. What evidence would prove the idea wrong?

Be skeptical.
"""


            result = await asyncio.to_thread(

                generate_gemini_content,

                prompt,

                SYSTEM_PROMPT

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

        return


    if query.data == "btn_next_opp":

        await pitch_command(
            update,
            context
        )

        return


# ================================================================
# 21. REPLY HANDLER
# ================================================================

async def reply_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if context.user_data.get(
        "awaiting_candidate"
    ):

        await outreach_analysis(
            update,
            context
        )

        return


# ================================================================
# 22. DAILY OPPORTUNITY
# ================================================================

async def scheduled_daily_pitch(
    context: ContextTypes.DEFAULT_TYPE
):

    if not MY_TELEGRAM_CHAT_ID:
        return


    try:

        pitch_text = await asyncio.to_thread(

            generate_gemini_content,

            prompt=(
                "Find one fresh business problem "
                "that could be investigated by a "
                "beginner AI freelancer."
            ),

            system_instruction=SYSTEM_PROMPT

        )


        await context.bot.send_message(

            chat_id=MY_TELEGRAM_CHAT_ID,

            text=(
                "☀️ TODAY'S 11HUNT OPPORTUNITY\n\n"
                + pitch_text
            ),

            reply_markup=get_keyboard()

        )


    except Exception as error:

        print(
            "Daily Scout Error:",
            error
        )


# ================================================================
# 23. APPLICATION STARTUP
# ================================================================

def main():

    app = (
        Application
        .builder()
        .token(
            TELEGRAM_BOT_TOKEN
        )
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
            filters.TEXT
            & ~filters.COMMAND,
            reply_handler
        )
    )


    # Daily opportunity

    if MY_TELEGRAM_CHAT_ID:

        india_tz = pytz.timezone(
            "Asia/Kolkata"
        )

        target_time = datetime.time(
            hour=8,
            minute=0,
            second=0,
            tzinfo=india_tz
        )

        app.job_queue.run_daily(

            scheduled_daily_pitch,

            time=target_time

        )


    print(
        "🚀 11Hunt Prospect Discovery running..."
    )

    print(
        "🎯 Target: Beginner AI freelancers "
        "struggling to get first clients"
    )

    print(
        "🔎 Public discovery: ON"
    )

    print(
        "📩 Automatic DMs: OFF"
    )

    print(
        "💬 Automatic comments: OFF"
    )

    print(
        "✅ Commands: /start /pitch /hunt /outreach"
    )


    app.run_polling(
        drop_pending_updates=True
    )


# ================================================================
# 24. RUN
# ================================================================

if __name__ == "__main__":

    main()
