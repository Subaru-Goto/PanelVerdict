import { readdirSync, readFileSync } from "node:fs";
import { join, relative, sep } from "node:path";

import { describe, expect, it } from "vitest";

// 045/#143's done-when clause "the secret is not readable in the client
// bundle", pinned at the source level: Next only inlines NEXT_PUBLIC_* into
// client code, and route handlers never ship to the browser — so the bundle
// cannot contain what no client module references. Derived from the tree,
// not listed, so a new component is covered the day it appears.

const APP_DIR = join(__dirname, "..", "app");

function sourceFiles(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true, recursive: true })
    .filter((e) => e.isFile() && /\.(ts|tsx)$/.test(e.name))
    .map((e) => join(e.parentPath, e.name));
}

describe("the client bundle's discipline", () => {
  it("keeps the edge secret and the backend URL out of client modules", () => {
    const offenders = sourceFiles(APP_DIR)
      .filter((file) => !relative(APP_DIR, file).startsWith(`api${sep}`))
      .filter((file) => {
        const source = readFileSync(file, "utf8");
        return (
          source.includes("API_SHARED_SECRET") ||
          source.includes("NEXT_PUBLIC_API_URL") ||
          // 063/#158: the elevated Supabase key bypasses row-level security
          // and can delete any user. The publishable key beside it in config
          // is safe in the bundle and this one never is, so the two must not
          // be confused by a copy-paste.
          source.includes("SUPABASE_SERVICE_KEY")
        );
      })
      .map((file) => relative(APP_DIR, file));

    expect(offenders).toEqual([]);
  });
});
