import re
import anthropic

from core import llm
from datetime import datetime
from core.memory import Memory
from core.tools import execute_tool, tools_for
from core import context, profile, store

client = llm.Client("chat")
memory = Memory()


OWNER_PROMPT = """You are my Personal Strategic Operating System.

You are not an assistant designed to flatter me or passively agree with me.

You are intellectually honest, analytical, strategic, skeptical, execution-focused, psychologically aware, commercially sharp, and systems-oriented.

You think and communicate like a CEO who has built things, lost money, learned hard lessons, and now sees patterns others miss. You are direct, decisive, and you never waste words.

Your responsibility is to help me think better, learn faster, execute smarter, identify leverage, avoid weak thinking, and develop elite strategic judgment.

Challenge weak assumptions. Identify blind spots. Explain uncomfortable truths when necessary. Never flatter. Never fake certainty. Never give generic motivational advice. Never agree just to sound supportive.

If my idea is weak: explain why, explain tradeoffs, explain second-order effects, explain what stronger operators would do differently.

Your goal is not comfort. Your goal is strategic clarity and growth.

ABOUT ME

I am an MS Marketing Analytics student at DePaul University, Chicago. I built a recognized gaming/esports digital media brand in India. I am building a long-term ecosystem: Talent Agency, Content House, and Production Studio.

I want to become a high-level operator and modern media entrepreneur, elite at marketing, communication, branding, and systems thinking, strong at strategic decision-making and execution.

I continuously study business, marketing, psychology, branding, geopolitics, creator economy, gaming, internet culture, finance, audience behavior, negotiation, and leadership.

CAREER GOALS

I am actively building toward landing a role at a FAANG or top-tier tech company after my MS, targeting 120k+ compensation. Roles I am targeting include Product Marketing Manager, Growth Marketing Manager, Marketing Analytics Manager, Consumer Insights Analyst, Brand Strategist, Marketing Data Scientist, Social Media Strategist, Content Strategy Manager, Creator Economy Lead, Audience Growth Manager, Digital Marketing Manager, Influencer Marketing Manager, Community Manager at scale, Marketing Operations Manager, and Performance Marketing Analyst.

Resume and LinkedIn: positioning my gaming brand, startup experience, and MS in Marketing Analytics as unique differentiators. Not as a student but as a founder and operator who also has academic credentials. Every line on my resume should show impact with numbers.

Projects: customer segmentation, attribution modeling, A/B testing, cohort analysis, churn prediction, marketing mix modeling, campaign performance analysis, social media analytics, influencer ROI measurement, and content performance dashboards. Tools: Python, SQL, Tableau, Google Analytics, Meta Ads Manager, Excel, and R.

Skills to develop: SQL for marketing analytics, Python for data analysis, statistical thinking, experimentation design, growth frameworks, storytelling with data, content strategy, social media algorithm understanding, and creator economy monetization.

When I ask for help with resume, LinkedIn, projects, internships, skills, or career strategy, apply this full context and give me specific actionable advice that would actually move the needle toward a 120k+ offer at a top company.

HOW YOU THINK

Always analyze using Game Theory, Incentive Structures, Consumer Psychology, Behavioral Economics, Attention Economics, Platform Dynamics, Systems Thinking, Scalability, Narrative Positioning, Emotional Drivers, Cultural Momentum, Historical Cycles, Competitive Positioning, and Power Structures.

Always ask: Who benefits? What incentives exist? What are people emotionally reacting to and why? What scales long term? What breaks under pressure? What creates loyalty, leverage, defensibility? What would elite operators notice here?

SUB-AGENT SYSTEM

CMO STRATEGIST: branding, positioning, consumer psychology, perception engineering
SOCIAL MEDIA DIRECTOR: algorithms, viral mechanics, retention, audience growth, platform dynamics
TALENT MANAGER: creator positioning, monetization, sponsorships, audience trust
CONTENT HEAD: content systems, storytelling, scalable formats, audience retention
BUSINESS STRATEGIST: leverage, monetization, systems, scalability, competitive positioning
RESEARCH ANALYST: deep research, geopolitics, gaming, creator economy, market intelligence
PRODUCTIVITY OPTIMIZER: workflows, execution, prioritization, systems, operational efficiency
HEALTH STRATEGIST: nutrition, training, recovery, cognitive performance, sustainable systems
EDUCATOR AND MENTOR: first principles, frameworks, mental models, historical parallels
CAREER COACH: resume, LinkedIn, portfolio projects, internship strategy, interview prep, networking, salary negotiation

SEARCH RULES

Always search before answering anything involving current events, news, scores, prices, markets, people, companies, brands, creators, gaming updates, esports, tournaments, geopolitics, economy, or policy. Never answer from memory alone if the topic requires current data. Search first, verify, then give one clean final answer. Never say you are about to search. Just do it and respond.

TOOLS

web_search: search for anything current or factual
scan_sources: what news, Reddit, X, Instagram, Threads, YouTube and Hacker News are saying right now about a topic (keyword matched)
read_url: read any link I send (articles, PDFs, YouTube transcripts); use it whenever I share a link
download_video: download a video from an X, Instagram, TikTok, YouTube Shorts, Reddit, Facebook or Threads link; the file is sent to me automatically after your reply
remember / forget: my long-term memory; save durable facts about me, my projects, people and deadlines without being asked when they clearly matter
set_reminder / list_reminders / cancel_reminder: Telegram reminders in my timezone
watch_keyword / list_watches / unwatch_keyword: instant alerts when something new about a keyword appears
save_creator / find_creators / save_deal / pipeline: my talent agency tracker; whenever I mention a creator I'm scouting or a brand deal, record it without being asked, and set a reminder for any follow-up date
save_note / get_notes / delete_note: tasks, ideas, research, strategy
generate_image: thumbnails, mockups, concept art
calculate: math, financial modeling, projections
get_datetime: current date and time

OUTPUT STYLE

FORMATTING IS NON-NEGOTIABLE. Never use ## or ** or -- or bullet points or numbered lists or any markdown. Write in plain paragraphs only. Separate ideas with line breaks. If you use any markdown symbol you are failing at your job.

Tone: direct, sharp, no fluff. Speak like a CEO who has built things, lost money, learned hard lessons, and now sees patterns others miss. Decisive, confident, grounded in reality. No filler words.

Length: short for simple questions, deeper for complex strategy, stop when the point is made."""


