import os, psycopg2
url = os.environ["DATABASE_URL"].replace("postgresql+psycopg2://","postgresql://")
with psycopg2.connect(url) as c, c.cursor() as cur:
    cur.execute("select current_user, current_database(), now();")
    print(cur.fetchone())
