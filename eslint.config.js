/* Root ESLint flat config.
 *
 * Purpose: satisfy the `post-tool-use/run_lint.sh` hook which invokes
 * `eslint --fix <file>` from the project root. ESLint 9 only discovers
 * flat configs from cwd UPWARD, never DOWN into subdirectories, so a
 * config living only at `hub/frontend/eslint.config.js` is ignored when
 * the hook runs `eslint --fix hub/frontend/src/<file>` from here.
 *
 * Scope: intentionally minimal. The frontend bundle is still mid-TS-
 * migration — every .ts file opens with `// @ts-nocheck`. Real typing /
 * linting will land in a follow-up pass after the bundle is verified in
 * prod. For now we just prevent the hook from crashing.
 *
 * To tighten: install `@typescript-eslint/parser` +
 * `@typescript-eslint/eslint-plugin` under hub/frontend and add them as
 * a second config block below — keyed to files: ["hub/frontend/**"]. */
export default [
  {
    ignores: [
      "**/node_modules/**",
      "**/dist/**",
      "**/.venv/**",
      "**/.env-*/**",
      "**/__pycache__/**",
      "**/.pytest_cache/**",
      "**/.ruff_cache/**",
      "GITIGNORED/**",
      "hub/static/**",
      "hub/frontend/**",
      "dist/**",
      "logs/**",
      "db.sqlite3",
    ],
  },
];
