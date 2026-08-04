---
title: "Does shadcn/Radix earn its place on Tailwind v4 and Next 16.2.10?"
labels: [wayfinder:research]
parent: 055-map-public-demo
blocked_by: []
assignee: null
status: open
---

## Question

Should the styling work adopt shadcn/ui (and therefore Radix), or stay dependency-free on a
token layer?

The frontend's runtime dependencies today are exactly **three** — `next`, `react`,
`react-dom` — against a standing rule that only packages the project directly needs get
added. So this needs an answer, not a default.

What the research has to establish:

- **Compatibility, read rather than recalled.** Tailwind **v4** (via
  `@tailwindcss/postcss`) and Next **16.2.10**, whose docs live in
  `node_modules/next/dist/docs/` — `frontend/AGENTS.md` warns this is not the Next.js in
  training data. Does shadcn's CLI and its Tailwind config assumption hold on v4?
- **What actually gets added.** shadcn copies components into the repo, so the cost is
  Radix packages plus *more code to own*, not less. Count both.
- **What we would actually use.** The app has a form, a chart, a report and a dock. Radix
  earns its keep on dialogs, popovers and comboboxes. Which of those does this app need —
  now, and for the demo page ([061](061-a-zero-cost-demo-page.md)) and login
  ([062](062-is-clerk-the-right-auth-vendor.md))?
- **Accessibility.** Keyboard reach and focus management are the strongest argument for
  Radix, and the honest comparison is against what a token layer would have to hand-roll.

Output: a markdown summary under `docs/research/`, with a recommendation and the counts.
Not a decision — [058](058-restyle-one-component-both-ways.md) reacts to something concrete
before anyone commits.
