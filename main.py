import os
import asyncio
import threading
import datetime
import pytz
from http.server import HTTPServer, BaseHTTPRequestHandler
from google import genai
from google.genai import types
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
# 2. Environment Setup & Prompts (V1 through V7)
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

OUTREACH_PROMPT = """
You are an evidence-first customer discovery outreach assistant.

Startup/problem we are validating:
{idea_context}

Candidate/post/profile:
{candidate}

Analyze ONLY what is actually present in the candidate text.
Do not invent facts.

Return:
🎯 RELEVANCE: HIGH / MEDIUM / LOW
🔎 EVIDENCE: 1-3 concrete reasons from the candidate text.
⚠️ UNKNOWN: What we still don't know.
💬 PUBLIC COMMENT: A short, natural research comment. Do not pitch a product.
📩 RESEARCH DM: A short message asking about their real experience. Do not claim we have a product.
❓ FOLLOW-UP: One non-leading question if they respond.
"""

HUNT_PROMPT = """
You are a web research agent helping a founder validate ONE startup problem.

Problem to validate:
{topic}

Use Google Search grounding to find REAL, public discussions from Reddit, X/Twitter, forums, blogs, GitHub issues, or public community pages where people appear to experience this problem.

For this validation round, prioritize people who:
- run AI/automation workflows for clients, or manage many production automations;
- mention n8n, Make, Zapier, webhooks, client automations, monitoring, silent failures, missed leads, broken workflows, or similar issues;
- describe an actual incident, workaround, frustration, or operational cost.

Do NOT return generic articles, vendor marketing pages, or invented people.
Do NOT recommend a solution.

Return up to 8 prospects. For each:
1. PERSON/USERNAME (if publicly shown)
2. PLATFORM
3. POST/TOPIC TITLE
4. WHY RELEVANT (one sentence)
5. EVIDENCE QUOTE (short, max 20 words)
6. PUBLIC URL
7. CONTACT METHOD: COMMENT / DM / UNKNOWN

Finish with:
🎯 NEXT ACTION: Which 3 prospects should be reviewed first, based only on relevance of their documented problem.
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

EXPERIMENT_PROMPT = """
You are a Lean Startup Experiment Designer.
Validated Opportunity:
{idea_context}

Discovery Evidence So Far:
{user_findings}

Design the absolute smallest concierge, manual, or zero-code experiment to test demand before building software:

🧪 LOW-FIDELITY DEMAND EXPERIMENT

1. The Concierge/Wizard-of-Oz Offer
How can the founder deliver this outcome manually (e.g., using spreadsheets, manual processing, or a Google Form) to test if the customer actually cares?

2. Success Metric
What exact commitment proves demand? (e.g., "3 out of 5 targets send us 20 real files to process", or "Target agrees to a 14-day paid pilot").

3. The 24-Hour Pitch / Landing Page Copy
A 3-sentence headline and value proposition to send directly to interviewees.
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

