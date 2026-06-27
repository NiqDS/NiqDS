import { createHash, randomBytes } from 'node:crypto';
import { SignJWT, jwtVerify } from 'jose';
import { loadConfig } from '../config/index.js';
import type { Queryable } from '../db/pool.js';
import { unauthorized } from '../util/errors.js';

const config = loadConfig();
const accessKey = new TextEncoder().encode(config.JWT_ACCESS_SECRET);
const ISSUER = 'safeword-backend';
const AUDIENCE = 'safeword-app';

export interface AccessTokenClaims {
  sub: string; // user id
}

/** Issue a short-lived access JWT for a user id. */
export async function issueAccessToken(userId: string): Promise<string> {
  return new SignJWT({})
    .setProtectedHeader({ alg: 'HS256' })
    .setSubject(userId)
    .setIssuer(ISSUER)
    .setAudience(AUDIENCE)
    .setIssuedAt()
    .setExpirationTime(`${config.JWT_ACCESS_TTL_SECONDS}s`)
    .sign(accessKey);
}

export async function verifyAccessToken(
  token: string,
): Promise<AccessTokenClaims> {
  try {
    const { payload } = await jwtVerify(token, accessKey, {
      issuer: ISSUER,
      audience: AUDIENCE,
    });
    if (!payload.sub) throw new Error('no sub');
    return { sub: payload.sub };
  } catch {
    throw unauthorized('Invalid or expired access token', 'access_token_invalid');
  }
}

const hashToken = (raw: string) =>
  createHash('sha256').update(raw).digest('hex');

export interface IssuedRefreshToken {
  token: string; // raw value returned to the client ONCE
  expiresAt: Date;
}

/**
 * Mint a refresh token, store only its hash, and return the raw value to the
 * caller. The raw token is never persisted.
 */
export async function issueRefreshToken(
  db: Queryable,
  userId: string,
): Promise<IssuedRefreshToken> {
  const raw = randomBytes(48).toString('base64url');
  const expiresAt = new Date(
    Date.now() + config.JWT_REFRESH_TTL_SECONDS * 1000,
  );
  await db.query(
    `INSERT INTO refresh_tokens (user_id, token_hash, expires_at)
     VALUES ($1, $2, $3)`,
    [userId, hashToken(raw), expiresAt],
  );
  return { token: raw, expiresAt };
}

/**
 * Rotate a refresh token: validate it is live, revoke it, and issue a fresh
 * one. Returns the owning user id plus the new refresh token. Throws if the
 * token is unknown, expired, or already revoked (possible reuse/theft).
 */
export async function rotateRefreshToken(
  db: Queryable,
  rawToken: string,
): Promise<{ userId: string; refresh: IssuedRefreshToken }> {
  const hash = hashToken(rawToken);
  const { rows } = await db.query<{
    id: string;
    user_id: string;
    expires_at: Date;
    revoked_at: Date | null;
  }>(
    `SELECT id, user_id, expires_at, revoked_at
       FROM refresh_tokens WHERE token_hash = $1`,
    [hash],
  );
  const row = rows[0];
  if (!row || row.revoked_at || row.expires_at.getTime() < Date.now()) {
    throw unauthorized('Refresh token is not valid', 'refresh_token_invalid');
  }
  await db.query(
    `UPDATE refresh_tokens SET revoked_at = now() WHERE id = $1`,
    [row.id],
  );
  const refresh = await issueRefreshToken(db, row.user_id);
  return { userId: row.user_id, refresh };
}

/** Revoke every refresh token for a user (logout-all / account deletion). */
export async function revokeAllRefreshTokens(
  db: Queryable,
  userId: string,
): Promise<void> {
  await db.query(
    `UPDATE refresh_tokens SET revoked_at = now()
       WHERE user_id = $1 AND revoked_at IS NULL`,
    [userId],
  );
}
