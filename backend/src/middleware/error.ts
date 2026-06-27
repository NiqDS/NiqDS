import type { ErrorRequestHandler, RequestHandler } from 'express';
import { ZodError } from 'zod';
import { HttpError } from '../util/errors.js';
import { logger } from '../util/logger.js';

export const notFoundHandler: RequestHandler = (_req, res) => {
  res.status(404).json({ error: { code: 'not_found', message: 'Not found' } });
};

// eslint-disable-next-line @typescript-eslint/no-unused-vars
export const errorHandler: ErrorRequestHandler = (err, _req, res, _next) => {
  if (err instanceof HttpError) {
    res
      .status(err.status)
      .json({ error: { code: err.code, message: err.message } });
    return;
  }
  if (err instanceof ZodError) {
    res.status(400).json({
      error: {
        code: 'validation_error',
        message: 'Request validation failed',
        details: err.issues.map((i) => ({
          path: i.path.join('.'),
          message: i.message,
        })),
      },
    });
    return;
  }
  logger.error({ err }, 'Unhandled error');
  res
    .status(500)
    .json({ error: { code: 'internal_error', message: 'Internal server error' } });
};
