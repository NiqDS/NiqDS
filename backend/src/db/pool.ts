import pg from 'pg';
import { loadConfig } from '../config/index.js';

const config = loadConfig();

/** Shared connection pool. Imported wherever a query is needed. */
export const pool = new pg.Pool({
  connectionString: config.DATABASE_URL,
  max: 10,
  idleTimeoutMillis: 30_000,
});

export type Queryable = Pick<pg.Pool, 'query'>;

export async function closePool(): Promise<void> {
  await pool.end();
}
