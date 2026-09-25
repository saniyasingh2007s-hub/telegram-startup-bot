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
# 1. Health-Check HTTP Server
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
MY_TELEGRAM_CHAT_ID = os.getenv("MY_TELEGRAM_CHAT_ID")

if not TELEGRAM_BOT_TOKEN or not GEMINI_API_KEY:
    raise ValueError("Missing TELEGRAM_BOT_TOKEN or GEMINI_API_KEY environment variable.")

ai_client = genai.Client(api_key=GEMINI_API_KEY)

SYSTEM_PROMPT = """
You are an visionary Venture Capitalist & Startup Founder.
Your job is to discover massive, untapped gaps in the market and pitch completely novel startup ideas.

DO NOT restrict ideas to developer tools, APIs, or website crashes. Rotate randomly across diverse categories:
- Highly creative Consumer Apps (B2C) that have never been built before.
- Blue Ocean opportunities solving real-world lifestyle, health, hardware, or social friction.
- AI-native products for everyday non-technical users.
- Niche vertical marketplaces and novel platform business models.

Return your response following this exact structured format:

🚀 DAILY STARTUP BLUEPRINT

### 1. Story & Problem Context
Describe a relatable, real-world scenario showing a massive gap or frustration in consumer behavior or industry standard practice.

### 2. Proposed Solution
Detail the novel app, platform, or product concept that solves this gap. Explain why this specific approach has never succeeded or been tried before.

### 3. DOA Scorecard (1-10)
• Pain Intensity: X/10
• Willingness to Pay: X/10
• Distribution Ease: X/10
• Technical Feasibility: X/10

### 4. Competitor Matrix & Moat
• Existing Substitutes: How people cope today
• Why Big Players Miss This: Why incumbents won't build this
• Your Moat: Core unfair advantage or network effect

### 5. First 100 Clients / Users (GTM)
A creative, zero-budget growth hack to acquire initial users.

### 6. Daily Stress-Test Questions
1. A tactical hurdle regarding user habit adoption or retention.
2. A defensibility question about competition or economics.
"""

IMPLEMENTATION_PROMPT = """
You are a Principal Technical Architect helping a founder build an MVP.
Idea Context: {idea_context}

Provide a concrete implementation plan for this idea:

🏗️ MVP IMPLEMENTATION BLUEPRINT

1. Key System Architecture & Flow
Explain how the app works from user trigger to core value delivery.

2. Core Data Requirements
What primary entities, user profiles, or data models need to be stored?

3. Essential MVP Features (V1)
List the absolute minimum 3-4 features needed for launch.

4. 3-Day Build Sprint Plan
• Day 1: Core Mechanics & Prototype Interface
• Day 2: Primary Logic & Integration
• Day 3: User Onboarding & Launch Readiness
"""

STRESS_TEST_EVAL_PROMPT = """
You are a YC-style startup partner evaluating a founder's solution.
Startup Idea: {idea_context}
Founder's Solution: {user_answer}

Provide a quick critique:
1. What is strong about their approach?
2. What key flaw or user friction are they underestimating?
3. What is 1 actionable pivot to make it stronger?
"""

# -------------------------------------------------------------------
# 3. Resilient Dynamic Gemini Generator
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
                config={"system_instruction": system_instruction, "temperature": 0.85}
            )
            if response and response.text:
                return response.text
        except Exception as e:
            last_error = e
            continue

    raise Exception(f"Gemini Engine Error: {str(last_error)}")

# -------------------------------------------------------------------
# 4. Telegram Handlers
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
        f"👋 Startup Co-Pilot Active!\n\n"
        f"• Type /pitch to get a novel startup blueprint.\n"
        f"• Chat ID: `{chat_id}`",
        parse_mode="Markdown"
    )

async def pitch_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    status_msg = await update.message.reply_text("🤖 Scanning market gaps & crafting novel pitch...")
    try:
        pitch_text = await asyncio.to_thread(
            generate_gemini_content,
            prompt="Generate a novel, high-potential startup blueprint across consumer apps, untapped market gaps, or innovative platforms.",
            system_instruction=SYSTEM_PROMPT
        )
        context.user_data['last_idea'] = pitch_text
        await status_msg.delete()
        await update.message.reply_text(text=pitch_text, reply_markup=get_keyboard())
    except Exception as e:
        await status_msg.delete()
        await update.message.reply_text(f"❌ Error: {str(e)}")

