import { Router, type RequestHandler } from 'express';
import { z } from 'zod';
import { pool } from '../db/pool.js';
import { signInWithApple, refreshSession } from '../services/authService.js';

export const authRouter = Router();

const SignInSchema = z.object({
  identityToken: z.string().min(1),
  // Apple provides the name only on first authorization; client forwards it.
  displayName: z.string().trim().min(1).max(100).nullish(),
});

const signIn: RequestHandler = async (req, res, next) => {
  try {
    const body = SignInSchema.parse(req.body);
    const result = await signInWithApple(pool, {
      identityToken: body.identityToken,
      displayName: body.displayName ?? null,
    });
    res.status(200).json(result);
  } catch (err) {
    next(err);
  }
};

const RefreshSchema = z.object({ refreshToken: z.string().min(1) });

const refresh: RequestHandler = async (req, res, next) => {
  try {
    const body = RefreshSchema.parse(req.body);
    const tokens = await refreshSession(pool, body.refreshToken);
    res.status(200).json(tokens);
  } catch (err) {
    next(err);
  }
};

authRouter.post('/apple', signIn);
authRouter.post('/refresh', refresh);
