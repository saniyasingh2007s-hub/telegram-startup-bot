import os
import asyncio
import threading
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

# ============================================================
# 1. RENDER HEALTH CHECK
# ============================================================

class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"11Hunt Startup Agent is running.")

    def do_HEAD(self):
        self.send_response(200)
        self.end_headers()


def run_health_server():
    port = int(os.getenv("PORT", "8080"))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    server.serve_forever()


threading.Thread(target=run_health_server, daemon=True).start()


# ============================================================
# 2. API SETUP
# ============================================================

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

if not TELEGRAM_BOT_TOKEN:
    raise ValueError("Missing TELEGRAM_BOT_TOKEN")

if not GEMINI_API_KEY:
    raise ValueError("Missing GEMINI_API_KEY")

ai_client = genai.Client(api_key=GEMINI_API_KEY)

# IMPORTANT:
# Use the model currently available to your Gemini API project.
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")


# ============================================================
# 3. STARTUP AGENT PROMPT
# ============================================================

SYSTEM_PROMPT = """
You are 11Hunt Startup Agent.

You help a student founder discover, evaluate and build startup ideas.

Your ideas must be:
- practical
- buildable by a student/solo founder
- capable of becoming an app, SaaS, AI tool or AI agent
- based on a real problem
- specific rather than generic
- realistic about competition
- focused on getting first users

When generating an idea, use this format:

🚀 STARTUP BLUEPRINT

🎯 IDEA
Name + one-line description.

🔥 PROBLEM
Who has the problem and what exactly is painful?

💡 SOLUTION
What does the product do?

👤 TARGET USER
Who would actually use/pay for it?

🤖 AI / AUTOMATION
Explain where AI or automation is genuinely useful.

🛠 MVP
Give the smallest version that can be built first.

💰 MONETIZATION
How could this make money?

🥊 COMPETITION
Mention relevant existing alternatives.

📈 FIRST USERS
Give practical ways to find the first users.

⚠️ BIGGEST RISK
The biggest reason this idea might fail.

🚀 IMPLEMENTATION
Give a simple first build plan.
"""


# ============================================================
# 4. GEMINI CALL
# ============================================================

def generate_content(prompt: str, system_instruction: str = SYSTEM_PROMPT) -> str:

    response = ai_client.models.generate_content(
        model=GEMINI_MODEL,
        contents=prompt,
        config={
            "system_instruction": system_instruction,
            "temperature": 0.7,
        },
    )

    if not response or not response.text:
        raise Exception("Gemini returned an empty response.")

    return response.text


# ============================================================
# 5. KEYBOARDS
# ============================================================

def idea_keyboard():

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🚀 Implement This",
                callback_data="implement"
            )
        ],
        [
            InlineKeyboardButton(
                "🛠 Tech Stack",
                callback_data="tech"
            ),
            InlineKeyboardButton(
                "🥊 Stress Test",
                callback_data="stress"
            )
        ],
        [
            InlineKeyboardButton(
                "🔄 New Idea",
                callback_data="new_idea"
            )
        ]
    ])


def startup_type_keyboard():

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "📱 App / SaaS",
                callback_data="type_app"
            )
        ],
        [
            InlineKeyboardButton(
                "🤖 AI Agent",
                callback_data="type_agent"
            )
        ],
        [
            InlineKeyboardButton(
                "🎲 Surprise Me",
                callback_data="type_random"
            )
        ]
    ])


# ============================================================
# 6. /START
# ============================================================

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):

    text = """
🚀 11Hunt Startup Agent

I'm your startup idea + execution copilot.

What do you want to explore?
"""

    await update.message.reply_text(
        text,
        reply_markup=startup_type_keyboard()
    )


# ============================================================
# 7. /PITCH
# ============================================================

