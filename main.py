import os
import random
import threading
from datetime import time
from zoneinfo import ZoneInfo
from http.server import HTTPServer, BaseHTTPRequestHandler

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)


# ============================================================
# 1. RENDER HEALTH CHECK
# ============================================================

class HealthCheckHandler(BaseHTTPRequestHandler):

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"11Hunt Startup Agent is running!")

    def do_HEAD(self):
        self.send_response(200)
        self.end_headers()

    def log_message(self, format, *args):
        return


def run_health_server():
    port = int(os.getenv("PORT", 10000))

    server = HTTPServer(
        ("0.0.0.0", port),
        HealthCheckHandler
    )

    print(f"🌐 Health server running on port {port}")
    server.serve_forever()


threading.Thread(
    target=run_health_server,
    daemon=True
).start()


# ============================================================
# 2. TELEGRAM CONFIG
# ============================================================

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

if not TELEGRAM_BOT_TOKEN:
    raise ValueError(
        "Missing TELEGRAM_BOT_TOKEN environment variable."
    )


# ============================================================
# 3. TIMEZONE
# ============================================================

INDIA_TZ = ZoneInfo("Asia/Kolkata")


# ============================================================
# 4. STARTUP IDEA DATABASE
# ============================================================

STARTUP_IDEAS = [

    {
        "name": "Local Business Follow-Up Agent",
        "type": "AI Agent / SaaS",
        "problem": (
            "Small businesses receive enquiries through WhatsApp, "
            "Instagram and calls but frequently forget to follow up."
        ),
        "solution": (
            "A lightweight lead tracker that reminds owners about "
            "follow-ups and prepares personalized responses."
        ),
        "customer": (
            "Salons, clinics, tutors, repair businesses and local "
            "service businesses."
        ),
        "mvp": (
            "Lead list + customer status + follow-up reminders + "
            "message templates."
        ),
    },

    {
        "name": "Student Opportunity Tracker",
        "type": "Web App",
        "problem": (
            "Students discover internships, hackathons, competitions "
            "and startup programs but lose track of deadlines."
        ),
        "solution": (
            "A personal opportunity dashboard that organizes "
            "opportunities and application progress."
        ),
        "customer": (
            "Students, freelancers and early-career builders."
        ),
        "mvp": (
            "Opportunity database + deadline + status + reminders."
        ),
    },

    {
        "name": "Creator Sponsorship CRM",
        "type": "SaaS",
        "problem": (
            "Small creators contact brands but lose track of "
            "conversations, follow-ups and sponsorship deals."
        ),
        "solution": (
            "A simple CRM designed specifically for creator-brand "
            "outreach."
        ),
        "customer": (
            "YouTubers, Instagram creators and creator agencies."
        ),
        "mvp": (
            "Brand list + outreach status + follow-up date + notes."
        ),
    },

    {
        "name": "Website Opportunity Scanner",
        "type": "AI Tool",
        "problem": (
            "Small businesses often have weak websites but don't "
            "know exactly what needs improvement."
        ),
        "solution": (
            "A website scanner that identifies visible problems "
            "and turns them into a client-ready improvement report."
        ),
        "customer": (
            "Small businesses and freelance web designers."
        ),
        "mvp": (
            "URL input + website checks + opportunity report."
        ),
    },

    {
        "name": "Freelancer Proposal Builder",
        "type": "Web App / AI Tool",
        "problem": (
            "Beginner freelancers send generic proposals and "
            "struggle to explain their value."
        ),
        "solution": (
            "A tool that converts a client's requirement into "
            "a personalized proposal and project scope."
        ),
        "customer": (
            "Students, freelancers and small agencies."
        ),
        "mvp": (
            "Client requirement + proposal + scope + pricing template."
        ),
    },

    {
        "name": "Appointment Recovery App",
        "type": "SaaS",
        "problem": (
            "Appointment businesses lose revenue when customers "
            "cancel or fail to show up."
        ),
        "solution": (
            "A simple system that tracks cancellations and helps "
            "businesses fill empty appointment slots."
        ),
        "customer": (
            "Clinics, salons, tutors and consultants."
        ),
        "mvp": (
            "Appointment calendar + cancellation status + "
            "replacement-customer workflow."
        ),
    },

    {
        "name": "AI Meeting Action Tracker",
        "type": "AI App",
        "problem": (
            "Teams finish meetings with unclear responsibilities "
            "and forgotten action items."
        ),
        "solution": (
            "An app that converts meeting notes into owners, "
            "deadlines and follow-up tasks."
        ),
        "customer": (
            "Small startups, agencies and student teams."
        ),
        "mvp": (
            "Paste meeting notes + extract tasks + assign owner + deadline."
        ),
    },

    {
        "name": "Local Service Lead Finder",
        "type": "Web App",
        "problem": (
            "Freelancers struggle to identify local businesses "
            "that genuinely need their service."
        ),
        "solution": (
            "A tool that helps freelancers discover businesses, "
            "inspect their public presence and identify potential "
            "service opportunities."
        ),
        "customer": (
            "Web designers, automation freelancers and small agencies."
        ),
        "mvp": (
            "Business list + website/social checks + opportunity notes."
        ),
    },

    {
        "name": "Student Project Builder",
        "type": "AI App",
        "problem": (
            "Students have project ideas but don't know what to "
            "build first or how to turn an idea into an MVP."
        ),
        "solution": (
            "An app that converts a project idea into features, "
            "screens, architecture and a build sequence."
        ),
        "customer": (
            "College students and beginner developers."
        ),
        "mvp": (
            "Idea input + feature list + screen plan + build roadmap."
        ),
    },

    {
        "name": "Small Agency Client Tracker",
        "type": "SaaS",
        "problem": (
            "Small agencies manage leads using spreadsheets, chats "
            "and scattered notes."
        ),
        "solution": (
            "A simple client pipeline designed for small agencies."
        ),
        "customer": (
            "Marketing, design, automation and web agencies."
        ),
        "mvp": (
            "Lead pipeline + notes + follow-up + deal status."
        ),
    },

]


