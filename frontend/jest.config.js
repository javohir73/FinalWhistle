/** Jest config for the Next.js/TypeScript frontend.
 *  Uses ts-jest now; task 1.5 (Next.js scaffold) may switch to next/jest. */
module.exports = {
  preset: "ts-jest",
  testEnvironment: "jsdom",
  testMatch: ["**/*.test.ts", "**/*.test.tsx"],
  setupFilesAfterEnv: ["<rootDir>/jest.setup.ts"],
  moduleNameMapper: {
    "^@/(.*)$": "<rootDir>/$1",
  },
};
