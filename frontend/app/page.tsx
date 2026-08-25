import HealthCheck from "./components/health-check";
import EvaluateForm from "./components/evaluate-form";
import SignIn from "./components/sign-in";

export default function Home() {
  return (
    <main className="mx-auto flex w-full max-w-2xl flex-1 flex-col gap-8 px-6 py-12">
      <header className="flex flex-col gap-1">
        <h1 className="text-2xl font-semibold">PanelVerdict</h1>
        <HealthCheck />
        <SignIn />
      </header>
      <EvaluateForm />
    </main>
  );
}
