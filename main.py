import os
import asyncio
import threading
import datetime
import pytz
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
# 1. Health-Check HTTP Server (Satisfies Render Free Web Service)
# -------------------------------------------------------------------
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is active and running!")

def run_health_server():
    port = int(os.getenv("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    server.serve_forever()

threading.Thread(target=run_health_server, daemon=True).start()

# -------------------------------------------------------------------
# 2. Environment Setup & Prompts
# -------------------------------------------------------------------
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
MY_TELEGRAM_CHAT_ID = os.getenv("MY_TELEGRAM_CHAT_ID")  # Your chat ID for 8 AM alerts

if not TELEGRAM_BOT_TOKEN or not GEMINI_API_KEY:
    raise ValueError("Missing TELEGRAM_BOT_TOKEN or GEMINI_API_KEY environment variable.")

ai_client = genai.Client(api_key=GEMINI_API_KEY)

SYSTEM_PROMPT = """
You are an elite Startup Analyst & Co-Pilot for a CS student/founder. 
Generate a sharp, deeply analytical startup pitch.

Return your response following this exact structured format:

🚀 DAILY STARTUP BLUEPRINT

1. Story & Problem Context
Write a 2-3 sentence realistic story illustrating a severe inefficiency or pain point in B2B/Dev/AI tools.

2. Proposed Solution
Describe the core micro-SaaS or AI agent solution and its main value proposition.

3. DOA Scorecard (1-10)
• Pain Intensity: X/10
• Willingness to Pay: X/10
• Distribution Ease: X/10
• Technical Feasibility: X/10

4. Competitor Matrix & Moat
• Incumbents: Names
• Where They Fail: Key weakness
• Your Moat: Why a solo builder can win

5. First 100 Clients (GTM)
Actionable, non-paid strategy to acquire first customers.

6. Daily Stress-Test Questions
1. A hard tactical question about edge cases or execution.
2. A hard question about user acquisition or defensibility.
"""

IMPLEMENTATION_PROMPT = """
You are a Principal Software Architect helping a solo developer build an MVP.
Idea: {idea_context}

Provide a concrete, actionable implementation blueprint following this exact structure:

🏗️ MVP IMPLEMENTATION BLUEPRINT

1. Project Folder Structure
Show a clean text directory layout (e.g., app/api, app/services, app/models).

2. Database Schema (PostgreSQL/Supabase)
Provide the core SQL tables and fields needed to store essential state.

3. Primary API Endpoints
List 3-4 essential REST/GraphQL endpoints (HTTP Method, Route, Purpose).

4. 3-Day Build Sprint Plan
• Day 1: Core Backend & Data Models
• Day 2: LLM Agent Integration / Third-Party Services
• Day 3: Frontend Interface & MVP Deployment
"""

STRESS_TEST_EVAL_PROMPT = """
You are a tough YC-style startup reviewer evaluating a founder's answer to a stress-test challenge.
Original Idea: {idea_context}
Founder's Answer: {user_answer}

Critique their answer concisely:
1. What is strong about their plan?
2. What edge case or risk are they missing?
3. Give 1 actionable improvement to refine their approach.
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
                config={"system_instruction": system_instruction, "temperature": 0.7}
            )
            if response and response.text:
                return response.text
        except Exception as e:
            last_error = e
            continue

    raise Exception(f"Gemini API Engine Error: {str(last_error)}")

# -------------------------------------------------------------------
# 4. Telegram UI & Handlers
# -------------------------------------------------------------------
def get_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🎯 Answer Stress-Test", callback_data="btn_stress_test"),
            InlineKeyboardButton("🛠 Tech Stack Ideas", callback_data="btn_tech_stack"),
        ],
        [
            InlineKeyboardButton("🏗️ Implement This Idea", callback_data="btn_implement"),
            InlineKeyboardButton("🔄 Generate Another Idea", callback_data="btn_new_idea"),
        ]
    ])

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    await update.message.reply_text(
        f"👋 Startup Co-Pilot active!\n\n"
        f"• Type /pitch to receive today's blueprint.\n"
        f"• Your Chat ID is `{chat_id}` (save this in Render environment variables as `MY_TELEGRAM_CHAT_ID` for daily 8 AM pitches).",
        parse_mode="Markdown"
    )

async def pitch_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    status_msg = await update.message.reply_text("🤖 Agent scanning market gaps & compiling pitch...")
    try:
        pitch_text = await asyncio.to_thread(
            generate_gemini_content,
            prompt="Provide today's unique B2B micro-SaaS or AI Agent startup blueprint.",
            system_instruction=SYSTEM_PROMPT
        )
        context.user_data['last_idea'] = pitch_text
        await status_msg.delete()
        await update.message.reply_text(text=pitch_text, reply_markup=get_keyboard())
    except Exception as e:
        await status_msg.delete()
        await update.message.reply_text(f"❌ {str(e)}")

async def scheduled_daily_pitch(context: ContextTypes.DEFAULT_TYPE):
    if not MY_TELEGRAM_CHAT_ID:
        return
    try:
        pitch_text = await asyncio.to_thread(
            generate_gemini_content,
            prompt="Provide today's unique B2B micro-SaaS or AI Agent startup blueprint.",
            system_instruction=SYSTEM_PROMPT
        )
        await context.bot.send_message(
            chat_id=MY_TELEGRAM_CHAT_ID,
            text=f"☀️ **GOOD MORNING! TODAY'S STARTUP BLUEPRINT**\n\n{pitch_text}",
            reply_markup=get_keyboard(),
            parse_mode="Markdown"
        )
    except Exception as e:
        print(f"Daily Pitch Error: {e}")

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    try:
        await query.answer()
    except Exception:
        pass

    if query.data == "btn_stress_test":
        context.user_data['awaiting_stress_reply'] = True
        await query.message.reply_text("🥊 Reply directly to this message with your solution to one of today's stress-test questions.")

    elif query.data == "btn_tech_stack":
        await query.message.reply_text(
            "🛠 Recommended MVP Tech Stack:\n"
            "• Backend: FastAPI / Python\n"
            "• DB: Supabase (PostgreSQL)\n"
            "• Agent LLM Engine: Gemini Engine\n"
            "• Distribution: Automated Cold Outreach"
        )

    elif query.data == "btn_implement":
        last_idea = context.user_data.get('last_idea', 'Recent Startup Idea')
        status_msg = await query.message.reply_text("⚙️ Architecting MVP implementation blueprint...")
        try:
            prompt = IMPLEMENTATION_PROMPT.format(idea_context=last_idea)
            plan = await asyncio.to_thread(
                generate_gemini_content,
                prompt=prompt,
                system_instruction="You are a Principal Software Architect."
            )
            await status_msg.delete()
            await query.message.reply_text(text=plan)
        except Exception as e:
            await status_msg.delete()
            await query.message.reply_text(f"❌ {str(e)}")

    elif query.data == "btn_new_idea":
        status_msg = await query.message.reply_text("🔄 Agent brainstorming fresh concept...")
        try:
            pitch_text = await asyncio.to_thread(
                generate_gemini_content,
                prompt="Provide today's unique B2B micro-SaaS or AI Agent startup blueprint.",
                system_instruction=SYSTEM_PROMPT
            )
            context.user_data['last_idea'] = pitch_text
            await status_msg.delete()
            await query.message.reply_text(text=pitch_text, reply_markup=get_keyboard())
        except Exception as e:
            await status_msg.delete()
            await query.message.reply_text(f"❌ {str(e)}")

async def reply_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get('awaiting_stress_reply'):
        context.user_data['awaiting_stress_reply'] = False
        user_answer = update.message.text
        last_idea = context.user_data.get('last_idea', 'Startup Pitch')
        status_msg = await update.message.reply_text("🧐 Agent evaluating execution plan...")
        try:
            prompt = STRESS_TEST_EVAL_PROMPT.format(idea_context=last_idea, user_answer=user_answer)
            critique = await asyncio.to_thread(
                generate_gemini_content,
                prompt=prompt,
                system_instruction="You are a tough YC-style startup reviewer."
            )
            await status_msg.delete()
            await update.message.reply_text(f"📋 CRITIQUE:\n\n{critique}")
        except Exception as e:
            await status_msg.delete()
            await update.message.reply_text(f"❌ {str(e)}")

# -------------------------------------------------------------------
# 5. Main Application Loop & Scheduler
# -------------------------------------------------------------------
def main():
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("pitch", pitch_command))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, reply_handler))

    # Schedule Daily 8:00 AM Pitch (Asia/Kolkata timezone)
    if MY_TELEGRAM_CHAT_ID:
        target_time = datetime.time(hour=8, minute=0, second=0, tzinfo=pytz.timezone("Asia/Kolkata"))
        app.job_queue.run_daily(scheduled_daily_pitch, time=target_time)

    print("🚀 Bot initialized, listening for updates...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
