"use client";

import { useEffect, useState } from "react";

type Health = { status: string; db: string };

export default function HealthCheck() {
  const [health, setHealth] = useState<Health | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();

    async function load() {
      try {
        // Same origin, through the proxy (045/#143) — the backend URL lives
        // only in the server-side route handlers.
        const res = await fetch("/api/health", {
          signal: controller.signal,
        });
        if (!res.ok) throw new Error(`API responded ${res.status}`);
        setHealth((await res.json()) as Health);
      } catch (err) {
        if (err instanceof Error && err.name !== "AbortError") {
          setError(err.message);
        }
      }
    }

    load();
    return () => controller.abort();
  }, []);

  if (error) return <p className="text-red-600">API unreachable: {error}</p>;
  if (!health) return <p className="text-zinc-500">Checking API…</p>;

  return (
    <p className="text-zinc-700 dark:text-zinc-300">
      API: <strong>{health.status}</strong> · DB: <strong>{health.db}</strong>
    </p>
  );
}
