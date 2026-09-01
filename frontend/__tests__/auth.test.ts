import { afterEach, describe, expect, it, vi } from "vitest";

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
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("records the sign-out with Google, so nothing signs back in automatically", async () => {
    // Claiming only what disableAutoSelect does: it blocks *automatic*
    // re-sign-in (auto_select / FedCM auto flows). The personalized
    // "Continue as \u2026" button is the browser's own Google session and no
    // site call removes it.
    const disabled = vi.fn();
    vi.stubGlobal("google", {
      accounts: { id: { disableAutoSelect: disabled } },
    });

    await signOut();

    expect(disabled).toHaveBeenCalledTimes(1);
  });

  it("survives the Google script never having loaded", async () => {
    // The common case, not an edge: the script loads only while signed out,
    // so a restored session reaches sign-out with no GSI at all.
    await expect(signOut()).resolves.toBeUndefined();
  });

  it("survives another script owning the google global", async () => {
    // `window.google` is a shared namespace: Maps, Translate and extensions
    // claim it with shapes GSI never promised. A partial global must not
    // turn the app's sign-out into a TypeError that leaves the session live.
    vi.stubGlobal("google", { maps: {} });

    await expect(signOut()).resolves.toBeUndefined();
  });

  it("survives Google's own code throwing mid-call", async () => {
    // Present-but-broken GSI (extension or policy interference) is Google's
    // failure, not the sign-out's.
    vi.stubGlobal("google", {
      accounts: {
        id: {
          disableAutoSelect: () => {
            throw new Error("credential manager unavailable");
          },
        },
      },
    });

    await expect(signOut()).resolves.toBeUndefined();
  });
});
