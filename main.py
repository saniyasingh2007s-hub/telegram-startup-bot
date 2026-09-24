import os
import time
import asyncio
import threading
import requests
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

if not TELEGRAM_BOT_TOKEN or not GEMINI_API_KEY:
    raise ValueError("Missing TELEGRAM_BOT_TOKEN or GEMINI_API_KEY environment variable.")

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
# 3. Rock-Solid Production Engine (Stable Models + Instant Fallback)
# -------------------------------------------------------------------
class GeminiAgentEngine:
    def __init__(self, api_key: str):
        self.api_key = api_key
        # Strict fallback array targeting reliable, production-tier endpoints
        self.models = ["gemini-1.5-flash", "gemini-1.5-pro"]

    def generate(self, prompt: str, system_instruction: str) -> str:
        last_error = ""
        
        for model in self.models:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={self.api_key}"
            headers = {"Content-Type": "application/json"}
            payload = {
                "contents": [{"parts": [{"text": prompt}]}],
                "systemInstruction": {"parts": [{"text": system_instruction}]},
                "generationConfig": {"temperature": 0.7}
            }

            # Retry each model up to 2 times before failing over to the next
            for attempt in range(2):
                try:
                    res = requests.post(url, headers=headers, json=payload, timeout=25)
                    res_data = res.json()

                    if res.status_code == 200:
                        return res_data["candidates"][0]["content"]["parts"][0]["text"]
                    
                    # Capture Google API error message
                    last_error = res_data.get("error", {}).get("message", f"HTTP {res.status_code}")
                    time.sleep(1) # Wait 1s before retry
                except Exception as e:
                    last_error = str(e)
                    time.sleep(1)

        raise Exception(f"Google API Error: {last_error}")

agent_engine = GeminiAgentEngine(GEMINI_API_KEY)

# -------------------------------------------------------------------
# 4. Telegram Handlers
# -------------------------------------------------------------------
def get_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🎯 Answer Stress-Test", callback_data="btn_stress_test"),
            InlineKeyboardButton("🛠 Tech Stack Ideas", callback_data="btn_tech_stack"),
        ],
        [InlineKeyboardButton("🔄 Generate Another Idea", callback_data="btn_new_idea")]
    ])

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Startup Co-Pilot active! Type /pitch to receive today's blueprint.")

async def pitch_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    status_msg = await update.message.reply_text("🤖 Agent scanning market gaps & compiling pitch...")
    try:
        pitch_text = await asyncio.to_thread(
            agent_engine.generate,
            prompt="Provide today's unique B2B micro-SaaS or AI Agent startup blueprint.",
            system_instruction=SYSTEM_PROMPT
        )
        context.user_data['last_idea'] = pitch_text
        await status_msg.delete()
        await update.message.reply_text(text=pitch_text, reply_markup=get_keyboard())
    except Exception as e:
        await status_msg.delete()
        await update.message.reply_text(f"❌ {str(e)}")

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "btn_stress_test":
        context.user_data['awaiting_stress_reply'] = True
        await query.message.reply_text("🥊 Reply directly to this message with your solution to one of today's stress-test questions.")
    elif query.data == "btn_tech_stack":
        await query.message.reply_text(
            "🛠 Recommended MVP Tech Stack:\n"
            "• Backend: FastAPI / Python\n"
            "• DB: Supabase (PostgreSQL)\n"
            "• Agent LLM Engine: Gemini 1.5 Flash\n"
            "• Distribution: Automated Cold Outreach"
        )
    elif query.data == "btn_new_idea":
        status_msg = await query.message.reply_text("🔄 Agent brainstorming fresh concept...")
        try:
            pitch_text = await asyncio.to_thread(
                agent_engine.generate,
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
                agent_engine.generate,
                prompt=prompt,
                system_instruction="You are a tough YC-style startup reviewer."
            )
            await status_msg.delete()
            await update.message.reply_text(f"📋 CRITIQUE:\n\n{critique}")
        except Exception as e:
            await status_msg.delete()
            await update.message.reply_text(f"❌ {str(e)}")

# -------------------------------------------------------------------
# 5. Main Execution Entry Point
# -------------------------------------------------------------------
def main():
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("pitch", pitch_command))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, reply_handler))

    print("🚀 Bot initialized, listening for updates...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
