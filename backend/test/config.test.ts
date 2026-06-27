import { describe, it, expect } from 'vitest';
import { loadConfig, resetConfigForTests } from '../src/config/index.js';

describe('config', () => {
  it('parses a valid environment', () => {
    resetConfigForTests();
    const cfg = loadConfig({
      DATABASE_URL: 'postgres://u:p@localhost:5432/db',
      JWT_ACCESS_SECRET: 'x'.repeat(32),
      JWT_REFRESH_SECRET: 'y'.repeat(32),
      APPLE_CLIENT_ID: 'com.example.safeword',
    } as NodeJS.ProcessEnv);
    expect(cfg.PORT).toBe(8080);
    expect(cfg.DEFAULT_RECORDING_SECONDS).toBe(300);
    expect(cfg.DEFAULT_RETENTION_DAYS).toBe(30);
    resetConfigForTests();
  });

  it('rejects a config missing required secrets', () => {
    resetConfigForTests();
    expect(() =>
      loadConfig({
        DATABASE_URL: 'postgres://u:p@localhost:5432/db',
        // no JWT secrets, no APPLE_CLIENT_ID
      } as NodeJS.ProcessEnv),
    ).toThrow(/Invalid environment configuration/);
    resetConfigForTests();
  });

  it('rejects a too-short JWT secret', () => {
    resetConfigForTests();
    expect(() =>
      loadConfig({
        DATABASE_URL: 'postgres://u:p@localhost:5432/db',
        JWT_ACCESS_SECRET: 'short',
        JWT_REFRESH_SECRET: 'y'.repeat(32),
        APPLE_CLIENT_ID: 'com.example.safeword',
      } as NodeJS.ProcessEnv),
    ).toThrow();
    resetConfigForTests();
  });
});
