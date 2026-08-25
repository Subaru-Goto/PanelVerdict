# Does shadcn/Radix earn its place? — the 057 result

**Researched 2026-08-24.** Ticket:
[057 · #152](https://github.com/Subaru-Goto/PanelVerdict/issues/152). Every Next.js fact
below is read from the **on-disk docs shipped with the installed compiler**
(`frontend/node_modules/next/dist/docs/`, `next@16.2.10`) — not from memory, not from
nextjs.org, because `frontend/AGENTS.md` warns that Next 16 broke things a model's
training data still remembers as working. Every shadcn/Radix fact is from their own docs
sites, read 2026-08-24, with the URL and the retrieval date in **Sources**. Every count
and byte figure is **measured** in three throwaway Next 16.2.10 projects built outside
this repo; where something is quoted from docs rather than measured, it says so.

## Verdict: take **Radix**, decline **shadcn** — and the token layer (056) goes first either way

shadcn/ui works on this stack. That is not the question; the question is whether it earns
its place, and on the measurements below it does not, because **the thing this app
actually needs from it is the accessibility behaviour of four or five primitives, and
that can be bought for 1 dependency and 13 KB instead of 7 dependencies, 379 packages,
1,130 lines of code to own, and a rewrite of `app/globals.css` that silently kills all 54
`dark:` utilities already in the app.**

The recommendation, in one line: **`npm i @radix-ui/react-dialog` when the analyst dock
is rebuilt; hand-author the token layer per [056 · #151](https://github.com/Subaru-Goto/PanelVerdict/issues/151);
do not run `shadcn init`.**

This is a recommendation, not the decision — [058 · #153](https://github.com/Subaru-Goto/PanelVerdict/issues/153)
reacts to something concrete. What #153 should build is named at the bottom.

---

## 1. Compatibility — read, not recalled

### The stack, as pinned

`frontend/package.json` pins `next` at **16.2.10** (exact, not a range), `react` and
`react-dom` at **19.2.4**. Tailwind is `tailwindcss ^4` + `@tailwindcss/postcss ^4`, both
dev dependencies. **There is no `tailwind.config.js`, `.ts`, or `.mjs` in `frontend/`** —
configuration is CSS-first, in `app/globals.css`, which is 26 lines and declares two
colour variables plus a four-line `@theme inline` block.

That layout is exactly what the installed Next docs prescribe for Tailwind v4:
`npm install -D tailwindcss @tailwindcss/postcss`, add `'@tailwindcss/postcss': {}` to
`postcss.config.mjs`, `@import 'tailwindcss';` in the global CSS
(`01-app/01-getting-started/11-css.md`, lines 22–60). Tailwind v3 is demoted to a
separate legacy guide whose own preamble points back: *"For the latest Tailwind 4 setup,
see the Tailwind CSS setup instructions"* (`01-app/02-guides/tailwind-v3-css.md`, line 12).
So the repo is on the version the compiler documents as current, and a library that still
needs a JS config file would be the odd one out.

### Does shadcn's CLI work here? Measured: yes

| probe | what was run | result |
|---|---|---|
| `probe` | Next 16.2.10 + React 19.2.4 + Tailwind v4, no UI library | `next build` **passes** — the baseline |
| `probe-radix` | `npx shadcn@latest init --yes --no-monorepo --no-rtl --base radix --preset nova`, then `add` for 11 components | `next build` **passes**, Turbopack, static pages emitted |
| `probe-dialog` | `npm i @radix-ui/react-dialog`, one modal hand-composed | `next build` **passes** |

shadcn CLI version measured: **4.19.0**. It wrote `components.json` with
`"tailwind": { "config": "" }` — the empty `config` is what its own docs prescribe:
*"Path to where your `tailwind.config.js` file is located. **For Tailwind CSS v4, leave
this blank.**"* (components.json docs, line 53). No `tailwind.config.js` was created. The
generated components import from `radix-ui@1.6.7`, whose `peerDependencies` are
`"react": "^16.8 || ^17.0 || ^18.0 || ^19.0 || ^19.0.0-rc"` — 19.2.4 is inside that range,
so npm resolved without `--force` or `--legacy-peer-deps`.

One CLI wrinkle worth recording: **`shadcn init --yes` alone did not produce a
`components.json`.** v4.19.0 prompts for a component library base (`base` | `radix` |
`aria`) and the non-interactive run exited 0 having written nothing. `--base radix` (or a
`--preset`) is required for an unattended init. That is a change in shape from the
shadcn-is-Radix assumption: **shadcn 4.x is a generator with a swappable base, and Radix
is now one of three.**

### What shadcn's docs claim, and where they are silent

- **Tailwind v4:** claimed outright — *"Full support for the new `@theme` directive and
  `@theme inline` option"*, *"The CLI can now initialize projects with Tailwind v4"*,
  *"All components are updated for Tailwind v4 and React 19"* (tailwind-v4 docs, lines
  10–12).
- **React 19:** claimed outright — *"We have added full support for React 19 and Tailwind
  v4 in the `latest` release"* (react-19 docs, lines 7–8).
- **Next.js 16: silent.** There is no stated minimum, maximum, or tested Next.js version
  anywhere in the installation, CLI, or theming docs. The one page that names a Next
  version is titled **"Next.js 15 + React 19"** and carries a callout on its own content:
  *"This guide might be outdated. Proceed with caution."* The Next.js installation page
  describes the three setup routes (`shadcn/create`, CLI scaffold, existing project) and
  names no version at all.

So: **16.2.10 is neither inside nor outside what shadcn's docs claim, because its docs do
not draw that line.** The evidence that it works on 16.2.10 is the build in `probe-radix`,
run today — an observation of this exact version pair, not a support statement. That
distinction matters for a production-ready requirement: nobody upstream has promised it,
so a Next minor bump is on us to re-verify.

The installed Next docs contain **zero** occurrences of "shadcn" or "Radix", so nothing
from the Next side either endorses or warns.

### The one Next-16-specific hazard, and why it does not bite

`01-app/01-getting-started/05-server-and-client-components.md` (line 517) tells library
authors: *"If you're building a component library, add the `"use client"` directive to
entry points that rely on client-only features. This lets your users import components
into Server Components without needing to create wrappers."* Four of the eleven generated
files (`button.tsx`, `card.tsx`, `input.tsx`, `textarea.tsx`) have **no** `"use client"`.
The build still passed with them imported into a Server Component page, because
`@radix-ui/react-dialog@1.1.23`'s own `dist/index.js` carries the directive — the
published package follows the advice even where the generated wrapper does not. Same
outcome, but note where the guarantee lives: **in Radix's dist, not in shadcn's output.**

---

## 2. What actually gets added — counted, not estimated

All three probes are real `npm install`s in `/private/tmp/…/scratchpad/`, outside this
repo. Package counts are `npm ls --all --parseable | wc -l` minus the root entry.
Byte figures are `find .next/static/chunks -name '*.js' -exec cat {} + | gzip -c | wc -c`
after `npx next build`, on comparable pages (same controls rendered: a confirm button, an
account menu, an analyst panel, a labelled input, a select).

| | direct runtime deps | installed packages | `node_modules` dirs | gzip JS | gzip CSS | source lines to own |
|---|---|---|---|---|---|---|
| **today** | **3** | 47 | 34 | 181,705 B | 1,371 B | 0 |
| **shadcn (radix base, 11 components)** | **10** (+7) | **426** (+379) | 286 (+252) | 233,438 B (**+51,733**, +28.5%) | 8,942 B (**+7,571**) | **1,130** |
| **`@radix-ui/react-dialog` alone** | **4** (+1) | **71** (+24) | 43 (+9) | 194,914 B (**+13,209**, +7.3%) | 1,773 B (+402) | 0 |

### (a) The seven packages shadcn puts in `dependencies`

Named, with the versions it resolved on 2026-08-24:

1. `radix-ui@^1.6.7` — the umbrella. It declares **55 dependencies** and installed
   **60 `@radix-ui/*` packages** into `node_modules/@radix-ui/`, regardless of how many
   primitives are actually imported.
2. `lucide-react@^1.34.0` — icon set, pulled in by the generated components.
3. `class-variance-authority@^0.7.1` — variant maps in `button.tsx` etc.
4. `clsx@^2.1.1` and 5. `tailwind-merge@^3.6.0` — together they *are* `lib/utils.ts`,
   whose entire body is `return twMerge(clsx(inputs))`.
6. `tw-animate-css@^1.4.0` — `@import`ed by the rewritten `globals.css`.
7. **`shadcn@^4.19.0` itself, as a runtime dependency** — because init writes
   `@import "shadcn/tailwind.css"` into the global CSS. Its docs confirm this and offer
   an escape: *"Use the `eject` command to inline `shadcn/tailwind.css` into your global
   CSS file and remove the `shadcn` dependency from your project"*, with
   *"**Note: This action is irreversible.**"* Ejecting trades one dependency for a
   permanently forked copy of their utility layer.

Three runtime dependencies become ten. Against a standing rule that only directly-needed
packages get added, four of the seven (`lucide-react`, `cva`, `clsx`, `tailwind-merge`)
are needed only *because the generated code is written to need them*.

### (b) Lines of copied source

Components chosen as the plausible set for this app (button, card, dialog, dropdown-menu,
input, label, popover, select, separator, sheet, textarea) — `wc -l` on the generated
files:

```
  67 button.tsx      103 card.tsx       168 dialog.tsx    269 dropdown-menu.tsx
  19 input.tsx        24 label.tsx       89 popover.tsx   192 select.tsx
  28 separator.tsx   147 sheet.tsx       18 textarea.tsx
```

**1,124 lines** in `components/ui/`, plus **6** in `lib/utils.ts` = **1,130 lines** of new
first-party TypeScript. `app/globals.css` goes from **1 line to 128** in the probe; in
this repo it would go from **26 to roughly 128**, since init overwrites rather than merges.

For scale: the entire current frontend, excluding tests, is **1,669 lines**
(`app/**/*.{ts,tsx,css}`). Adopting shadcn's eleven components would add **~68% more
frontend code to own, review, and keep**, none of it about panel evaluation. The
component count is a judgement call and the line count scales with it — a three-component
adoption (dialog, popover, button) is 324 lines. But the direction is fixed: shadcn is a
code-generation tool, so "adopt a library" here means "adopt a fork".

---

## 3. Per-surface: does Radix have a primitive that earns its place?

The frontend today is one route (`app/page.tsx`, 14 lines) and five components:
`evaluate-form.tsx` (159), `posterior-chart.tsx` (242, hand-rolled inline SVG, no chart
library), `report.tsx` (344), `analyst-dock.tsx` (175), `health-check.tsx` (42).
`app/layout.tsx` is 33 lines, has **no header chrome and zero providers**.

| surface | ticket | Radix primitive | earns it? |
|---|---|---|---|
| **analyst dock** (exists) | — | `Dialog` (non-modal) or `Popover` | **Yes — the one clear earner** |
| **panel preview** | [077 · #167](https://github.com/Subaru-Goto/PanelVerdict/issues/167) | `Dialog` / `AlertDialog` | **Probably** — if it overlays |
| **login chrome** | [063 · #158](https://github.com/Subaru-Goto/PanelVerdict/issues/158), [092 · #197](https://github.com/Subaru-Goto/PanelVerdict/issues/197) | `DropdownMenu` | **Only if** the signed-in indicator is a real menu |
| **HITL confirmation gate** | [076 · #166](https://github.com/Subaru-Goto/PanelVerdict/issues/166) | `AlertDialog` | **Only if** it overlays rather than replaces |
| **$0 demo page** | [061 · #156](https://github.com/Subaru-Goto/PanelVerdict/issues/156) | none | **No** |

(The task brief numbered the demo page #155; the mapping resolved against the tracker is
**#156 · 061 "A $0 demo page: fixed target, stored report, no translator call"**. #155 is
060, the tests table.)

**The analyst dock.** This is the strongest case in the app and it is not close. The open
state is `<aside aria-label="Analyst chat" className="fixed bottom-6 right-6 …">` holding
a scrollable transcript, suggestion chips, a text input and a send button. It has no
`role="dialog"`, no `aria-modal`, no focus trap, no Escape handler, and no focus
restoration to the launcher button on close. Radix's Dialog docs list exactly these as
shipped behaviour: *"Supports modal and non-modal modes. Focus is automatically trapped
within modal. … Manages screen reader announcements with Title and Description
components. Esc closes the component automatically"*, and *"Adheres to the Dialog WAI-ARIA
design pattern"* with a documented keyboard table (Space/Enter open and close, Tab and
Shift+Tab move focus, Esc closes and returns focus to the trigger). A **non-modal** Dialog
is the right fit — the dock is meant to sit beside a readable report, not blank it — and
non-modal is a documented mode, not a hack.

**The panel preview (077).** "A reader sees who was seated and accepts or redraws —
before paying." A decision that gates spending, with two mutually exclusive answers, is
the textbook `AlertDialog`: it wants focus pinned to the choice and Escape *not* silently
meaning "accept". Worth Radix if it renders as an overlay. If 077 renders it as a section
of the page and the buttons are just buttons, Radix adds nothing.

**The login chrome (063 / 092).** A sign-in button is an `<a>` or a `<button>` — Radix has
nothing to offer, and Google's flow is a redirect. The signed-in indicator is where it
turns: an avatar that opens a menu with "Sign out" wants roving-tabindex arrow-key
navigation, typeahead, Escape, outside-click dismissal and correct `aria-*` — that is
`DropdownMenu`, and it is real work to hand-roll. But note the shape of the bet:
`dropdown-menu.tsx` is the **largest** generated file at 269 lines, for what may be a menu
with one item. Until 092 settles whether the indicator is a menu or just a name and a
sign-out link, this surface does not justify a dependency.

**The HITL confirmation gate (076).** The ticket authors the graph around
`screen → select → confirm → vote → assemble`. The `confirm` step is a *graph interrupt*
first and a screen second. If the UI expression is a full-route blocking state — the page
becomes the confirmation — then there is no overlay, nothing to trap focus against, and
no Radix primitive applies; it is routing plus a form. Only if it is an overlay does
`AlertDialog` earn its place. **This is the surface most likely to be assumed into a
modal that it does not need to be.**

**The $0 demo page (061).** A second route showing a fixed target and a stored report:
headings, prose, the existing chart. No dismissable layer, no focus management, no
composite widget. Radix has no primitive here, and this is the surface where a token layer
pays off instead — the demo page's job is to look finished.

**Score: one clear earner today, two conditional, two no.** Every conditional resolves to
`Dialog`/`AlertDialog`, which is the same package.

---

## 4. Accessibility — the real argument, stated against what we'd otherwise write

Measured across `frontend/app/` (excluding tests):

| | current app | shadcn's generated components |
|---|---|---|
| `focus-visible:` utilities | **0** | **15**, across 4 files |
| `focus:` utilities | **0** | — |
| `outline` utilities | **0** | — |
| `Escape` / `keydown` handlers | **0** | supplied by Radix |
| `role="…"` attributes | **2** (`status`, `img`) | supplied by Radix |
| `aria-*` attributes | **6** total (3 `aria-label`, 2 `aria-hidden`, 1 `aria-live`) | `aria-invalid` styling hooks in 4 files; the rest supplied by Radix |
| `data-slot` styling hooks | 0 | 68 |

**There is no `focus-visible:` style anywhere in the app.** Every interactive element —
the submit button, the suggestion chips, the dock launcher, the dock's close button, the
dock's input — renders whatever the browser's default focus ring is over a custom
background, which in the dark-mode branch is `bg-zinc-900`. A keyboard user can tab
through this app; they cannot reliably see where they are.

What Radix gives for free, per surface, quoting its docs:

- **Dock as non-modal Dialog** — Escape-to-close and focus return to the trigger
  (*"Esc closes the component automatically"*; the keyboard table documents Esc returning
  focus to `Dialog.Trigger`), `Title`/`Description` wired to the container for screen
  reader announcement, and the WAI-ARIA dialog role/attribute set. Today the dock has
  **none** of these four; hand-rolling them is a `useEffect` keydown listener, a ref to
  the launcher, a tab-cycle sentinel pair, and the `aria-modal`/`role`/`aria-labelledby`
  triad — the sentinel-based focus trap is the part that is genuinely easy to get subtly
  wrong (shift-tab off the first element, portal ordering, restoring focus when the
  trigger has unmounted).
- **Preview / confirm as AlertDialog** — the same, plus the "no accidental dismissal"
  semantics a spend gate wants.
- **Account menu as DropdownMenu** — arrow-key roving focus, typeahead, `aria-expanded`
  on the trigger, `aria-orientation`, outside-pointerdown dismissal, and focus return.
  This is the one where hand-rolling is not a weekend.
- **Popover** — *"Focus is fully managed and customizable"*, *"Dismissing and layering
  behavior is highly customizable"*, and its own Esc-returns-focus-to-trigger table.

**What Radix does not give:** the focus ring itself. Radix manages *where* focus goes;
`focus-visible:ring-2 focus-visible:ring-…` is a token-layer decision and must be
authored either way. shadcn's 15 `focus-visible:` utilities are a **style default**, not
an accessibility primitive — and they are hard-coded against shadcn's own `--ring`
variable, so taking them means taking its palette (see §5).

The honest split, then: **focus *management* is worth a dependency; focus *appearance* is
[056 · #151](https://github.com/Subaru-Goto/PanelVerdict/issues/151)'s job and no library
does it for us in a way we'd keep.**

---

## 5. Does shadcn sit *on top of* a hand-authored token layer, or compete with it?

056 says a library "would sit on top of it rather than replace it". **For shadcn, that is
false in one specific, measurable way, and true in another.**

### Where it does not collide: the variable names

Today's `app/globals.css` declares `--background` / `--foreground` under `:root` and maps
them with `@theme inline { --color-background: var(--background); … }`. shadcn's Token
Convention is the same shape — *"Given the following CSS variables: `--primary`,
`--primary-foreground` … the `background` color of the following component will be
`var(--primary)` and the `foreground` color will be `var(--primary-foreground)`"* — and
its generated `globals.css` uses the identical `@theme inline` → `--color-*` → `var(--*)`
indirection. Both descend from the same Tailwind v4 starter. So the naming would not
*clash*; shadcn would **absorb** the two-variable layer into a 72-variable one (31 of them
`--color-*` mappings), rewritten in `oklch()`, with `--chart-1..5` and eight `--sidebar-*`
tokens this app has no use for.

That absorption is the competition. A hand-authored `@theme` layer for this project is a
small, argued set of semantic colours and a type scale; shadcn's is a generated set sized
for a dashboard kit. Merging a designed layer into a generated one is not "sitting on
top", it is inheriting someone else's vocabulary and then deleting from it.

### Where it collides hard: dark mode. Measured.

The same source line, `<span className="dark:bg-red-500">`, compiled in two probes:

```css
/* probe (Next 16.2.10 + Tailwind v4, no shadcn) */
@media (prefers-color-scheme:dark){ .dark\:bg-red-500{background-color:var(--color-red-500)} }

/* probe-radix (after `shadcn init`) */
.dark\:bg-red-500:is(.dark *){background-color:var(--color-red-500)}
```

`shadcn init` writes `@custom-variant dark (&:is(.dark *));` into the global CSS, which
**re-points the entire `dark:` variant from the OS preference to a `.dark` ancestor
class.** Counted in the built CSS: the baseline has **1** `prefers-color-scheme` block;
after init there are **0**, and **46** `.dark` selectors.

This repo has **54 `dark:` utilities across all five components**
(`analyst-dock`, `evaluate-form`, `health-check`, `posterior-chart`, `report`), **zero
occurrences of a `.dark` class**, no theme provider, and — per `app/layout.tsx` — no
provider of any kind. Running `shadcn init` here would leave the app in permanent light
mode with 54 dead utilities and no error, until a theme provider, a class toggle, and a
persistence story are added. That is a whole unplanned ticket, arriving as a side effect
of a styling decision.

Two smaller ones in the same file: shadcn's `@theme inline` emits
`--font-sans: var(--font-sans)`, while `app/globals.css` maps
`--font-sans: var(--font-geist-sans)` from `next/font` — the overwrite would drop the
Geist wiring that 056 is specifically trying to fix. And `body { font-family: Arial,
Helvetica, sans-serif }` (the line 056 is about) survives init untouched, so shadcn does
**not** solve 056; it lands on top of the same bug.

### Verdict on sequencing

**056 before 057's outcome is right, but the map's stated reason is wrong.** The reason is
not "the layer is a foundation a library sits on" — it is that **shadcn would overwrite
the file 056 authors**, so doing 056 first and then running `shadcn init` is wasted work.
Under the recommendation here (Radix without shadcn), the conflict disappears entirely:
**`@radix-ui/react-dialog` touched `app/globals.css` not at all** — the probe's global CSS
was still the one line it started as, `prefers-color-scheme` intact.

`cn()` deserves the same treatment. `twMerge(clsx(...))` is a genuinely useful ~6-line
helper for a component with variants, and it is 2 dependencies. It does not *compete* with
a token layer, but it does not require shadcn either — it can be typed by hand into
`app/lib/cn.ts` when the first component actually needs class-list merging, and not
before.

---

## What 058 (#153) should build to settle this

#153 is "restyle one component both ways and react to it". Make the component **the
analyst dock**, not the evaluate form — the dock is where the two options actually
diverge, and a form restyle would compare two token layers and prove nothing.

Two arms, both on throwaway branches:

- **Arm A — token layer only.** Author the 056 `@theme` layer, restyle the dock against
  it, and hand-roll the four missing behaviours: Escape-to-close, focus trap, focus return
  to the launcher, `role="dialog"` + `aria-modal` + `aria-labelledby`. Record the line
  count of the focus-management code and whether it survives a keyboard walkthrough
  (tab-cycle at both ends, Escape, focus after close).
- **Arm B — `@radix-ui/react-dialog` (non-modal), styled by the same token layer.**
  Same visual result, same tokens, Radix supplying behaviour. Record the gzip delta on
  the real app (the +13,209 B here is a synthetic page) and the diff to `globals.css`
  (expected: none).

Do **not** make Arm B `shadcn init` — that arm would confound the comparison with a
palette rewrite and a dark-mode regression, and this document already measured that.
If someone wants shadcn back on the table, the reaction to look for in Arm A is
*"the focus-management code is bigger and more fragile than expected"*; that argues for
more Radix, still not for the generator.

The decision reduces to one question #153 can answer by feel: **is 13 KB and one
dependency worth not owning a focus trap?** The measurements say the question is that
small — which is the useful result here, because the framing "adopt shadcn or don't" made
it look much bigger.

---

## Could not confirm from primary sources

1. **That shadcn supports Next.js 16 at all.** Its docs name no minimum, no maximum, no
   tested version; the only Next-versioned page is titled "Next.js 15 + React 19" and
   self-flags as possibly outdated. The build passing in `probe-radix` on 2026-08-24 is
   *my* observation, not an upstream claim. **UNVERIFIED: whether shadcn tests against
   Next 16.**
2. **Whether `radix-ui@1.6.7` tree-shakes.** The +51,733 B gzip figure is for a page
   importing five primitives via the umbrella package; I did not isolate how much of that
   is the umbrella versus the primitives. The `@radix-ui/react-dialog`-only probe
   (+13,209 B for one primitive) suggests it does shake, but that is inference from two
   different import styles, not a controlled measurement.
3. **The Radix docs' feature text is from the rendered docs site, not the package.** The
   dialog page displayed "Version: 1.1.20" while the installed package is 1.1.23; I did
   not verify that the focus-trap and Escape behaviour is byte-identical between them.
4. **The 1,130-line and 7-package counts assume an eleven-component adoption.** That set
   is my reading of what this app's surfaces would want; a different set gives different
   numbers. The seven `dependencies` are what `init` + those eleven `add`s produced —
   a smaller set may pull fewer (`lucide-react` in particular is icon-driven).
5. **Bundle deltas are from synthetic pages**, built outside this repo with pages that
   render the controls in isolation. The real app's delta will differ; #153 Arm B should
   measure it on the actual dock.
6. **Whether 076's confirmation gate is an overlay or a route.** The ticket authors the
   graph, not the screen. My "only if it overlays" verdict is conditional on a decision
   that has not been made.
7. **shadcn's `aria` base** (the third `--base` option alongside `base` and `radix`) was
   not evaluated. If React Aria is a serious alternative to Radix for this project, that
   is a separate question and this document does not answer it.
8. **`npx shadcn@latest eject`** was not run. Its effect ("inline `shadcn/tailwind.css`,
   remove the `shadcn` dependency", irreversible) is quoted from the CLI docs, not
   measured.

---

## Sources

**Primary — on disk, `next@16.2.10`** (`frontend/node_modules/next/dist/docs/`, read 2026-08-24):

- `01-app/01-getting-started/11-css.md` — Tailwind v4 install, `@tailwindcss/postcss`, `@import 'tailwindcss'`.
- `01-app/02-guides/tailwind-v3-css.md` — v3 as the legacy path; points back to the v4 instructions.
- `01-app/01-getting-started/05-server-and-client-components.md` — third-party components and `"use client"`; library-author advice at line 517.

**Primary — vendor docs** (read 2026-08-24):

- `https://ui.shadcn.com/docs/installation/next.md` — Next.js setup; no version stated.
- `https://ui.shadcn.com/docs/tailwind-v4.md` — `@theme` / `@theme inline` support claim.
- `https://ui.shadcn.com/docs/react-19.md` — React 19 support claim; page titled "Next.js 15 + React 19", flagged possibly outdated.
- `https://ui.shadcn.com/docs/components-json.md` — `"config": ""` for Tailwind v4.
- `https://ui.shadcn.com/docs/theming.md` — Token Convention, `@theme inline`, `--no-css-variables`.
- `https://ui.shadcn.com/docs/cli.md` — `init`, `add`, `eject`, `migrate radix`.
- `https://www.radix-ui.com/primitives/docs/components/dialog` — Features list, WAI-ARIA conformance, keyboard table.
- `https://www.radix-ui.com/primitives/docs/components/popover` — focus management, modal/non-modal, keyboard table.

**Primary — measurements** (three throwaway Next 16.2.10 projects built outside this repo,
2026-08-24; `shadcn` CLI 4.19.0, `radix-ui` 1.6.7, `@radix-ui/react-dialog` 1.1.23):
package counts via `npm ls --all --parseable`, byte figures via
`find .next/static/chunks -name '*.js' -exec cat {} + | gzip -c | wc -c` after
`npx next build`, dark-variant compilation read from the emitted CSS chunk.

**Primary — this repo** (`frontend/`, 2026-08-24): `package.json`, `app/globals.css`,
`app/layout.tsx`, `app/components/*.tsx`; `wc -l` and `grep -r` counts as quoted.

No blog posts, aggregator answers, or video sources were used.
