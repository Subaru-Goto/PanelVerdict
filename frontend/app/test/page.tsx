import { Suspense } from "react";

import { backendTracing } from "../api/proxy";
import EvaluateForm from "../components/evaluate-form";
import HealthCheck from "../components/health-check";

// A server component, so the tracing disclosure is in the HTML the reader is
// first served rather than appearing a moment after hydration.
export default async function TestPage() {
  const tracing = await backendTracing();

  return (
    <div className="mx-auto flex w-full max-w-2xl flex-col gap-6 px-6 py-12">
      <HealthCheck />
      {/* The wizard reads `?open=` from the address; Suspense is what Next
          asks of a page that does (the fallback is the frame, instantly). */}
      <Suspense>
        <EvaluateForm tracing={tracing} />
      </Suspense>
    </div>
  );
}
