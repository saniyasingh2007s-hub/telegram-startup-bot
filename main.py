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
        self.wfile.write(b"Opportunity Scout Bot is active!")

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
You are a Daily Startup Opportunity Scout & Founder Validation Coach. 
Your goal is NOT to pitch shiny startup ideas, but to highlight unvalidated market problems, acute operational friction, and unaddressed customer pains across B2B, B2C, dev tools, and emerging platforms.

Return your response following this exact structured format:

🔎 DAILY OPPORTUNITY HYPOTHESIS

### 1. Problem
What appears to be happening in the market or workflow right now?

### 2. Who Experiences It
Specific target customer, role, or business type facing this exact friction.

### 3. Evidence to Look For
Specific places, complaints, or signals in reality that would prove this is a real issue.

### 4. Current Workaround
How people attempt to solve or cope with this problem today (e.g., manual spreadsheets, hacky scripts, Zapier, ignoring it).

### 5. Why It Might Be Worth Solving
The potential business value, saved hours, or avoided losses if solved cleanly.

### 6. What We DON'T Know Yet
The critical assumptions and open questions requiring real customer discovery.

---

🎯 TODAY'S VALIDATION MISSION
Target: 5 specific individuals or businesses fitting the persona.
Ask Them: "1-2 sharp discovery questions to uncover if this pain exists."
Record:
• Did it happen?
• How often?
• What was the damage/loss?
• How do they currently handle it?
• Would they pay to eliminate this?
"""

VALIDATION_PROMPT = """
You are a Lean Startup Customer Discovery Expert.
Opportunity Hypothesis:
{idea_context}

Provide a concrete, step-by-step Validation Roadmap:

🎯 OPPORTUNITY VALIDATION ROADMAP

1. TARGET CUSTOMER PROFILE
Who exactly to talk to (Job title, company size, niche, or demographic).

2. WHERE TO FIND THEM
Specific online channels, directories, communities, or platforms to locate 10 targets today.

3. DISCOVERY QUESTIONS (NOT A PITCH)
3-4 non-leading questions to ask to test if the pain is real without pitching a solution.

4. STRONG SIGNALS vs. INVALIDATION SIGNALS
• Strong Signal (Green Light): What exact behaviors or quotes confirm real pain.
• Invalidation Signal (Red Light): What responses indicate this is a non-issue.
"""

FIND_CUSTOMERS_PROMPT = """
You are a Lead Generation & Outreach Strategist.
Opportunity Hypothesis:
{idea_context}

Provide a tactical customer search blueprint:

👥 FIND POTENTIAL CUSTOMERS

1. TARGET PERSONA
Exact roles or business types to search for.

2. SPECIFIC SEARCH QUERIES
Exact search strings to copy/paste into Google, LinkedIn, X, and Reddit.

3. PLACES & COMMUNITIES
Specific subreddits, Discord/Slack groups, forums, or platforms where they hang out.

4. TRIGGER PHRASES & CONVERSATION STARTERS
Key phrases they use when complaining about this issue, and a non-spammy cold message script to open a conversation.
"""

CHALLENGE_PROMPT = """
You are a Devil's Advocate Startup Investor. Your goal is to aggressively challenge this opportunity hypothesis so the founder doesn't waste months on a dead idea.

Opportunity Hypothesis:
{idea_context}

Challenge this idea ruthlessly across these 5 questions:

🥊 OPPORTUNITY CHALLENGE

❌ Why might customers NOT pay for this?
❌ What are they already using that is "good enough"?
❌ Could this easily be solved with a simple native feature or free tool?
❌ Who experiences this frequently enough to actually care?
❌ What is the absolute smallest non-code version someone would pay for today?
"""

MVP_PROMPT = """
You are a Principal Architect helping a founder build a minimum viable product AFTER initial validation.
Opportunity Context: {idea_context}

Provide the leanest MVP build plan:

🛠️ LEAN MVP BUILD BLUEPRINT

1. Smallest Solvable Problem
The single core feature to build—omit all secondary features.

2. Core Tech Stack
Fastest, low-overhead stack to launch in 48 hours.

3. Essential User Flow
User trigger → Input → Processing → Delivered Value.

4. 3-Day Build Sprint
• Day 1: Schema & Core Logic
• Day 2: Primary Feature Delivery
• Day 3: Payment/Access Link & Deployment
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
                config={"system_instruction": system_instruction, "temperature": 0.8}
            )
            if response and response.text:
                return response.text
        except Exception as e:
            last_error = e
            continue

    raise Exception(f"Gemini Engine Error: {str(last_error)}")

# -------------------------------------------------------------------
# 4. Telegram UI & Handlers
# -------------------------------------------------------------------
def get_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🎯 Validate Opportunity", callback_data="btn_validate"),
            InlineKeyboardButton("👥 Find Potential Customers", callback_data="btn_find_customers"),
        ],
        [
            InlineKeyboardButton("🥊 Challenge Idea", callback_data="btn_challenge"),
            InlineKeyboardButton("🛠️ Build MVP", callback_data="btn_build_mvp"),
        ],
        [
            InlineKeyboardButton("🔄 Next Opportunity", callback_data="btn_next_opp"),
        ]
    ])

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    await update.message.reply_text(
        f"👋 Daily Startup Opportunity Scout Active!\n\n"
        f"• Type /pitch to get today's opportunity hypothesis.\n"
        f"• Chat ID: `{chat_id}`",
        parse_mode="Markdown"
    )

