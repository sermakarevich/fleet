// Flat eslint config: typescript-eslint recommended plus react-hooks rules.
// Run with `npm run lint`; enforced in CI via `just ui-check`.
import tseslint from 'typescript-eslint';
import reactHooks from 'eslint-plugin-react-hooks';

export default tseslint.config(
  { ignores: ['dist', 'node_modules', 'src/shared/api-types.gen.ts'] },
  ...tseslint.configs.recommended,
  {
    plugins: { 'react-hooks': reactHooks },
    rules: { ...reactHooks.configs.recommended.rules },
  },
);
