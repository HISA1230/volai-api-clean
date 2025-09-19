# check_macro2.py (差し替え)
import os, re, psycopg2, urllib.parse as up

raw = os.environ.get("DATABASE_URL","")
print("RAW (masked):", re.sub(r"://([^:]+):([^@]+)@", r"://\\1:***@", raw))

# psycopg2 が理解できるスキームに置換
url = raw.replace("postgresql+psycopg2://","postgresql://")

parts = up.urlsplit(url)
user = up.unquote(parts.username or "")
pwd  = up.unquote(parts.password or "")
host = parts.hostname
port = parts.port or 5432
db   = (parts.path or "").lstrip("/")
qs   = dict(up.parse_qsl(parts.query or ""))

print(f"user={user}, host={host}, db={db}, port={port}, sslmode={qs.get('sslmode')}")
print(f"password_length={len(pwd)} (was_encoded={parts.password != pwd})")

try:
    conn = psycopg2.connect(
        host=host, port=port, dbname=db,
        user=user, password=pwd,
        sslmode=qs.get('sslmode','require')
    )
    with conn, conn.cursor() as cur:
        cur.execute("select current_user, version();")
        print("OK:", cur.fetchone())
except Exception as e:
    print("CONNECT FAILED:", repr(e))
    raise