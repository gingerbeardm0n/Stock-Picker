#!/usr/bin/env python3
"""
Test TimescaleDB connection
"""

import psycopg2
import os
from dotenv import load_dotenv

load_dotenv()

def test_connection():
    """Test database connection and verify setup"""

    # Get connection string from env or use default
    conn_string = os.getenv('TIMESCALE_CONNECTION_STRING',
                            'postgresql://postgres:yourpassword@localhost:5432/stockdata')

    print("=" * 70)
    print("  TimescaleDB Connection Test")
    print("=" * 70)
    print(f"\nConnection string: {conn_string.replace(conn_string.split('@')[0].split('//')[1].split(':')[1], '***')}")

    try:
        # Connect
        print("\n[1/5] Connecting to database...")
        conn = psycopg2.connect(conn_string)
        cursor = conn.cursor()
        print("      [OK] Connected successfully!")

        # Check PostgreSQL version
        print("\n[2/5] Checking PostgreSQL version...")
        cursor.execute("SELECT version();")
        version = cursor.fetchone()[0]
        print(f"      {version[:50]}...")

        # Check TimescaleDB extension
        print("\n[3/5] Checking TimescaleDB extension...")
        cursor.execute("SELECT extname, extversion FROM pg_extension WHERE extname = 'timescaledb';")
        result = cursor.fetchone()
        if result:
            print(f"      [OK] TimescaleDB version: {result[1]}")
        else:
            print("      [ERROR] TimescaleDB extension not found!")
            return False

        # List tables
        print("\n[4/5] Checking tables...")
        cursor.execute("""
            SELECT tablename
            FROM pg_tables
            WHERE schemaname = 'public'
            ORDER BY tablename;
        """)
        tables = cursor.fetchall()
        if tables:
            print(f"      [OK] Found {len(tables)} tables:")
            for table in tables:
                print(f"         - {table[0]}")
        else:
            print("      [WARNING] No tables found. Run schema.sql to create tables.")

        # Check hypertables
        print("\n[5/5] Checking hypertables...")
        cursor.execute("""
            SELECT hypertable_name, num_chunks
            FROM timescaledb_information.hypertables;
        """)
        hypertables = cursor.fetchall()
        if hypertables:
            print(f"      [OK] Found {len(hypertables)} hypertables:")
            for ht in hypertables:
                print(f"         - {ht[0]}: {ht[1]} chunks")
        else:
            print("      [WARNING] No hypertables found. Run schema.sql to create hypertables.")

        # Test insert (if tables exist)
        if tables:
            print("\n[BONUS] Testing insert capability...")
            try:
                cursor.execute("""
                    INSERT INTO stock_metadata (symbol, name, exchange, asset_class, status, tradable)
                    VALUES ('TEST', 'Test Stock', 'NASDAQ', 'us_equity', 'active', true)
                    ON CONFLICT (symbol) DO NOTHING;
                """)
                conn.commit()

                cursor.execute("SELECT * FROM stock_metadata WHERE symbol = 'TEST';")
                test_row = cursor.fetchone()
                if test_row:
                    print("        [OK] Insert/query working correctly!")
                    # Clean up
                    cursor.execute("DELETE FROM stock_metadata WHERE symbol = 'TEST';")
                    conn.commit()
            except Exception as e:
                print(f"        [WARNING] Insert test failed: {e}")

        # Close
        cursor.close()
        conn.close()

        print("\n" + "=" * 70)
        print("  [SUCCESS] Database is ready to use!")
        print("=" * 70)
        print("\nNext steps:")
        print("  1. Run 'python database/collect_data.py' to start collecting live data")
        print("  2. Run 'python database/backfill_historical.py' to add historical data")
        print("  3. Update your scanner to query the database instead of APIs\n")

        return True

    except psycopg2.OperationalError as e:
        print(f"\n[ERROR] Could not connect to database:")
        print(f"        {e}")
        print("\nTroubleshooting:")
        print("  - Is PostgreSQL/Docker running?")
        print("  - Is the password correct in your .env file?")
        print("  - Is port 5432 accessible?")
        print("  - Try: docker ps  (to see if container is running)")
        return False

    except Exception as e:
        print(f"\n[ERROR] Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_connection()
    exit(0 if success else 1)
