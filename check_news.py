import os, psycopg2
url = os.environ["DATABASE_URL"].replace("postgresql+psycopg2://","postgresql://")
with psycopg2.connect(url) as c, c.cursor() as cur:
    cur.execute("select count(*) from news_sentiment;")
    n = cur.fetchone()[0]
    cur.execute("select published_at, ticker, left(title,60) from news_sentiment order by published_at desc nulls last limit 5;")
    rows = cur.fetchall()
    print("news_sentiment count =", n)
    for r in rows: print(r)
