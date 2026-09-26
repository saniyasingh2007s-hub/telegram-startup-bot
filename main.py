import os
import asyncio
import threading
import datetime
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
# 1. HEALTH CHECK SERVER
# ================================================================

class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(
            b"11Hunt Evidence-First Prospect Discovery Agent is active!"
        )

    def log_message(self, format, *args):
        # Keep hosting logs clean.
        return


def run_health_server():
    port = int(os.getenv("PORT", "8080"))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    server.serve_forever()


threading.Thread(target=run_health_server, daemon=True).start()


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
# 3. DEFAULT 11HUNT PROJECT
# ================================================================

DEFAULT_PROJECT = """
11Hunt is an evidence-first opportunity discovery platform for
students, beginner freelancers, AI/no-code builders and small
agencies.

The product helps people find genuine business problems that they
can realistically solve and sell.

Core workflow:

Business / Person
→ Evidence
→ Problem Signal
→ Opportunity
→ Solution
→ Personalized Pitch
→ Client

11Hunt should NOT assume that a missing feature means a real problem.

We need evidence before making a claim.

The current goal is to discover potential users, early adopters,
design partners, or people publicly experiencing the problem of
finding clients, discovering real business problems, validating
opportunities, or turning their AI/no-code skills into paid work.
"""

DEFAULT_TARGET = """
Potential 11Hunt users:

- students trying to start freelancing
- beginner freelancers
- AI freelancers
- no-code builders
- automation freelancers
- small AI agencies
- student entrepreneurs
- people learning AI/automation and trying to get clients
- people publicly asking how to find clients
- people struggling with cold outreach or getting their first client
- people looking for practical freelance opportunities
"""


# ================================================================
# 4. AI PROMPTS
# ================================================================

SYSTEM_PROMPT = """
You are the Chief AI Opportunity Scout for 11Hunt.

11Hunt helps beginners, students, freelancers, AI/no-code builders
and small agencies discover genuine business problems that they can
realistically solve and sell.

Your job is NOT to manufacture problems.

You must separate:

🟢 OBSERVED
Something directly supported by evidence.

🟡 HYPOTHESIS
A reasonable interpretation that still needs validation.

🔴 UNKNOWN
Something we do not know yet.

Never treat:
- a missing feature
- a complaint without context
- a generic request
- a hypothetical statement

as proof of a real business problem.

Always use evidence-first reasoning.
"""


OPPORTUNITY_PROMPT = """
Scout one specific, unvalidated business problem or workflow
friction that could potentially become a realistic opportunity.

Return:

🔎 OPPORTUNITY HYPOTHESIS

STATUS: 🔴 UNVALIDATED

### 1. EVIDENCE BREAKDOWN

🟢 OBSERVED:
- 1-2 observable market facts.

🟡 HYPOTHESIS:
- 2-3 possible problems or friction points.

🔴 UNKNOWN:
- 3 things that must be validated with real people.

### 2. TARGET PERSONA

• Who experiences this?
• What are they trying to accomplish?
• What are they currently doing?

### 3. VALIDATION MISSION

Find 5 real people/businesses matching the target.

Do NOT pitch a solution yet.

Questions:

1. How do you currently handle this?
2. What is the hardest part?
3. When did this last cause a problem?
4. What do you currently do when it happens?
"""


VALIDATION_PROMPT = """
You are a Lean Customer Discovery Expert.

Opportunity:

{idea_context}

Create a concrete validation plan.

Return:

🎯 CUSTOMER DISCOVERY ROADMAP

1. TARGET PROFILE
Who exactly should be interviewed?

2. WHERE TO FIND THEM
Give 5 specific search locations/platforms.

3. SEARCH QUERIES
Give copy-paste search queries.

4. NON-LEADING QUESTIONS
Give 5 neutral questions.

5. REAL SIGNALS
What answers would indicate meaningful pain?

6. INVALIDATION SIGNALS
What answers would indicate this is probably not important?

Do not assume the problem is real.
"""


FIND_CUSTOMERS_PROMPT = """
You are a customer discovery strategist.

Project:

{project}

Target:

{target}

Create a prospect discovery blueprint.

Return:

👥 FIND POTENTIAL CUSTOMERS

1. EXACT PERSONA
2. SEARCH QUERIES
3. REDDIT SEARCHES
4. LINKEDIN SEARCH IDEAS
5. X/TWITTER SEARCH IDEAS
6. COMMUNITIES
7. WHAT EVIDENCE TO LOOK FOR
8. WHAT NOT TO COUNT AS EVIDENCE
9. NON-PITCH RESEARCH MESSAGE
"""


