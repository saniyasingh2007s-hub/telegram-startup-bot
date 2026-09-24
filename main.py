import os
import asyncio
import logging
import nest_asyncio
import requests
from typing import List
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

nest_asyncio.apply()

# Read credentials safely from Environment Variables
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

if not TELEGRAM_BOT_TOKEN or not GEMINI_API_KEY:
    raise ValueError("Missing environment variables: TELEGRAM_BOT_TOKEN or GEMINI_API_KEY")

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

class GeminiAgentEngine:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.available_models: List[str] = []
        self.active_model_index: int = 0
        self.discover_models()

    def discover_models(self) -> None:
        url = f"https://generativelanguage.googleapis.com/v1beta/models?key={self.api_key}"
        try:
            res = requests.get(url, timeout=15)
            if res.status_code == 200:
                raw_models = res.json().get("models", [])
                valid = []
                for m in raw_models:
                    name = m.get("name", "").replace("models/", "")
                    methods = m.get("supportedGenerationMethods", [])
                    if "generateContent" in methods and "tts" not in name and "image" not in name:
                        valid.append(name)
                
                priority_order = ["gemini-2.5-flash", "gemini-3.6-flash", "gemini-3.5-flash", "gemini-flash-latest"]
                sorted_models = [m for m in priority_order if m in valid]
                sorted_models.extend([m for m in valid if m not in sorted_models])
                
                self.available_models = sorted_models
            else:
                self.available_models = ["gemini-2.5-flash", "gemini-2.5-pro"]
        except Exception:
            self.available_models = ["gemini-2.5-flash", "gemini-2.5-pro"]

    def generate(self, prompt: str, system_instruction: str) -> str:
        if not self.available_models:
            self.discover_models()

        attempts = 0
        max_attempts = len(self.available_models)

        while attempts < max_attempts:
            current_model = self.available_models[self.active_model_index]
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{current_model}:generateContent?key={self.api_key}"
            headers = {"Content-Type": "application/json"}
            payload = {
                "contents": [{"parts": [{"text": prompt}]}],
                "systemInstruction": {"parts": [{"text": system_instruction}]},
                "generationConfig": {"temperature": 0.7}
            }

            try:
                response = requests.post(url, headers=headers, json=payload, timeout=30)
                res_data = response.json()

                if response.status_code == 200:
                    return res_data["candidates"][0]["content"]["parts"][0]["text"]
                elif response.status_code in (404, 429):
                    self.active_model_index = (self.active_model_index + 1) % len(self.available_models)
                    attempts += 1
                else:
                    err_msg = res_data.get("error", {}).get("message", f"HTTP {response.status_code}")
                    raise Exception(f"API Error ({response.status_code}): {err_msg}")
            except requests.RequestException:
                self.active_model_index = (self.active_model_index + 1) % len(self.available_models)
                attempts += 1

        raise Exception("All auto-discovered Gemini models failed or hit rate limits.")

    async def async_generate(self, prompt: str, system_instruction: str) -> str:
        return await asyncio.to_thread(self.generate, prompt, system_instruction)

agent_engine = GeminiAgentEngine(GEMINI_API_KEY)

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
        pitch_text = await agent_engine.async_generate(
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
        active_model = agent_engine.available_models[agent_engine.active_model_index]
        await query.message.reply_text(
            f"🛠 Recommended MVP Tech Stack:\n"
            f"• Backend: FastAPI / Python\n"
            f"• DB: Supabase (PostgreSQL)\n"
            f"• Agent LLM Engine: {active_model}\n"
            f"• Distribution: Automated Cold Outreach"
        )
    elif query.data == "btn_new_idea":
        status_msg = await query.message.reply_text("🔄 Agent brainstorming fresh concept...")
        try:
            pitch_text = await agent_engine.async_generate(
                prompt="Provide today's unique B2B micro-SaaS or AI Agent startup blueprint.",
                system_instruction=SYSTEM_PROMPT
            )
            context.user_data['last_idea'] = pitch_text
            await status_msg.delete()
            await update.message.reply_text(text=pitch_text, reply_markup=get_keyboard())
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
            critique = await agent_engine.async_generate(
                prompt=prompt,
                system_instruction="You are a tough YC-style startup reviewer."
            )
            await status_msg.delete()
            await update.message.reply_text(f"📋 CRITIQUE:\n\n{critique}")
        except Exception as e:
            await status_msg.delete()
            await update.message.reply_text(f"❌ {str(e)}")

async def main():
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("pitch", pitch_command))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, reply_handler))

    await app.initialize()
    await app.bot.delete_webhook(drop_pending_updates=True)
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)

if __name__ == "__main__":
    asyncio.run(main())