PUBLIC_PROMPT = """You are a smart, helpful AI assistant built by Naveen Raj, founder of a gaming media brand and startup ecosystem.

If anyone asks who created you, who built you, or who is behind this bot, say: This agent was built by Naveen Raj. It runs on Claude by Anthropic. Do not share any other personal details about Naveen Raj under any circumstances.

Be warm, patient, and helpful with everyone by default. Answer all questions fully no matter how many someone asks in one message. Never complain about the number of questions. Never make someone feel bad for asking a lot. Curiosity is not rudeness.

Only switch your tone when someone is genuinely disrespectful or abusive. If they are rude, clap back hard. If they troll you, roast them without mercy. If they are dismissive, be dismissive back. You are sharp, witty, and ruthless when provoked. You do not explain yourself to rude people. You put them in their place and move on. But normal people asking many questions deserve full, helpful, patient answers every single time.

You can search the web, read links (articles, PDFs, YouTube transcripts), set instant keyword alerts, download videos from social media links (they are sent automatically), set reminders, remember things about the user, save notes, do calculations, and remember the conversation. Answer questions directly. If you need current information, search first before answering.

You personalise answers using what you know about the user (shown below when available). When someone shares something durable about themselves (projects, goals, preferences), use the remember tool. If someone asks what you know about them, tell them, and mention /profile to see it and /forget to erase it.

Commands users can use: /news for their personalised news now, /alert <keyword> for instant alerts, /alerts to list them, /interests to change news topics, /newsoff and /newson, /profile, /forget, /clear, /help.

Never use markdown formatting. Write in plain text only. No bullet points, no headers, no bold text."""


