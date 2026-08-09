import os
# Fix OpenSSL FIPS self-test failure inside Databricks sandbox
os.environ.pop("OPENSSL_FORCE_FIPS_MODE", None)

import sys
import datetime
import json
import numpy as np
from sentence_transformers import SentenceTransformer
from dotenv import load_dotenv

# Ensure parent directory is on the path to import lakebase and massive_client
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from lakebase import get_connection, USE_POSTGRES, USE_PGVECTOR, python_cosine_similarity
from massive_client import MassiveClient

# Load env variables
load_dotenv()

# Initialize API Client
massive = MassiveClient()

# Load model for semantic search inside the broker
print("Loading model for broker semantic search...")
model = SentenceTransformer("all-MiniLM-L6-v2", device="cpu")

class FinancialBroker:
    """
    Adapter/Broker module that separates raw HTTP requests and database
    operations from the MCP tool definitions.
    """
    @staticmethod
    def get_stock_summary(ticker):
        ticker = ticker.upper().strip()
        try:
            # Fetch latest quote
            quote = massive.get("quote", {"ticker": ticker})
            # Fetch historical data to compute simple performance (e.g. 30-day trend)
            history = massive.get("historical", {"ticker": ticker, "days": 30})
            
            # Summarize performance
            perf_summary = "No history available"
            if history and "data" in history and len(history["data"]) > 1:
                hist_data = history["data"]
                start_price = float(hist_data[0]["close"])
                end_price = float(hist_data[-1]["close"])
                pct_change = ((end_price - start_price) / start_price) * 100
                perf_summary = f"30-day performance: {pct_change:+.2f}% (from ${start_price:.2f} to ${end_price:.2f})"
                
            return {
                "ticker": ticker,
                "current_price": quote.get("price"),
                "open": quote.get("open"),
                "high": quote.get("high"),
                "low": quote.get("low"),
                "volume": quote.get("volume"),
                "performance_30d": perf_summary,
                "timestamp": quote.get("timestamp")
            }
        except Exception as e:
            return {"error": f"Failed to retrieve stock summary for {ticker}: {str(e)}"}

    @staticmethod
    def get_company_context(ticker):
        ticker = ticker.upper().strip()
        try:
            # Fetch company details
            profile = massive.get("companies", {"tickers": ticker})
            # Fetch recent news
            news_response = massive.get("news", {"tickers": ticker, "limit": 3})
            news_list = news_response.get("articles", []) if news_response else []
            
            return {
                "ticker": ticker,
                "name": profile.get("name", "N/A"),
                "sector": profile.get("sector", "N/A"),
                "industry": profile.get("industry", "N/A"),
                "profile": profile.get("profile_text", "No profile description found."),
                "filings_excerpt": profile.get("filings_excerpt", "No filings excerpt found."),
                "earnings_summary": profile.get("earnings_summary", "No earnings summary found."),
                "recent_news": [
                    {"headline": n["headline"], "published_at": n["published_at"]} 
                    for n in news_list
                ]
            }
        except Exception as e:
            return {"error": f"Failed to retrieve company context for {ticker}: {str(e)}"}

    @staticmethod
    def compare_tickers(tickers_str):
        tickers = [t.upper().strip() for t in tickers_str.split(",") if t.strip()]
        comparison = []
        for t in tickers:
            try:
                # Fetch quote
                quote = massive.get("quote", {"ticker": t})
                # Fetch fundamentals/profile
                profile = massive.get("companies", {"tickers": t})
                
                comparison.append({
                    "ticker": t,
                    "name": profile.get("name", "N/A"),
                    "price": quote.get("price"),
                    "change_today": round(float(quote.get("price", 0)) - float(quote.get("open", 0)), 2),
                    "sector": profile.get("sector", "N/A"),
                    "industry": profile.get("industry", "N/A")
                })
            except Exception as e:
                comparison.append({"ticker": t, "error": str(e)})
        return {"comparison": comparison}

    @staticmethod
    def manage_watchlist(action, ticker, watchlist_name="Default"):
        ticker = ticker.upper().strip()
        action = action.lower().strip()
        
        try:
            with get_connection() as conn:
                cursor = conn.cursor()
                
                # Check / Ensure user exists
                cursor.execute("SELECT id FROM users LIMIT 1")
                user = cursor.fetchone()
                if not user:
                    # Create default user
                    cursor.execute(
                        "INSERT INTO users (username, email) VALUES (%s, %s) RETURNING id" if USE_POSTGRES
                        else "INSERT INTO users (username, email) VALUES (?, ?)",
                        ("default_user", "user@dataexpert.io")
                    )
                    user_id = cursor.lastrowid if not USE_POSTGRES else cursor.fetchone()["id"]
                else:
                    user_id = user["id"] if USE_POSTGRES else user[0]

                # Ensure watchlist exists
                if USE_POSTGRES:
                    cursor.execute("SELECT id FROM watchlists WHERE name = %s AND user_id = %s", (watchlist_name, user_id))
                else:
                    cursor.execute("SELECT id FROM watchlists WHERE name = ? AND user_id = ?", (watchlist_name, user_id))
                wl = cursor.fetchone()
                
                if not wl:
                    cursor.execute(
                        "INSERT INTO watchlists (name, user_id) VALUES (%s, %s) RETURNING id" if USE_POSTGRES
                        else "INSERT INTO watchlists (name, user_id) VALUES (?, ?)",
                        (watchlist_name, user_id)
                    )
                    wl_id = cursor.lastrowid if not USE_POSTGRES else cursor.fetchone()["id"]
                else:
                    wl_id = wl["id"] if USE_POSTGRES else wl[0]

                # Perform Add or Remove action
                if action == "add":
                    if USE_POSTGRES:
                        cursor.execute("""
                            INSERT INTO watchlist_tickers (watchlist_id, ticker, notes)
                            VALUES (%s, %s, %s)
                            ON CONFLICT (watchlist_id, ticker) DO NOTHING;
                        """, (wl_id, ticker, "Added via MCP Agent"))
                    else:
                        cursor.execute("""
                            INSERT INTO watchlist_tickers (watchlist_id, ticker, notes)
                            VALUES (?, ?, ?)
                            ON CONFLICT(watchlist_id, ticker) DO NOTHING;
                        """, (wl_id, ticker, "Added via MCP Agent"))
                    return {"status": "success", "message": f"Added {ticker} to watchlist '{watchlist_name}'"}
                elif action == "remove":
                    if USE_POSTGRES:
                        cursor.execute("DELETE FROM watchlist_tickers WHERE watchlist_id = %s AND ticker = %s", (wl_id, ticker))
                    else:
                        cursor.execute("DELETE FROM watchlist_tickers WHERE watchlist_id = ? AND ticker = ?", (wl_id, ticker))
                    return {"status": "success", "message": f"Removed {ticker} from watchlist '{watchlist_name}'"}
                else:
                    return {"error": "Invalid action. Choose 'add' or 'remove'."}
        except Exception as e:
            return {"error": f"Failed to manage watchlist: {str(e)}"}

    @staticmethod
    def save_research_report(ticker, report_text):
        ticker = ticker.upper().strip()
        try:
            with get_connection() as conn:
                cursor = conn.cursor()
                if USE_POSTGRES:
                    cursor.execute(
                        "INSERT INTO analysis_reports (ticker, report_text) VALUES (%s, %s)",
                        (ticker, report_text)
                    )
                else:
                    cursor.execute(
                        "INSERT INTO analysis_reports (ticker, report_text) VALUES (?, ?)",
                        (ticker, report_text)
                    )
            return {"status": "success", "message": f"Research report for {ticker} saved successfully."}
        except Exception as e:
            return {"error": f"Failed to save report: {str(e)}"}

    @staticmethod
    def check_watchlist_updates():
        try:
            # Get default watchlist tickers
            with get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT DISTINCT wt.ticker 
                    FROM watchlist_tickers wt
                    JOIN watchlists w ON w.id = wt.watchlist_id
                    LIMIT 10
                """)
                rows = cursor.fetchall()
                tickers = [r["ticker"] if USE_POSTGRES else r[0] for r in rows]

            if not tickers:
                return {"message": "Your watchlist is empty. Add tickers first to see updates."}

            updates = []
            for t in tickers:
                quote = massive.get("quote", {"ticker": t})
                price = float(quote.get("price", 0))
                open_p = float(quote.get("open", 0))
                diff_pct = ((price - open_p) / open_p) * 100 if open_p > 0 else 0
                
                # Flag if move is greater than 1.5%
                if abs(diff_pct) >= 1.5:
                    updates.append({
                        "ticker": t,
                        "price": price,
                        "change_pct": f"{diff_pct:+.2f}%",
                        "severity": "HIGH",
                        "message": f"Notable intraday move detected for {t}."
                    })
                else:
                    updates.append({
                        "ticker": t,
                        "price": price,
                        "change_pct": f"{diff_pct:+.2f}%",
                        "severity": "NORMAL",
                        "message": "Intraday movement within normal range."
                    })
            return {"updates": updates}
        except Exception as e:
            return {"error": f"Failed to check watchlist updates: {str(e)}"}

    @staticmethod
    def semantic_company_search(query):
        try:
            query_emb = model.encode(query).tolist()
            matches = []

            if USE_PGVECTOR:
                with get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute("""
                        SELECT ticker, name, sector, industry, profile_text, filings_excerpt,
                               1 - (profile_embedding <=> %s::vector) AS similarity
                        FROM companies
                        WHERE profile_embedding IS NOT NULL
                        ORDER BY profile_embedding <=> %s::vector
                        LIMIT 5;
                    """, (query_emb, query_emb))
                    rows = cursor.fetchall()
                    for r in rows:
                        matches.append({
                            "ticker": r["ticker"],
                            "name": r["name"],
                            "sector": r["sector"],
                            "industry": r["industry"],
                            "profile": r["profile_text"],
                            "filings": r["filings_excerpt"],
                            "similarity": float(r["similarity"])
                        })
            else:
                # Python fallback similarity calculation
                raw_matches = python_cosine_similarity(query_emb, limit=5, table="companies")
                for r in raw_matches:
                    matches.append({
                        "ticker": r["ticker"],
                        "name": r["name"],
                        "sector": r["sector"],
                        "industry": r["industry"],
                        "profile": r["profile_text"],
                        "filings": r["filings_excerpt"],
                        "similarity": float(r["similarity"])
                    })
            return {"results": matches}
        except Exception as e:
            return {"error": f"Failed to run semantic company search: {str(e)}"}
