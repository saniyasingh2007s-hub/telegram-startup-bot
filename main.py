```python
import os
import asyncio
import threading
import time
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
        self.wfile.write(b"11Hunt Startup Bot is running!")

    def do_HEAD(self):
        self.send_response(200)
        self.end_headers()


def run_health_server():
    port = int(os.getenv("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    server.serve_forever()


threading.Thread(target=run_health_server, daemon=True).start()


# ============================================================
# 2. ENVIRONMENT
# ============================================================

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

if not TELEGRAM_BOT_TOKEN:
    raise ValueError("Missing TELEGRAM_BOT_TOKEN")

if not GEMINI_API_KEY:
    raise ValueError("Missing GEMINI_API_KEY")

ai_client = genai.Client(api_key=GEMINI_API_KEY)

# Your Render variable can override this.
PRIMARY_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.7-flash")

# Automatic fallbacks.
FALLBACK_MODELS = [
    PRIMARY_MODEL,
    "gemini-3.8-flash",
    "gemini-3.6-flash",
    "gemini-3.5-flash",
]

# Remove duplicates while keeping order.
MODEL_LIST = list(dict.fromkeys(FALLBACK_MODELS))


# ============================================================
# 3. STARTUP IDEA PROMPT
# ============================================================

SYSTEM_PROMPT = """
You are an elite Startup Analyst & Co-Pilot for a CS student/founder.

Your job is NOT to generate random startup ideas.

Generate practical startup opportunities that a student or solo founder
could realistically validate and begin building.

IMPORTANT:

- Include both AI-agent ideas AND normal app/SaaS ideas.
- Do not force every idea to be an AI agent.
- Prefer ideas that can realistically be built as an MVP.
- Focus on a clear customer, painful problem and realistic distribution.
- Avoid generic "AI wrapper" ideas.
- Explain why someone would actually pay.
- Give concrete implementation direction.

Return exactly this structure:

🚀 DAILY STARTUP BLUEPRINT

💡 IDEA
Name + one-line description.

1. STORY & PROBLEM
A realistic situation showing the problem.

2. PROPOSED SOLUTION
Explain what the product/app/agent actually does.

3. WHO PAYS?
Target customer and why they would pay.

4. SCORECARD
• Pain Intensity: X/10
• Willingness to Pay: X/10
• Distribution Ease: X/10
• Technical Feasibility: X/10

5. COMPETITORS
Existing alternatives and what they don't solve well.

6. MVP
List the smallest version that can be built first.

7. HOW TO BUILD
Give a simple practical implementation path for a beginner.

8. FIRST 10 USERS
Give a realistic way to find the first users without paid ads.

9. STRESS TEST
Give two difficult questions the founder must answer.

10. BUILD THIS?
End with:
"Recommended next action: Validate / Build / Reject"
and explain why in one sentence.
"""


STRESS_TEST_EVAL_PROMPT = """
You are reviewing a founder's answer to a startup stress-test.

Original startup:
{idea_context}

Founder answer:
{user_answer}

Give a concise review:

1. What is strong?
2. What is weak or risky?
3. What assumption needs validation?
4. One specific improvement.
"""


# ============================================================
# 4. GEMINI ENGINE WITH RETRIES + FALLBACKS
# ============================================================

def generate_gemini_content(prompt: str, system_instruction: str) -> str:

    last_error = None

    for model in MODEL_LIST:

        # Try each model up to 2 times.
        for attempt in range(2):

            try:
                print(
                    f"🤖 Trying Gemini model: {model} "
                    f"(attempt {attempt + 1}/2)"
                )

                response = ai_client.models.generate_content(
                    model=model,
                    contents=prompt,
                    config={
                        "system_instruction": system_instruction,
                        "temperature": 0.7,
                    },
                )

                if response and response.text:
                    print(f"✅ Gemini response received from {model}")
                    return response.text

                last_error = Exception(
                    f"{model} returned an empty response"
                )

            except Exception as e:

                last_error = e
                error_text = str(e)

                print(f"⚠️ {model} failed: {error_text}")

                # Temporary errors:
                # 503 = overloaded/unavailable
                # 429 = quota/rate limit
                if "503" in error_text or "UNAVAILABLE" in error_text:
                    if attempt == 0:
                        print("⏳ Temporary Gemini overload. Retrying...")
                        time.sleep(3)
                        continue

                    print(f"➡️ Falling back from {model}")
                    break

                if "429" in error_text or "RESOURCE_EXHAUSTED" in error_text:
                    print(f"➡️ Quota/rate issue on {model}. Trying fallback.")
                    break

                if "404" in error_text or "NOT_FOUND" in error_text:
                    print(f"➡️ Model unavailable: {model}")
                    break

                # Other errors: move to next model.
                break

    raise Exception(
        "Gemini temporarily unavailable. "
        "All configured models failed. "
        f"Last error: {str(last_error)}"
    )


# ============================================================
# 5. TELEGRAM KEYBOARD
# ============================================================

def get_keyboard():

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🎯 Answer Stress-Test",
                callback_data="btn_stress_test"
            ),
            InlineKeyboardButton(
                "🛠 Build Plan",
                callback_data="btn_build_plan"
            ),
        ],
        [
            InlineKeyboardButton(
                "🚀 Implement Idea",
                callback_data="btn_implement"
            )
        ],
        [
            InlineKeyboardButton(
                "🔄 Generate Another",
                callback_data="btn_new_idea"
            )
        ]
    ])


# ============================================================
# 6. /START
# ============================================================

async def start_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    await update.message.reply_text(
        "👋 Welcome to your Startup Co-Pilot.\n\n"
        "I can help you discover, stress-test and build startup ideas.\n\n"
        "Use /pitch to generate today's startup opportunity."
    )


# ============================================================
# 7. /PITCH
# ============================================================

async def pitch_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    status_msg = await update.message.reply_text(
        "🤖 Hunting for a practical startup opportunity..."
    )

    try:

        pitch_text = await asyncio.to_thread(
            generate_gemini_content,
            prompt=(
                "Generate one strong startup idea for a CS student/founder. "
                "It can be an AI agent, AI application, SaaS, mobile/web app "
                "or other software product. Prefer something realistically "
                "buildable and sellable."
            ),
            system_instruction=SYSTEM_PROMPT
        )

        context.user_data["last_idea"] = pitch_text
        context.user_data["awaiting_stress_reply"] = False

        await status_msg.delete()

        await update.message.reply_text(
            text=pitch_text,
            reply_markup=get_keyboard()
        )

    except Exception as e:

        await status_msg.delete()

        await update.message.reply_text(
            f"⚠️ AI temporarily unavailable.\n\n"
            f"{str(e)}\n\n"
            "Please try /pitch again in a moment."
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

    # ----------------------------
    # Stress Test
    # ----------------------------

    if query.data == "btn_stress_test":

        context.user_data["awaiting_stress_reply"] = True

        await query.message.reply_text(
            "🥊 Send your answer to one of the stress-test questions.\n\n"
            "I'll challenge the reasoning and point out the biggest risk."
        )

    # ----------------------------
    # Build Plan
    # ----------------------------

    elif query.data == "btn_build_plan":

        idea = context.user_data.get(
            "last_idea",
            "No startup idea selected."
        )

        status_msg = await query.message.reply_text(
            "🛠 Creating a beginner-friendly MVP build plan..."
        )

        try:

            build_prompt = f"""
Based on this startup idea:

{idea}

Create a practical MVP build plan.

Include:

1. What to build first
2. Main screens/features
3. Backend requirements
4. AI requirements if needed
5. Database requirements
6. No-code/low-code alternatives
7. 48-hour MVP scope
8. What NOT to build yet
"""

            plan = await asyncio.to_thread(
                generate_gemini_content,
                build_prompt,
                "You are a practical startup MVP architect."
            )

            await status_msg.delete()

            await query.message.reply_text(
                f"🛠 BUILD PLAN\n\n{plan}"
            )

        except Exception as e:

            await status_msg.delete()

            await query.message.reply_text(
                f"⚠️ Build planner temporarily unavailable.\n\n{e}"
            )

    # ----------------------------
    # Implement
    # ----------------------------

    elif query.data == "btn_implement":

        idea = context.user_data.get(
            "last_idea",
            "No startup idea selected."
        )

        status_msg = await query.message.reply_text(
            "🚀 Preparing implementation blueprint..."
        )

        try:

            implementation_prompt = f"""
Startup idea:

{idea}

Create a practical implementation blueprint for a beginner founder.

Return:

1. Product name
2. Core user flow
3. MVP features
4. Recommended stack
5. Database structure
6. AI/API components
7. Step-by-step build order
8. First version that can be shipped in 48 hours
9. What can be done using no-code/AI coding tools
10. First validation test before building too much
"""

            implementation = await asyncio.to_thread(
                generate_gemini_content,
                implementation_prompt,
                "You are an expert startup product and implementation architect."
            )

            await status_msg.delete()

            await query.message.reply_text(
                f"🚀 IMPLEMENTATION BLUEPRINT\n\n{implementation}"
            )

        except Exception as e:

            await status_msg.delete()

            await query.message.reply_text(
                f"⚠️ Implementation planner temporarily unavailable.\n\n{e}"
            )

    # ----------------------------
    # New Idea
    # ----------------------------

    elif query.data == "btn_new_idea":

        status_msg = await query.message.reply_text(
            "🔄 Finding another opportunity..."
        )

        try:

            pitch_text = await asyncio.to_thread(
                generate_gemini_content,
                prompt=(
                    "Generate a DIFFERENT startup idea from previous ideas. "
                    "It may be an AI agent, AI app, SaaS, web app or software "
                    "product. Make it realistic for a student founder."
                ),
                system_instruction=SYSTEM_PROMPT
            )

            context.user_data["last_idea"] = pitch_text

            await status_msg.delete()

            await query.message.reply_text(
                text=pitch_text,
                reply_markup=get_keyboard()
            )

        except Exception as e:

            await status_msg.delete()

            await query.message.reply_text(
                f"⚠️ AI temporarily unavailable.\n\n{e}"
            )


# ============================================================
# 9. STRESS TEST ANSWER
# ============================================================

async def reply_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not context.user_data.get("awaiting_stress_reply"):
        return

    context.user_data["awaiting_stress_reply"] = False

    user_answer = update.message.text

    last_idea = context.user_data.get(
        "last_idea",
        "Startup Pitch"
    )

    status_msg = await update.message.reply_text(
        "🧐 Stress-testing your answer..."
    )

    try:

        prompt = STRESS_TEST_EVAL_PROMPT.format(
            idea_context=last_idea,
            user_answer=user_answer
        )

        critique = await asyncio.to_thread(
            generate_gemini_content,
            prompt,
            "You are a tough but constructive startup reviewer."
        )

        await status_msg.delete()

        await update.message.reply_text(
            f"📋 STRESS TEST REVIEW\n\n{critique}"
        )

    except Exception as e:

        await status_msg.delete()

        await update.message.reply_text(
            f"⚠️ Reviewer temporarily unavailable.\n\n{e}"
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

    print("🚀 11Hunt Startup Co-Pilot running...")
    print(f"🤖 Primary Gemini model: {PRIMARY_MODEL}")
    print(f"🔄 Fallback models: {MODEL_LIST}")

    app.run_polling(
        drop_pending_updates=True
    )


if __name__ == "__main__":
    main()
```
