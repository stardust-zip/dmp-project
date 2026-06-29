import { resolve } from "node:path";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { "@": resolve(__dirname, "./src") },
  },
  test: {
    typecheck: { tsconfig: "./tsconfig.test.json" },
    globals: true,
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    exclude: ["**/node_modules/**", "**/.next/**", "src/e2e/**"],
    coverage: {
      provider: "v8",
      include: [
        "src/lib/rbac.ts",
        "src/lib/format.ts",
        "src/lib/auth-api.ts",
        "src/components/auth/auth-gate.tsx",
        "src/components/auth/auth-provider.tsx",
      ],
      exclude: ["src/**/*.d.ts"],
      thresholds: { lines: 80, functions: 80 },
    },
  },
});
