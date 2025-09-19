import os, psycopg2
url = os.environ["DATABASE_URL"].replace("postgresql+psycopg2://","postgresql://")
with psycopg2.connect(url) as c, c.cursor() as cur:
    for key in ("CPI","CPI_YoY","US10Y_Yield","US2Y_Yield","YieldCurve_10Y_minus_2Y",
                "VIX_Close","DXY_Close","USD_Index_Return","Gold_Return","Copper_Return","NatGas_Return"):
        cur.execute("select count(*) from macro_features where name=%s;", (key,))
        n = cur.fetchone()[0]
        cur.execute("""select name, asof_date, value
                       from macro_features where name=%s
                       order by asof_date desc limit 3;""", (key,))
        rows = cur.fetchall()
        print(f"\n[{key}] count={n}")
        for r in rows: print(r)
