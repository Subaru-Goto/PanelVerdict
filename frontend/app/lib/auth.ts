import { createClient, type SupabaseClient } from "@supabase/supabase-js";

/** Signing in, which exists to bound spending and nothing else (063/#158).
 *
 * A run costs money, so the backend counts runs per caller — and that limit is
 * worth exactly what the identity behind it is worth. An address costs nothing
 * to change; a Google account does not. So the browser proves who is spending,
 * and the backend checks the proof rather than taking our word for it.
 *
 * Plain `supabase-js`, deliberately not `@supabase/ssr`: the session lives in
 * this bundle and travels as an `Authorization` header, because our route
 * handlers are pure proxies that never read it. That is the whole reason the
 * cookie/middleware apparatus is absent here — nothing server-side needs a
 * session, so nothing pays for one.
 */

/** Both halves of one nonce: Google is given the hash, Supabase the original.
 *
 * Supabase's guide is explicit that this asymmetry is required — "you need to
 * provide a hashed version to Google and a non-hashed version to
 * `signInWithIdToken`" — and swapping them fails at the provider, far from
 * here.
 */
export type Nonce = { raw: string; hashed: string };

export async function createNonce(): Promise<Nonce> {
  // 32 bytes is Supabase's own generator, copied from their guide rather than
  // chosen here — the guide specifies the hashing, and this is the input it
  // specifies it over.
  const raw = btoa(
    String.fromCharCode(...crypto.getRandomValues(new Uint8Array(32))),
  );
  const digest = await crypto.subtle.digest(
    "SHA-256",
    new TextEncoder().encode(raw),
  );
  const hashed = Array.from(new Uint8Array(digest))
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
  return { raw, hashed };
}

// Written out in full rather than looked up through a variable: Next inlines
// `NEXT_PUBLIC_*` by textual substitution at build time, and "dynamic lookups
// will not be inlined" (next/docs, environment-variables). A variable name
// here would compile to `undefined` in the browser. These values are also
// frozen at build time, so the deploy must set them before `next build`, not
// after.
const SUPABASE_URL = process.env.NEXT_PUBLIC_SUPABASE_URL;
const SUPABASE_PUBLISHABLE_KEY =
  process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY;
const GOOGLE_CLIENT_ID = process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID;

let client: SupabaseClient | null = null;

/** The Supabase client, or null where sign-in is not configured.
 *
 * The publishable key is safe in this bundle by the vendor's own statement —
 * it identifies the project, it does not authorise anything. The elevated key
 * is a different value that lives only on the backend.
 */
export function authClient(): SupabaseClient | null {
  if (!SUPABASE_URL || !SUPABASE_PUBLISHABLE_KEY) return null;
  client ??= createClient(SUPABASE_URL, SUPABASE_PUBLISHABLE_KEY);
  return client;
}

/** Whether this build can sign anyone in at all — the UI asks before offering. */
export function signInAvailable(): boolean {
  return authClient() !== null && Boolean(GOOGLE_CLIENT_ID);
}

/** The current session's access token, or null when nobody is signed in.
 *
 * `getSession` rather than a cached copy: the client refreshes in the
 * background, and a token read once and kept would go stale mid-session and
 * turn a signed-in visitor into a 401.
 */
export async function accessToken(): Promise<string | null> {
  const supabase = authClient();
  if (supabase === null) return null;
  const { data } = await supabase.auth.getSession();
  return data.session?.access_token ?? null;
}

declare global {
  interface Window {
    google?: {
      accounts: {
        id: {
          initialize(config: Record<string, unknown>): void;
          renderButton(parent: HTMLElement, options: Record<string, unknown>): void;
        };
      };
    };
  }
}

const GSI_SRC = "https://accounts.google.com/gsi/client";

let scriptLoad: Promise<void> | null = null;

function loadGoogleScript(): Promise<void> {
  // Memoised rather than re-derived from the DOM: a second caller that found
  // the tag already present but the global not yet assigned used to attach a
  // `load` listener to a script that had already fired, and wait forever — a
  // button that renders and then does nothing at all.
  scriptLoad ??= new Promise<void>((resolve, reject) => {
    if (window.google?.accounts?.id) {
      resolve();
      return;
    }
    const script = document.createElement("script");
    script.src = GSI_SRC;
    script.async = true;
    script.onload = () => resolve();
    script.onerror = () => {
      scriptLoad = null;
      reject(new Error("google identity services did not load"));
    };
    document.head.append(script);
  });
  return scriptLoad;
}

/** Render Google's own sign-in button into `container`.
 *
 * Google's **pre-built button**, not a button of ours calling One Tap's
 * `prompt()`. The two look interchangeable and are not: FedCM puts the prompt
 * into a cooldown once a visitor dismisses it, so our own button would
 * silently do nothing on the next visit — working, then not, with no error and
 * nothing on screen to explain it.
 *
 * The page never navigates, and that is a product constraint rather than a
 * preference: signing in has to resume into whatever it interrupted, with
 * whatever was on screen still on screen, and a full-page redirect discards
 * both. `signInWithOAuth` is a `window.location.assign` with no popup variant;
 * Google renders this button in an iframe and Supabase documents feeding its
 * credential to `signInWithIdToken`, which is an ordinary fetch.
 *
 * Resolves once the button is on screen — not once anyone has signed in.
 * `onAuthChange` is what reports that.
 */
export async function mountGoogleButton(container: HTMLElement): Promise<void> {
  const supabase = authClient();
  if (supabase === null || !GOOGLE_CLIENT_ID) {
    throw new Error("sign-in is not configured for this build");
  }
  await loadGoogleScript();
  const nonce = await createNonce();
  window.google!.accounts.id.initialize({
    client_id: GOOGLE_CLIENT_ID,
    // Chrome's third-party-cookie removal means this needs FedCM; Supabase's
    // guide calls setting it out explicitly.
    use_fedcm_for_prompt: true,
    nonce: nonce.hashed,
    callback: async (response: { credential?: string }) => {
      if (!response.credential) return;
      await supabase.auth.signInWithIdToken({
        provider: "google",
        token: response.credential,
        // Raw here, hashed above — the way round Supabase's guide specifies,
        // and the easy thing to get backwards.
        nonce: nonce.raw,
      });
    },
  });
  window.google!.accounts.id.renderButton(container, { type: "standard" });
}

export async function signOut(): Promise<void> {
  await authClient()?.auth.signOut();
}

/** Watch whether anyone is signed in. Returns an unsubscribe.
 *
 * Fires once with the state at subscription time and again on every change,
 * so a caller never has to ask separately — a component that mounted after a
 * session was restored would otherwise render signed-out until the next event
 * that never comes.
 */
export function onAuthChange(
  listener: (signedIn: boolean) => void,
): () => void {
  const supabase = authClient();
  if (supabase === null) {
    listener(false);
    return () => {};
  }
  void supabase.auth
    .getSession()
    .then(({ data }) => listener(data.session !== null));
  const { data } = supabase.auth.onAuthStateChange((_event, session) =>
    listener(session !== null),
  );
  return () => data.subscription.unsubscribe();
}

/** The session as request headers, or nothing at all.
 *
 * One place, because three callers need it and a fourth that quietly forgot
 * would not fail loudly — it would just spend against the wrong identity, or
 * be refused with no obvious cause. Empty when nobody is signed in: the
 * backend's refusal is the right answer, and an empty bearer would only make
 * it a worse-shaped one.
 */
export async function authHeaders(): Promise<Record<string, string>> {
  const session = await accessToken();
  return session ? { Authorization: `Bearer ${session}` } : {};
}
