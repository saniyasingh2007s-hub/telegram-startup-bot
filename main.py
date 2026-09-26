import os
import asyncio
import threading
import datetime
import pytz
import json
from urllib.parse import urlencode
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


# ================================================================
# 1. HEALTH-CHECK HTTP SERVER
# ================================================================

class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(
            b"11Hunt Evidence-First Prospect Discovery is active!"
        )

    def log_message(self, format, *args):
        return


def run_health_server():
    port = int(os.getenv("PORT", 8080))
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
# 3. 11HUNT CORE SYSTEM PROMPT
# ================================================================

SYSTEM_PROMPT = """
You are the AI Opportunity Scout inside 11Hunt.

11Hunt helps beginner AI freelancers, students, no-code builders,
AI automation freelancers and early AI service providers discover
real opportunities to get their first clients.

The core loop is:

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
PERSONALIZED PITCH
        ↓
CLIENT

You must NOT invent problems.

Strictly classify statements as:

🟢 OBSERVED
Something directly supported by evidence.

🟡 HYPOTHESIS
A reasonable interpretation that still requires validation.

🔴 UNKNOWN
Something we do not know yet.

Never treat:
- a missing feature
- a weak website
- a social media post
- someone asking a question
- low follower count
- a job post
- someone saying they are struggling

as proof that they will pay.

Return:

🔎 OPPORTUNITY HYPOTHESIS

STATUS: 🔴 UNVALIDATED

### 1. EPISTEMIC BREAKDOWN

🟢 OBSERVED:
- 1-2 concrete facts.

🟡 HYPOTHESIS:
- 2-3 possible pains.

🔴 UNKNOWN:
- 3 things that must be validated.

### 2. TARGET PROFILE

• Target Persona:
• Current Situation:
• Likely Existing Workaround:

### 3. VALIDATION MISSION

Target 5 specific people.

Do not pitch a solution yet.

Ask:

1. How are you currently getting clients?
2. What is the hardest part of that process?
3. What have you already tried?
4. When was the last time this caused a real problem?
5. What would you change if you could?
"""


# ================================================================
# 4. VALIDATION PROMPT
# ================================================================

VALIDATION_PROMPT = """
You are a Lean Customer Discovery Expert working inside 11Hunt.

Opportunity Context:
{idea_context}

Current Status:
{current_status}

Create a concrete customer-discovery plan.

🎯 CUSTOMER DISCOVERY ROADMAP

1. TARGET PROFILES

Identify exact types of people we should talk to.

Focus on:
- beginner AI freelancers
- students building AI services
- AI automation freelancers
- no-code builders
- people trying to get their first freelance client
- people who have tried outreach but are getting little/no response

2. WHERE TO FIND THEM

Give 3 specific platforms and search queries.

3. NON-LEADING QUESTIONS

Give 5 neutral questions.

Do NOT pitch a product.

4. SIGNAL EVALUATION

GREEN:
What evidence would prove this is a meaningful problem?

RED:
What evidence would show this is not a meaningful problem?

5. NEXT ACTION

Give one concrete action for today.
"""


# ================================================================
# 5. FIND CUSTOMERS PROMPT
# ================================================================

FIND_CUSTOMERS_PROMPT = """
You are the customer-discovery strategist for 11Hunt.

Opportunity Context:
{idea_context}

We are looking for beginner AI freelancers and early AI builders
who are struggling to acquire their first clients.

Create:

👥 FIND POTENTIAL CUSTOMERS

1. EXACT SEARCH QUERIES

Give copy/paste queries for:

Google
Reddit
X
LinkedIn
YouTube

Focus on people expressing actual client-acquisition problems.

Examples of intent:

"how to get first AI client"
"no clients AI automation"
"sent 50 cold messages no response"
"how to find clients as AI freelancer"
"AI freelancer struggling"
"first freelance client AI"

2. COMMUNITIES

Identify communities where these people naturally discuss their problems.

3. DISCOVERY MESSAGE

Write a short research message.

Do NOT sell.

Do NOT pretend we already have a product.

Do NOT make claims about their business.
"""


# ================================================================
# 6. OUTREACH PROMPT
# ================================================================

OUTREACH_PROMPT = """
You are the evidence-first outreach assistant inside 11Hunt.

TARGET:
Beginner AI freelancers, students and early AI builders struggling
to get their first clients.

Opportunity Context:
{idea_context}

Candidate/Post/Profile:
{candidate}

Analyze ONLY what is actually present in the candidate text.

Never invent:
- their business
- their income
- their number of clients
- their skill level
- their willingness to pay
- their pain

Return:

🎯 RELEVANCE:
HIGH / MEDIUM / LOW

🔎 EVIDENCE:
1-3 concrete things actually visible in the candidate text.

🟡 HYPOTHESIS:
What their problem might be.

🔴 UNKNOWN:
What we still need to know.

💬 PUBLIC COMMENT:
A short natural research-oriented comment.

📩 RESEARCH DM:
A short human message asking about their experience.

Do not pitch a product.

❓ FOLLOW-UP:
One non-leading question.

⚠️ APPROVAL:
The message must be reviewed and sent manually by the user.
"""