# ============================================================
# 5. IDEA GENERATOR
# ============================================================

def generate_startup_idea():

    idea = random.choice(STARTUP_IDEAS)

    return {
        "data": idea,
        "text": f"""
🚀 DAILY STARTUP BLUEPRINT

💡 {idea["name"]}

TYPE
{idea["type"]}

━━━━━━━━━━━━━━━━━━

1. STORY & PROBLEM

{idea["problem"]}

━━━━━━━━━━━━━━━━━━

2. PROPOSED SOLUTION

{idea["solution"]}

━━━━━━━━━━━━━━━━━━

3. WHO PAYS?

{idea["customer"]}

━━━━━━━━━━━━━━━━━━

4. SCORECARD

• Pain Intensity: 8/10
• Willingness to Pay: 7/10
• Distribution Ease: 8/10
• Technical Feasibility: 9/10

━━━━━━━━━━━━━━━━━━

5. COMPETITORS

Possible alternatives:

• Spreadsheets
• Generic CRM tools
• Manual workflows
• Existing specialized tools

WHERE THEY MAY FALL SHORT

Generic tools may require too much setup for this specific workflow.

━━━━━━━━━━━━━━━━━━

6. MVP

{idea["mvp"]}

━━━━━━━━━━━━━━━━━━

7. HOW TO BUILD

START WITH:

• One target customer
• One painful problem
• One core workflow
• Simple interface
• Simple database
• Basic automation

Do NOT build advanced features before validation.

━━━━━━━━━━━━━━━━━━

8. FIRST 10 USERS

1. Find 20 potential users.
2. Contact them personally.
3. Ask how they currently solve the problem.
4. Show the proposed solution.
5. Offer a small MVP/pilot.
6. Collect feedback.
7. Improve only what users actually need.

━━━━━━━━━━━━━━━━━━

9. STRESS TEST

❓ Will people actually change their current workflow to use this?

❓ Who specifically would pay for it?

❓ What evidence proves the problem is painful?

❓ Can the first 10 users be reached without paid ads?

━━━━━━━━━━━━━━━━━━

10. NEXT ACTION

VALIDATE FIRST.

Talk to real potential users before building the full product.
"""
    }


