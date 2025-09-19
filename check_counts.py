# check_counts.py
import re, sys, psycopg2
sys.path.append("scripts")
from common_db import get_db_url

def mask(u: str) -> str:
    return re.sub(r"://([^:]+):([^@]+)@", r"://\1:***@", u or "")

def main():
    url = get_db_url()  # ここで +psycopg2 を正規化済み
    print("DB URL (masked):", mask(url))

    keys = [
        "CPI","CPI_YoY",
        "PPI","PPI_YoY",
        "CorePCE","CorePCE_YoY",
        "GDP","GDP_YoY",
        "UnemploymentRate","FederalFundsRate",
        "US10Y_Yield","US2Y_Yield","YieldCurve_10Y_minus_2Y",
        "VIX_Close","DXY_Close","USD_Index_Return",
        "Gold_Close","Gold_Return","Copper_Close","Copper_Return",
        "NatGas_Close","NatGas_Return",
        "SP500_Close","SP500_Return",
    ]

    with psycopg2.connect(url) as c, c.cursor() as cur:
        cur.execute("select current_user")
        print("current_user:", cur.fetchone()[0])
        for k in keys:
            cur.execute("select count(*) from macro_features where name=%s;", (k,))
            n = cur.fetchone()[0]
            cur.execute(
                """select asof_date, value
                   from macro_features
                   where name=%s
                   order by asof_date desc limit 3;""",
                (k,),
            )
            rows = cur.fetchall()
            print(f"[{k}] count={n} last3={rows}")

if __name__ == "__main__":
    main()