# ================================================================
# 7. CHALLENGE PROMPT
# ================================================================

CHALLENGE_PROMPT = """
You are a Devil's Advocate Startup Investor inside 11Hunt.

Opportunity Context:
{idea_context}

Challenge this opportunity.

🥊 HYPOTHESIS CHALLENGE

1. What if beginner AI freelancers don't actually care enough?
2. What if they can acquire clients through existing communities?
3. What if the real problem is skill rather than client acquisition?
4. What if they don't have money to pay for a solution?
5. What if free AI tools already solve most of this?
6. What is the simplest zero-code test that could prove this idea wrong?

Be skeptical.

Do not encourage the founder merely because the idea sounds interesting.
"""


# ================================================================
# 8. ANALYZE FINDINGS
# ================================================================

ANALYZE_FINDINGS_PROMPT = """
You are a truth-seeking customer discovery evaluator.

Original Opportunity:
{idea_context}

Current Status:
{current_status}

Founder Discovery Findings:
{user_findings}

Evaluate ONLY the evidence provided.

📊 DISCOVERY FINDINGS EVALUATION

1. EVIDENCE ANALYSIS

Confirmed:
What observations support the hypothesis?

Disproved:
What assumptions appear wrong?

2. SIGNAL

Choose one:

NO SIGNAL
WEAK SIGNAL
STRONG SIGNAL
PAYMENT SIGNAL

Explain exactly why.

3. STATUS

Choose one:

🔴 UNVALIDATED
🟡 SIGNAL FOUND
🟢 PROBLEM VALIDATED
💰 PAYMENT SIGNAL
❌ KILL

Do not promote an idea simply because someone expressed interest.

4. NEXT ACTIONS

Give 2 concrete next steps.
"""


# ================================================================
# 9. EXPERIMENT PROMPT
# ================================================================

EXPERIMENT_PROMPT = """
You are a Lean Startup Experiment Designer.

Opportunity:
{idea_context}

Discovery Evidence:
{user_findings}

Design the smallest possible demand experiment.

🧪 LOW-FIDELITY DEMAND EXPERIMENT

1. Manual Offer

How can the result be delivered manually?

2. Success Metric

What exact behavior would prove demand?

Examples:

- person agrees to a call
- person gives real data
- person allows a manual pilot
- person agrees to pay
- person introduces another person

3. 24-HOUR TEST

Give a simple test that can be completed within 24 hours.

4. MESSAGE

Write the shortest possible research/demand message.

Do not overpromise.
"""


# ================================================================
# 10. MVP PROMPT
# ================================================================

MVP_PROMPT = """
You are a Technical Product Architect.

Opportunity:
{idea_context}

Validation Status:
{current_status}

Design a lean MVP only if the problem has sufficient evidence.

🛠️ LEAN MVP BLUEPRINT

1. Validated Problem

2. Target User

3. Core Job-To-Be-Done

4. Simplest Solution

5. Fastest Technology Stack

6. 3-Day Build Plan

DAY 1:
Core data and logic.

DAY 2:
Main value delivery.

DAY 3:
Interface and pilot.

Avoid unnecessary features.
"""


# ================================================================
# 11. SALES PROMPT
# ================================================================

SALES_PROMPT = """
You are a B2B customer acquisition strategist.

Opportunity:
{idea_context}

Discovery Results:
{user_findings}

Create:

💼 FIRST CUSTOMER ACQUISITION ROADMAP

1. WHO TO FOLLOW UP WITH

2. VALUE PROPOSITION

3. PAID PILOT

4. FOLLOW-UP MESSAGE

5. OBJECTION HANDLING

Keep claims evidence-based.
Do not fabricate results.
"""


# ================================================================
# 12. GEMINI GENERATOR
# ================================================================

