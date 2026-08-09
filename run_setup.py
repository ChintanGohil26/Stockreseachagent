import os
import sys
from lakebase import init_db, get_connection, USE_POSTGRES
from dotenv import load_dotenv

# Ensure root is on path
sys.path.append(os.path.abspath(os.path.dirname(__file__)))

# Load env variables
load_dotenv()

def seed_data():
    """
    Seeds initial company descriptions, watchlist items, and default user records
    to make the app immediately testable.
    """
    print("Seeding initial records into database...")
    
    with get_connection() as conn:
        cursor = conn.cursor()
        
        # 1. Create default user
        if USE_POSTGRES:
            cursor.execute("""
                INSERT INTO users (id, username, email) 
                VALUES (1, 'default_user', 'user@dataexpert.io')
                ON CONFLICT (id) DO NOTHING;
            """)
        else:
            cursor.execute("""
                INSERT INTO users (id, username, email) 
                VALUES (1, 'default_user', 'user@dataexpert.io')
                ON CONFLICT(id) DO NOTHING;
            """)
            
        # 2. Create default watchlist
        if USE_POSTGRES:
            cursor.execute("""
                INSERT INTO watchlists (id, user_id, name)
                VALUES (1, 1, 'Default')
                ON CONFLICT (id) DO NOTHING;
            """)
        else:
            cursor.execute("""
                INSERT INTO watchlists (id, user_id, name)
                VALUES (1, 1, 'Default')
                ON CONFLICT(id) DO NOTHING;
            """)

        # 3. Seed default watchlist tickers
        default_tickers = [("AAPL", "Core Tech Core"), ("MSFT", "Enterprise AI"), ("GOOGL", "Search Dominance")]
        for ticker, note in default_tickers:
            if USE_POSTGRES:
                cursor.execute("""
                    INSERT INTO watchlist_tickers (watchlist_id, ticker, notes)
                    VALUES (1, %s, %s)
                    ON CONFLICT (watchlist_id, ticker) DO NOTHING;
                """, (ticker, note))
            else:
                cursor.execute("""
                    INSERT INTO watchlist_tickers (watchlist_id, ticker, notes)
                    VALUES (1, ?, ?)
                    ON CONFLICT(watchlist_id, ticker) DO NOTHING;
                """, (ticker, note))

        # 4. Seed default analytics logs
        if USE_POSTGRES:
            cursor.execute("""
                INSERT INTO analytics_log (user_id, action_type, details)
                VALUES (1, 'database_initialized', 'Database initialized and seeded.');
            """)
        else:
            cursor.execute("""
                INSERT INTO analytics_log (user_id, action_type, details)
                VALUES (1, 'database_initialized', 'Database initialized and seeded.');
            """)
            
    print("Database seeding completed.")

if __name__ == "__main__":
    # Initialize the tables using schema.sql DDL
    init_db()
    # Seed values
    seed_data()

    # Automatically trigger ingestion of initial stock data and embeddings
    print("\nRunning initial ingestion pipeline...")
    from dashboard.app import trigger_sync
    res, err = trigger_sync(["AAPL", "MSFT", "GOOGL"], 5)
    if err:
        print(f"Ingestion failed: {err}")
    else:
        print(f"Successfully ingested mock quotes and historical snapshots: {res}")
        
    print("\nRunning embedding pipeline...")
    from notebooks.ingest_ticker_news_embeddings import ingest_embeddings
    ingest_embeddings()
    print("\nInitialization complete! You can now start the application.")