OUTREACH_PROMPT = """
You are an evidence-first outreach assistant.

PROJECT:
{project}

TARGET:
{target}

CANDIDATE / POST:
{candidate}

Analyze ONLY the information provided.

Never invent:
- their business
- their pain
- their budget
- their job
- their intentions
- their experience

Return:

🎯 PROSPECT RELEVANCE
HIGH / MEDIUM / LOW

🔎 EVIDENCE
List concrete evidence from the candidate text.

🟡 INFERENCE
What might be true but is not confirmed.

🔴 UNKNOWN
What we still need to learn.

💬 PUBLIC COMMENT
Write a short natural research-oriented comment.
Do NOT pitch a product.

📩 RESEARCH DM
Write a short message asking about their actual experience.
Do NOT pretend we already know their problem.

❓ FOLLOW-UP
Give one non-leading question.

⚠️ HUMAN APPROVAL REQUIRED
The message must be reviewed and manually sent by the user.
"""


CHALLENGE_PROMPT = """
You are a skeptical startup advisor.

Project / opportunity:

{idea_context}

Challenge the opportunity.

Return:

🥊 HYPOTHESIS CHALLENGE

1. What if the problem is too rare?
2. What if the current workaround is good enough?
3. What if people do not have budget?
4. What if they do not care enough to change?
5. What evidence would prove this hypothesis wrong?
6. What can be tested manually in 24 hours?
"""


ANALYZE_FINDINGS_PROMPT = """
You are a truth-seeking customer discovery evaluator.

Original opportunity:

{idea_context}

Current status:

{current_status}

Discovery findings:

{user_findings}

Evaluate ONLY the supplied findings.

Return:

📊 DISCOVERY FINDINGS EVALUATION

1. CONFIRMED EVIDENCE
2. SUPPORTED HYPOTHESES
3. DISPROVED HYPOTHESES
4. UNKNOWN
5. TRUTH SIGNAL

Choose exactly one:

NO SIGNAL
WEAK SIGNAL
STRONG SIGNAL
PAYMENT SIGNAL

6. RECOMMENDED STATUS

Choose one:

🔴 UNVALIDATED
🟡 SIGNAL FOUND
🟢 PROBLEM VALIDATED
💰 PAYMENT SIGNAL
❌ KILL

7. NEXT TWO ACTIONS
"""


EXPERIMENT_PROMPT = """
You are a Lean Startup Experiment Designer.

Project / opportunity:

{idea_context}

Findings:

{user_findings}

Design the smallest possible demand experiment.

Return:

🧪 LOW-FIDELITY DEMAND EXPERIMENT

1. MANUAL / CONCIERGE TEST
2. EXACT CUSTOMER ACTION REQUIRED
3. SUCCESS METRIC
4. FAILURE CONDITION
5. 24-HOUR TEST
6. MESSAGE TO SEND TO PARTICIPANTS

Do not recommend building software before demand is tested.
"""


MVP_PROMPT = """
You are a technical product architect.

Opportunity:

{idea_context}

Validation status:

{current_status}

Create a lean MVP plan.

Return:

🛠️ LEAN MVP BUILD BLUEPRINT

1. Validated problem
2. Target user
3. Core workflow
4. Minimum features
5. What NOT to build
6. Fastest implementation approach
7. 3-day build sprint
8. Pilot test
"""


SALES_PROMPT = """
You are a B2B customer acquisition strategist.

Project:

{idea_context}

Evidence:

{user_findings}

Create a first-customer strategy.

Return:

💼 FIRST CUSTOMER ACQUISITION ROADMAP

1. Who to contact first
2. Why they are qualified
3. Pilot offer
4. Personalized outreach
5. Follow-up
6. Common objections
7. What evidence should be collected before asking for payment
"""


SEARCH_QUERY_PROMPT = """
You are a prospect research strategist.

PROJECT:
{project}

TARGET:
{target}

Generate public-web searches that can discover real people who may
be experiencing the target problem or actively looking for the type
of help/opportunity described.

Rules:

- Search for people, not generic articles.
- Search for first-hand experiences.
- Search for questions.
- Search for frustrations.
- Search for people asking for help.
- Search for people trying to solve the problem.
- Avoid generic "best tools" content.
- Avoid marketing spam.
- Avoid company promotional pages.

Return ONLY 10 search queries, one per line.

Queries should work reasonably well on:
Reddit
Hacker News
GitHub
"""


