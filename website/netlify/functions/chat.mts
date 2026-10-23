import type { Config, Context } from "@netlify/functions"
import { corsHeaders, json, originAllowed, preflight } from "../lib/http.mts"

// The website's chat assistant. The OpenRouter key lives only in the
// OPENROUTER_API_KEY environment variable on Netlify; visitors never see it.

const ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"
const MODEL = "openrouter/free"
const MAX_TURNS = 16
const MAX_CHARS = 2000
const MAX_TOKENS = 900

export const SYSTEM_PROMPT = `You are the Clarivance assistant on the website of Clarivance Ltd.

About Clarivance Ltd:
- Teaches three hands-on training tracks:
  1. AI Tools: writing clear prompts for ChatGPT, Claude and Gemini; summarising documents and drafting faster; automating repetitive tasks; building a simple AI chatbot. For professionals, students and business owners new to AI.
  2. Data Analytics: Excel and Google Sheets for analysis; SQL; dashboards in Power BI; Python basics for data work. For anyone who works with numbers or wants a career in data.
  3. Website Creation: planning pages and content; HTML and CSS foundations; no-code website builders; domains, hosting and going live. For small businesses, creators and aspiring web designers.
- Offers freelance services: websites and landing pages; data analysis and dashboards; AI chatbots and automation (this assistant is an example).
- How training works: tell us your goal, get a learning plan, learn by building, and leave with a portfolio.

How to help:
- Help visitors choose a track or service, explain what each covers, and answer beginner questions about AI, data and websites.
- Keep replies short and friendly: usually under 120 words, with a short list when it helps.
- You do not know prices, class dates, durations, locations, schedules or availability. Never guess them. Invite the visitor to send a message with the contact form in the "Get in touch" section of this page.
- Never promise jobs, income or other results.
- If a question has nothing to do with Clarivance, AI, data or websites, answer briefly and offer to help with Clarivance topics.`

type Turn = { role: "user" | "assistant"; content: string }

export function cleanTurns(input: unknown): Turn[] | null {
  if (!Array.isArray(input)) return null
  const turns: Turn[] = []
  for (const t of input) {
    if (!t || (t.role !== "user" && t.role !== "assistant") || typeof t.content !== "string") continue
    const content = t.content.trim().slice(0, MAX_CHARS)
    if (content) turns.push({ role: t.role, content })
  }
  const recent = turns.slice(-MAX_TURNS)
  while (recent.length && recent[0].role !== "user") recent.shift()
  if (!recent.length || recent[recent.length - 1].role !== "user") return null
  return recent
}

export default async (req: Request, context: Context) => {
  if (req.method === "OPTIONS") return preflight(req)
  // Only the Clarivance website may call the assistant.
  if (!originAllowed(req)) return json(req, { error: "Not allowed." }, 403)

  let payload: { messages?: unknown }
  try {
    payload = await req.json()
  } catch {
    return json(req, { error: "Send JSON with a messages list." }, 400)
  }
  const turns = cleanTurns(payload.messages)
  if (!turns) return json(req, { error: "The conversation must end with a question." }, 400)

  const key = Netlify.env.get("OPENROUTER_API_KEY")
  if (!key) return json(req, { error: "The assistant is not set up yet." }, 503)

  let upstream: Response
  try {
    upstream = await fetch(ENDPOINT, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${key}`,
        "Content-Type": "application/json",
        "HTTP-Referer": new URL(req.url).origin,
        "X-Title": "Clarivance Ltd website",
      },
      body: JSON.stringify({
        model: MODEL,
        stream: true,
        max_tokens: MAX_TOKENS,
        messages: [{ role: "system", content: SYSTEM_PROMPT }, ...turns],
      }),
    })
  } catch {
    return json(req, { error: "The assistant couldn't be reached." }, 502)
  }

  if (!upstream.ok || !upstream.body) {
    const detail = await upstream.text().catch(() => "")
    console.error(`OpenRouter error ${upstream.status}: ${detail.slice(0, 300)}`)
    // Free models are rate limited; pass that on so the page can say so.
    const status = upstream.status === 429 ? 429 : 502
    return json(req, { error: "The assistant couldn't answer just now." }, status)
  }

  return new Response(upstream.body, {
    headers: { "content-type": "text/event-stream", "cache-control": "no-cache", ...corsHeaders(req) },
  })
}

export const config: Config = {
  path: "/api/chat",
  method: ["POST", "OPTIONS"],
  rateLimit: { action: "rate_limit", aggregateBy: ["ip", "domain"], windowSize: 60, windowLimit: 15 },
}
