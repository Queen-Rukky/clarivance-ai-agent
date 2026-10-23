import type { Config, Context } from "@netlify/functions"
import { json, originAllowed, preflight } from "../lib/http.mts"

// Receives the website's contact form and records it as a Netlify Forms
// submission ("contact" form), so messages show under Forms in Netlify and
// trigger any email notifications set up there.

const LIMITS = { name: 100, email: 200, interest: 100, message: 5000 }
const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/

export default async (req: Request, context: Context) => {
  if (req.method === "OPTIONS") return preflight(req)
  if (!originAllowed(req)) return json(req, { error: "Not allowed." }, 403)

  let data: Record<string, unknown>
  try {
    data = await req.json()
  } catch {
    return json(req, { error: "Send the form as JSON." }, 400)
  }
  // Honeypot: real visitors never fill this hidden field.
  if (typeof data["bot-field"] === "string" && data["bot-field"].trim()) return json(req, { ok: true }, 200)

  const field = (name: keyof typeof LIMITS) =>
    typeof data[name] === "string" ? (data[name] as string).trim().slice(0, LIMITS[name]) : ""
  const name = field("name")
  const email = field("email")
  const interest = field("interest")
  const message = field("message")
  if (!name || !message || !EMAIL.test(email)) {
    return json(req, { error: "Please fill in your name, a valid email and a message." }, 400)
  }

  const siteUrl = context.site?.url || new URL(req.url).origin
  const res = await fetch(new URL("/", siteUrl), {
    method: "POST",
    headers: { "content-type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({ "form-name": "contact", name, email, interest, message }).toString(),
  }).catch(() => null)
  if (!res || !res.ok) {
    console.error(`Form submission failed: ${res ? res.status : "network error"}`)
    return json(req, { error: "Your message couldn't be saved. Please try again." }, 502)
  }
  return json(req, { ok: true }, 200)
}

export const config: Config = {
  path: "/api/contact",
  method: ["POST", "OPTIONS"],
  rateLimit: { action: "rate_limit", aggregateBy: ["ip", "domain"], windowSize: 60, windowLimit: 5 },
}