# ================================================================
# 5. GEMINI ENGINE
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

            if "generateContent" in methods or not methods:
                available_models.append(model_id)

        # Prefer flash models.
        available_models.sort(
            key=lambda name: (
                "flash" not in name.lower(),
                name
            )
        )

    except Exception as list_error:
        last_error = list_error

        available_models = [
            "gemini-2.5-flash",
            "gemini-1.5-flash",
        ]

    for model in available_models:

        try:

            response = ai_client.models.generate_content(
                model=model,
                contents=prompt,
                config={
                    "system_instruction": system_instruction,
                    "temperature": 0.4,
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
# 6. PUBLIC WEB HELPERS
# ================================================================

def _fetch_json(url: str, timeout: int = 15):

    request = Request(
        url,
        headers={
            "User-Agent":
                "11Hunt-Prospect-Discovery/1.0"
        },
    )

    with urlopen(
        request,
        timeout=timeout
    ) as response:

        return json.loads(
            response.read().decode("utf-8")
        )


# ================================================================
# 7. REDDIT SEARCH
# ================================================================

def _search_reddit(query: str):

    params = urlencode({
        "q": query,
        "sort": "new",
        "t": "year",
        "limit": "15",
        "raw_json": "1",
    })

    url = (
        "https://www.reddit.com/search.json?"
        + params
    )

    data = _fetch_json(url)

    results = []

    for child in data.get(
        "data",
        {}
    ).get(
        "children",
        []
    ):

        item = child.get("data", {})

        title = item.get(
            "title",
            ""
        ).strip()

        body = item.get(
            "selftext",
            ""
        ).strip()

        author = (
            item.get("author")
            or "[deleted]"
        )

        permalink = item.get(
            "permalink",
            ""
        )

        if permalink and not permalink.startswith("http"):
            permalink = (
                "https://www.reddit.com"
                + permalink
            )

        if not title and not body:
            continue

        results.append({
            "platform": "Reddit",
            "person": f"u/{author}",
            "title": title or "Reddit post",
            "evidence": " ".join(body.split())[:600],
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
        })

    return results


# ================================================================
# 8. HACKER NEWS SEARCH
# ================================================================

def _search_hackernews(query: str):

    params = urlencode({
        "query": query,
        "tags": "(story,comment)",
        "hitsPerPage": "15",
    })

    url = (
        "https://hn.algolia.com/api/v1/"
        "search_by_date?"
        + params
    )

    data = _fetch_json(url)

    results = []

    for hit in data.get(
        "hits",
        []
    ):

        author = (
            hit.get("author")
            or "[unknown]"
        )

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

        # Remove simple HTML.
        text = re.sub(
            r"<[^>]+>",
            " ",
            str(text)
        )

        text = " ".join(
            text.split()
        )

        item_url = (
            hit.get("url")
            or (
                "https://news.ycombinator.com/"
                f"item?id={object_id}"
                if object_id
                else ""
            )
        )

        results.append({
            "platform": "Hacker News",
            "person": f"@{author}",
            "title": title,
            "evidence": text[:600],
            "url": item_url,
            "contact":
                "PUBLIC PROFILE / COMMENT",
            "score":
                hit.get("points") or 0,
        })

    return results


# ================================================================
# 9. GITHUB SEARCH
# ================================================================

def _search_github(query: str):

    github_query = (
        f"{query} "
        "in:title,body "
        "is:issue"
    )

    params = urlencode({
        "q": github_query,
        "sort": "updated",
        "order": "desc",
        "per_page": "15",
    })

    url = (
        "https://api.github.com/search/issues?"
        + params
    )

    data = _fetch_json(url)

    results = []

    for item in data.get(
        "items",
        []
    ):

        user = (
            item.get("user") or {}
        ).get(
            "login"
        ) or "[unknown]"

        body = " ".join(
            (
                item.get("body")
                or ""
            ).split()
        )

        results.append({
            "platform": "GitHub",
            "person": f"@{user}",
            "title":
                item.get(
                    "title",
                    "GitHub issue"
                ),
            "evidence":
                body[:600],
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
        })

    return results


# ================================================================
# 10. SEARCH QUERY GENERATION
# ================================================================

async def generate_search_queries(
    project: str,
    target: str
):

    prompt = SEARCH_QUERY_PROMPT.format(
        project=project,
        target=target
    )

    try:

        result = await asyncio.to_thread(
            generate_gemini_content,
            prompt,
            "You generate precise public-web prospect research queries."
        )

        queries = []

        for line in result.splitlines():

            line = re.sub(
                r"^\s*[\d\-\*\.)]+\s*",
                "",
                line
            ).strip()

            line = line.strip(
                "\"'"
            )

            if (
                line
                and len(line) > 5
                and line not in queries
            ):
                queries.append(line)

        if queries:
            return queries[:10]

    except Exception:
        pass

    # Fallback searches.
    return [
        "struggling to get freelance clients",
        "how to get first freelance client",
        "freelancer no clients",
        "AI freelancer looking for clients",
        "no code freelancer looking for work",
        "student freelancer getting clients",
        "cold outreach no replies freelancer",
        "how do freelancers find clients",
        "AI automation freelancer clients",
        "looking for freelance opportunities",
    ]


# ================================================================
# 11. PROSPECT SIGNAL SCORING
# ================================================================

def score_prospect(
    result,
    target
):

    text = (
        f"{result.get('title', '')} "
        f"{result.get('evidence', '')}"
    ).lower()

    positive_signals = [
        "looking for",
        "struggling",
        "can't find",
        "cannot find",
        "no clients",
        "first client",
        "need clients",
        "get clients",
        "finding clients",
        "cold outreach",
        "outreach",
        "freelance",
        "freelancer",
        "ai automation",
        "no-code",
        "nocode",
        "agency",
        "client acquisition",
        "looking for work",
        "need work",
        "how do i get",
        "how can i get",
        "any advice",
        "anyone hiring",
    ]

    spam_signals = [
        "buy now",
        "discount",
        "casino",
        "crypto giveaway",
        "seo agency",
        "best vpn",
        "newsletter",
        "sponsored",
    ]

    score = 0
    evidence_matches = []

    for term in positive_signals:

        if term in text:

            score += 8

            if len(evidence_matches) < 4:
                evidence_matches.append(term)

    for term in spam_signals:

        if term in text:
            score -= 25

    # First-person discussion is more useful.
    first_person = [
        "i am",
        "i'm",
        "i have",
        "i'm struggling",
        "i need",
        "my",
        "we are",
        "we're",
        "our",
    ]

    if any(term in text for term in first_person):
        score += 15

    # Questions often represent active discovery.
    if "?" in text:
        score += 8

    # Longer evidence generally gives us more to work with.
    if len(result.get("evidence", "")) > 120:
        score += 5

    if score >= 55:
        signal = "🔥 HIGH"

    elif score >= 30:
        signal = "🟡 MEDIUM"

    else:
        signal = "🔴 LOW"

    result["signal"] = signal
    result["signal_score"] = score
    result["matched_signals"] = evidence_matches

    return result


# ================================================================
# 12. HUNT PUBLIC PROSPECTS
# ================================================================

async def hunt_public_prospects(
    project: str,
    target: str
):

    queries = await generate_search_queries(
        project,
        target
    )

    all_results = []
    source_errors = []

    # Keep the hunt lightweight.
    selected_queries = queries[:6]

    for query in selected_queries:

        searches = [
            ("Reddit", _search_reddit),
            ("Hacker News", _search_hackernews),
            ("GitHub", _search_github),
        ]

        for source_name, search_function in searches:

            try:

                found = await asyncio.to_thread(
                    search_function,
                    query
                )

                all_results.extend(found)

            except Exception as error:

                warning = (
                    f"{source_name}: "
                    f"{str(error)[:140]}"
                )

                if warning not in source_errors:
                    source_errors.append(
                        warning
                    )

    # Remove duplicates.
    unique_results = []
    seen_urls = set()

    for result in all_results:

        url = (
            result.get("url")
            or ""
        ).strip()

        if not url:
            continue

        if url in seen_urls:
            continue

        seen_urls.add(url)

        unique_results.append(
            result
        )

    # Score.
    scored = []

    for result in unique_results:

        result = score_prospect(
            result,
            target
        )

        if result["signal"] != "🔴 LOW":
            scored.append(result)

    scored.sort(
        key=lambda item: (
            item.get(
                "signal_score",
                0
            ),
            item.get(
                "score",
                0
            ),
        ),
        reverse=True
    )

    return {
        "queries": selected_queries,
        "results": scored[:12],
        "errors": source_errors,
    }


# ================================================================
# 13. FORMAT HUNT RESULTS
# ================================================================

def format_hunt_results(
    hunt_data,
    project,
    target
):

    results = hunt_data["results"]

    lines = [
        "🎯 11HUNT PROSPECT DISCOVERY",
        "",
        "Mode: Evidence-first public discovery",
        "Automatic DMs: OFF",
        "Automatic comments: OFF",
        "",
        f"TARGET:",
        target[:600],
        "",
        "────────────────────",
        "",
    ]

    if not results:

        lines.extend([
            "No medium/high prospect signals were found.",
            "",
            "This does NOT mean there are no prospects.",
            "It means the current public search did not find enough evidence.",
            "",
            "Try:",
            "/hunt students freelancers",
            "/hunt AI freelancers looking for clients",
            "/hunt people struggling with client acquisition",
        ])

        if hunt_data["errors"]:

            lines.extend([
                "",
                "SOURCE WARNINGS:"
            ])

            for error in hunt_data["errors"]:
                lines.append(
                    f"• {error}"
                )

        return "\n".join(lines)

    for index, result in enumerate(
        results,
        1
    ):

        evidence = (
            result.get("evidence")
            or "No text excerpt available."
        )

        matched = ", ".join(
            result.get(
                "matched_signals",
                []
            )
        )

        lines.extend([
            f"{index}. {result['signal']} "
            f"— {result['person']}",
            f"Platform: {result['platform']}",
            f"POST: {result['title']}",
            f"EVIDENCE: {evidence[:450]}",
            f"SIGNAL: {matched or 'Context requires review'}",
            f"URL: {result['url']}",
            f"CONTACT: {result['contact']}",
            "",
        ])

    lines.extend([
        "────────────────────",
        "",
        "NEXT STEP",
        "",
        "Open the strongest candidates.",
        "",
        "Then use:",
        "/outreach",
        "",
        "Paste the post/profile text.",
        "",
        "11Hunt will analyze the candidate and prepare",
        "a research comment + DM + follow-up.",
        "",
        "You approve and send it yourself.",
    ])

    if hunt_data["errors"]:

        lines.extend([
            "",
            "SOURCE WARNINGS:"
        ])

        for error in hunt_data["errors"]:
            lines.append(
                f"• {error}"
            )

    return "\n".join(lines)


# ================================================================
# 14. TELEGRAM KEYBOARD
# ================================================================

def get_keyboard(
    status="🔴 UNVALIDATED"
):

    if status in [
        "🔴 UNVALIDATED",
        "🟡 SIGNAL FOUND",
    ]:

        return InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "🎯 Validate",
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
                    "💬 Outreach",
                    callback_data="btn_outreach"
                ),
            ],
            [
                InlineKeyboardButton(
                    "📥 Enter Findings",
                    callback_data="btn_enter_findings"
                ),
                InlineKeyboardButton(
                    "🥊 Challenge",
                    callback_data="btn_challenge"
                ),
            ],
            [
                InlineKeyboardButton(
                    "🧪 Experiment",
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
                "📥 Enter Findings",
                callback_data="btn_enter_findings"
            ),
            InlineKeyboardButton(
                "🧪 Experiment",
                callback_data="btn_experiment"
            ),
        ],
        [
            InlineKeyboardButton(
                "🛠️ Plan MVP",
                callback_data="btn_build_mvp"
            ),
            InlineKeyboardButton(
                "💼 Sales",
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
# 15. /START
# ================================================================

async def start_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    chat_id = update.effective_chat.id

    if "project" not in context.user_data:
        context.user_data["project"] = DEFAULT_PROJECT

    if "target" not in context.user_data:
        context.user_data["target"] = DEFAULT_TARGET

    await update.message.reply_text(
        f"""
👋 11Hunt Prospect Discovery Agent

Evidence first.
Human approval required.
No automatic DMs.

Your Chat ID:
{chat_id}

COMMANDS

/pitch
Generate an opportunity.

/project
Set the project you want prospects for.

/target
Set who you want to find.

/hunt
Find public prospect signals.

/outreach
Analyze a candidate and create research outreach.

/start
Show this menu.
"""
    )


# ================================================================
# 16. /PROJECT
# ================================================================

async def project_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    project_text = " ".join(
        context.args
    ).strip()

    if not project_text:

        current = context.user_data.get(
            "project",
            DEFAULT_PROJECT
        )

        await update.message.reply_text(
            "📌 CURRENT PROJECT\n\n"
            + current
            + "\n\n"
            "To change it:\n"
            "/project Your project description"
        )

        return

    context.user_data["project"] = project_text

    await update.message.reply_text(
        "✅ Project context updated.\n\n"
        f"{project_text}\n\n"
        "Now use /target and /hunt."
    )


# ================================================================
# 17. /TARGET
# ================================================================

async def target_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    target_text = " ".join(
        context.args
    ).strip()

    if not target_text:

        current = context.user_data.get(
            "target",
            DEFAULT_TARGET
        )

        await update.message.reply_text(
            "🎯 CURRENT TARGET\n\n"
            + current
            + "\n\n"
            "To change it:\n"
            "/target beginner AI freelancers looking for clients"
        )

        return

    context.user_data["target"] = target_text

    await update.message.reply_text(
        "✅ Target updated.\n\n"
        f"{target_text}\n\n"
        "Use /hunt to search for them."
    )


# ================================================================
# 18. /PITCH
# ================================================================

async def pitch_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    status_msg = await update.message.reply_text(
        "🔎 Scouting a fresh opportunity..."
    )

    try:

        pitch = await asyncio.to_thread(
            generate_gemini_content,
            "Scout one fresh unvalidated opportunity.",
            SYSTEM_PROMPT
        )

        context.user_data[
            "last_idea"
        ] = pitch

        context.user_data[
            "validation_status"
        ] = "🔴 UNVALIDATED"

        await status_msg.delete()

        await update.message.reply_text(
            pitch,
            reply_markup=get_keyboard(
                "🔴 UNVALIDATED"
            )
        )

    except Exception as error:

        await status_msg.delete()

        await update.message.reply_text(
            f"❌ Error:\n{error}"
        )


# ================================================================
# 19. /HUNT
# ================================================================

async def hunt_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    project = context.user_data.get(
        "project",
        DEFAULT_PROJECT
    )

    target = context.user_data.get(
        "target",
        DEFAULT_TARGET
    )

    # Optional custom hunt:
    # /hunt AI freelancers struggling to get clients
    custom_query = " ".join(
        context.args
    ).strip()

    if custom_query:

        target = custom_query

        context.user_data[
            "target"
        ] = custom_query

    status_msg = await update.message.reply_text(
        "🔎 11Hunt is searching public discussions...\n\n"
        "Sources:\n"
        "• Reddit\n"
        "• Hacker News\n"
        "• GitHub\n\n"
        "Finding people, not generic articles."
    )

    try:

        hunt_data = await hunt_public_prospects(
            project,
            target
        )

        output = format_hunt_results(
            hunt_data,
            project,
            target
        )

        await status_msg.delete()

        # Telegram limit protection.
        chunks = [
            output[i:i + 3800]
            for i in range(
                0,
                len(output),
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
            f"❌ Hunt failed:\n{error}"
        )


# ================================================================
# 20. /OUTREACH
# ================================================================

async def outreach_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    project = context.user_data.get(
        "project",
        DEFAULT_PROJECT
    )

    context.user_data[
        "awaiting_candidate"
    ] = True

    await update.message.reply_text(
        """
🎯 OUTREACH ASSISTANT

Paste:

• Reddit post
• Reddit comment
• X post
• LinkedIn post text
• profile description
• job post
• founder post
• candidate description

I will analyze:

🔎 Evidence
🟡 Inference
🔴 Unknown
🎯 Relevance
💬 Public comment
📩 Research DM
❓ Follow-up

⚠️ I will NOT automatically send anything.

You approve and send the message yourself.
"""
    )


# ================================================================
# 21. OUTREACH ANALYSIS
# ================================================================

async def outreach_analysis(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    candidate = (
        update.message.text
        or ""
    ).strip()

    project = context.user_data.get(
        "project",
        DEFAULT_PROJECT
    )

    target = context.user_data.get(
        "target",
        DEFAULT_TARGET
    )

    status_msg = await update.message.reply_text(
        "🔎 Analyzing candidate evidence..."
    )

    try:

        prompt = OUTREACH_PROMPT.format(
            project=project,
            target=target,
            candidate=candidate
        )

        result = await asyncio.to_thread(
            generate_gemini_content,
            prompt,
            "You are an evidence-first customer discovery outreach assistant."
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

        await status_msg.delete()

        await update.message.reply_text(
            "🎯 PROSPECT ANALYSIS\n\n"
            + result
            + "\n\n"
            "⚠️ HUMAN APPROVAL REQUIRED\n"
            "Review everything before sending."
        )

    except Exception as error:

        context.user_data[
            "awaiting_candidate"
        ] = False

        await status_msg.delete()

        await update.message.reply_text(
            f"❌ Error:\n{error}"
        )


# ================================================================
# 22. DAILY OPPORTUNITY
# ================================================================

async def scheduled_daily_pitch(
    context: ContextTypes.DEFAULT_TYPE
):

    if not MY_TELEGRAM_CHAT_ID:
        return

    try:

        pitch = await asyncio.to_thread(
            generate_gemini_content,
            "Scout one fresh unvalidated market opportunity.",
            SYSTEM_PROMPT
        )

        await context.bot.send_message(
            chat_id=MY_TELEGRAM_CHAT_ID,
            text=(
                "☀️ TODAY'S OPPORTUNITY\n\n"
                + pitch
            ),
            reply_markup=get_keyboard(
                "🔴 UNVALIDATED"
            )
        )

    except Exception as error:

        print(
            "Daily opportunity error:",
            error
        )


# ================================================================
# 23. BUTTON HANDLER
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
        "Market Opportunity"
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
            """
🔎 11HUNT PROSPECT HUNT

The bot will search public discussions for people
matching your current target.

Use:

/hunt

Or specify a target:

/hunt AI freelancers struggling to get clients

The bot does NOT automatically contact anyone.
"""
        )

    # ------------------------------------------------------------
    # OUTREACH
    # ------------------------------------------------------------

    elif query.data == "btn_outreach":

        context.user_data[
            "awaiting_candidate"
        ] = True

        await query.message.reply_text(
            """
🎯 OUTREACH ASSISTANT

Paste the candidate's post/profile text.

I'll analyze:

• Evidence
• Relevance
• Unknowns
• Public comment
• Research DM
• Follow-up

You approve before sending.
"""
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
                current_status=current_status
            )

            result = await asyncio.to_thread(
                generate_gemini_content,
                prompt,
                "You are a Customer Discovery Expert."
            )

            await status_msg.delete()

            await query.message.reply_text(
                result
            )

        except Exception as error:

            await status_msg.delete()

            await query.message.reply_text(
                f"❌ Error:\n{error}"
            )

    # ------------------------------------------------------------
    # FIND CUSTOMERS
    # ------------------------------------------------------------

    elif query.data == "btn_find_customers":

        project = context.user_data.get(
            "project",
            DEFAULT_PROJECT
        )

        target = context.user_data.get(
            "target",
            DEFAULT_TARGET
        )

        status_msg = await query.message.reply_text(
            "👥 Building customer discovery strategy..."
        )

        try:

            prompt = FIND_CUSTOMERS_PROMPT.format(
                project=project,
                target=target
            )

            result = await asyncio.to_thread(
                generate_gemini_content,
                prompt,
                "You are a Lead Generation Specialist."
            )

            await status_msg.delete()

            await query.message.reply_text(
                result
            )

        except Exception as error:

            await status_msg.delete()

            await query.message.reply_text(
                f"❌ Error:\n{error}"
            )

    # ------------------------------------------------------------
    # ENTER FINDINGS
    # ------------------------------------------------------------

    elif query.data == "btn_enter_findings":

        context.user_data[
            "awaiting_findings"
        ] = True

        await query.message.reply_text(
            """
📥 DISCOVERY FINDINGS

Send your interview/discovery notes.

Include:

1. Who you talked to
2. What they said
3. Their current workflow
4. Problems they described
5. Existing workaround
6. Any pricing/willingness-to-pay signal
"""
        )

    # ------------------------------------------------------------
    # CHALLENGE
    # ------------------------------------------------------------

    elif query.data == "btn_challenge":

        status_msg = await query.message.reply_text(
            "🥊 Stress-testing the hypothesis..."
        )

        try:

            prompt = CHALLENGE_PROMPT.format(
                idea_context=last_idea
            )

            result = await asyncio.to_thread(
                generate_gemini_content,
                prompt,
                "You are a skeptical startup advisor."
            )

            await status_msg.delete()

            await query.message.reply_text(
                result
            )

        except Exception as error:

            await status_msg.delete()

            await query.message.reply_text(
                f"❌ Error:\n{error}"
            )

    # ------------------------------------------------------------
    # EXPERIMENT
    # ------------------------------------------------------------

    elif query.data == "btn_experiment":

        findings = context.user_data.get(
            "last_findings",
            "No discovery findings recorded yet."
        )

        status_msg = await query.message.reply_text(
            "🧪 Designing smallest demand experiment..."
        )

        try:

            prompt = EXPERIMENT_PROMPT.format(
                idea_context=last_idea,
                user_findings=findings
            )

            result = await asyncio.to_thread(
                generate_gemini_content,
                prompt,
                "You are a Lean Startup Experiment Designer."
            )

            await status_msg.delete()

            await query.message.reply_text(
                result
            )

        except Exception as error:

            await status_msg.delete()

            await query.message.reply_text(
                f"❌ Error:\n{error}"
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
                f"""
🛑 BUILD LOCKED

Current status:
{current_status}

Collect evidence first.

Recommended sequence:

1. Find people
2. Talk to them
3. Record evidence
4. Validate the problem
5. Run a demand experiment
6. Then build
"""
            )

            return

        status_msg = await query.message.reply_text(
            "⚙️ Building lean MVP blueprint..."
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

            await status_msg.delete()

            await query.message.reply_text(
                result
            )

        except Exception as error:

            await status_msg.delete()

            await query.message.reply_text(
                f"❌ Error:\n{error}"
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
                f"""
🛑 SALES LOCKED

Current status:
{current_status}

Validate the problem and test demand first.
"""
            )

            return

        findings = context.user_data.get(
            "last_findings",
            "Validated customer problem."
        )

        status_msg = await query.message.reply_text(
            "💼 Building first-customer strategy..."
        )

        try:

            prompt = SALES_PROMPT.format(
                idea_context=last_idea,
                user_findings=findings
            )

            result = await asyncio.to_thread(
                generate_gemini_content,
                prompt,
                "You are a B2B Sales Strategist."
            )

            await status_msg.delete()

            await query.message.reply_text(
                result
            )

        except Exception as error:

            await status_msg.delete()

            await query.message.reply_text(
                f"❌ Error:\n{error}"
            )

    # ------------------------------------------------------------
    # NEXT OPPORTUNITY
    # ------------------------------------------------------------

    elif query.data == "btn_next_opp":

        status_msg = await query.message.reply_text(
            "🔄 Scouting another opportunity..."
        )

        try:

            pitch = await asyncio.to_thread(
                generate_gemini_content,
                "Scout one fresh unvalidated market opportunity.",
                SYSTEM_PROMPT
            )

            context.user_data[
                "last_idea"
            ] = pitch

            context.user_data[
                "validation_status"
            ] = "🔴 UNVALIDATED"

            await status_msg.delete()

            await query.message.reply_text(
                pitch,
                reply_markup=get_keyboard(
                    "🔴 UNVALIDATED"
                )
            )

        except Exception as error:

            await status_msg.delete()

            await query.message.reply_text(
                f"❌ Error:\n{error}"
            )


# ================================================================
# 24. GENERAL TEXT REPLY HANDLER
# ================================================================

async def reply_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    # ------------------------------------------------------------
    # Candidate for outreach
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

        findings = (
            update.message.text
            or ""
        )

        context.user_data[
            "last_findings"
        ] = findings

        last_idea = context.user_data.get(
            "last_idea",
            "Market Opportunity"
        )

        current_status = context.user_data.get(
            "validation_status",
            "🔴 UNVALIDATED"
        )

        status_msg = await update.message.reply_text(
            "🧐 Evaluating discovery evidence..."
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
                "You are a Truth-Seeking Startup Evaluator."
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

                new_status = "❌ KILL"

            context.user_data[
                "validation_status"
            ] = new_status

            await status_msg.delete()

            await update.message.reply_text(
                f"""
📋 DISCOVERY EVALUATION

UPDATED STATUS:
{new_status}

{evaluation}
""",
                reply_markup=get_keyboard(
                    new_status
                )
            )

        except Exception as error:

            await status_msg.delete()

            await update.message.reply_text(
                f"❌ Error:\n{error}"
            )


# ================================================================
# 25. APPLICATION STARTUP
# ================================================================

def main():

    application = (
        Application
        .builder()
        .token(TELEGRAM_BOT_TOKEN)
        .build()
    )

    # Commands
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

    application.add_handler(
        CommandHandler(
            "project",
            project_command
        )
    )

    application.add_handler(
        CommandHandler(
            "target",
            target_command
        )
    )

    # Buttons
    application.add_handler(
        CallbackQueryHandler(
            button_handler
        )
    )

    # Normal messages
    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            reply_handler
        )
    )

    print(
        "🚀 11Hunt Prospect Discovery Agent running..."
    )

    print(
        "✅ Commands:"
        " /start"
        " /pitch"
        " /project"
        " /target"
        " /hunt"
        " /outreach"
    )

    application.run_polling(
        drop_pending_updates=True
    )


# ================================================================
# 26. RUN
# ================================================================

if __name__ == "__main__":
    main()
