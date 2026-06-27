import type { RequestHandler } from 'express';
import { verifyAccessToken } from '../auth/tokens.js';
import { unauthorized } from '../util/errors.js';

declare global {
  // eslint-disable-next-line @typescript-eslint/no-namespace
  namespace Express {
    interface Request {
      userId?: string;
    }
  }
}

/** Require a valid Bearer access token; attaches `req.userId`. */
export const requireAuth: RequestHandler = (req, _res, next) => {
  const header = req.header('authorization');
  if (!header?.startsWith('Bearer ')) {
    return next(unauthorized('Missing bearer token', 'missing_token'));
  }
  const token = header.slice('Bearer '.length).trim();
  verifyAccessToken(token)
    .then((claims) => {
      req.userId = claims.sub;
      next();
    })
    .catch(next);
};
