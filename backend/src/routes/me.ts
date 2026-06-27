import { Router, type RequestHandler } from 'express';
import { z } from 'zod';
import { pool } from '../db/pool.js';
import { requireAuth } from '../middleware/auth.js';
import { findUserById, deleteUser } from '../models/user.js';
import { recordConsent, getLatestConsent } from '../models/consent.js';
import { revokeAllRefreshTokens } from '../auth/tokens.js';
import { notFound } from '../util/errors.js';

export const meRouter = Router();
meRouter.use(requireAuth);

const getMe: RequestHandler = async (req, res, next) => {
  try {
    const user = await findUserById(pool, req.userId!);
    if (!user) throw notFound('User not found', 'user_not_found');
    const consent = await getLatestConsent(pool, user.id);
    res.json({
      id: user.id,
      email: user.email,
      displayName: user.displayName,
      consent: consent
        ? { version: consent.version, acceptedAt: consent.acceptedAt }
        : null,
    });
  } catch (err) {
    next(err);
  }
};

const ConsentSchema = z.object({
  version: z.string().min(1),
  acknowledged: z.record(z.boolean()),
});

const postConsent: RequestHandler = async (req, res, next) => {
  try {
    const body = ConsentSchema.parse(req.body);
    const record = await recordConsent(pool, {
      userId: req.userId!,
      version: body.version,
      acknowledged: body.acknowledged,
    });
    res
      .status(201)
      .json({ version: record.version, acceptedAt: record.acceptedAt });
  } catch (err) {
    next(err);
  }
};

// Full account deletion — App Store requirement. ON DELETE CASCADE purges all
// owned rows; tokens are revoked first so any in-flight session dies immediately.
const deleteMe: RequestHandler = async (req, res, next) => {
  try {
    await revokeAllRefreshTokens(pool, req.userId!);
    await deleteUser(pool, req.userId!);
    res.status(204).send();
  } catch (err) {
    next(err);
  }
};

meRouter.get('/', getMe);
meRouter.post('/consent', postConsent);
meRouter.delete('/', deleteMe);
