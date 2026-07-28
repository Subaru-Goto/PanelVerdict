import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  resolve: {
    // Next's vitest guide reaches for the vite-tsconfig-paths plugin here, but
    // Vite now resolves tsconfig paths natively and the plugin prints a
    // deprecation notice saying exactly that.
    tsconfigPaths: true,
  },
  test: {
    environment: "jsdom",
  },
});
