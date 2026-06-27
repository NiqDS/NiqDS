import { createApp } from './app.js';
import { loadConfig } from './config/index.js';
import { logger } from './util/logger.js';
import { closePool } from './db/pool.js';

const config = loadConfig();
const app = createApp();

const server = app.listen(config.PORT, () => {
  logger.info(`SafeWord backend listening on :${config.PORT}`);
});

async function shutdown(signal: string): Promise<void> {
  logger.info({ signal }, 'Shutting down');
  server.close(() => {
    void closePool().finally(() => process.exit(0));
  });
}

process.on('SIGINT', () => void shutdown('SIGINT'));
process.on('SIGTERM', () => void shutdown('SIGTERM'));
