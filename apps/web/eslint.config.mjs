import { FlatCompat } from "@eslint/eslintrc";

const compat = new FlatCompat({
  baseDirectory: import.meta.dirname,
});

const eslintConfig = [
  ...compat.config({
    extends: ["next/core-web-vitals", "next/typescript"],
  }),
  {
    ignores: ["node_modules/**", ".next/**", "out/**", "next-env.d.ts"],
  },
  {
    files: ["src/**/*.{ts,tsx}"],
    rules: {
      "no-restricted-imports": [
        "error",
        {
          patterns: [
            {
              group: ["**/services/**", "**/packages/platform-*"],
              message:
                "Frontera del monorepo (BUILD-001): apps/web no importa código de services/ ni de los paquetes Python (platform-kernel/platform-contracts).",
            },
          ],
        },
      ],
    },
  },
];

export default eslintConfig;
