import { createRemoteJWKSet, jwtVerify, type JWTPayload } from 'jose';
import { loadConfig } from '../config/index.js';
import { unauthorized } from '../util/errors.js';

const config = loadConfig();

/**
 * Apple rotates its signing keys, so we use a cached remote JWKS. `jose` handles
 * refresh + caching internally. Typed as the key resolver `jwtVerify` accepts so
 * tests can inject a local JWKS (`createLocalJWKSet`) instead of hitting Apple.
 */
export type AppleKeySet = Parameters<typeof jwtVerify>[1];

let defaultKeySet: AppleKeySet | null = null;
function appleKeySet(): AppleKeySet {
  if (!defaultKeySet) {
    defaultKeySet = createRemoteJWKSet(new URL(config.APPLE_JWKS_URL));
  }
  return defaultKeySet;
}

export interface AppleIdentity {
  subject: string;
  email: string | null;
  emailVerified: boolean;
}

/**
 * Verify a Sign in with Apple identity token. Checks signature against Apple's
 * JWKS, plus issuer and audience (our bundle ID). Returns the stable user
 * subject and (first-login-only) email.
 */
export async function verifyAppleIdentityToken(
  identityToken: string,
  keySet: AppleKeySet = appleKeySet(),
): Promise<AppleIdentity> {
  let payload: JWTPayload;
  try {
    const result = await jwtVerify(identityToken, keySet, {
      issuer: config.APPLE_ISSUER,
      audience: config.APPLE_CLIENT_ID,
    });
    payload = result.payload;
  } catch {
    throw unauthorized('Invalid Apple identity token', 'apple_token_invalid');
  }

  if (!payload.sub) {
    throw unauthorized('Apple token missing subject', 'apple_token_invalid');
  }

  const email =
    typeof payload.email === 'string' ? payload.email : null;
  // Apple sends email_verified as either boolean or the string "true".
  const rawVerified = (payload as Record<string, unknown>).email_verified;
  const emailVerified = rawVerified === true || rawVerified === 'true';

  return { subject: payload.sub, email, emailVerified };
}
