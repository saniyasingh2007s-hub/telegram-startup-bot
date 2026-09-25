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
        self.wfile.write(b"Evidence-First Opportunity Scout is active!")

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
You are an Evidence-First Startup Opportunity Scout & Founder Discovery Coach.
Your goal is to highlight unvalidated market problems, operational friction, and unaddressed customer pains without treating assumptions as facts.

Strictly categorize all statements into:
🟢 OBSERVED — Confirmed real-world behaviors or existing data.
🟡 HYPOTHESIS — Educated assumptions about pain, workflow loss, or willingness to pay that MIGHT be true.
🔴 UNKNOWN — Critical questions requiring customer discovery.

Return your response following this exact structured format:

🔎 OPPORTUNITY HYPOTHESIS

STATUS: 🔴 UNVALIDATED

### 1. Epistemic Breakdown
🟢 OBSERVED:
- State 1-2 factual, observable market dynamics or current tools in use.

🟡 HYPOTHESIS:
- State 2-3 key hypotheses about the specific friction, impact, or business cost.

🔴 UNKNOWN:
- State 3 critical unanswered questions that require customer discovery.

### 2. Target Profile & Workaround
• Target Persona: Specific role, job title, or business type.
• Current Workaround: How they attempt to cope today (or if they ignore it).

---

🎯 TODAY'S VALIDATION MISSION
Target: 5 specific individuals or businesses fitting the persona.
Objective: Do NOT pitch a solution. Ask non-leading questions to uncover truth.

Questions to Ask:
1. "How do you currently handle [specific workflow/task]?"
2. "What's the hardest part about that process?"
3. "When was the last time this caused a delay, financial loss, or major frustration?"
"""

VALIDATION_PROMPT = """
You are a Lean Customer Discovery Expert.
Opportunity Context:
{idea_context}

Current Status: {current_status}

Provide a concrete Discovery Plan:

🎯 CUSTOMER DISCOVERY ROADMAP

1. TARGET PROFILES & WHERE TO FIND THEM
Exact roles/titles and 3 specific platforms/directories/search queries to find 10 targets today.

2. NON-LEADING DISCOVERY QUESTIONS
3-4 neutral questions designed to extract raw truth without biasing the target toward a solution.

3. SIGNAL EVALUATION MATRIX
• Green Flag (Pain Exists): Specific quotes or behaviors proving real friction.
• Red Flag (Invalidation): Specific responses indicating this is a minor/non-issue.
"""

FIND_CUSTOMERS_PROMPT = """
You are a Lead Generation & Outreach Strategist.
Opportunity Context:
{idea_context}

Provide a customer search blueprint:

👥 FIND POTENTIAL CUSTOMERS

1. TARGET SEARCH QUERIES
Exact search strings to copy/paste into Google, LinkedIn, X, and Reddit.

2. COMMUNITIES & HANGOUTS
Specific subreddits, Slack/Discord groups, forums, or platforms where this target hangs out.

3. UNBIASED OUTREACH SCRIPT
A non-pitch, research-focused cold outreach message asking for 10 minutes of feedback on their workflow.
"""

CHALLENGE_PROMPT = """
You are a Devil's Advocate Startup Investor. Your goal is to ruthlessly attack the assumptions in this hypothesis so the founder doesn't waste time on a non-problem.

Opportunity Context:
{idea_context}

Attack this hypothesis across these 5 questions:

🥊 HYPOTHESIS CHALLENGE

❌ What if this problem is too rare or infrequent to matter?
❌ What if the current workaround is actually "good enough"?
❌ What if the target persona lacks spending authority or budget?
❌ Could this easily be rendered obsolete by a minor update to an existing platform?
❌ What is the simplest zero-code test to prove this hypothesis false in 24 hours?
"""

ANALYZE_FINDINGS_PROMPT = """
You are a Truth-Seeking Lean Startup Coach evaluating real customer discovery findings.

Original Opportunity Context:
{idea_context}

Current Validation Status: {current_status}

Founder's Discovery Findings / Interview Notes:
{user_findings}

Provide an Unbiased Analysis:

📊 DISCOVERY FINDINGS EVALUATION

1. EVIDENCE ANALYSIS
• Confirmed Hypotheses (What findings support real pain):
• Disproved Hypotheses (What assumptions were wrong):

