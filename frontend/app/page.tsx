import HealthCheck from "./components/health-check";

export default function Home() {
  return (
    <main className="flex flex-1 flex-col items-center justify-center gap-4">
      <h1 className="text-2xl font-semibold">PanelVerdict</h1>
      <HealthCheck />
    </main>
  );
}