# ============================================================
# 6. TELEGRAM KEYBOARD
# ============================================================

def get_keyboard():

    return InlineKeyboardMarkup([

        [
            InlineKeyboardButton(
                "🎯 Answer Stress-Test",
                callback_data="stress"
            ),

            InlineKeyboardButton(
                "🛠 Build Plan",
                callback_data="build"
            ),
        ],

        [
            InlineKeyboardButton(
                "🚀 Implement Idea",
                callback_data="implement"
            ),
        ],

        [
            InlineKeyboardButton(
                "🔄 Generate Another Idea",
                callback_data="new"
            ),
        ],

    ])


# ============================================================
# 7. SAVE CURRENT IDEA
# ============================================================

def save_idea(context, idea):

    context.user_data["last_idea"] = idea["data"]
    context.user_data["last_idea_text"] = idea["text"]


# ============================================================
# 8. /START
# ============================================================

async def start_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    chat_id = update.effective_chat.id

    # Register user for daily 8 AM startup idea.
    context.application.bot_data.setdefault(
        "daily_subscribers",
        set()
    ).add(chat_id)

    await update.message.reply_text(
        "👋 Welcome to your Startup Co-Pilot!\n\n"

        "I help you discover startup opportunities, "
        "stress-test them and turn them into MVP plans.\n\n"

        "⏰ Daily startup ideas are scheduled for "
        "8:00 AM IST.\n\n"

        "Commands:\n"
        "/pitch — Generate an idea now\n"
        "/alarm — Enable daily 8 AM ideas\n"
        "/stopalarm — Disable daily ideas\n\n"

        "Let's build. 🚀"
    )


# ============================================================
# 9. /PITCH
# ============================================================

async def pitch_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    idea = generate_startup_idea()

    save_idea(context, idea)

    await update.message.reply_text(
        idea["text"],
        reply_markup=get_keyboard()
    )


# ============================================================
# 10. /ALARM
# ============================================================

async def alarm_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    chat_id = update.effective_chat.id

    context.application.bot_data.setdefault(
        "daily_subscribers",
        set()
    ).add(chat_id)

    await update.message.reply_text(
        "⏰ Daily Startup Alarm ENABLED.\n\n"
        "You will receive a fresh startup blueprint every day at "
        "8:00 AM IST.\n\n"
        "Use /stopalarm to disable it."
    )


# ============================================================
# 11. /STOPALARM
# ============================================================

async def stop_alarm_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    chat_id = update.effective_chat.id

    subscribers = context.application.bot_data.setdefault(
        "daily_subscribers",
        set()
    )

    subscribers.discard(chat_id)

    await update.message.reply_text(
        "🔕 Daily Startup Alarm disabled."
    )


# ============================================================
# 12. DAILY 8 AM JOB
# ============================================================

async def daily_startup_job(
    context: ContextTypes.DEFAULT_TYPE
):

    subscribers = context.application.bot_data.get(
        "daily_subscribers",
        set()
    )

    if not subscribers:
        print("⏰ 8 AM job ran — no subscribers.")
        return

    print(
        f"⏰ Sending daily startup blueprint "
        f"to {len(subscribers)} subscriber(s)."
    )

    idea = generate_startup_idea()

    for chat_id in list(subscribers):

        try:

            await context.bot.send_message(
                chat_id=chat_id,
                text=idea["text"],
                reply_markup=get_keyboard()
            )

        except Exception as e:

            print(
                f"⚠️ Could not send daily idea to "
                f"{chat_id}: {e}"
            )


