// ESLint v9 flat config for the TaskOrbit frontend.
//
// Rule sources are kept minimal and rely on plugins already declared in
// `package.json` so `npm ci` is enough to install everything CI needs:
//   - @eslint/js                  -> JavaScript recommended rules
//   - typescript-eslint           -> TypeScript-aware parser + recommended rules
//   - eslint-plugin-react-hooks   -> Rules of Hooks (rules-of-hooks, exhaustive-deps)
//   - eslint-plugin-react-refresh -> Vite Fast Refresh boundary checks
//   - globals                     -> Browser global names
//
// To extend with stricter type-checked rules later, swap
// `tseslint.configs.recommended` for `tseslint.configs.recommendedTypeChecked`
// and add a `parserOptions.project` pointing at `tsconfig.app.json`.
import js from "@eslint/js";
import globals from "globals";
import reactHooks from "eslint-plugin-react-hooks";
import reactRefresh from "eslint-plugin-react-refresh";
import tseslint from "typescript-eslint";

export default tseslint.config(
  {
    // Files ESLint should never look at. Lockfiles, build output, type-check
    // caches, and generated assets stay out of the lint surface.
    ignores: ["dist", "node_modules", "*.tsbuildinfo", "public", "vite.config.ts.timestamp-*"],
  },
  {
    files: ["**/*.{ts,tsx}"],
    extends: [js.configs.recommended, ...tseslint.configs.recommended],
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: "module",
      globals: {
        ...globals.browser,
        ...globals.es2022,
      },
    },
    plugins: {
      "react-hooks": reactHooks,
      "react-refresh": reactRefresh,
    },
    rules: {
      ...reactHooks.configs.recommended.rules,
      // Vite Fast Refresh requires every module that defines a component to
      // export only components. Allow constant exports (e.g. router objects)
      // so files like `router.tsx` don't have to be split.
      // Option key is `allowConstantExport` (singular) in
      // eslint-plugin-react-refresh >= 0.4.x; the schema is strictly validated
      // by ESLint 9 so spelling matters.
      "react-refresh/only-export-components": ["warn", { allowConstantExport: true }],
      // Allow `_`-prefixed unused arguments (matches typescript-eslint convention).
      "@typescript-eslint/no-unused-vars": [
        "error",
        { argsIgnorePattern: "^_", varsIgnorePattern: "^_" },
      ],
    },
  },
  {
    // Node-context config files don't need browser globals and may use
    // `process`/`__dirname` legitimately.
    files: ["vite.config.ts", "eslint.config.js"],
    languageOptions: {
      globals: { ...globals.node },
    },
  },
);
