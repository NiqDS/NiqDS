import { describe, it, expect, beforeAll, afterAll } from 'vitest';
import {
  SignJWT,
  exportJWK,
  generateKeyPair,
  createLocalJWKSet,
  type KeyLike,
} from 'jose';
import { pool, closePool } from '../src/db/pool.js';
import { signInWithApple, refreshSession } from '../src/services/authService.js';
import { findUserById, deleteUser } from '../src/models/user.js';
import { recordConsent, getLatestConsent } from '../src/models/consent.js';
import { verifyAccessToken } from '../src/auth/tokens.js';
import type { AppleKeySet } from '../src/auth/apple.js';

// Opt-in: set RUN_DB_TESTS=1 with a reachable Postgres (CI provides one). The
// suite is otherwise skipped so `npm test` works with no services running.
const runDb = process.env.RUN_DB_TESTS === '1';

describe.skipIf(!runDb)('auth flow (integration)', () => {
  let keySet: AppleKeySet;
  let privateKey: KeyLike;
  const subject = `apple-sub-${Date.now()}`;

  async function appleToken(claims: Record<string, unknown>) {
    return new SignJWT(claims)
      .setProtectedHeader({ alg: 'RS256', kid: 'test-key' })
      .setIssuer('https://appleid.apple.com')
      .setAudience('com.example.safeword')
      .setIssuedAt()
      .setExpirationTime('5m')
      .sign(privateKey);
  }

  beforeAll(async () => {
    const kp = await generateKeyPair('RS256');
    privateKey = kp.privateKey;
    const jwk = await exportJWK(kp.publicKey);
    jwk.kid = 'test-key';
    jwk.alg = 'RS256';
    keySet = createLocalJWKSet({ keys: [jwk] }) as AppleKeySet;
  });

  afterAll(async () => {
    await closePool();
  });

  it('signs in, refreshes, records consent, and deletes the account', async () => {
    const token = await appleToken({ sub: subject, email: 'a@b.com' });

    // First sign-in creates the user and issues tokens.
    const result = await signInWithApple(
      pool,
      { identityToken: token, displayName: 'Test User' },
      keySet,
    );
    expect(result.user.email).toBe('a@b.com');
    const claims = await verifyAccessToken(result.accessToken);
    expect(claims.sub).toBe(result.user.id);

    // Refresh rotates to a new pair.
    const refreshed = await refreshSession(pool, result.refreshToken);
    expect(refreshed.accessToken).not.toBe(result.accessToken);
    // The old refresh token is now revoked and cannot be reused.
    await expect(refreshSession(pool, result.refreshToken)).rejects.toThrow();

    // Consent is recorded and read back.
    await recordConsent(pool, {
      userId: result.user.id,
      version: '1.0.0',
      acknowledged: { lawfulUse: true, ownership: true },
    });
    const consent = await getLatestConsent(pool, result.user.id);
    expect(consent?.version).toBe('1.0.0');

    // Second sign-in with the same Apple subject returns the same user.
    const again = await signInWithApple(pool, { identityToken: token }, keySet);
    expect(again.user.id).toBe(result.user.id);

    // Account deletion purges the user (cascade removes consents/tokens).
    await deleteUser(pool, result.user.id);
    expect(await findUserById(pool, result.user.id)).toBeNull();
  });
});
