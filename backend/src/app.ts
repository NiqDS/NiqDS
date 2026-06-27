import express, { type Express } from 'express';
import helmet from 'helmet';
import { authRouter } from './routes/auth.js';
import { meRouter } from './routes/me.js';
import { errorHandler, notFoundHandler } from './middleware/error.js';

/**
 * Builds the Express app without binding a port, so tests can drive it directly
 * (e.g. with supertest / fetch against an in-process server).
 */
export function createApp(): Express {
  const app = express();

  app.use(helmet());
  app.use(express.json({ limit: '1mb' }));

  app.get('/health', (_req, res) => {
    res.json({ status: 'ok', service: 'safeword-backend' });
  });

  app.use('/v1/auth', authRouter);
  app.use('/v1/me', meRouter);

  app.use(notFoundHandler);
  app.use(errorHandler);

  return app;
}
