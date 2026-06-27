import { readFile, readdir } from 'node:fs/promises';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { pool, closePool } from './pool.js';

/**
 * Minimal forward-only migration runner. Applies every *.sql file in
 * ./migrations in lexical order exactly once, tracked in schema_migrations.
 * Kept deliberately dependency-free for reviewability.
 */
const migrationsDir = join(dirname(fileURLToPath(import.meta.url)), 'migrations');

async function run(): Promise<void> {
  await pool.query(`
    CREATE TABLE IF NOT EXISTS schema_migrations (
      name TEXT PRIMARY KEY,
      applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
  `);

  const files = (await readdir(migrationsDir))
    .filter((f) => f.endsWith('.sql'))
    .sort();

  for (const file of files) {
    const already = await pool.query(
      'SELECT 1 FROM schema_migrations WHERE name = $1',
      [file],
    );
    if (already.rowCount && already.rowCount > 0) {
      // eslint-disable-next-line no-console
      console.log(`= skip ${file} (already applied)`);
      continue;
    }
    const sql = await readFile(join(migrationsDir, file), 'utf8');
    const client = await pool.connect();
    try {
      await client.query('BEGIN');
      await client.query(sql);
      await client.query(
        'INSERT INTO schema_migrations(name) VALUES ($1)',
        [file],
      );
      await client.query('COMMIT');
      // eslint-disable-next-line no-console
      console.log(`+ applied ${file}`);
    } catch (err) {
      await client.query('ROLLBACK');
      throw err;
    } finally {
      client.release();
    }
  }
}

run()
  .then(() => closePool())
  .then(() => process.exit(0))
  .catch((err) => {
    // eslint-disable-next-line no-console
    console.error('Migration failed:', err);
    process.exit(1);
  });