# ============================================================
# 13. BUTTON HANDLER
# ============================================================

async def button_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.callback_query

    await query.answer()

    # --------------------------------------------------------
    # GENERATE ANOTHER
    # --------------------------------------------------------

    if query.data == "new":

        idea = generate_startup_idea()

        save_idea(context, idea)

        await query.message.reply_text(
            idea["text"],
            reply_markup=get_keyboard()
        )

        return

    # --------------------------------------------------------
    # STRESS TEST
    # --------------------------------------------------------

    if query.data == "stress":

        context.user_data["awaiting_stress"] = True

        await query.message.reply_text(
            "🎯 STRESS TEST\n\n"

            "Answer this question:\n\n"

            "What is the biggest assumption behind "
            "this startup, and how would you validate "
            "it with 5 potential customers?\n\n"

            "Reply with your answer and I'll challenge it."
        )

        return

    # --------------------------------------------------------
    # BUILD PLAN
    # --------------------------------------------------------

    if query.data == "build":

        idea = context.user_data.get(
            "last_idea"
        )

        if not idea:

            await query.message.reply_text(
                "Generate a startup idea first using /pitch."
            )

            return

        await query.message.reply_text(
            f"""
🛠 BUILD PLAN

PRODUCT
{idea["name"]}

━━━━━━━━━━━━━━━━━━

PHASE 1 — VALIDATE

• Talk to 5 potential users.
• Confirm the problem exists.
• Ask how they solve it today.
• Find out whether they already spend money
  solving it.

━━━━━━━━━━━━━━━━━━

PHASE 2 — DEFINE MVP

Build ONLY:

• Core user flow
• One main screen/dashboard
• Required database
• One useful automation
• Basic feedback mechanism

━━━━━━━━━━━━━━━━━━

PHASE 3 — BUILD

Recommended beginner approach:

Frontend:
React / Vite or a no-code builder

Backend:
Python / FastAPI or Supabase

Database:
Supabase / PostgreSQL

Automation:
n8n / Make / Zapier

AI:
Only if it provides a clear advantage.

━━━━━━━━━━━━━━━━━━

PHASE 4 — TEST

Give the MVP to 3–5 real users.

Observe:

• What they use
• What they ignore
• Where they get confused
• What they request

━━━━━━━━━━━━━━━━━━

PHASE 5 — SELL

Contact 20 potential customers.

Do not ask:

"Do you like my idea?"

Ask:

"How do you currently solve this problem?"

Then show the solution.

━━━━━━━━━━━━━━━━━━

RULE

Do not build the complete product before validation.
"""
        )

        return

    # --------------------------------------------------------
    # IMPLEMENT IDEA
    # --------------------------------------------------------

    if query.data == "implement":

        idea = context.user_data.get(
            "last_idea"
        )

        if not idea:

            await query.message.reply_text(
                "Generate a startup idea first using /pitch."
            )

            return

        await query.message.reply_text(
            f"""
🚀 IMPLEMENTATION BLUEPRINT

PRODUCT
{idea["name"]}

━━━━━━━━━━━━━━━━━━

STEP 1 — TARGET

Customer:
{idea["customer"]}

━━━━━━━━━━━━━━━━━━

STEP 2 — CORE PROBLEM

{idea["problem"]}

━━━━━━━━━━━━━━━━━━

STEP 3 — CORE SOLUTION

{idea["solution"]}

━━━━━━━━━━━━━━━━━━

STEP 4 — MVP FEATURES

1. User onboarding
2. Main dashboard
3. Core workflow
4. Data storage
5. Basic notifications
6. Feedback/reporting

━━━━━━━━━━━━━━━━━━

STEP 5 — TECH STACK

Frontend:
React + Vite

Backend:
Python / FastAPI OR Supabase

Database:
Supabase PostgreSQL

Automation:
n8n / Make

AI:
Only where required.

━━━━━━━━━━━━━━━━━━

STEP 6 — BUILD ORDER

Day 1:
• UI
• Database
• Core workflow

Day 2:
• Automation
• Testing
• First user

Day 3:
• Fix problems
• Improve UX
• Start outreach

━━━━━━━━━━━━━━━━━━

STEP 7 — FIRST VALIDATION

Before building advanced features:

Talk to 5 target customers.

Ask:

"What do you do today?"

"What does this cost you?"

"How often does this happen?"

"What have you already tried?"

"Would you pay for a better solution?"

━━━━━━━━━━━━━━━━━━

IMPLEMENTATION RULE

Build → Test → Learn → Improve.

Not:

Build everything → Hope people buy.
"""
        )

        return


