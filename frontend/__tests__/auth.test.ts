import { describe, expect, it } from "vitest";

import { createNonce } from "../app/lib/auth";

// 063/#158. The nonce is the one part of Google's pre-built sign-in that is
// easy to get backwards, and getting it backwards fails at the provider rather
// than here: Supabase's guide says "you need to provide a hashed version to
// Google and a non-hashed version to signInWithIdToken".

describe("the sign-in nonce", () => {
  it("hands Google the hash of what Supabase is handed", async () => {
    const nonce = await createNonce();

    const digest = await crypto.subtle.digest(
      "SHA-256",
      new TextEncoder().encode(nonce.raw),
    );
    const expected = Array.from(new Uint8Array(digest))
      .map((b) => b.toString(16).padStart(2, "0"))
      .join("");
    expect(nonce.hashed).toBe(expected);
  });

  it("hashes to lowercase hex, which is the representation Supabase compares", async () => {
    const nonce = await createNonce();

    expect(nonce.hashed).toMatch(/^[0-9a-f]{64}$/);
  });

  it("never hands out the same nonce twice", async () => {
    // "The nonce should be generated randomly each time" — a fixed one is a
    // replayable one.
    const [first, second] = await Promise.all([createNonce(), createNonce()]);

    expect(first.raw).not.toBe(second.raw);
  });
});