async def scheduled_daily_pitch(context: ContextTypes.DEFAULT_TYPE):
    if not MY_TELEGRAM_CHAT_ID:
        return
    try:
        pitch_text = await asyncio.to_thread(
            generate_gemini_content,
            prompt="Generate a novel, high-potential startup blueprint across consumer apps, untapped market gaps, or innovative platforms.",
            system_instruction=SYSTEM_PROMPT
        )
        await context.bot.send_message(
            chat_id=MY_TELEGRAM_CHAT_ID,
            text=f"☀️ **MORNING MARKET GAP & STARTUP IDEA**\n\n{pitch_text}",
            reply_markup=get_keyboard()
        )
    except Exception as e:
        print(f"Daily Push Error: {e}")

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    
    # Always acknowledge the callback query immediately so Telegram buttons do not freeze
    try:
        await query.answer()
    except Exception:
        pass

    if query.data == "btn_stress_test":
        context.user_data['awaiting_stress_reply'] = True
        await query.message.reply_text("🥊 Reply directly to this message with your solution to one of today's stress-test questions.")

    elif query.data == "btn_tech_stack":
        await query.message.reply_text(
            "🛠 Recommended Tech Stack Options:\n\n"
            "• Mobile/Consumer: React Native / Flutter + Supabase\n"
            "• Web Platform: Next.js + Tailwind + PostgreSQL\n"
            "• AI Engine: Gemini API / OpenAI\n"
            "• Analytics & Growth: PostHog + Mixpanel"
        )

    elif query.data == "btn_implement":
        last_idea = context.user_data.get('last_idea', 'Recent Startup Concept')
        status_msg = await query.message.reply_text("⚙️ Generating MVP implementation roadmap...")
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
            await query.message.reply_text(f"❌ Error: {str(e)}")

    elif query.data == "btn_new_idea":
        status_msg = await query.message.reply_text("🔄 Exploring fresh consumer gaps & novel apps...")
        try:
            pitch_text = await asyncio.to_thread(
                generate_gemini_content,
                prompt="Generate a novel, high-potential startup blueprint across consumer apps, untapped market gaps, or innovative platforms.",
                system_instruction=SYSTEM_PROMPT
            )
            context.user_data['last_idea'] = pitch_text
            await status_msg.delete()
            await query.message.reply_text(text=pitch_text, reply_markup=get_keyboard())
        except Exception as e:
            await status_msg.delete()
            await query.message.reply_text(f"❌ Error: {str(e)}")

async def reply_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get('awaiting_stress_reply'):
        context.user_data['awaiting_stress_reply'] = False
        user_answer = update.message.text
        last_idea = context.user_data.get('last_idea', 'Startup Pitch')
        status_msg = await update.message.reply_text("🧐 Analyzing your execution plan...")
        try:
            prompt = STRESS_TEST_EVAL_PROMPT.format(idea_context=last_idea, user_answer=user_answer)
            critique = await asyncio.to_thread(
                generate_gemini_content,
                prompt=prompt,
                system_instruction="You are a tough YC startup reviewer."
            )
            await status_msg.delete()
            await update.message.reply_text(f"📋 CRITIQUE:\n\n{critique}")
        except Exception as e:
            await status_msg.delete()
            await update.message.reply_text(f"❌ Error: {str(e)}")

# -------------------------------------------------------------------
# 5. Application Startup
# -------------------------------------------------------------------
def main():
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("pitch", pitch_command))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, reply_handler))

    if MY_TELEGRAM_CHAT_ID:
        target_time = datetime.time(hour=8, minute=0, second=0, tzinfo=pytz.timezone("Asia/Kolkata"))
        app.job_queue.run_daily(scheduled_daily_pitch, time=target_time)

    print("🚀 Bot running...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
