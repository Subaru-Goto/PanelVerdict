---
title: "Is Clerk the right auth vendor, and what do we owe the user's data?"
labels: [wayfinder:research]
parent: 055-map-public-demo
blocked_by: []
assignee: null
status: open
---

## Question

Is Clerk the provider, and what obligations come with it?

Raised because the author's own read is that *"auth data or personal data is a serious
topic"* — which is correct, and settles the shape of the answer before the vendor: **the
dangerous option is rolling our own.** Auth.js or a direct Google OAuth integration means we
store the emails, secure the sessions and handle rotation, and a leak is ours. A managed
provider keeps the sensitive material and hands back an opaque subject id.

So this is not *"managed or not"* — it is *"which managed, and verified how."*

What to establish, from their own documents rather than from reputation:

- **SOC 2 Type II**, a **GDPR DPA**, the **subprocessor list**, and **data residency** (EU or
  US) — the four things that make a vendor defensible rather than merely popular
- **free-tier limits** in MAU, and what happens at the boundary, since the map makes hosted
  services conditional on being free
- **FastAPI-side verification**: Clerk issues JWTs with a JWKS endpoint, and the backend must
  verify against it. Establish the library and whether it adds a dependency.
- **Category honesty:** Clerk's centre of gravity is startups and the Next.js ecosystem;
  large enterprises more typically run Auth0/Okta or Entra ID. Worth writing down so nobody
  later claims enterprise pedigree the research did not find.
- **Lock-in:** subject ids are vendor-specific, so a later move re-identifies every user.
  Harmless at demo scale with per-day quotas, real if this gets traction. Name the cost.

Also compare **Supabase Auth**, which is free and would arrive with the database — and whose
trade is the one that matters here: users live in *our* Postgres, so **we would hold the
email** and inherit exactly the obligation a managed provider absorbs.

Output: a markdown summary under `docs/research/` with a recommendation, the tier numbers,
and the compliance findings dated. No figures from memory.
