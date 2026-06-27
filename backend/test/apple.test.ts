import { describe, it, expect } from 'vitest';
import {
  SignJWT,
  exportJWK,
  generateKeyPair,
  createLocalJWKSet,
} from 'jose';
import { verifyAppleIdentityToken, type AppleKeySet } from '../src/auth/apple.js';

// Build a local JWKS that stands in for Apple's, so the test never hits the
// network. We sign tokens with our own key and verify against its public JWK.
async function makeAppleStub() {
  const { publicKey, privateKey } = await generateKeyPair('RS256');
  const jwk = await exportJWK(publicKey);
  jwk.kid = 'test-key';
  jwk.alg = 'RS256';
  jwk.use = 'sig';
  const keySet = createLocalJWKSet({ keys: [jwk] }) as AppleKeySet;

  async function signIdentityToken(claims: Record<string, unknown>) {
    return new SignJWT(claims)
      .setProtectedHeader({ alg: 'RS256', kid: 'test-key' })
      .setIssuer('https://appleid.apple.com')
      .setAudience('com.example.safeword')
      .setIssuedAt()
      .setExpirationTime('5m')
      .sign(privateKey);
  }

  return { keySet, signIdentityToken };
}

describe('verifyAppleIdentityToken', () => {
  it('accepts a valid token and extracts subject + email', async () => {
    const { keySet, signIdentityToken } = await makeAppleStub();
    const token = await signIdentityToken({
      sub: 'apple-sub-001',
      email: 'relay@privaterelay.appleid.com',
      email_verified: 'true',
    });
    const identity = await verifyAppleIdentityToken(token, keySet);
    expect(identity.subject).toBe('apple-sub-001');
    expect(identity.email).toBe('relay@privaterelay.appleid.com');
    expect(identity.emailVerified).toBe(true);
  });

  it('rejects a token with the wrong audience', async () => {
    const { keySet } = await makeAppleStub();
    const { privateKey } = await generateKeyPair('RS256');
    const badToken = await new SignJWT({ sub: 'x' })
      .setProtectedHeader({ alg: 'RS256', kid: 'test-key' })
      .setIssuer('https://appleid.apple.com')
      .setAudience('com.someone.else')
      .setIssuedAt()
      .setExpirationTime('5m')
      .sign(privateKey);
    await expect(verifyAppleIdentityToken(badToken, keySet)).rejects.toThrow();
  });

  it('rejects a token signed by an unknown key', async () => {
    const { keySet } = await makeAppleStub();
    const { privateKey } = await generateKeyPair('RS256'); // not in the JWKS
    const forged = await new SignJWT({ sub: 'x' })
      .setProtectedHeader({ alg: 'RS256', kid: 'other-key' })
      .setIssuer('https://appleid.apple.com')
      .setAudience('com.example.safeword')
      .setIssuedAt()
      .setExpirationTime('5m')
      .sign(privateKey);
    await expect(verifyAppleIdentityToken(forged, keySet)).rejects.toThrow();
  });
});
