---
title: "Geist is loaded and Arial renders; there is no token layer"
labels: [wayfinder:task]
parent: 055-map-public-demo
blocked_by: []
assignee: null
status: open
---

## Goal

The app downloads two Google fonts and renders in Arial.

- `layout.tsx:5-13` loads `Geist` and `Geist_Mono` and puts them on `<html>` as CSS variables
- `globals.css:11-12` maps them to Tailwind's `--font-sans` / `--font-mono`
- `globals.css:25` then sets `body { font-family: Arial, Helvetica, sans-serif; }`
- **no component applies `font-sans` or `font-mono`** — zero occurrences across `app/`

So the body rule wins everywhere. This is `create-next-app` scaffolding nobody cleaned, and
`globals.css` is otherwise the untouched default: two colour variables, no type scale, no
spacing rhythm, no semantic colours, no focus styles.

Which reframes *"the design is horrible"* — it is **unstyled**, not badly designed. 1020
lines of components choosing ad-hoc utilities on an Arial baseline with no shared vocabulary.

Deliver: delete the override so Geist renders, then a real `@theme` layer — type scale,
spacing rhythm, semantic colours (`surface`, `border`, `muted`, `accent`), focus-visible
states — and sweep the five components in `frontend/app/components/` onto that vocabulary.

**Independent of the shadcn question** ([057](057-does-shadcn-earn-its-place.md)): a token
layer is wanted either way, and a library would sit on top of it rather than replace it. Do
this first so any comparison is against a fair baseline rather than against Arial.

Restyle only — no copy, no layout order, no chart geometry. See the map's *Restyle, do not
redesign*.
