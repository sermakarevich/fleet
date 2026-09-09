// Flat eslint config: typescript-eslint recommended plus react-hooks and
// jsx-a11y rules. Run with `npm run lint`; enforced via `just ui-check`.
import tseslint from 'typescript-eslint';
import reactHooks from 'eslint-plugin-react-hooks';
import jsxA11y from 'eslint-plugin-jsx-a11y';

export default tseslint.config(
  { ignores: ['dist', 'node_modules', 'src/shared/api-types.gen.ts'] },
  ...tseslint.configs.recommended,
  {
    plugins: { 'react-hooks': reactHooks, 'jsx-a11y': jsxA11y },
    rules: {
      ...reactHooks.configs.recommended.rules,
      'react-hooks/exhaustive-deps': 'error',
      ...jsxA11y.flatConfigs.recommended.rules,
    },
  },
);