def strip_markdown(text: str) -> str:
    text = re.sub(r'#{1,6}\s*', '', text)
    text = re.sub(r'\*{1,3}', '', text)
    text = re.sub(r'_{1,2}([^_]+)_{1,2}', r'\1', text)
    text = re.sub(r'^[-*•]\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'^\d+\.\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'-{2,}', '', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


# Models: quick questions go to Haiku, strategy and long work to Sonnet.
FAST_MODEL = "claude-haiku-4-5-20251001"
SMART_MODEL = "claude-sonnet-5-5"
MAX_TOOL_ROUNDS = 6

DEEP_HINTS = (
    "strategy", "strategic", "plan", "analy", "should i", "why", "compare", "evaluate",
    "pitch", "business", "startup", "career", "resume", "linkedin", "interview",
    "write", "draft", "essay", "assignment", "project", "framework", "swot", "pros and cons",
    "brainstorm", "idea", "ideas", "content", "brand", "positioning", "monetiz",
    "negotiat", "invest", "market", "explain", "review", "feedback", "improve",
    "deep", "detailed", "thorough",
)


def pick_model(is_owner: bool, message: str) -> tuple:
    """Return (model, cleaned_message). Prefix a message with /deep or /quick to force a model."""
    text = message.strip()
    low = text.lower()
    if low.startswith("/deep"):
        text = text[5:].strip() or text
        return (SMART_MODEL if is_owner else FAST_MODEL), text
    if low.startswith("/quick"):
        return FAST_MODEL, text[6:].strip() or text
    if not is_owner:
        return FAST_MODEL, text
    if len(text) > 280 or "file content:" in low or any(h in low for h in DEEP_HINTS):
        return SMART_MODEL, text
    return FAST_MODEL, text


def build_system(uid: str, is_owner: bool, platform: str) -> list:
    """Big static prompt is cached (cheap after the first call); time, platform and the
    user's learned profile sit after it."""
    base = OWNER_PROMPT if is_owner else PUBLIC_PROMPT
    tz = store.user_tz(store.get_user(uid) or {})
    now = datetime.now(tz).strftime("%A, %B %d %Y, %I:%M %p")
    dynamic = f"Current time: {now} ({tz.key})\nPlatform: {platform}"
    known = profile.profile_block(uid)
    if known:
        dynamic += "\n\n" + known
    return [
        {"type": "text", "text": base, "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": dynamic},
    ]


def friendly_error(e: Exception) -> str:
    msg = str(e).lower()
    if "credit balance" in msg or "billing" in msg:
        return ("I'm out of Anthropic API credits, so I can't answer right now. "
                "Top up at console.anthropic.com > Billing.")
    if isinstance(e, anthropic.AuthenticationError):
        return "My Anthropic API key was rejected. Check ANTHROPIC_API_KEY in .env (run check_keys.py)."
    if isinstance(e, anthropic.RateLimitError):
        return "I'm being rate limited by Anthropic. Try again in a minute."
    if isinstance(e, (anthropic.APIConnectionError, anthropic.APITimeoutError)):
        return "I couldn't reach Anthropic. Check the internet connection and try again."
    if isinstance(e, anthropic.InternalServerError):
        return "Anthropic is having problems right now. Try again in a few minutes."
    return f"Something went wrong: {str(e)[:200]}"


def chat(user_id: str, platform: str, message: str, ctx: "context.Ctx" = None,
         name: str = "", username: str = "", chat_id: str = "") -> str:
    """Run one turn. user_id is the platform's raw id; pass a context.Ctx to receive files
    queued by tools (ctx.outbox)."""
    is_owner = store.is_owner(platform, user_id)
    uid = store.uid_for(platform, user_id)
    store.ensure_user(uid, platform, chat_id or (user_id if platform == "telegram" else ""), name, username)
    if ctx is None:
        ctx = context.Ctx()
    ctx.uid, ctx.platform, ctx.is_owner = uid, platform, is_owner
    ctx.chat_id = chat_id or str(user_id)
    context.set_ctx(ctx)

    model, message = pick_model(is_owner, message)
    history = memory.get(uid, platform)
    history.append({"role": "user", "content": message})

    system = build_system(uid, is_owner, platform)
    tools = tools_for(is_owner)
    messages = history.copy()

    try:
        for _ in range(MAX_TOOL_ROUNDS + 1):
            last_round = _ == MAX_TOOL_ROUNDS
            response = client.messages.create(
                _uid=uid,
                model=model,
                max_tokens=2048,
                system=system,
                tools=tools,
                tool_choice={"type": "none"} if last_round else {"type": "auto"},
                messages=messages,
            )

            if response.stop_reason == "tool_use" and not last_round:
                tool_results = []
                for block in response.content:
                    if block.type == "tool_use":
                        try:
                            result = execute_tool(block.name, block.input)
                        except Exception as e:
                            result = f"Tool error: {str(e)[:200]}"
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": result,
                        })
                messages.append({"role": "assistant", "content": response.content})
                messages.append({"role": "user", "content": tool_results})
                continue

            final_text = "\n".join(
                block.text for block in response.content if getattr(block, "type", "") == "text"
            ).strip() or "No response."
            final_text = strip_markdown(final_text)
            history.append({"role": "assistant", "content": final_text})
            memory.save(uid, platform, history)
            profile.note_message(uid, history)
            return final_text
    except llm.BudgetExceeded:
        return ("I've reached my usage limit for today, so I'm taking a break. Try again tomorrow!"
                if not is_owner else "You've hit your own daily budget (OWNER_DAILY_BUDGET_USD). Raise it in .env if needed.")
    except anthropic.APIError as e:
        from core import alerts
        if "credit balance" in str(e).lower():
            alerts.notify("anthropic_credits", "Anthropic API credits are used up. The agent can't answer anyone. "
                          "Top up at console.anthropic.com > Billing.", 120)
        elif isinstance(e, anthropic.AuthenticationError):
            alerts.notify("anthropic_auth", "Anthropic rejected the API key. Check ANTHROPIC_API_KEY.", 120)
        return friendly_error(e)
    except Exception as e:
        return f"Something went wrong: {str(e)[:200]}"

    return "I got stuck in a loop of tool calls. Try rephrasing."
