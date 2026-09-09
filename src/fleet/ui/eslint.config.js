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
      // ADR 0009 rule 6: colours live in shared/styles/tokens.ts only.
      // Rejects any pure hex colour string literal elsewhere; other
      // modules reference T.colors / statusColor / eventKindColor.
      'no-restricted-syntax': [
        'error',
        {
          selector: 'Literal[value=/^#[0-9a-fA-F]{3,8}$/]',
          message:
            'Hex colours are banned outside shared/styles/tokens.ts. Use T.colors (or statusColor/eventKindColor) instead.',
        },
      ],
    },
  },
  {
    files: ['src/shared/styles/tokens.ts'],
    rules: { 'no-restricted-syntax': 'off' },
  },
);
