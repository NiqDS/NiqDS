import type { Queryable } from '../db/pool.js';

export interface ConsentRecord {
  id: string;
  userId: string;
  version: string;
  acknowledged: Record<string, boolean>;
  acceptedAt: Date;
}

interface ConsentRow {
  id: string;
  user_id: string;
  version: string;
  acknowledged: Record<string, boolean>;
  accepted_at: Date;
}

const toConsent = (r: ConsentRow): ConsentRecord => ({
  id: r.id,
  userId: r.user_id,
  version: r.version,
  acknowledged: r.acknowledged,
  acceptedAt: r.accepted_at,
});

/** Record consent for a version. Idempotent per (user, version). */
export async function recordConsent(
  db: Queryable,
  params: {
    userId: string;
    version: string;
    acknowledged: Record<string, boolean>;
  },
): Promise<ConsentRecord> {
  const { rows } = await db.query<ConsentRow>(
    `
    INSERT INTO consents (user_id, version, acknowledged)
    VALUES ($1, $2, $3)
    ON CONFLICT (user_id, version) DO UPDATE
      SET acknowledged = EXCLUDED.acknowledged
    RETURNING *;
    `,
    [params.userId, params.version, JSON.stringify(params.acknowledged)],
  );
  return toConsent(rows[0]!);
}

export async function getLatestConsent(
  db: Queryable,
  userId: string,
): Promise<ConsentRecord | null> {
  const { rows } = await db.query<ConsentRow>(
    `SELECT * FROM consents WHERE user_id = $1 ORDER BY accepted_at DESC LIMIT 1`,
    [userId],
  );
  return rows[0] ? toConsent(rows[0]) : null;
}