async def pitch_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    status_msg = await update.message.reply_text("🔎 Scouting market friction & compiling opportunity hypothesis...")
    try:
        pitch_text = await asyncio.to_thread(
            generate_gemini_content,
            prompt="Scout a fresh, unvalidated market opportunity, workflow pain, or customer problem.",
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
            prompt="Scout a fresh, unvalidated market opportunity, workflow pain, or customer problem.",
            system_instruction=SYSTEM_PROMPT
        )
        await context.bot.send_message(
            chat_id=MY_TELEGRAM_CHAT_ID,
            text=f"☀️ **TODAY'S MARKET OPPORTUNITY HYPOTHESIS**\n\n{pitch_text}",
            reply_markup=get_keyboard()
        )
    except Exception as e:
        print(f"Daily Scout Push Error: {e}")

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    
    # Immediately acknowledge callback to stop Telegram loading spinner
    try:
        await query.answer()
    except Exception:
        pass

    last_idea = context.user_data.get('last_idea', 'Market Opportunity Hypothesis')

    if query.data == "btn_validate":
        status_msg = await query.message.reply_text("🎯 Architecting Customer Discovery Plan...")
        try:
            prompt = VALIDATION_PROMPT.format(idea_context=last_idea)
            res = await asyncio.to_thread(
                generate_gemini_content,
                prompt=prompt,
                system_instruction="You are a Customer Discovery Expert."
            )
            await status_msg.delete()
            await query.message.reply_text(text=res)
        except Exception as e:
            await status_msg.delete()
            await query.message.reply_text(f"❌ Error: {str(e)}")

    elif query.data == "btn_find_customers":
        status_msg = await query.message.reply_text("👥 Scouting target platforms, queries, and communities...")
        try:
            prompt = FIND_CUSTOMERS_PROMPT.format(idea_context=last_idea)
            res = await asyncio.to_thread(
                generate_gemini_content,
                prompt=prompt,
                system_instruction="You are a Lead Generation Specialist."
            )
            await status_msg.delete()
            await query.message.reply_text(text=res)
        except Exception as e:
            await status_msg.delete()
            await query.message.reply_text(f"❌ Error: {str(e)}")

    elif query.data == "btn_challenge":
        status_msg = await query.message.reply_text("🥊 Stress-testing assumptions & weakness points...")
        try:
            prompt = CHALLENGE_PROMPT.format(idea_context=last_idea)
            res = await asyncio.to_thread(
                generate_gemini_content,
                prompt=prompt,
                system_instruction="You are a tough Devil's Advocate Investor."
            )
            await status_msg.delete()
            await query.message.reply_text(text=res)
        except Exception as e:
            await status_msg.delete()
            await query.message.reply_text(f"❌ Error: {str(e)}")

    elif query.data == "btn_build_mvp":
        # Guidance message reinforcing validation discipline
        await query.message.reply_text(
            "⚠️ **FOUNDER DISCIPLINE CHECK:**\n"
            "Ensure you have talked to at least 5 potential customers and verified strong signals BEFORE building!\n\n"
            "Generating Lean MVP Sprint Plan..."
        )
        status_msg = await query.message.reply_text("⚙️ Compiling MVP specification...")
        try:
            prompt = MVP_PROMPT.format(idea_context=last_idea)
            res = await asyncio.to_thread(
                generate_gemini_content,
                prompt=prompt,
                system_instruction="You are a Technical Product Architect."
            )
            await status_msg.delete()
            await query.message.reply_text(text=res)
        except Exception as e:
            await status_msg.delete()
            await query.message.reply_text(f"❌ Error: {str(e)}")

    elif query.data == "btn_next_opp":
        status_msg = await query.message.reply_text("🔄 Scouting next market opportunity hypothesis...")
        try:
            pitch_text = await asyncio.to_thread(
                generate_gemini_content,
                prompt="Scout a fresh, unvalidated market opportunity, workflow pain, or customer problem.",
                system_instruction=SYSTEM_PROMPT
            )
            context.user_data['last_idea'] = pitch_text
            await status_msg.delete()
            await query.message.reply_text(text=pitch_text, reply_markup=get_keyboard())
        except Exception as e:
            await status_msg.delete()
            await query.message.reply_text(f"❌ Error: {str(e)}")

# -------------------------------------------------------------------
# 5. Application Startup
# -------------------------------------------------------------------
def main():
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("pitch", pitch_command))
    app.add_handler(CallbackQueryHandler(button_handler))

    if MY_TELEGRAM_CHAT_ID:
        target_time = datetime.time(hour=8, minute=0, second=0, tzinfo=pytz.timezone("Asia/Kolkata"))
        app.job_queue.run_daily(scheduled_daily_pitch, time=target_time)

    print("🚀 Opportunity Scout Bot running...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
