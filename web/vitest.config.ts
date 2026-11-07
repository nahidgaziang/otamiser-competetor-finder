import { defineConfig } from 'vitest/config';

// End-to-end tests run against the *built* server (npm run build first) and a disposable
// PostgreSQL database whose name ends in "_test". See tests/global-setup.ts.
export default defineConfig({
  test: {
    include: ['tests/**/*.test.ts'],
    globalSetup: ['tests/global-setup.ts'],
    fileParallelism: false,
    testTimeout: 20_000,
    hookTimeout: 60_000,
  },
});
