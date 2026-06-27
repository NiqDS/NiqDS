import type { Queryable } from '../db/pool.js';

export interface User {
  id: string;
  appleSubject: string;
  email: string | null;
  displayName: string | null;
  createdAt: Date;
  updatedAt: Date;
}

interface UserRow {
  id: string;
  apple_subject: string;
  email: string | null;
  display_name: string | null;
  created_at: Date;
  updated_at: Date;
}

const toUser = (r: UserRow): User => ({
  id: r.id,
  appleSubject: r.apple_subject,
  email: r.email,
  displayName: r.display_name,
  createdAt: r.created_at,
  updatedAt: r.updated_at,
});

/**
 * Find an existing user by Apple subject or create one. Sign in with Apple only
 * sends email/name on the *first* authorization, so we update them when present
 * but never overwrite a stored value with null.
 */
export async function upsertUserByAppleSubject(
  db: Queryable,
  params: { appleSubject: string; email?: string | null; displayName?: string | null },
): Promise<User> {
  const { rows } = await db.query<UserRow>(
    `
    INSERT INTO users (apple_subject, email, display_name)
    VALUES ($1, $2, $3)
    ON CONFLICT (apple_subject) DO UPDATE
      SET email        = COALESCE(EXCLUDED.email, users.email),
          display_name = COALESCE(EXCLUDED.display_name, users.display_name),
          updated_at   = now()
    RETURNING *;
    `,
    [params.appleSubject, params.email ?? null, params.displayName ?? null],
  );
  // INSERT ... RETURNING always yields exactly one row here.
  return toUser(rows[0]!);
}

export async function findUserById(
  db: Queryable,
  id: string,
): Promise<User | null> {
  const { rows } = await db.query<UserRow>(
    'SELECT * FROM users WHERE id = $1',
    [id],
  );
  return rows[0] ? toUser(rows[0]) : null;
}

export async function deleteUser(db: Queryable, id: string): Promise<void> {
  // ON DELETE CASCADE purges consents, devices, refresh tokens, recordings.
  await db.query('DELETE FROM users WHERE id = $1', [id]);
}
