import type { Queryable } from '../db/pool.js';
import { verifyAppleIdentityToken, type AppleKeySet } from '../auth/apple.js';
import {
  issueAccessToken,
  issueRefreshToken,
  rotateRefreshToken,
} from '../auth/tokens.js';
import { upsertUserByAppleSubject, type User } from '../models/user.js';

export interface AuthResult {
  user: Pick<User, 'id' | 'email' | 'displayName'>;
  accessToken: string;
  refreshToken: string;
}

/**
 * Sign in with Apple: verify the identity token, upsert the user, and issue our
 * own access + refresh tokens. `displayName` is only present on first login
 * (Apple sends the name once, client-side), so it's accepted as a parameter.
 */
export async function signInWithApple(
  db: Queryable,
  params: {
    identityToken: string;
    displayName?: string | null;
  },
  keySet?: AppleKeySet,
): Promise<AuthResult> {
  const identity = await verifyAppleIdentityToken(params.identityToken, keySet);
  const user = await upsertUserByAppleSubject(db, {
    appleSubject: identity.subject,
    email: identity.email,
    displayName: params.displayName ?? null,
  });
  const accessToken = await issueAccessToken(user.id);
  const { token: refreshToken } = await issueRefreshToken(db, user.id);
  return {
    user: { id: user.id, email: user.email, displayName: user.displayName },
    accessToken,
    refreshToken,
  };
}

/** Exchange a valid refresh token for a new access + refresh pair. */
export async function refreshSession(
  db: Queryable,
  rawRefreshToken: string,
): Promise<{ accessToken: string; refreshToken: string }> {
  const { userId, refresh } = await rotateRefreshToken(db, rawRefreshToken);
  const accessToken = await issueAccessToken(userId);
  return { accessToken, refreshToken: refresh.token };
}
