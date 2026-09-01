import { describe, expect, it, vi } from "vitest";

import { authHeaders, createNonce, signOut } from "../app/lib/auth";

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

describe("the session as headers", () => {
  it("is empty where no session can exist", async () => {
    // No Supabase project is configured in test, so there is nobody signed in.
    // An empty object, never an empty bearer: `Authorization: Bearer ` is a
    // malformed credential rather than an absent one, and the backend would
    // have to decide what to do with it.
    expect(await authHeaders()).toEqual({});
  });
});

describe("signing out", () => {
  it("tells Google too, so the button does not offer one-click re-entry", async () => {
    // Two sessions exist: the app's (Supabase) and the browser's Google
    // session. Ending only the first leaves Google free to re-personalize
    // the button into "Continue as …" — a sign-out that signs you back in.
    // Google's integration docs require disableAutoSelect on sign-out.
    const disabled = vi.fn();
    (window as unknown as Record<string, unknown>).google = {
      accounts: { id: { disableAutoSelect: disabled } },
    };

    await signOut();

    expect(disabled).toHaveBeenCalledTimes(1);
    delete (window as unknown as Record<string, unknown>).google;
  });

  it("survives the Google script never having loaded", async () => {
    // Sign-out must work even when the button's script failed or was blocked:
    // ending the app session cannot depend on Google being reachable.
    await expect(signOut()).resolves.toBeUndefined();
  });
});
