import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    environment: 'node',
    globals: true,
    setupFiles: ['./test/setup.ts'],
    // Integration tests opt in via DATABASE_URL; unit tests need no services.
    include: ['test/**/*.test.ts'],
  },
});