2. TRUTH SIGNAL
Rate the signal: [NO SIGNAL / WEAK SIGNAL / STRONG SIGNAL / PAYMENT SIGNAL]
Explain why based strictly on the user's notes (no wishful thinking).

3. RECOMMENDED ACTION & STATUS UPDATE
• Recommended Status: [🔴 UNVALIDATED / 🟡 SIGNAL FOUND / 🟢 PROBLEM VALIDATED / 💰 PAYMENT SIGNAL / ❌ KILL]
• Next Steps: 2 concrete actions for the next discovery round or pivot.
"""

MVP_PROMPT = """
You are a Technical Product Architect.
Opportunity Context: {idea_context}
Validation Status: {current_status}

Provide a lean MVP build plan:

🛠️ LEAN MVP BUILD BLUEPRINT

1. Core Problem Being Solved (Validated Scope)
The single validated pain point to automate or solve.

2. Fastest Tech Stack
Simplest stack (FastAPI, Supabase, Flutter/Next.js, LLM) to deliver core value in 48 hours.

3. 3-Day Build Sprint
• Day 1: Data Models & Core Trigger
• Day 2: Primary Value Delivery Mechanics
• Day 3: Output Interface & Pilot Access Link
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
                config={"system_instruction": system_instruction, "temperature": 0.75}
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
def get_keyboard(status="🔴 UNVALIDATED"):
    build_button_text = f"🛠️ Build MVP ({'LOCKED' if status in ['🔴 UNVALIDATED', '🟡 SIGNAL FOUND'] else 'UNLOCKED'})"
    
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🎯 Validate Opportunity", callback_data="btn_validate"),
            InlineKeyboardButton("👥 Find Customers", callback_data="btn_find_customers"),
        ],
        [
            InlineKeyboardButton("📥 Enter Discovery Findings", callback_data="btn_enter_findings"),
            InlineKeyboardButton("🥊 Challenge Idea", callback_data="btn_challenge"),
        ],
        [
            InlineKeyboardButton(build_button_text, callback_data="btn_build_mvp"),
            InlineKeyboardButton("🔄 Next Opportunity", callback_data="btn_next_opp"),
        ]
    ])

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    await update.message.reply_text(
        f"👋 Evidence-First Opportunity Scout Active!\n\n"
        f"• Type /pitch to receive today's unvalidated hypothesis.\n"
        f"• Chat ID: `{chat_id}`",
        parse_mode="Markdown"
    )

async def pitch_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    status_msg = await update.message.reply_text("🔎 Scouting market friction & building hypothesis...")
    try:
        pitch_text = await asyncio.to_thread(
            generate_gemini_content,
            prompt="Scout a fresh, unvalidated market opportunity, workflow friction, or customer problem.",
            system_instruction=SYSTEM_PROMPT
        )
        context.user_data['last_idea'] = pitch_text
        context.user_data['validation_status'] = "🔴 UNVALIDATED"
        await status_msg.delete()
        await update.message.reply_text(text=pitch_text, reply_markup=get_keyboard("🔴 UNVALIDATED"))
    except Exception as e:
        await status_msg.delete()
        await update.message.reply_text(f"❌ Error: {str(e)}")