SALES_PROMPT = """
You are a B2B Sales & Customer Acquisition Strategist.
Opportunity Context:
{idea_context}

Validation & Experiment Results:
{user_findings}

Provide a closing strategy to secure your first paying customer:

💼 FIRST CUSTOMER ACQUISITION ROADMAP

1. Pre-Order / Paid Pilot Offer
How to structure a risk-free paid pilot (e.g., 50% discount for design partners, money-back guarantee).

2. Direct Outreach Email / Follow-up Script
A tailored follow-up template for the targets who confirmed pain during your discovery calls.

3. Handling Key Sales Objections
• "We don't have budget for this right now."
• "We need to check with IT / Security first."
• "Can we try it for free for 3 months?"
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
def generate_grounded_search(prompt: str) -> str:
    """Run the Hunt using one fixed, standard text model.

    Do not enumerate models here: the Gemini model list can contain Live
    models that are incompatible with generate_content(). If this fixed
    model cannot perform the requested grounded call, surface that error
    instead of silently falling through to a Live model.
    """
    model = "gemini-3.8-flash"
    try:
        response = ai_client.models.generate_content(
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.2,
                tools=[types.Tool(google_search=types.GoogleSearch())],
            ),
        )
        if response and response.text:
            return response.text
        raise Exception("Gemini returned an empty response.")
    except Exception as e:
        raise Exception(f"Grounded search error using {model}: {str(e)}")

def get_keyboard(status="🔴 UNVALIDATED"):
    if status in ["🔴 UNVALIDATED", "🟡 SIGNAL FOUND"]:
        return InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🎯 Validate Opportunity", callback_data="btn_validate"),
                InlineKeyboardButton("👥 Find Customers", callback_data="btn_find_customers"),
            ],
            [
                InlineKeyboardButton("🔎 Hunt Prospects", callback_data="btn_hunt"),
                InlineKeyboardButton("💬 Outreach Assistant", callback_data="btn_outreach"),
            ],
            [
                InlineKeyboardButton("📥 Enter Discovery Findings", callback_data="btn_enter_findings"),
                InlineKeyboardButton("🥊 Challenge Idea", callback_data="btn_challenge"),
            ],
            [
                InlineKeyboardButton("🧪 Design Experiment (V5)", callback_data="btn_experiment"),
                InlineKeyboardButton("🔄 Next Opportunity", callback_data="btn_next_opp"),
            ]
        ])
    else:  # 🟢 PROBLEM VALIDATED, 💰 PAYMENT SIGNAL, or 🛠️ BUILD MVP
        return InlineKeyboardMarkup([
            [
                InlineKeyboardButton("📥 Enter Discovery Findings", callback_data="btn_enter_findings"),
                InlineKeyboardButton("🧪 Design Experiment (V5)", callback_data="btn_experiment"),
            ],
            [
                InlineKeyboardButton("🛠️ Plan MVP Sprint (V6)", callback_data="btn_build_mvp"),
                InlineKeyboardButton("💼 Sales & Conversion (V7)", callback_data="btn_sales"),
            ],
            [
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

async def outreach_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    last_idea = context.user_data.get('last_idea')
    if not last_idea:
        await update.message.reply_text(
            "🛑 No active opportunity yet.\n\nUse /pitch first, then open 🎯 Outreach Assistant."
        )
        return

    context.user_data['awaiting_candidate'] = True
    await update.message.reply_text(
        "🎯 **OUTREACH ASSISTANT**\n\n"
        "Paste a Reddit/X post, comment, profile text, or candidate description here.\n\n"
        "I'll tell you:\n"
        "• whether they're relevant\n"
        "• what evidence they gave\n"
        "• what to comment\n"
        "• what DM to send\n"
        "• the best follow-up question\n\n"
        "⚠️ I won't automatically send messages."
    )

async def outreach_analysis(update: Update, context: ContextTypes.DEFAULT_TYPE):
    candidate = update.message.text
    last_idea = context.user_data.get('last_idea', 'Market Opportunity Hypothesis')

    status_msg = await update.message.reply_text("🔎 Evaluating prospect...")
    try:
        prompt = OUTREACH_PROMPT.format(
            idea_context=last_idea,
            candidate=candidate
        )
        res = await asyncio.to_thread(
            generate_gemini_content,
            prompt=prompt,
            system_instruction="You are an evidence-first customer discovery and outreach assistant."
        )

        # Keep a lightweight local outreach log in Telegram user state.
        prospects = context.user_data.setdefault('outreach_prospects', [])
        prospects.append({
            "candidate": candidate,
            "analysis": res,
            "status": "prepared"
        })
        context.user_data['last_candidate'] = candidate
        context.user_data['awaiting_candidate'] = False

        await status_msg.delete()
        await update.message.reply_text(
            f"🎯 **PROSPECT ANALYSIS**\n\n{res}\n\n"
            f"📌 Saved as prospect #{len(prospects)} in this Telegram session."
        )
    except Exception as e:
        context.user_data['awaiting_candidate'] = False
        await status_msg.delete()
        await update.message.reply_text(f"❌ Error: {str(e)}")


async def hunt_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Find public prospects relevant to the validation problem."""
    topic = " ".join(context.args).strip()
    if not topic:
        # Keep the command useful even when no topic is supplied.
        topic = (
            "SentinelFlow: AI automation agencies or operators managing client "
            "n8n, Make, Zapier, webhook, or production workflows that experience "
            "silent failures, missed leads, or workflows that appear successful "
            "but fail in reality"
        )

    status_msg = await update.message.reply_text(
        "🔎 Hunting for real public discussions and potential prospects...\n\n"
        "This can take a little while."
    )

    prompt = HUNT_PROMPT.format(topic=topic)

    try:
        result = await asyncio.to_thread(generate_grounded_search, prompt)

        await status_msg.delete()
        await update.message.reply_text(
            f"🔎 **HUNT RESULTS**\n\n{result}\n\n"
            "Next: use /outreach and paste any candidate post/profile you want me to qualify.",
            parse_mode="Markdown"
        )
    except Exception as e:
        await status_msg.delete()
        await update.message.reply_text(
            f"❌ Hunt failed:\n`{str(e)}`",
            parse_mode="Markdown"
        )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    
    try:
        await query.answer()
    except Exception:
        pass

    last_idea = context.user_data.get('last_idea', 'Market Opportunity Hypothesis')
    current_status = context.user_data.get('validation_status', '🔴 UNVALIDATED')

    if query.data == "btn_hunt":
        await query.message.reply_text(
            "🔎 **SENTINELFLOW PROSPECT HUNT**\n\n"
            "Use /hunt to search the public web for real automation operators discussing silent failures.\n\n"
            "Example:\n`/hunt n8n client workflow silent failure`"
        )

    elif query.data == "btn_outreach":
        if not last_idea:
            await query.message.reply_text("🛑 Generate an opportunity first with /pitch.")
            return
        context.user_data['awaiting_candidate'] = True
        await query.message.reply_text(
            "🎯 **OUTREACH ASSISTANT**\n\n"
            "Paste a Reddit/X post, comment, profile text, or candidate description.\n\n"
            "I'll qualify it and create:\n"
            "• a public comment\n"
            "• a private research DM\n"
            "• one follow-up question\n\n"
            "⚠️ You approve and send the message yourself."
        )

    elif query.data == "btn_validate":
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
            await update.message.reply_text(f"❌ Error: {str(e)}")

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
            await update.message.reply_text(f"❌ Error: {str(e)}")

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
            await update.message.reply_text(f"❌ Error: {str(e)}")

    elif query.data == "btn_experiment":
        status_msg = await query.message.reply_text("🧪 Designing zero-code demand experiment...")
        try:
            user_findings = context.user_data.get('last_findings', 'No interview findings recorded yet.')
            prompt = EXPERIMENT_PROMPT.format(idea_context=last_idea, user_findings=user_findings)
            res = await asyncio.to_thread(
                generate_gemini_content,
                prompt=prompt,
                system_instruction="You are a Lean Startup Experiment Designer."
            )
            await status_msg.delete()
            await query.message.reply_text(text=res)
        except Exception as e:
            await status_msg.delete()
            await update.message.reply_text(f"❌ Error: {str(e)}")

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
            await update.message.reply_text(f"❌ Error: {str(e)}")

    elif query.data == "btn_sales":
        if current_status in ["🔴 UNVALIDATED", "🟡 SIGNAL FOUND"]:
            await query.message.reply_text(
                f"🛑 **SALES STRATEGY LOCKED (Current Status: {current_status})**\n\n"
                "Validate the problem and conduct an experiment before crafting sales offers!"
            )
            return

        status_msg = await query.message.reply_text("💼 Compiling customer acquisition & closing blueprint...")
        try:
            user_findings = context.user_data.get('last_findings', 'Customer validated problem and workflow pain.')
            prompt = SALES_PROMPT.format(idea_context=last_idea, user_findings=user_findings)
            res = await asyncio.to_thread(
                generate_gemini_content,
                prompt=prompt,
                system_instruction="You are a B2B Sales Strategist."
            )
            await status_msg.delete()
            await query.message.reply_text(text=res)
        except Exception as e:
            await status_msg.delete()
            await update.message.reply_text(f"❌ Error: {str(e)}")

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
            await update.message.reply_text(f"❌ Error: {str(e)}")

async def reply_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get('awaiting_candidate'):
        await outreach_analysis(update, context)
        return

    if context.user_data.get('awaiting_findings'):
        context.user_data['awaiting_findings'] = False
        user_findings = update.message.text
        
        # Store user interview notes for V5 & V7 prompts
        context.user_data['last_findings'] = user_findings

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
            
            # Auto-promote or update status based on key phrase presence
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
    app.add_handler(CommandHandler("hunt", hunt_command))
    app.add_handler(CommandHandler("outreach", outreach_command))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, reply_handler))

    if MY_TELEGRAM_CHAT_ID:
        target_time = datetime.time(hour=8, minute=0, second=0, tzinfo=pytz.timezone("Asia/Kolkata"))
        app.job_queue.run_daily(scheduled_daily_pitch, time=target_time)

    print("🚀 Evidence-First Opportunity Scout running...")
    print("✅ Commands registered: /start /pitch /hunt /outreach")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
