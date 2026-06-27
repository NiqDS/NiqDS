import { describe, it, expect } from 'vitest';
import { issueAccessToken, verifyAccessToken } from '../src/auth/tokens.js';

describe('access tokens', () => {
  it('round-trips a user id', async () => {
    const token = await issueAccessToken('user-123');
    const claims = await verifyAccessToken(token);
    expect(claims.sub).toBe('user-123');
  });

  it('rejects a garbage token', async () => {
    await expect(verifyAccessToken('not-a-jwt')).rejects.toThrow();
  });

  it('rejects a token signed with the wrong secret', async () => {
    // Tamper: flip a character in the signature segment.
    const token = await issueAccessToken('user-123');
    const parts = token.split('.');
    parts[2] = parts[2]!.slice(0, -1) + (parts[2]!.endsWith('A') ? 'B' : 'A');
    await expect(verifyAccessToken(parts.join('.'))).rejects.toThrow();
  });
});
