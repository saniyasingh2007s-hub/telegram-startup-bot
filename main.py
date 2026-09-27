import os
import asyncio
import threading
from datetime import time
from http.server import HTTPServer, BaseHTTPRequestHandler

import pytz
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
# 1. RENDER HEALTH SERVER
# ================================================================

class HealthCheckHandler(BaseHTTPRequestHandler):

    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Startup Co-Pilot is alive!")

    def do_HEAD(self):
        self.send_response(200)
        self.end_headers()

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

if not TELEGRAM_BOT_TOKEN:
    raise ValueError("Missing TELEGRAM_BOT_TOKEN")

if not GEMINI_API_KEY:
    raise ValueError("Missing GEMINI_API_KEY")


ai_client = genai.Client(api_key=GEMINI_API_KEY)

TIMEZONE = pytz.timezone("Asia/Kolkata")


# ================================================================
# 3. GEMINI ENGINE
# ================================================================

MODELS = [
    "gemini-3.8-flash",
    "gemini-3.7-flash",
    "gemini-3.6-flash",
    "gemini-3.5-flash-lite",
]


async def ask_ai(prompt):
    """
    Runs Gemini without automatic function calling.
    """

    last_error = None

    for model in MODELS:

        try:
            response = await asyncio.to_thread(
                ai_client.models.generate_content,
                model=model,
                contents=prompt,
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
# 4. PROMPTS
# ================================================================

BLUEPRINT_PROMPT = """
You are Startup Co-Pilot for a CS student founder.

Generate ONE realistic startup idea that a student could actually
build using AI/no-code/low-code tools.

IMPORTANT:
The idea should preferably be an APP, micro-SaaS, AI tool,
automation product, or useful web product.

Use this exact structure:

🚀 DAILY STARTUP BLUEPRINT

💡 IDEA
Name:
One-line description:

🎯 PROBLEM
Who has the problem?
What exactly is painful?

🛠 SOLUTION
What would the app do?

👤 FIRST USER
Who should use it first?

💰 MONETIZATION
How could it make money?

⚡ MVP
List only the 3-5 features required for version 1.

📈 FIRST 10 USERS
Give a realistic way for a student to find the first users.

🥊 STRESS TEST
Give 2 difficult questions the founder must answer.

Keep it practical.
Do not invent fake statistics.
Do not claim something is guaranteed.
"""


APP_IDEA_PROMPT = """
You are an expert product founder helping a CS student build an
actual app.

Generate ONE buildable app startup idea.

The idea must:
- solve a specific problem
- have a clear target user
- be possible to prototype quickly
- use AI only where it adds real value
- have a possible path to revenue

Return:

💡 APP IDEA

Name:
Target user:
Problem:
Solution:

CORE USER FLOW
1.
2.
3.
4.

MVP FEATURES
1.
2.
3.
4.
5.

WHY SOMEONE WOULD PAY

HOW TO GET FIRST 10 USERS

BIGGEST RISK

Keep it realistic and concise.
"""


BUILD_PROMPT = """
You are a startup product architect.

Take the following startup idea and turn it into a practical MVP.

STARTUP IDEA:
{idea}

Return:

🚀 BUILD SPEC

1. PRODUCT
What exactly are we building?

2. USER
Who uses it?

3. CORE WORKFLOW
Step-by-step user journey.

4. MVP FEATURES
Only essential features.

5. AI ROLE
Exactly where AI is used.

6. TECH STACK
Frontend:
Backend:
Database:
AI:
Hosting:

7. 48-HOUR MVP
Day 1:
Day 2:

8. WHAT NOT TO BUILD
List unnecessary features.

Make this realistic for a beginner/student founder.
"""


IMPLEMENT_PROMPT = """
You are the technical implementation mentor for a beginner founder.

The founder wants to build this product:

{idea}

Create a concrete implementation plan.

Return:

⚙️ IMPLEMENTATION PLAN

STEP 1 — SETUP
Exact project setup.

STEP 2 — FRONTEND
What screens/components to create.

STEP 3 — BACKEND
What APIs/endpoints are required.

STEP 4 — DATABASE
Tables/data required.

STEP 5 — AI
What Gemini/AI should do.

STEP 6 — CONNECT EVERYTHING
How the pieces communicate.

STEP 7 — TEST
What must be tested.

STEP 8 — DEPLOY
Simple deployment plan.

🔥 FIRST VERSION
Tell the founder exactly what the smallest working version should contain.

Do NOT add unnecessary complexity.
"""


STRESS_PROMPT = """
You are a brutally honest startup reviewer.

Startup idea:
{idea}

Founder answer:
{answer}

Review:

✅ WHAT IS GOOD

⚠️ WHAT IS WEAK

🔍 WHAT THEY MISSED

🎯 ONE SPECIFIC IMPROVEMENT

Keep it concise and practical.
"""


TECH_PROMPT = """
For this startup idea:

{idea}

Give a beginner-friendly MVP tech stack.

Include:

Frontend:
Backend:
Database:
AI:
Authentication:
Hosting:
Useful APIs:

Then explain why each choice is appropriate.

Avoid overengineering.
"""


# ================================================================
# 5. KEYBOARDS
# ================================================================

def main_keyboard():

    return InlineKeyboardMarkup([

        [
            InlineKeyboardButton(
                "💡 App Idea",
                callback_data="app_idea"
            ),
            InlineKeyboardButton(
                "🚀 Build This",
                callback_data="build"
            ),
        ],

        [
            InlineKeyboardButton(
                "⚙️ Implement",
                callback_data="implement"
            ),
            InlineKeyboardButton(
                "🥊 Stress Test",
                callback_data="stress"
            ),
        ],

        [
            InlineKeyboardButton(
                "🛠 Tech Stack",
                callback_data="tech"
            ),
            InlineKeyboardButton(
                "🔄 New Idea",
                callback_data="new"
            ),
        ],

        [
            InlineKeyboardButton(
                "⏰ 8 AM Daily",
                callback_data="alarm"
            )
        ]

    ])


# ================================================================
# 6. START
# ================================================================

async def start_command(update, context):

    chat_id = update.effective_chat.id

    context.user_data["chat_id"] = chat_id

    await update.message.reply_text(
        """
👋 *Startup Co-Pilot is active.*

I can help you:

💡 Find app ideas
🚀 Turn ideas into MVPs
⚙️ Create implementation plans
🥊 Stress-test ideas
🛠 Choose a tech stack
⏰ Send you a startup blueprint every morning

Start with:

/pitch
        """,
        parse_mode="Markdown",
        reply_markup=main_keyboard()
    )


# ================================================================
# 7. GENERATE DAILY IDEA
# ================================================================

async def generate_blueprint():

    return await ask_ai(BLUEPRINT_PROMPT)


async def pitch_command(update, context):

    status = await update.message.reply_text(
        "🤖 Thinking of a practical startup idea..."
    )

    try:

        idea = await generate_blueprint()

        context.user_data["last_idea"] = idea

        await status.delete()

        await update.message.reply_text(
            idea,
            reply_markup=main_keyboard()
        )

    except Exception as error:

        await status.edit_text(
            f"❌ {error}"
        )


# ================================================================
# 8. APP IDEA
# ================================================================

async def app_idea(update, context):

    status = await update.message.reply_text(
        "💡 Finding a buildable app idea..."
    )

    try:

        idea = await ask_ai(APP_IDEA_PROMPT)

        context.user_data["last_idea"] = idea

        await status.delete()

        await update.message.reply_text(
            idea,
            reply_markup=main_keyboard()
        )

    except Exception as error:

        await status.edit_text(
            f"❌ {error}"
        )


# ================================================================
# 9. BUILD
# ================================================================

async def build_app(update, context):

    idea = context.user_data.get(
        "last_idea",
        "No startup idea selected yet."
    )

    status = await update.message.reply_text(
        "🚀 Turning the idea into an MVP..."
    )

    try:

        prompt = BUILD_PROMPT.format(
            idea=idea
        )

        result = await ask_ai(prompt)

        context.user_data["build_plan"] = result

        await status.delete()

        await update.message.reply_text(
            result,
            reply_markup=main_keyboard()
        )

    except Exception as error:

        await status.edit_text(
            f"❌ {error}"
        )


# ================================================================
# 10. IMPLEMENT
# ================================================================

async def implement_app(update, context):

    idea = context.user_data.get(
        "build_plan",
        context.user_data.get(
            "last_idea",
            "No startup idea selected."
        )
    )

    status = await update.message.reply_text(
        "⚙️ Creating the implementation roadmap..."
    )

    try:

        prompt = IMPLEMENT_PROMPT.format(
            idea=idea
        )

        result = await ask_ai(prompt)

        await status.delete()

        await update.message.reply_text(
            result,
            reply_markup=main_keyboard()
        )

    except Exception as error:

        await status.edit_text(
            f"❌ {error}"
        )


# ================================================================
# 11. TECH STACK
# ================================================================

async def tech_stack(update, context):

    idea = context.user_data.get(
        "last_idea",
        "No startup idea selected."
    )

    status = await update.message.reply_text(
        "🛠 Designing the simplest tech stack..."
    )

    try:

        prompt = TECH_PROMPT.format(
            idea=idea
        )

        result = await ask_ai(prompt)

        await status.delete()

        await update.message.reply_text(
            result,
            reply_markup=main_keyboard()
        )

    except Exception as error:

        await status.edit_text(
            f"❌ {error}"
        )


# ================================================================
# 12. STRESS TEST
# ================================================================

async def stress_test(update, context):

    idea = context.user_data.get(
        "last_idea",
        "No startup idea selected."
    )

    context.user_data["waiting_for_stress"] = True

    await update.message.reply_text(
        f"""
🥊 *STRESS TEST*

Startup:

{idea}

Tell me:

*Why would someone pay for this instead of
using an existing solution?*

Reply with your answer.
        """,
        parse_mode="Markdown"
    )


async def stress_reply(update, context):

    if not context.user_data.get("waiting_for_stress"):
        return

    context.user_data["waiting_for_stress"] = False

    idea = context.user_data.get(
        "last_idea",
        "Unknown startup"
    )

    answer = update.message.text

    status = await update.message.reply_text(
        "🧐 Stress-testing your answer..."
    )

    try:

        prompt = STRESS_PROMPT.format(
            idea=idea,
            answer=answer
        )

        result = await ask_ai(prompt)

        await status.delete()

        await update.message.reply_text(
            result,
            reply_markup=main_keyboard()
        )

    except Exception as error:

        await status.edit_text(
            f"❌ {error}"
        )


# ================================================================
# 13. NEW IDEA
# ================================================================

async def new_idea(update, context):

    status = await update.message.reply_text(
        "🔄 Generating a fresh idea..."
    )

    try:

        idea = await generate_blueprint()

        context.user_data["last_idea"] = idea

        await status.delete()

        await update.message.reply_text(
            idea,
            reply_markup=main_keyboard()
        )

    except Exception as error:

        await status.edit_text(
            f"❌ {error}"
        )


# ================================================================
# 14. 8 AM DAILY ALARM
# ================================================================

async def daily_blueprint(context):

    chat_id = context.job.chat_id

    try:

        idea = await generate_blueprint()

        context.user_data["last_idea"] = idea

        await context.bot.send_message(
            chat_id=chat_id,
            text="☀️ *YOUR 8 AM STARTUP BLUEPRINT*\n\n"
                 + idea,
            parse_mode="Markdown",
            reply_markup=main_keyboard()
        )

    except Exception as error:

        await context.bot.send_message(
            chat_id=chat_id,
            text=f"❌ Daily blueprint failed:\n{error}"
        )


def schedule_alarm(application, chat_id):

    # Remove previous alarm for this chat
    if application.job_queue:

        for job in application.job_queue.get_jobs_by_name(
            f"daily_{chat_id}"
        ):
            job.schedule_removal()

        application.job_queue.run_daily(
            daily_blueprint,
            time=time(
                hour=8,
                minute=0,
                tzinfo=TIMEZONE
            ),
            chat_id=chat_id,
            name=f"daily_{chat_id}"
        )


async def alarm_command(update, context):

    chat_id = update.effective_chat.id

    schedule_alarm(
        context.application,
        chat_id
    )

    await update.message.reply_text(
        "⏰ *8 AM alarm activated.*\n\n"
        "I'll send you a startup blueprint every morning at 8:00 AM IST.",
        parse_mode="Markdown"
    )


async def stop_alarm(update, context):

    chat_id = update.effective_chat.id

    if context.application.job_queue:

        jobs = context.application.job_queue.get_jobs_by_name(
            f"daily_{chat_id}"
        )

        for job in jobs:
            job.schedule_removal()

    await update.message.reply_text(
        "🔕 8 AM startup alarm stopped."
    )


# ================================================================
# 15. BUTTON HANDLER
# ================================================================

async def button_handler(update, context):

    query = update.callback_query

    await query.answer()

    if query.data == "app_idea":

        await app_idea(update, context)

    elif query.data == "build":

        await build_app(update, context)

    elif query.data == "implement":

        await implement_app(update, context)

    elif query.data == "stress":

        await stress_test(update, context)

    elif query.data == "tech":

        await tech_stack(update, context)

    elif query.data == "new":

        await new_idea(update, context)

    elif query.data == "alarm":

        schedule_alarm(
            context.application,
            update.effective_chat.id
        )

        await query.message.reply_text(
            "⏰ 8 AM daily startup blueprint activated."
        )


# ================================================================
# 16. MAIN
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
        CommandHandler("start", start_command)
    )

    app.add_handler(
        CommandHandler("pitch", pitch_command)
    )

    app.add_handler(
        CommandHandler("alarm", alarm_command)
    )

    app.add_handler(
        CommandHandler("stopalarm", stop_alarm)
    )

    # Buttons
    app.add_handler(
        CallbackQueryHandler(button_handler)
    )

    # Text / stress-test replies
    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            stress_reply
        )
    )

    print("🚀 Startup Co-Pilot running...")

    app.run_polling(
        drop_pending_updates=True
    )


if __name__ == "__main__":
    main()
