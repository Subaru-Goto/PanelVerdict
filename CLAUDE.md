# PanelVerdict — agent notes

## Issue tracker

**Live work is tracked on GitHub Issues** (migrated 2026-08-21, ticket 082):

- The map — the effort's destination and index — is the issue labelled `wayfinder:map`
  ("078 · Map: PanelVerdict next chapter"). Tickets are its sub-issues, labelled
  `wayfinder:task` / `wayfinder:grilling` / `wayfinder:research` / `wayfinder:prototype`.
- **The frontier** = open, unblocked, unassigned issues. Claim by assigning yourself
  before any work. "Blocked by #N" lines in the body are the dependency convention.
- Resolve a ticket by posting the answer as a comment, closing the issue (PRs use
  `Closes #N`), and appending a one-line gist to the map's *Decisions so far*.
- Issue titles carry the pre-migration id ("067 · …"); the id↔issue mapping is in
  `docs/decisions/README.md`.

**Closed tickets from the file-tracker era live in `docs/decisions/`** — they are the
project's decision record (ADRs in ticket form). Read them before re-arguing anything;
a decision lives in exactly one place, its ticket.

## Standing conventions

- Work flows through PRs off `main`; branch names like `feat/NNN-slug`, `docs/NNN-slug`.
- No unsourced constants: numbers come from a measurement or a quoted, dated source
  (see `docs/research/`).
- Cumulative findings: `docs/lessons-so-far.md`. Product vision (living draft):
  `docs/project-idea.md`. Security stance: `docs/least-privilege.md`.
- Requirement set (author, 2026-08-21): agent, LangGraph, RAG, human-in-the-loop,
  deployed, production-ready — judge ticket priority against these; don't gold-plate a
  requirement already met.
