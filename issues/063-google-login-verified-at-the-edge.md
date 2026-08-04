---
title: "Google login, verified at the edge, storing no personal data"
labels: [wayfinder:task]
parent: 055-map-public-demo
blocked_by: [062-is-clerk-the-right-auth-vendor]
assignee: null
status: open
---

## Goal

A visitor signs in with Google to run a paid test. Reading the demo needs no account.

**Login gates spending, not the app.** An unauthenticated visitor reads a real report
([061](061-a-zero-cost-demo-page.md)) and only *"run your own test"* asks for Google. A login
wall in front of everything would hide the work from the people the deployment exists to
reach.

Two things this must get right, because they are where auth is usually decorative:

- **The backend verifies, it does not trust.** If `/evaluate` accepts a user id from the
  request body, anyone with `curl` bypasses every quota. FastAPI validates the JWT against
  the provider's JWKS, and the identity used for quota accounting comes **only** from the
  verified token.
- **Store the subject id. Never the email, never a token.** The app asks only *"same person?
  how many runs used?"*, and a subject id answers both — so the database holds no PII. OAuth
  tokens are the genuinely dangerous class and the provider keeps them. Note this
  *delegates* the obligation rather than removing it: the provider is processor, we remain
  controller.

Scope:

- provider integration in the frontend, per [062](062-is-clerk-the-right-auth-vendor.md)
- a FastAPI dependency that verifies the token and yields a subject id — **at the edge**, so
  it can return 401 before anything streams, which middleware structurally cannot do
- `/chat` gated the same way, since the analyst spends money too
- a deletion path: delete our rows, ask the provider to delete the user. Cheap because the
  subject-id rule means there is nowhere else to look.

Not in scope: accounts as a product — no owned history, no report library. See the map's
*Out of scope*.
