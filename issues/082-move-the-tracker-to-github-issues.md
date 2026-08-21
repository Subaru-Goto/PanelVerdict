---
title: "Move the tracker to GitHub Issues, and clean house on the way"
labels: [wayfinder:task]
parent: 078-map-next-chapter
blocked_by: []
assignee: null
status: open
---

## Goal

The live backlog moves to GitHub Issues (author's direction, 2026-08-21) — native
open/closed state, `Closes #N` automation, sub-issues for map→ticket hierarchy,
`wayfinder:*` labels, assignee-as-claim — and the file tree is cleaned up in the same
arc.

## The fork that needs the author's sign-off before anything runs

- **Recommended: open tickets + the live map → GitHub; closed tickets stay in-repo**
  (moved to `docs/decisions/`), because the ~40 closed tickets are the project's ADR
  record — dense, cross-linked rationale that `docs/` links into — and burying them as
  pre-closed GitHub issues breaks every relative link for no workflow gain.
- Alternative: **everything** → GitHub. One home, at the cost of ~40 dead issues in the
  tracker and much heavier link surgery.

## What cannot survive the move, said now

GitHub issue numbers share a counter with PRs (already past #121), so ticket ids will
not match file numbers. Mitigation: old id kept in each issue title ("067 · …") plus a
committed mapping table, so every existing reference stays resolvable.

## Scope, in order

1. **After the pending replan PR merges** — migrating under it guarantees conflicts.
2. **Triage in file-land first** (cheaper than post-migration): every open ticket judged
   against [078](078-map-next-chapter.md)'s destination — still wanted, or closed with a
   one-line reason. Ambiguous calls listed for the author, not guessed.
3. **Docs audit:** sweep `docs/` for claims the last month falsified (model names,
   dropped fields, superseded defaults); fix or date-stamp. `docs/research/` stays
   untouched — it is already the sourced archive.
4. **Migration run** (`gh`): create labels, create issues oldest-first, rewrite
   cross-links from the mapping, wire sub-issues; native blocked-by if the repo has
   issue dependencies, body convention if not.
5. **Final PR:** archive per the fork's answer, delete migrated files, update the map
   and CLAUDE.md to name GitHub as the tracker.

## Done when

`gh issue list` is the frontier; every old `NNN` reference resolves via title or mapping;
the decision record is intact wherever the fork put it; and no ticket exists in two
places.
