import os
import random
import threading
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
        self.end_headers()
        self.wfile.write(b"11Hunt Startup Agent is running!")

    def do_HEAD(self):
        self.send_response(200)
        self.end_headers()


def run_health_server():
    port = int(os.getenv("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    server.serve_forever()


threading.Thread(
    target=run_health_server,
    daemon=True
).start()


# ============================================================
# 2. TELEGRAM TOKEN
# ============================================================

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

if not TELEGRAM_BOT_TOKEN:
    raise ValueError("Missing TELEGRAM_BOT_TOKEN")


# ============================================================
# 3. STARTUP IDEAS
# ============================================================

STARTUP_IDEAS = [

    {
        "name": "Local Business Follow-Up Agent",
        "problem": (
            "Small businesses receive enquiries through WhatsApp and "
            "Instagram but often forget to follow up with potential customers."
        ),
        "solution": (
            "A lightweight system that collects enquiries, reminds the "
            "business owner to follow up and prepares personalized messages."
        ),
        "customer": (
            "Salons, clinics, tutors, repair businesses and other local "
            "service businesses."
        ),
        "mvp": (
            "Lead list + follow-up reminders + message templates + "
            "simple customer status."
        ),
    },

    {
        "name": "Student Opportunity Tracker",
        "problem": (
            "Students discover internships, hackathons, startup programs "
            "and competitions but lose track of deadlines and applications."
        ),
        "solution": (
            "A personal dashboard that organizes opportunities, deadlines "
            "and application progress."
        ),
        "customer": (
            "Students, beginner freelancers and early-career builders."
        ),
        "mvp": (
            "Opportunity entry + deadline + application status + "
            "reminders."
        ),
    },

    {
        "name": "Website Problem Scanner",
        "problem": (
            "Many small businesses have outdated websites but do not know "
            "what should actually be improved."
        ),
        "solution": (
            "A simple website analysis tool that produces a clear list "
            "of visible problems and improvement opportunities."
        ),
        "customer": (
            "Small businesses and freelancers who sell website services."
        ),
        "mvp": (
            "URL input + basic website checks + opportunity report."
        ),
    },

    {
        "name": "Creator Sponsorship Tracker",
        "problem": (
            "Small creators contact brands for sponsorships but lose track "
            "of conversations, follow-ups and deal status."
        ),
        "solution": (
            "A lightweight CRM designed specifically for creator-brand "
            "outreach."
        ),
        "customer": (
            "YouTubers, Instagram creators and small creator agencies."
        ),
        "mvp": (
            "Brand contacts + outreach status + follow-up dates + notes."
        ),
    },

    {
        "name": "Freelancer Proposal Builder",
        "problem": (
            "Beginner freelancers waste time writing proposals and often "
            "send generic messages that do not address the client's actual need."
        ),
        "solution": (
            "A tool that turns a client's requirement into a personalized "
            "proposal and simple project plan."
        ),
        "customer": (
            "Students, freelancers and beginner agencies."
        ),
        "mvp": (
            "Client requirement input + proposal generator + project scope."
        ),
    },

    {
        "name": "Local Appointment Recovery",
        "problem": (
            "Appointment-based businesses lose revenue when customers "
            "cancel or fail to show up."
        ),
        "solution": (
            "A simple system that tracks appointments and helps businesses "
            "fill cancelled slots using their existing customer list."
        ),
        "customer": (
            "Clinics, salons, tutors, consultants and other appointment businesses."
        ),
        "mvp": (
            "Appointment list + cancellation status + replacement reminder."
        ),
    },

]


# ============================================================
# 4. GENERATE STARTUP IDEA
# ============================================================

def generate_startup_idea():

    idea = random.choice(STARTUP_IDEAS)

    return f"""🚀 DAILY STARTUP BLUEPRINT

💡 IDEA
{idea["name"]}

1. STORY & PROBLEM

{idea["problem"]}

2. PROPOSED SOLUTION

{idea["solution"]}

3. WHO PAYS?

{idea["customer"]}

4. SCORECARD

• Pain Intensity: 8/10
• Willingness to Pay: 7/10
• Distribution Ease: 8/10
• Technical Feasibility: 9/10

5. COMPETITORS

Existing spreadsheets, CRMs and generic automation tools.

WHERE THEY FAIL:
They are built for broad workflows rather than this specific problem.

6. MVP

{idea["mvp"]}

7. HOW TO BUILD

Start with:

• Simple web/mobile interface
• Small database
• Basic workflow automation
• AI only where it provides a clear advantage

Do not build advanced features before validating the workflow.

8. FIRST 10 USERS

Find 20 potential users manually.

Ask about their current workflow.

Show them the problem.

Offer the first version to a few users in exchange for feedback.

9. STRESS TEST

1. Will users actually change their current workflow to use this?

2. Can the first 10 customers be reached without paid advertising?

10. BUILD THIS?

Recommended next action: VALIDATE FIRST.

Prove that the problem exists before spending significant time building.
"""


# ============================================================
# 5. KEYBOARD
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
                "🔄 Generate Another",
                callback_data="new"
            ),
        ],
    ])


