import pino from 'pino';
import { loadConfig } from '../config/index.js';

const config = loadConfig();

export const logger = pino({
  level: config.LOG_LEVEL,
  // Never let tokens or auth headers leak into logs.
  redact: {
    paths: [
      'req.headers.authorization',
      'req.headers.cookie',
      '*.identityToken',
      '*.refreshToken',
      '*.accessToken',
    ],
    censor: '[redacted]',
  },
});
