# test_neon.py
import os, sys, urllib.parse as u
import psycopg2

url = os.environ.get("TEST_DB_URL", "")
if not url:
    print("TEST_DB_URL not set"); sys.exit(2)

# psycopg2 は "postgresql://" 形式を想定（SQLAlchemyの "+psycopg2" は不要）
url = url.replace("postgresql+psycopg2://", "postgresql://", 1)

print("TRY:", url.split("@")[1].split("?")[0])  # host:port/db だけ表示（PWは出さない）

try:
    conn = psycopg2.connect(url)  # sslmode=require をURLに含めてOK
    with conn.cursor() as cur:
        cur.execute("select current_database(), current_user")
        print("OK:", cur.fetchone())
    conn.close()
    sys.exit(0)
except Exception as e:
    print("NG:", type(e).__name__, e)
    sys.exit(1)