async def pitch_command(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await update.message.reply_text(
        "🚀 What should I generate?",
        reply_markup=startup_type_keyboard()
    )


# ============================================================
# 8. GENERATE IDEA
# ============================================================

async def generate_idea(
    query,
    context,
    idea_type="random"
):

    if idea_type == "app":
        request = """
Generate ONE strong startup idea that is primarily an APP or SaaS product.

Do not give a generic AI wrapper.

Think about:
- real user pain
- specific niche
- recurring use
- simple MVP
- potential monetization

Return the complete STARTUP BLUEPRINT.
"""

    elif idea_type == "agent":
        request = """
Generate ONE strong startup idea that is primarily an AI AGENT.

The agent must perform useful multi-step work for a specific user.

Do not simply say "AI chatbot".

Explain:
- what triggers the agent
- what information it processes
- what actions it performs
- what result it produces
- why the user would pay

Return the complete STARTUP BLUEPRINT.
"""

    else:
        request = """
Generate ONE practical startup idea.

It can be:
- an app
- SaaS
- AI agent
- automation product

Prefer an idea that a student/solo founder could realistically build an MVP for.
Return the complete STARTUP BLUEPRINT.
"""

    status = await query.message.reply_text(
        "🧠 11Hunt is thinking..."
    )

    try:

        result = await asyncio.to_thread(
            generate_content,
            request
        )

        context.user_data["last_idea"] = result

        await status.delete()

        await query.message.reply_text(
            result,
            reply_markup=idea_keyboard()
        )

    except Exception as e:

        await status.edit_text(
            f"❌ Gemini Error\n\n{str(e)}"
        )


# ============================================================
# 9. BUTTON HANDLER
# ============================================================

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query
    await query.answer()

    # -----------------------------
    # SELECT APP
    # -----------------------------

    if query.data == "type_app":

        await generate_idea(
            query,
            context,
            "app"
        )

    # -----------------------------
    # SELECT AI AGENT
    # -----------------------------

    elif query.data == "type_agent":

        await generate_idea(
            query,
            context,
            "agent"
        )

    # -----------------------------
    # RANDOM
    # -----------------------------

    elif query.data == "type_random":

        await generate_idea(
            query,
            context,
            "random"
        )

    # -----------------------------
    # NEW IDEA
    # -----------------------------

    elif query.data == "new_idea":

        await generate_idea(
            query,
            context,
            "random"
        )

    # -----------------------------
    # IMPLEMENT
    # -----------------------------

    elif query.data == "implement":

        idea = context.user_data.get(
            "last_idea",
            "No startup idea stored."
        )

        status = await query.message.reply_text(
            "🛠 Creating implementation plan..."
        )

        prompt = f"""
The founder wants to IMPLEMENT this startup idea:

{idea}

Create a practical MVP implementation plan.

Include:

1. MVP goal
2. Core features
3. User flow
4. Recommended tech stack
5. AI components
6. Database requirements
7. What to build first
8. What NOT to build yet
9. 48-hour prototype plan
10. First test user strategy

Keep it realistic for a student/solo founder.
"""

        try:

            result = await asyncio.to_thread(
                generate_content,
                prompt
            )

            await status.delete()

            await query.message.reply_text(
                "🚀 IMPLEMENTATION PLAN\n\n" + result
            )

        except Exception as e:

            await status.edit_text(
                f"❌ Error\n\n{str(e)}"
            )

    # -----------------------------
    # TECH STACK
    # -----------------------------

    elif query.data == "tech":

        idea = context.user_data.get(
            "last_idea",
            ""
        )

        status = await query.message.reply_text(
            "🛠 Designing the MVP stack..."
        )

        prompt = f"""
For this startup:

{idea}

Give a simple student-friendly technology stack.

Include:
- frontend
- backend
- database
- AI model
- authentication
- deployment
- integrations

Avoid unnecessary infrastructure.
Explain why each technology is needed.
"""

        try:

            result = await asyncio.to_thread(
                generate_content,
                prompt
            )

            await status.delete()

            await query.message.reply_text(
                "🛠 TECH STACK\n\n" + result
            )

        except Exception as e:

            await status.edit_text(
                f"❌ Error\n\n{str(e)}"
            )

    # -----------------------------
    # STRESS TEST
    # -----------------------------

    elif query.data == "stress":

        idea = context.user_data.get(
            "last_idea",
            ""
        )

        context.user_data["stress_mode"] = True

        await query.message.reply_text(
            f"""
🥊 STARTUP STRESS TEST

Here is your idea:

{idea}

Challenge:

What is the biggest reason a real customer might refuse to use or pay for this?

Reply with your answer.
I will challenge your reasoning.
"""
        )


# ============================================================
# 10. TEXT RESPONSE / STRESS TEST
# ============================================================

async def reply_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not context.user_data.get("stress_mode"):
        return

    context.user_data["stress_mode"] = False

    answer = update.message.text

    idea = context.user_data.get(
        "last_idea",
        ""
    )

    status = await update.message.reply_text(
        "🥊 Stress-testing your answer..."
    )

    prompt = f"""
You are a tough startup reviewer.

STARTUP IDEA:
{idea}

FOUNDER'S ANSWER:
{answer}

Analyze:

1. What is strong?
2. What assumption is weak?
3. What important risk is missing?
4. What experiment should the founder run?
5. Give one concrete next action.

Be direct. Do not blindly agree.
"""

    try:

        result = await asyncio.to_thread(
            generate_content,
            prompt,
            "You are a brutally honest but constructive startup reviewer."
        )

        await status.delete()

        await update.message.reply_text(
            "🥊 STRESS TEST RESULT\n\n" + result
        )

    except Exception as e:

        await status.edit_text(
            f"❌ Error\n\n{str(e)}"
        )


# ============================================================
# 11. DAILY 8 AM REMINDER
# ============================================================

async def daily_startup(context: ContextTypes.DEFAULT_TYPE):

    chat_id = context.job.chat_id

    await context.bot.send_message(
        chat_id=chat_id,
        text=(
            "☀️ GOOD MORNING, FOUNDER\n\n"
            "Ready for today's startup hunt?\n\n"
            "Use /pitch to generate today's idea."
        )
    )


async def setup_daily_reminder(update: Update, context: ContextTypes.DEFAULT_TYPE):

    chat_id = update.effective_chat.id

    # Remove previous reminder for this chat
    current_jobs = context.job_queue.get_jobs_by_name(
        f"daily_{chat_id}"
    )

    for job in current_jobs:
        job.schedule_removal()

    # 08:00 local bot/server timezone
    context.job_queue.run_daily(
        daily_startup,
        time=__import__("datetime").time(
            hour=8,
            minute=0
        ),
        chat_id=chat_id,
        name=f"daily_{chat_id}"
    )

    await update.message.reply_text(
        "⏰ Daily 8 AM startup reminder enabled."
    )


# ============================================================
# 12. MAIN
# ============================================================

def main():

    application = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .build()
    )

    application.add_handler(
        CommandHandler("start", start_command)
    )

    application.add_handler(
        CommandHandler("pitch", pitch_command)
    )

    application.add_handler(
        CommandHandler("reminder", setup_daily_reminder)
    )

    application.add_handler(
        CallbackQueryHandler(button_handler)
    )

    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            reply_handler
        )
    )

    print("🚀 11Hunt Startup Agent running...")

    application.run_polling(
        drop_pending_updates=True
    )


if __name__ == "__main__":
    main()
