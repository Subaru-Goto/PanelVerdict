/** The one deadline a paid run has (032/#133).
 *
 * The proxy routes run under this budget platform-side (`vercel.json`,
 * pinned equal by proxy.test.ts), and the browser's own request aborts at the
 * same number, so a connection that died quietly cannot outlive the proxy.
 *
 * Sourced, not picked: 300 s is the Hobby plan's default and maximum function
 * duration with Fluid compute (Vercel docs, "Configuring Maximum Duration",
 * read 2026-09-04). The run it bounds measures 45.3 s for a full 200-vote buy
 * (backend/app/data/demo/free-delivery.json, 2026-09-01), and the ticket's
 * worst-case arithmetic at that size — eight waves at a p99 of 14 s plus a
 * translator call — comes to about 112 s. The old 60 s budget cut runs that
 * arithmetic says are alive. */
export const RUN_BUDGET_SECONDS = 300;

/** What the reader is told when the deadline fires. The backend keeps going
 *  and the report lands in the rail if it finishes (099/#208 decided the run
 *  counts and nothing is refunded), so the sentence says where to look and
 *  that the money is already spent. */
export class RunTimedOut extends Error {
  constructor() {
    super(
      `This page stopped waiting after ${RUN_BUDGET_SECONDS / 60} minutes. ` +
        "The panel may still finish on its own; if it does, the test appears " +
        "under your past tests. Today's run count already includes it.",
    );
    this.name = "RunTimedOut";
  }
}