# ============================================================
# 6. /START
# ============================================================

async def start_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    await update.message.reply_text(
        "👋 Welcome to your Startup Co-Pilot!\n\n"
        "I can help you discover, stress-test and plan startup ideas.\n\n"
        "Use /pitch to get a startup opportunity."
    )


# ============================================================
# 7. /PITCH
# ============================================================

async def pitch_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    idea = generate_startup_idea()

    context.user_data["last_idea"] = idea
    context.user_data["awaiting_stress"] = False

    await update.message.reply_text(
        idea,
        reply_markup=get_keyboard()
    )


# ============================================================
# 8. BUTTON HANDLER
# ============================================================

async def button_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.callback_query

    await query.answer()

    # --------------------------------------------------------
    # NEW IDEA
    # --------------------------------------------------------

    if query.data == "new":

        idea = generate_startup_idea()

        context.user_data["last_idea"] = idea

        await query.message.reply_text(
            idea,
            reply_markup=get_keyboard()
        )

    # --------------------------------------------------------
    # STRESS TEST
    # --------------------------------------------------------

    elif query.data == "stress":

        context.user_data["awaiting_stress"] = True

        await query.message.reply_text(
            "🥊 STRESS TEST\n\n"
            "Answer this:\n\n"
            "What is the biggest assumption behind this startup, "
            "and how would you validate it with 5 potential customers?\n\n"
            "Reply with your answer."
        )

    # --------------------------------------------------------
    # BUILD PLAN
    # --------------------------------------------------------

    elif query.data == "build":

        await query.message.reply_text(
            "🛠 BUILD PLAN\n\n"
            "PHASE 1 — VALIDATE\n"
            "• Talk to 5 potential users\n"
            "• Confirm the problem\n"
            "• Ask how they solve it today\n\n"
            "PHASE 2 — MVP\n"
            "• Build only the core workflow\n"
            "• Create the minimum required screens\n"
            "• Add a simple database\n\n"
            "PHASE 3 — TEST\n"
            "• Give it to 3–5 users\n"
            "• Watch how they use it\n"
            "• Fix the biggest friction point\n\n"
            "PHASE 4 — SELL\n"
            "• Contact 20 potential customers\n"
            "• Show the actual solution\n"
            "• Ask for a paid pilot"
        )

    # --------------------------------------------------------
    # IMPLEMENT
    # --------------------------------------------------------

    elif query.data == "implement":

        await query.message.reply_text(
            "🚀 IMPLEMENTATION BLUEPRINT\n\n"
            "1. Define one target customer.\n\n"
            "2. Define ONE painful problem.\n\n"
            "3. Build the smallest workflow that solves it.\n\n"
            "4. Recommended beginner stack:\n"
            "• Frontend: React / Vite\n"
            "• Backend: Python or Supabase\n"
            "• Database: Supabase\n"
            "• AI: Add only if genuinely useful\n\n"
            "5. Build the first usable version.\n\n"
            "6. Test it with real users.\n\n"
            "7. Improve based on feedback.\n\n"
            "⚠️ Do not build the complete product before validation."
        )


# ============================================================
# 9. STRESS TEST REPLY
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
        "📋 STRESS TEST REVIEW\n\n"
        f"Your answer:\n{answer}\n\n"
        "Now challenge it:\n\n"
        "• What evidence proves the problem exists?\n"
        "• Who specifically would pay?\n"
        "• How would you reach the first 10 users?\n"
        "• What is the smallest experiment that could prove or "
        "disprove the idea?\n\n"
        "Next action: validate these assumptions with real users."
    )


# ============================================================
# 10. MAIN
# ============================================================

def main():

    app = (
        Application
        .builder()
        .token(TELEGRAM_BOT_TOKEN)
        .build()
    )

    app.add_handler(
        CommandHandler("start", start_command)
    )

    app.add_handler(
        CommandHandler("pitch", pitch_command)
    )

    app.add_handler(
        CallbackQueryHandler(button_handler)
    )

    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            reply_handler
        )
    )

    print("🚀 11Hunt Startup Agent running...")

    app.run_polling(
        drop_pending_updates=True
    )


if __name__ == "__main__":
    main()