# ============================================================
# 14. STRESS TEST ANSWER
# ============================================================

async def reply_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not context.user_data.get("awaiting_stress"):
        return

    context.user_data["awaiting_stress"] = False

    answer = update.message.text

    await update.message.reply_text(
        f"""
📋 STRESS TEST REVIEW

YOUR ANSWER
{answer}

━━━━━━━━━━━━━━━━━━

Now challenge your reasoning:

1. EVIDENCE

What evidence proves the problem actually exists?

2. CUSTOMER

Who specifically experiences it?

3. FREQUENCY

How often does the problem happen?

4. CURRENT SOLUTION

What do they use today?

5. PAYMENT

Why would they pay instead of continuing
with their current solution?

6. DISTRIBUTION

How will you reach the first 10 users?

━━━━━━━━━━━━━━━━━━

🔥 NEXT EXPERIMENT

Talk to 5 potential customers before building
the next major feature.

Your goal is not compliments.

Your goal is evidence.
"""
    )


# ============================================================
# 15. ERROR HANDLER
# ============================================================

async def error_handler(
    update: object,
    context: ContextTypes.DEFAULT_TYPE
):

    print(
        f"⚠️ Telegram error: {context.error}"
    )


# ============================================================
# 16. MAIN APPLICATION
# ============================================================

def main():

    print("🚀 Starting 11Hunt Startup Agent...")

    application = (
        Application
        .builder()
        .token(TELEGRAM_BOT_TOKEN)
        .build()
    )

    # --------------------------------------------------------
    # COMMANDS
    # --------------------------------------------------------

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
            "alarm",
            alarm_command
        )
    )

    application.add_handler(
        CommandHandler(
            "stopalarm",
            stop_alarm_command
        )
    )

    # --------------------------------------------------------
    # BUTTONS
    # --------------------------------------------------------

    application.add_handler(
        CallbackQueryHandler(
            button_handler
        )
    )

    # --------------------------------------------------------
    # TEXT / STRESS TEST
    # --------------------------------------------------------

    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            reply_handler
        )
    )

    # --------------------------------------------------------
    # ERROR HANDLER
    # --------------------------------------------------------

    application.add_error_handler(
        error_handler
    )

    # --------------------------------------------------------
    # DAILY 8 AM IST
    # --------------------------------------------------------

    job_queue = application.job_queue

    if job_queue is None:

        print(
            "⚠️ JobQueue unavailable. "
            "Make sure python-telegram-bot[job-queue] is installed."
        )

    else:

        job_queue.run_daily(
            daily_startup_job,
            time=time(
                hour=8,
                minute=0,
                second=0,
                tzinfo=INDIA_TZ
            ),
            name="daily_startup_blueprint"
        )

        print(
            "⏰ Daily Startup Blueprint scheduled "
            "for 08:00 IST."
        )

    print(
        "🚀 11Hunt Startup Agent running..."
    )

    application.run_polling(
        drop_pending_updates=True
    )


# ============================================================
# 17. START
# ============================================================

if __name__ == "__main__":
    main()
