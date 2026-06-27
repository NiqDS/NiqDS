import { z } from 'zod';

/**
 * Environment is validated once at boot. If a required secret is missing the
 * process refuses to start — we never run with a half-configured auth layer.
 */
const EnvSchema = z.object({
  NODE_ENV: z
    .enum(['development', 'test', 'production'])
    .default('development'),
  PORT: z.coerce.number().int().positive().default(8080),
  LOG_LEVEL: z
    .enum(['fatal', 'error', 'warn', 'info', 'debug', 'trace'])
    .default('info'),

  DATABASE_URL: z.string().url(),
  REDIS_URL: z.string().url().optional(),

  JWT_ACCESS_SECRET: z.string().min(32),
  JWT_REFRESH_SECRET: z.string().min(32),
  JWT_ACCESS_TTL_SECONDS: z.coerce.number().int().positive().default(900),
  JWT_REFRESH_TTL_SECONDS: z.coerce
    .number()
    .int()
    .positive()
    .default(2_592_000),

  APPLE_CLIENT_ID: z.string().min(1),
  APPLE_ISSUER: z.string().url().default('https://appleid.apple.com'),
  APPLE_JWKS_URL: z
    .string()
    .url()
    .default('https://appleid.apple.com/auth/keys'),

  DEFAULT_RECORDING_SECONDS: z.coerce.number().int().positive().default(300),
  DEFAULT_RETENTION_DAYS: z.coerce.number().int().positive().default(30),
});

export type AppConfig = z.infer<typeof EnvSchema>;

let cached: AppConfig | null = null;

export function loadConfig(env: NodeJS.ProcessEnv = process.env): AppConfig {
  if (cached) return cached;
  const parsed = EnvSchema.safeParse(env);
  if (!parsed.success) {
    const issues = parsed.error.issues
      .map((i) => `  - ${i.path.join('.') || '(root)'}: ${i.message}`)
      .join('\n');
    throw new Error(`Invalid environment configuration:\n${issues}`);
  }
  cached = parsed.data;
  return cached;
}

/** Test helper — forget the cached config so a new env can be loaded. */
export function resetConfigForTests(): void {
  cached = null;
}