async def scheduled_daily_pitch(context: ContextTypes.DEFAULT_TYPE):
    if not MY_TELEGRAM_CHAT_ID:
        return
    try:
        pitch_text = await asyncio.to_thread(
            generate_gemini_content,
            prompt="Scout a fresh, unvalidated market opportunity, workflow friction, or customer problem.",
            system_instruction=SYSTEM_PROMPT
        )
        await context.bot.send_message(
            chat_id=MY_TELEGRAM_CHAT_ID,
            text=f"☀️ **TODAY'S MARKET OPPORTUNITY HYPOTHESIS**\n\n{pitch_text}",
            reply_markup=get_keyboard("🔴 UNVALIDATED")
        )
    except Exception as e:
        print(f"Daily Scout Push Error: {e}")

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    
    try:
        await query.answer()
    except Exception:
        pass

    last_idea = context.user_data.get('last_idea', 'Market Opportunity Hypothesis')
    current_status = context.user_data.get('validation_status', '🔴 UNVALIDATED')

    if query.data == "btn_validate":
        status_msg = await query.message.reply_text("🎯 Architecting Unbiased Customer Discovery Plan...")
        try:
            prompt = VALIDATION_PROMPT.format(idea_context=last_idea, current_status=current_status)
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
        status_msg = await query.message.reply_text("👥 Generating customer search strategy...")
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

    elif query.data == "btn_enter_findings":
        context.user_data['awaiting_findings'] = True
        await query.message.reply_text(
            "📥 **DISCOVERY FINDINGS INPUT**\n\n"
            "Reply directly to this message with your notes or quotes from talking to target customers.\n\n"
            "Include:\n"
            "1. How many people you talked to\n"
            "2. What they said about their current workflow\n"
            "3. Any pricing or willingness-to-pay quotes"
        )

    elif query.data == "btn_challenge":
        status_msg = await query.message.reply_text("🥊 Attacking hypothesis assumptions...")
        try:
            prompt = CHALLENGE_PROMPT.format(idea_context=last_idea)
            res = await asyncio.to_thread(
                generate_gemini_content,
                prompt=prompt,
                system_instruction="You are a Devil's Advocate Investor."
            )
            await status_msg.delete()
            await query.message.reply_text(text=res)
        except Exception as e:
            await status_msg.delete()
            await query.message.reply_text(f"❌ Error: {str(e)}")

    elif query.data == "btn_build_mvp":
        if current_status in ["🔴 UNVALIDATED", "🟡 SIGNAL FOUND"]:
            await query.message.reply_text(
                f"🛑 **BUILD LOCKED (Current Status: {current_status})**\n\n"
                "You have not collected enough evidence yet!\n"
                "Talk to at least 5 target customers and enter your findings to promote the status to **🟢 PROBLEM VALIDATED** or **💰 PAYMENT SIGNAL** before building."
            )
            return

        status_msg = await query.message.reply_text("⚙️ Compiling Lean MVP Blueprint for Validated Problem...")
        try:
            prompt = MVP_PROMPT.format(idea_context=last_idea, current_status=current_status)
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
        status_msg = await query.message.reply_text("🔄 Scouting next unvalidated opportunity hypothesis...")
        try:
            pitch_text = await asyncio.to_thread(
                generate_gemini_content,
                prompt="Scout a fresh, unvalidated market opportunity, workflow friction, or customer problem.",
                system_instruction=SYSTEM_PROMPT
            )
            context.user_data['last_idea'] = pitch_text
            context.user_data['validation_status'] = "🔴 UNVALIDATED"
            await status_msg.delete()
            await query.message.reply_text(text=pitch_text, reply_markup=get_keyboard("🔴 UNVALIDATED"))
        except Exception as e:
            await status_msg.delete()
            await query.message.reply_text(f"❌ Error: {str(e)}")

async def reply_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get('awaiting_findings'):
        context.user_data['awaiting_findings'] = False
        user_findings = update.message.text
        last_idea = context.user_data.get('last_idea', 'Market Opportunity Hypothesis')
        current_status = context.user_data.get('validation_status', '🔴 UNVALIDATED')

        status_msg = await update.message.reply_text("🧐 Analyzing discovery notes for objective truth signals...")
        try:
            prompt = ANALYZE_FINDINGS_PROMPT.format(
                idea_context=last_idea,
                current_status=current_status,
                user_findings=user_findings
            )
            evaluation = await asyncio.to_thread(
                generate_gemini_content,
                prompt=prompt,
                system_instruction="You are a Truth-Seeking Startup Evaluator."
            )
            
            # Auto-promote or update status based on key phrase presence in evaluation
            new_status = current_status
            if "🟢 PROBLEM VALIDATED" in evaluation:
                new_status = "🟢 PROBLEM VALIDATED"
            elif "💰 PAYMENT SIGNAL" in evaluation:
                new_status = "💰 PAYMENT SIGNAL"
            elif "🟡 SIGNAL FOUND" in evaluation:
                new_status = "🟡 SIGNAL FOUND"
            elif "❌ KILL" in evaluation:
                new_status = "❌ KILLED"

            context.user_data['validation_status'] = new_status

            await status_msg.delete()
            await update.message.reply_text(
                f"📋 **EVALUATION & STATUS UPDATE**\n"
                f"**Updated Status:** {new_status}\n\n"
                f"{evaluation}",
                reply_markup=get_keyboard(new_status)
            )
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

    print("🚀 Evidence-First Opportunity Scout running...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
