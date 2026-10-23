// Shared helpers for the website's functions. The site itself is served by
// GitHub Pages (on the custom domain), so the functions answer cross-origin
// requests from the origins listed here.

export const ALLOWED_ORIGINS = [
  "https://queen-rukky.github.io",
  "https://clarivance.netlify.app",
  // Add the custom domain here once it is connected, e.g.
  // "https://clarivance.com", "https://www.clarivance.com",
]

export function originAllowed(req: Request): boolean {
  const origin = req.headers.get("origin")
  if (!origin) return true // not a browser request; rate limits still apply
  try {
    if (new URL(origin).host === new URL(req.url).host) return true
  } catch {
    return false
  }
  return ALLOWED_ORIGINS.includes(origin)
}

export function corsHeaders(req: Request): Record<string, string> {
  const origin = req.headers.get("origin")
  if (!origin || !originAllowed(req)) return {}
  return { "access-control-allow-origin": origin, vary: "Origin" }
}

export function preflight(req: Request): Response {
  return new Response(null, {
    status: originAllowed(req) ? 204 : 403,
    headers: {
      ...corsHeaders(req),
      "access-control-allow-methods": "POST, OPTIONS",
      "access-control-allow-headers": "content-type",
      "access-control-max-age": "86400",
    },
  })
}

export const json = (req: Request, body: unknown, status: number) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json", ...corsHeaders(req) },
  })
