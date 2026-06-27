/**
 * Test environment defaults. Real secrets are never needed for unit tests; these
 * placeholders satisfy the zod config schema so modules can import `loadConfig`.
 * Runs before any test module is imported (vitest setupFiles).
 */
process.env.NODE_ENV ??= 'test';
process.env.DATABASE_URL ??= 'postgres://safeword:safeword@localhost:5432/safeword';
process.env.JWT_ACCESS_SECRET ??= 'test-access-secret-please-change-0123456789';
process.env.JWT_REFRESH_SECRET ??= 'test-refresh-secret-please-change-0123456789';
process.env.APPLE_CLIENT_ID ??= 'com.example.safeword';
