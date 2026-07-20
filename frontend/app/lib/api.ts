export type Verdict = {
  counts: Record<string, number>;
  total: number;
  winner: string;
};

export type Vote = {
  persona_id: string;
  chosen_variant_id: string;
  reason: string;
};

export type EvaluateResponse = {
  verdict: Verdict;
  variants: Record<string, string>;
  votes: Vote[];
};

export async function evaluate(
  headlineA: string,
  headlineB: string,
): Promise<EvaluateResponse> {
  const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/evaluate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ headline_a: headlineA, headline_b: headlineB }),
  });
  if (!res.ok) throw new Error(`API responded ${res.status}`);
  return (await res.json()) as EvaluateResponse;
}
