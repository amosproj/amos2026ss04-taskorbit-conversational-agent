import { defineConfig } from "vitest/config";

// Standalone Vitest config (vite.config.ts stays untouched). Unit tests are
// pure-node only; nothing here needs a DOM environment.
export default defineConfig({
  test: {
    environment: "node",
    include: ["src/**/*.test.ts"],
  },
});
