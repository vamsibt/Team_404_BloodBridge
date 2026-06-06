# test_db.py

import psycopg2

try:
    conn = psycopg2.connect(
        host="localhost",
        port=5433,
        user="postgres",
        password="password",
        database="postgres"
    )

    print("SUCCESS")
    conn.close()

except Exception as e:
    print("FAILED")
    print(e)