def generate_gemini_content(
    prompt: str,
    system_instruction: str
) -> str:

    last_error = None

    try:
        available_models = []

        for model_info in ai_client.models.list():
            model_id = model_info.name.replace("models/", "")

            methods = getattr(
                model_info,
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

    except Exception as list_error:
        available_models = [
            "gemini-2.5-flash",
            "gemini-1.5-flash"
        ]
        last_error = list_error

    for model in available_models:

        try:
            response = ai_client.models.generate_content(
                model=model,
                contents=prompt,
                config={
                    "system_instruction": system_instruction,
                    "temperature": 0.65
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
# 13. PUBLIC HTTP HELPER
# ================================================================

def _fetch_json(url: str, timeout: int = 15):

    request = Request(
        url,
        headers={
            "User-Agent": (
                "11Hunt/1.0 "
                "(Evidence-First Prospect Discovery)"
            ),
            "Accept": "application/json"
        }
    )

    with urlopen(
        request,
        timeout=timeout
    ) as response:

        return json.loads(
            response.read().decode("utf-8")
        )


# ================================================================
# 14. HACKER NEWS SEARCH
# ================================================================

def _search_hackernews(query: str):

    params = urlencode({
        "query": query,
        "tags": "(story,comment)",
        "hitsPerPage": "20"
    })

    url = (
        "https://hn.algolia.com/api/v1/"
        f"search_by_date?{params}"
    )

    data = _fetch_json(url)

    results = []

    for hit in data.get("hits", []):

        author = hit.get("author") or "[unknown]"

        object_id = hit.get(
            "objectID",
            ""
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

        text = (
            str(text)
            .replace("<p>", " ")
            .replace("</p>", " ")
        )

        text = " ".join(
            text.split()
        )

        if not title and not text:
            continue

        result_url = (
            hit.get("url")
            or (
                f"https://news.ycombinator.com/"
                f"item?id={object_id}"
            )
        )

        results.append({
            "person": f"@{author}",
            "platform": "Hacker News",
            "title": title,
            "evidence": text[:500],
            "url": result_url,
            "contact": "PUBLIC PROFILE / COMMENT",
            "score": hit.get("points") or 0,
            "created": hit.get(
                "created_at_i",
                0
            )
        })

    return results


# ================================================================
# 15. GITHUB SEARCH
# ================================================================

def _search_github(query: str):

    github_query = (
        f'"{query}" '
        f'in:title,body '
        f'is:issue'
    )

    params = urlencode({
        "q": github_query,
        "sort": "updated",
        "order": "desc",
        "per_page": "20"
    })

    url = (
        "https://api.github.com/search/issues?"
        f"{params}"
    )

    data = _fetch_json(url)

    results = []

    for item in data.get("items", []):

        user = (
            item.get("user") or {}
        ).get("login") or "[unknown]"

        body = " ".join(
            (item.get("body") or "").split()
        )

        title = item.get(
            "title",
            "GitHub discussion"
        )

        results.append({
            "person": f"@{user}",
            "platform": "GitHub",
            "title": title,
            "evidence": body[:500],
            "url": item.get(
                "html_url",
                ""
            ),
            "contact": "ISSUE COMMENT / PROFILE",
            "score": item.get(
                "comments",
                0
            ),
            "created": 0
        })

    return results


# ================================================================
# 16. DEV.TO SEARCH
# ================================================================

def _search_devto(query: str):

    tag_map = {
        "freelance": "freelancing",
        "freelancer": "freelancing",
        "clients": "freelancing",
        "client": "freelancing",
        "ai": "ai",
        "artificial intelligence": "ai",
        "automation": "automation",
        "no-code": "nocode",
        "nocode": "nocode",
        "career": "career",
        "student": "career",
    }

    query_lower = query.lower()

    selected_tags = []

    for keyword, tag in tag_map.items():
        if keyword in query_lower:
            if tag not in selected_tags:
                selected_tags.append(tag)

    if not selected_tags:
        selected_tags = [
            "freelancing",
            "ai"
        ]

    results = []

    for tag in selected_tags[:2]:

        params = urlencode({
            "tag": tag,
            "per_page": 30
        })

        url = (
            "https://dev.to/api/articles?"
            f"{params}"
        )

        try:
            data = _fetch_json(url)
        except Exception:
            continue

        for article in data:

            title = article.get(
                "title",
                ""
            )

            description = article.get(
                "description",
                ""
            )

            combined = (
                f"{title} {description}"
            ).lower()

            # Only keep articles that contain
            # actual client-acquisition language.
            intent_terms = [
                "client",
                "clients",
                "freelance",
                "freelancer",
                "first client",
                "getting clients",
                "find clients",
                "cold outreach",
                "customer"
            ]

            if not any(
                term in combined
                for term in intent_terms
            ):
                continue

            author = (
                article.get("user") or {}
            ).get(
                "username",
                "[unknown]"
            )

            results.append({
                "person": f"@{author}",
                "platform": "Dev.to",
                "title": title,
                "evidence": description[:500],
                "url": article.get(
                    "url",
                    ""
                ),
                "contact": "PUBLIC PROFILE / ARTICLE",
                "score": article.get(
                    "positive_reactions_count",
                    0
                ),
                "created": 0
            })

    return results


# ================================================================
# 17. REDDIT
# ================================================================
#
# Reddit frequently returns HTTP 403 to unauthenticated
# server-side requests.
#
# We deliberately DO NOT make Reddit failure crash /hunt.
#
# If Reddit blocks the request, the source is simply marked
# unavailable and the other public sources continue.
# ================================================================

def _search_reddit(query: str):

    params = urlencode({
        "q": query,
        "sort": "new",
        "t": "year",
        "limit": "15",
        "raw_json": "1"
    })

    url = (
        "https://www.reddit.com/search.json?"
        f"{params}"
    )

    try:

        data = _fetch_json(url)

    except HTTPError as error:

        if error.code == 403:
            raise Exception(
                "Reddit denied unauthenticated public search (403)"
            )

        raise

    results = []

    for child in data.get(
        "data",
        {}
    ).get(
        "children",
        []
    ):

        item = child.get(
            "data",
            {}
        )

        title = item.get(
            "title",
            ""
        )

        body = item.get(
            "selftext",
            ""
        )

        if not title and not body:
            continue

        author = (
            item.get("author")
            or "[deleted]"
        )

        permalink = item.get(
            "permalink",
            ""
        )

        if permalink and not permalink.startswith(
            "http"
        ):
            permalink = (
                "https://www.reddit.com"
                + permalink
            )

        results.append({
            "person": f"u/{author}",
            "platform": "Reddit",
            "title": title,
            "evidence": body[:500],
            "url": permalink,
            "contact": (
                "COMMENT / DM"
                if author != "[deleted]"
                else "UNKNOWN"
            ),
            "score": item.get(
                "score",
                0
            ),
            "created": item.get(
                "created_utc",
                0
            )
        })

    return results


# ================================================================
# 18. 11HUNT TARGET SIGNAL SCORING
# ================================================================

def score_prospect(result):

    blob = (
        f"{result.get('title', '')} "
        f"{result.get('evidence', '')}"
    ).lower()

    # ------------------------------------------------------------
    # Strong target signals
    # ------------------------------------------------------------

    freelancer_terms = [
        "freelance",
        "freelancer",
        "freelancing",
        "ai freelancer",
        "freelance ai",
        "freelance developer",
        "freelance designer",
        "ai automation freelancer",
        "no-code freelancer",
        "student freelancer"
    ]

    client_terms = [
        "client",
        "clients",
        "customer",
        "customers",
        "first client",
        "first customer",
        "get clients",
        "getting clients",
        "find clients",
        "finding clients",
        "land clients",
        "landing clients",
        "client acquisition"
    ]

    struggle_terms = [
        "no clients",
        "no client",
        "can't get clients",
        "cant get clients",
        "cannot get clients",
        "struggling to get clients",
        "struggle to get clients",
        "hard to get clients",
        "difficult to get clients",
        "how do i get clients",
        "how to get clients",
        "looking for clients",
        "need clients",
        "need my first client",
        "first client",
        "haven't got a client",
        "havent got a client",
        "zero clients",
        "0 clients",
        "no response",
        "no replies",
        "no one responds",
        "cold outreach",
        "cold dm",
        "cold email",
        "sent messages",
        "sent 50",
        "sent 100"
    ]

    ai_terms = [
        "ai",
        "artificial intelligence",
        "chatgpt",
        "claude",
        "gemini",
        "ai automation",
        "automation",
        "agent",
        "ai agent",
        "n8n",
        "make.com",
        "zapier",
        "no-code",
        "nocode"
    ]

    student_beginner_terms = [
        "student",
        "beginner",
        "new freelancer",
        "starting freelancing",
        "just started",
        "starting out",
        "new to freelancing",
        "learning",
        "beginner freelancer"
    ]

    pain_terms = [
        "struggling",
        "struggle",
        "hard",
        "difficult",
        "problem",
        "issue",
        "frustrated",
        "frustrating",
        "confused",
        "don't know",
        "dont know",
        "help",
        "advice",
        "stuck",
        "failed",
        "not working"
    ]

    # ------------------------------------------------------------
    # Count signals
    # ------------------------------------------------------------

    freelancer_score = sum(
        1
        for term in freelancer_terms
        if term in blob
    )

    client_score = sum(
        1
        for term in client_terms
        if term in blob
    )

    struggle_score = sum(
        1
        for term in struggle_terms
        if term in blob
    )

    ai_score = sum(
        1
        for term in ai_terms
        if term in blob
    )

    beginner_score = sum(
        1
        for term in student_beginner_terms
        if term in blob
    )

    pain_score = sum(
        1
        for term in pain_terms
        if term in blob
    )

    # ------------------------------------------------------------
    # Ignore obvious non-human/bot content
    # ------------------------------------------------------------

    person = (
        result.get(
            "person",
            ""
        )
        .lower()
    )

    bot_terms = [
        "[bot]",
        "github-actions",
        "newsletter",
        "digest",
        "automoderator"
    ]

    if any(
        term in person
        for term in bot_terms
    ):
        return "🔴 LOW", 0

    # ------------------------------------------------------------
    # Scoring
    # ------------------------------------------------------------

    score = 0

    if freelancer_score:
        score += 30

    if ai_score:
        score += 20

    if client_score:
        score += 15

    if struggle_score:
        score += 30

    if beginner_score:
        score += 15

    if pain_score:
        score += 10

    # Strongest signal:
    # AI/freelancer + explicit client struggle
    if (
        (freelancer_score or beginner_score)
        and ai_score
        and struggle_score
    ):
        score += 30

    # ------------------------------------------------------------
    # Signal classification
    # ------------------------------------------------------------

    if score >= 100:
        return "🔥 HIGH", score

    if score >= 65:
        return "🟡 MEDIUM", score

    return "🔴 LOW", score


# ================================================================
# 19. MAIN 11HUNT PROSPECT HUNT
# ================================================================

def hunt_public_web(topic: str) -> str:

    """
    11Hunt Prospect Discovery.

    Target:
    Beginner AI freelancers and early AI builders
    struggling to get their first clients.

    Automatic DMs: OFF
    Automatic comments: OFF
    """

    # ------------------------------------------------------------
    # Default target
    # ------------------------------------------------------------

    if not topic:

        topic = (
            "beginner AI freelancers "
            "struggling to get first clients"
        )

    # ------------------------------------------------------------
    # Search queries
    # ------------------------------------------------------------

    search_queries = [

        "beginner AI freelancer first client",

        "AI freelancer struggling to get clients",

        "how to get first AI client",

        "AI freelancer no clients",

        "AI automation freelancer looking for clients",

        "student AI freelancer clients",

        "AI freelancer cold outreach no response",

        "freelancer sent messages no clients",

        "starting AI freelancing how to get clients",

        "AI automation freelance client acquisition",

        "beginner freelancer finding clients",

        "AI freelancer struggling client acquisition"

    ]

    # If the user explicitly supplied a focused
    # search topic, put it first.
    if topic.strip():

        custom_query = topic.strip()

        if custom_query.lower() not in [
            q.lower()
            for q in search_queries
        ]:
            search_queries.insert(
                0,
                custom_query
            )

    # Limit to prevent excessive API requests.
    search_queries = search_queries[:8]

    all_results = []

    source_errors = []

    # ------------------------------------------------------------
    # Search public sources
    # ------------------------------------------------------------

    for query in search_queries:

        sources = [

            (
                "Hacker News",
                _search_hackernews
            ),

            (
                "GitHub",
                _search_github
            ),

            (
                "Dev.to",
                _search_devto
            ),

            (
                "Reddit",
                _search_reddit
            )

        ]

        for source_name, source_function in sources:

            try:

                results = source_function(
                    query
                )

                all_results.extend(
                    results
                )

            except Exception as error:

                error_text = (
                    f"{source_name}: "
                    f"{str(error)[:180]}"
                )

                # Avoid printing the same
                # source error repeatedly.
                if not any(
                    source_name in existing
                    for existing in source_errors
                ):
                    source_errors.append(
                        error_text
                    )

    # ------------------------------------------------------------
    # Score + deduplicate
    # ------------------------------------------------------------

    scored = []

    seen_urls = set()

    for result in all_results:

        url = (
            result.get(
                "url",
                ""
            )
            or ""
        ).strip()

        if not url:
            continue

        if url in seen_urls:
            continue

        seen_urls.add(url)

        signal, score = score_prospect(
            result
        )

        if signal == "🔴 LOW":
            continue

        result["signal"] = signal
        result["signal_score"] = score

        scored.append(
            result
        )

    scored.sort(
        key=lambda result: (
            result.get(
                "signal_score",
                0
            ),
            result.get(
                "score",
                0
            )
        ),
        reverse=True
    )

    prospects = scored[:10]

    # ============================================================
    # NO RESULTS
    # ============================================================

    if not prospects:

        lines = [

            "🎯 11HUNT PROSPECT DISCOVERY",
            "",
            "Mode: Evidence-first public discovery",
            "",
            "Automatic DMs: OFF",
            "Automatic comments: OFF",
            "",
            "TARGET:",
            "Beginner AI freelancers struggling to get their first clients",
            "",
            "────────────────────",
            "",
            "No medium/high prospect signals were found.",
            "",
            "This does NOT mean there are no prospects.",
            "",
            "It means the current public search did not find enough",
            "evidence matching the target.",
            "",
            "Try:",
            "",
            "/hunt students freelancers",
            "",
            "/hunt AI freelancers looking for clients",
            "",
            "/hunt people struggling with client acquisition",
            "",
            "Sources searched:",
            "• Hacker News",
            "• GitHub",
            "• Dev.to",
            "• Reddit",
        ]

        if source_errors:

            lines.extend([
                "",
                "SOURCE STATUS:"
            ])

            for error in source_errors:
                lines.append(
                    f"• {error}"
                )

        return "\n".join(lines)

    # ============================================================
    # RESULTS
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
        "Beginner AI freelancers struggling to get their first clients",
        "",
        "────────────────────",
        "",
        f"Found {len(prospects)} potential public signals.",
        "",
        "IMPORTANT:",
        "These are signals, NOT confirmed prospects.",
        "Open the source and manually validate before contacting.",
        ""

    ]

    for index, prospect in enumerate(
        prospects,
        1
    ):

        evidence = (
            prospect.get(
                "evidence"
            )
            or
            "No excerpt available."
        )

        lines.extend([

            f"{index}. {prospect['signal']} "
            f"— {prospect['person']} "
            f"({prospect['platform']})",

            f"POST: {prospect.get('title', 'Untitled')}",

            f"EVIDENCE: {evidence}",

            f"URL: {prospect.get('url', '')}",

            f"CONTACT: {prospect.get('contact', 'UNKNOWN')}",

            f"SIGNAL SCORE: {prospect.get('signal_score', 0)}",

            ""

        ])

    lines.extend([

        "────────────────────",

        "NEXT STEP:",

        "Open the strongest 3 candidates.",

        "Read their full post/profile.",

        "Then use:",

        "/outreach",

        "Paste the actual post/profile text.",

        "",
        "11Hunt will analyze the evidence and prepare",
        "a research comment + DM for YOUR approval.",
        "",
        "No automatic messages are sent."

    ])

    if source_errors:

        lines.extend([
            "",
            "SOURCE WARNINGS:"
        ])

        for error in source_errors:
            lines.append(
                f"• {error}"
            )

    return "\n".join(lines)


# ================================================================
# 20. TELEGRAM KEYBOARD
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
# 21. /START
# ================================================================

async def start_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    chat_id = update.effective_chat.id

    await update.message.reply_text(

        "👋 11Hunt Evidence-First Prospect Discovery is active!\n\n"

        "🎯 Target:\n"
        "Beginner AI freelancers struggling to get their first clients.\n\n"

        "Commands:\n"
        "/pitch — Generate opportunity hypothesis\n"
        "/hunt — Find public prospect signals\n"
        "/outreach — Analyze a candidate manually\n\n"

        f"Chat ID: `{chat_id}`",

        parse_mode="Markdown"
    )


# ================================================================
# 22. /PITCH
# ================================================================

async def pitch_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    status_message = await update.message.reply_text(
        "🔎 Scouting a fresh market opportunity..."
    )

    try:

        pitch_text = await asyncio.to_thread(

            generate_gemini_content,

            prompt=(
                "Scout a fresh unvalidated opportunity "
                "related to beginner AI freelancers, "
                "AI builders, or client acquisition."
            ),

            system_instruction=SYSTEM_PROMPT
        )

        context.user_data[
            "last_idea"
        ] = pitch_text

        context.user_data[
            "validation_status"
        ] = "🔴 UNVALIDATED"

        await status_message.delete()

        await update.message.reply_text(
            text=pitch_text,
            reply_markup=get_keyboard(
                "🔴 UNVALIDATED"
            )
        )

    except Exception as error:

        await status_message.delete()

        await update.message.reply_text(
            f"❌ Error: {str(error)}"
        )


# ================================================================
# 23. DAILY PITCH
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
                "Scout a fresh unvalidated opportunity "
                "for beginner AI freelancers or "
                "early AI builders."
            ),

            system_instruction=SYSTEM_PROMPT
        )

        await context.bot.send_message(

            chat_id=MY_TELEGRAM_CHAT_ID,

            text=(
                "☀️ TODAY'S 11HUNT OPPORTUNITY\n\n"
                f"{pitch_text}"
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
# 24. /OUTREACH
# ================================================================

async def outreach_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    last_idea = context.user_data.get(
        "last_idea"
    )

    if not last_idea:

        await update.message.reply_text(

            "🛑 No active opportunity yet.\n\n"

            "Use /pitch first, then use "
            "🎯 Outreach Assistant."

        )

        return

    context.user_data[
        "awaiting_candidate"
    ] = True

    await update.message.reply_text(

        "🎯 OUTREACH ASSISTANT\n\n"

        "Paste a Reddit/X post, comment, "
        "profile text, GitHub discussion, "
        "or candidate description.\n\n"

        "I'll analyze:\n"
        "• relevance\n"
        "• evidence\n"
        "• hypothesis\n"
        "• unknowns\n"
        "• public comment\n"
        "• research DM\n"
        "• follow-up question\n\n"

        "⚠️ Nothing will be sent automatically."

    )


# ================================================================
# 25. OUTREACH ANALYSIS
# ================================================================

async def outreach_analysis(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    candidate = update.message.text

    last_idea = context.user_data.get(
        "last_idea",
        "Beginner AI freelancer client acquisition"
    )

    status_message = await update.message.reply_text(
        "🔎 Evaluating prospect evidence..."
    )

    try:

        prompt = OUTREACH_PROMPT.format(

            idea_context=last_idea,

            candidate=candidate

        )

        result = await asyncio.to_thread(

            generate_gemini_content,

            prompt=prompt,

            system_instruction=(
                "You are an evidence-first "
                "customer discovery and "
                "outreach assistant."
            )
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

        await status_message.delete()

        await update.message.reply_text(

            "🎯 PROSPECT ANALYSIS\n\n"

            f"{result}\n\n"

            f"📌 Saved as prospect "
            f"#{len(prospects)} in this Telegram session."

        )

    except Exception as error:

        context.user_data[
            "awaiting_candidate"
        ] = False

        await status_message.delete()

        await update.message.reply_text(
            f"❌ Error: {str(error)}"
        )


# ================================================================
# 26. /HUNT
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

    status_message = await update.message.reply_text(

        "🔎 11Hunt is searching public sources...\n\n"

        "Target:\n"
        "Beginner AI freelancers struggling "
        "to get their first clients.\n\n"

        "Automatic DMs: OFF\n"
        "Automatic comments: OFF"

    )

    try:

        result = await asyncio.to_thread(

            hunt_public_web,

            topic

        )

        await status_message.delete()

        # Telegram practical message size.
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

        await status_message.delete()

        await update.message.reply_text(

            "❌ Hunt failed:\n"
            f"{str(error)}"

        )


# ================================================================
# 27. BUTTON HANDLER
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
        "Beginner AI freelancer client acquisition"
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

            "Automatic DMs: OFF\n"
            "Automatic comments: OFF\n\n"

            "Run:\n"
            "`/hunt`\n\n"

            "Or focus the search:\n"
            "`/hunt AI freelancers looking for clients`\n\n"

            "`/hunt students struggling to get clients`",

            parse_mode="Markdown"

        )

    # ------------------------------------------------------------
    # OUTREACH
    # ------------------------------------------------------------

    elif query.data == "btn_outreach":

        context.user_data[
            "awaiting_candidate"
        ] = True

        await query.message.reply_text(

            "🎯 OUTREACH ASSISTANT\n\n"

            "Paste the actual public post/profile text.\n\n"

            "I'll prepare:\n"
            "• Evidence\n"
            "• Hypothesis\n"
            "• Unknowns\n"
            "• Public comment\n"
            "• Research DM\n"
            "• Follow-up question\n\n"

            "⚠️ You approve and send manually."

        )

    # ------------------------------------------------------------
    # VALIDATE
    # ------------------------------------------------------------

    elif query.data == "btn_validate":

        status_message = await query.message.reply_text(
            "🎯 Building customer discovery plan..."
        )

        try:

            prompt = VALIDATION_PROMPT.format(

                idea_context=last_idea,

                current_status=current_status

            )

            result = await asyncio.to_thread(

                generate_gemini_content,

                prompt=prompt,

                system_instruction=(
                    "You are a Customer Discovery Expert."
                )

            )

            await status_message.delete()

            await query.message.reply_text(
                result
            )

        except Exception as error:

            await status_message.delete()

            await query.message.reply_text(
                f"❌ Error: {str(error)}"
            )

    # ------------------------------------------------------------
    # FIND CUSTOMERS
    # ------------------------------------------------------------

    elif query.data == "btn_find_customers":

        status_message = await query.message.reply_text(
            "👥 Finding target customer channels..."
        )

        try:

            prompt = FIND_CUSTOMERS_PROMPT.format(
                idea_context=last_idea
            )

            result = await asyncio.to_thread(

                generate_gemini_content,

                prompt=prompt,

                system_instruction=(
                    "You are a Lead Generation Specialist."
                )

            )

            await status_message.delete()

            await query.message.reply_text(
                result
            )

        except Exception as error:

            await status_message.delete()

            await query.message.reply_text(
                f"❌ Error: {str(error)}"
            )

    # ------------------------------------------------------------
    # ENTER FINDINGS
    # ------------------------------------------------------------

    elif query.data == "btn_enter_findings":

        context.user_data[
            "awaiting_findings"
        ] = True

        await query.message.reply_text(

            "📥 DISCOVERY FINDINGS INPUT\n\n"

            "Send your notes.\n\n"

            "Include:\n"
            "1. Number of people interviewed\n"
            "2. What they said\n"
            "3. Their current workflow\n"
            "4. What they have tried\n"
            "5. Any willingness-to-pay evidence"

        )

    # ------------------------------------------------------------
    # CHALLENGE
    # ------------------------------------------------------------

    elif query.data == "btn_challenge":

        status_message = await query.message.reply_text(
            "🥊 Stress-testing the hypothesis..."
        )

        try:

            prompt = CHALLENGE_PROMPT.format(
                idea_context=last_idea
            )

            result = await asyncio.to_thread(

                generate_gemini_content,

                prompt=prompt,

                system_instruction=(
                    "You are a Devil's Advocate Investor."
                )

            )

            await status_message.delete()

            await query.message.reply_text(
                result
            )

        except Exception as error:

            await status_message.delete()

            await query.message.reply_text(
                f"❌ Error: {str(error)}"
            )

    # ------------------------------------------------------------
    # EXPERIMENT
    # ------------------------------------------------------------

    elif query.data == "btn_experiment":

        status_message = await query.message.reply_text(
            "🧪 Designing smallest demand experiment..."
        )

        try:

            user_findings = context.user_data.get(
                "last_findings",
                "No discovery findings recorded yet."
            )

            prompt = EXPERIMENT_PROMPT.format(

                idea_context=last_idea,

                user_findings=user_findings

            )

            result = await asyncio.to_thread(

                generate_gemini_content,

                prompt=prompt,

                system_instruction=(
                    "You are a Lean Startup Experiment Designer."
                )

            )

            await status_message.delete()

            await query.message.reply_text(
                result
            )

        except Exception as error:

            await status_message.delete()

            await query.message.reply_text(
                f"❌ Error: {str(error)}"
            )

    # ------------------------------------------------------------
    # BUILD MVP
    # ------------------------------------------------------------

    elif query.data == "btn_build_mvp":

        if current_status in [
            "🔴 UNVALIDATED",
            "🟡 SIGNAL FOUND"
        ]:

            await query.message.reply_text(

                f"🛑 BUILD LOCKED\n\n"
                f"Current status: {current_status}\n\n"
                "Collect more evidence before building."

            )

            return

        status_message = await query.message.reply_text(
            "⚙️ Creating lean MVP blueprint..."
        )

        try:

            prompt = MVP_PROMPT.format(

                idea_context=last_idea,

                current_status=current_status

            )

            result = await asyncio.to_thread(

                generate_gemini_content,

                prompt=prompt,

                system_instruction=(
                    "You are a Technical Product Architect."
                )

            )

            await status_message.delete()

            await query.message.reply_text(
                result
            )

        except Exception as error:

            await status_message.delete()

            await query.message.reply_text(
                f"❌ Error: {str(error)}"
            )

    # ------------------------------------------------------------
    # SALES
    # ------------------------------------------------------------

    elif query.data == "btn_sales":

        if current_status in [
            "🔴 UNVALIDATED",
            "🟡 SIGNAL FOUND"
        ]:

            await query.message.reply_text(

                f"🛑 SALES LOCKED\n\n"
                f"Current status: {current_status}\n\n"
                "Validate the problem first."

            )

            return

        status_message = await query.message.reply_text(
            "💼 Creating first-customer strategy..."
        )

        try:

            user_findings = context.user_data.get(
                "last_findings",
                "Validated problem."
            )

            prompt = SALES_PROMPT.format(

                idea_context=last_idea,

                user_findings=user_findings

            )

            result = await asyncio.to_thread(

                generate_gemini_content,

                prompt=prompt,

                system_instruction=(
                    "You are a B2B Sales Strategist."
                )

            )

            await status_message.delete()

            await query.message.reply_text(
                result
            )

        except Exception as error:

            await status_message.delete()

            await query.message.reply_text(
                f"❌ Error: {str(error)}"
            )

    # ------------------------------------------------------------
    # NEXT OPPORTUNITY
    # ------------------------------------------------------------

    elif query.data == "btn_next_opp":

        status_message = await query.message.reply_text(
            "🔄 Scouting next opportunity..."
        )

        try:

            pitch_text = await asyncio.to_thread(

                generate_gemini_content,

                prompt=(
                    "Scout a fresh unvalidated "
                    "market opportunity for "
                    "beginner AI freelancers."
                ),

                system_instruction=SYSTEM_PROMPT

            )

            context.user_data[
                "last_idea"
            ] = pitch_text

            context.user_data[
                "validation_status"
            ] = "🔴 UNVALIDATED"

            await status_message.delete()

            await query.message.reply_text(

                text=pitch_text,

                reply_markup=get_keyboard(
                    "🔴 UNVALIDATED"
                )

            )

        except Exception as error:

            await status_message.delete()

            await query.message.reply_text(
                f"❌ Error: {str(error)}"
            )


# ================================================================
# 28. TEXT REPLY HANDLER
# ================================================================

async def reply_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    # ------------------------------------------------------------
    # Candidate awaiting
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
    # Findings awaiting
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
            "Beginner AI freelancer client acquisition"
        )

        current_status = context.user_data.get(
            "validation_status",
            "🔴 UNVALIDATED"
        )

        status_message = await update.message.reply_text(
            "🧐 Evaluating discovery evidence..."
        )

        try:

            prompt = ANALYZE_FINDINGS_PROMPT.format(

                idea_context=last_idea,

                current_status=current_status,

                user_findings=user_findings

            )

            evaluation = await asyncio.to_thread(

                generate_gemini_content,

                prompt=prompt,

                system_instruction=(
                    "You are a Truth-Seeking "
                    "Startup Evaluator."
                )

            )

            # ----------------------------------------------------
            # Status update
            # ----------------------------------------------------

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

            await status_message.delete()

            await update.message.reply_text(

                "📋 EVALUATION & STATUS UPDATE\n\n"

                f"Updated Status: {new_status}\n\n"

                f"{evaluation}",

                reply_markup=get_keyboard(
                    new_status
                )

            )

        except Exception as error:

            await status_message.delete()

            await update.message.reply_text(
                f"❌ Error: {str(error)}"
            )


# ================================================================
# 29. APPLICATION STARTUP
# ================================================================

def main():

    application = (
        Application
        .builder()
        .token(
            TELEGRAM_BOT_TOKEN
        )
        .build()
    )

    # ------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------

    application.add_handler(
        CommandHandler(
            "start",
            start_command
        )
    )

    application.add_handler(
        CommandHandler(
            "pitch",
            pitch_command
        )
    )

    application.add_handler(
        CommandHandler(
            "hunt",
            hunt_command
        )
    )

    application.add_handler(
        CommandHandler(
            "outreach",
            outreach_command
        )
    )

    # ------------------------------------------------------------
    # Buttons
    # ------------------------------------------------------------

    application.add_handler(
        CallbackQueryHandler(
            button_handler
        )
    )

    # ------------------------------------------------------------
    # Normal text messages
    # ------------------------------------------------------------

    application.add_handler(

        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            reply_handler
        )

    )

    # ------------------------------------------------------------
    # Daily opportunity
    # ------------------------------------------------------------

    if MY_TELEGRAM_CHAT_ID:

        india_timezone = pytz.timezone(
            "Asia/Kolkata"
        )

        target_time = datetime.time(
            hour=8,
            minute=0,
            second=0,
            tzinfo=india_timezone
        )

        application.job_queue.run_daily(

            scheduled_daily_pitch,

            time=target_time

        )

    # ------------------------------------------------------------
    # Start
    # ------------------------------------------------------------

    print(
        "🚀 11Hunt Evidence-First Prospect Discovery running..."
    )

    print(
        "🎯 Target: Beginner AI freelancers struggling "
        "to get their first clients"
    )

    print(
        "🔒 Automatic DMs: OFF"
    )

    print(
        "🔒 Automatic comments: OFF"
    )

    print(
        "✅ Commands: /start /pitch /hunt /outreach"
    )

    application.run_polling(
        drop_pending_updates=True
    )


# ================================================================
# 30. RUN
# ================================================================

if __name__ == "__main__":
    main()
