import os, sys, psycopg2

def get_db_url():
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("[ERROR] DATABASE_URL is not set", file=sys.stderr); sys.exit(1)
    # psycopg2 は postgresql:// を期待。SQLAlchemy形式なら置換
    if url.startswith("postgresql+psycopg2://"):
        url = url.replace("postgresql+psycopg2://", "postgresql://", 1)
    return url

NORMALIZE_SQL = r"""
UPDATE users
   SET roles = '[]'::jsonb
 WHERE roles IS NULL OR jsonb_typeof(roles::jsonb) <> 'array';

ALTER TABLE users
  ALTER COLUMN roles TYPE jsonb USING
    CASE
      WHEN roles IS NULL THEN '[]'::jsonb
      WHEN jsonb_typeof(roles::jsonb) = 'array' THEN roles::jsonb
      ELSE '[]'::jsonb
    END,
  ALTER COLUMN roles SET DEFAULT '[]'::jsonb,
  ALTER COLUMN roles SET NOT NULL;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'users_roles_is_array'
  ) THEN
    ALTER TABLE users
      ADD CONSTRAINT users_roles_is_array
        CHECK (jsonb_typeof(roles) = 'array');
  END IF;
END$$;
"""

CHECKS = [
    ("column_meta",
     """SELECT data_type, column_default, is_nullable
          FROM information_schema.columns
         WHERE table_schema='public' AND table_name='users' AND column_name='roles';"""),
    ("constraint",
     """SELECT conname, pg_get_constraintdef(c.oid)
          FROM pg_constraint c
          JOIN pg_class t ON c.conrelid=t.oid
          JOIN pg_namespace n ON t.relnamespace=n.oid
         WHERE t.relname='users' AND n.nspname='public'
           AND conname='users_roles_is_array';"""),
    ("bad_rows",
     """SELECT count(*) AS not_array_or_null
          FROM users
         WHERE roles IS NULL OR jsonb_typeof(roles) <> 'array';"""),
    ("sample",
     """SELECT email, roles::text FROM users LIMIT 5;"""),
]

def main():
    url = get_db_url()
    conn = psycopg2.connect(url)  # sslmode等はURLに含まれている
    conn.autocommit = True
    cur = conn.cursor()
    try:
        # 正規化を1回で流す（idempotent）
        cur.execute(NORMALIZE_SQL)
        print("[OK] normalization applied")

        # チェックを実行
        for name, q in CHECKS:
            cur.execute(q)
            rows = cur.fetchall()
            print(f"\n--- {name} ---")
            for r in rows:
                print("| ".join(str(x) for x in r))
    except psycopg2.Error as e:
        print("[DB-ERROR]", e, file=sys.stderr); sys.exit(2)
    finally:
        cur.close(); conn.close()

if __name__ == "__main__":
    main()
