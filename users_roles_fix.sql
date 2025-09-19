UPDATE users SET roles = '[]'::jsonb
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
