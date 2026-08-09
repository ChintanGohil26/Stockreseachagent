import os
import json
from flask import Flask, request, jsonify
from sentence_transformers import SentenceTransformer
from lakebase import get_connection, USE_POSTGRES, sqlite_cosine_similarity
from massive_client import MassiveClient
import psycopg2
from psycopg2.extras import execute_values

# Initialize Flask App
app = Flask(__name__)

# Load Sentence Transformer Model (Load once at app startup)
# We specify device="cpu" to run efficiently on standard Databricks single nodes or local test runs
print("Loading sentence-transformers/all-MiniLM-L6-v2 model...")
model = SentenceTransformer("all-MiniLM-L6-v2", device="cpu")
print("Model loaded successfully.")

# Initialize Massive Stock Client
massive = MassiveClient()

@app.route("/healthz", methods=["GET"])
def health_check():
    """
    Standard health check endpoint.
    """
    return jsonify({
        "status": "healthy",
        "database": "postgresql" if USE_POSTGRES else "sqlite-fallback",
        "sandbox_mode": massive.is_sandbox
    })

@app.route("/stocks/sync", methods=["POST"])
def sync_stocks():
    """
    POST /stocks/sync
    Body: {"tickers": ["AAPL", "MSFT", "GOOGL"], "limit": 10}
    Fetches stock company profiles, fundamentals, price snapshots, and news from Massive Stocks API.
    Upserts them into Lakebase.
    """
    body = request.get_json() or {}
    tickers = body.get("tickers", ["AAPL", "MSFT", "GOOGL"])
    limit = int(body.get("limit", 10))

    if not isinstance(tickers, list) or not tickers:
        return jsonify({"error": "tickers must be a non-empty list"}), 400

    synced_companies = 0
    synced_news = 0
    synced_prices = 0

    with get_connection() as conn:
        cursor = conn.cursor()

        # 1. Sync Company Profiles & Fundamentals
        for ticker in tickers:
            try:
                # Fetch profile from Massive Stocks API
                profile = massive.get("companies", {"tickers": ticker})
                if not profile:
                    continue

                if USE_POSTGRES:
                    cursor.execute("""
                        INSERT INTO companies (ticker, name, sector, industry, profile_text, filings_excerpt, earnings_summary)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (ticker) DO UPDATE SET
                            name = EXCLUDED.name,
                            sector = EXCLUDED.sector,
                            industry = EXCLUDED.industry,
                            profile_text = EXCLUDED.profile_text,
                            filings_excerpt = EXCLUDED.filings_excerpt,
                            earnings_summary = EXCLUDED.earnings_summary;
                    """, (
                        profile["ticker"], profile["name"], profile.get("sector"), 
                        profile.get("industry"), profile.get("profile_text"), 
                        profile.get("filings_excerpt"), profile.get("earnings_summary")
                    ))
                else: # SQLite
                    cursor.execute("""
                        INSERT INTO companies (ticker, name, sector, industry, profile_text, filings_excerpt, earnings_summary)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(ticker) DO UPDATE SET
                            name=excluded.name,
                            sector=excluded.sector,
                            industry=excluded.industry,
                            profile_text=excluded.profile_text,
                            filings_excerpt=excluded.filings_excerpt,
                            earnings_summary=excluded.earnings_summary;
                    """, (
                        profile["ticker"], profile["name"], profile.get("sector"), 
                        profile.get("industry"), profile.get("profile_text"), 
                        profile.get("filings_excerpt"), profile.get("earnings_summary")
                    ))
                synced_companies += 1

                # 2. Sync Stock Price History
                hist = massive.get("historical", {"ticker": ticker, "days": 30})
                if hist and "data" in hist:
                    for snapshot in hist["data"]:
                        if USE_POSTGRES:
                            cursor.execute("""
                                INSERT INTO price_snapshots (ticker, timestamp, open, high, low, close, volume)
                                VALUES (%s, %s, %s, %s, %s, %s, %s)
                                ON CONFLICT (ticker, timestamp) DO UPDATE SET
                                    open = EXCLUDED.open,
                                    high = EXCLUDED.high,
                                    low = EXCLUDED.low,
                                    close = EXCLUDED.close,
                                    volume = EXCLUDED.volume;
                            """, (
                                snapshot["ticker"], snapshot["timestamp"], snapshot["open"],
                                snapshot["high"], snapshot["low"], snapshot["close"], snapshot["volume"]
                            ))
                        else: # SQLite
                            cursor.execute("""
                                INSERT INTO price_snapshots (ticker, timestamp, open, high, low, close, volume)
                                VALUES (?, ?, ?, ?, ?, ?, ?)
                                ON CONFLICT(ticker, timestamp) DO UPDATE SET
                                    open=excluded.open,
                                    high=excluded.high,
                                    low=excluded.low,
                                    close=excluded.close,
                                    volume=excluded.volume;
                            """, (
                                snapshot["ticker"], snapshot["timestamp"], snapshot["open"],
                                snapshot["high"], snapshot["low"], snapshot["close"], snapshot["volume"]
                            ))
                        synced_prices += 1

            except Exception as e:
                print(f"Error syncing profile/history for {ticker}: {e}")

        # 3. Sync News Articles
        try:
            news_response = massive.get("news", {"tickers": ",".join(tickers), "limit": limit})
            if news_response and "articles" in news_response:
                for art in news_response["articles"]:
                    t = art.get("ticker", "AAPL")
                    if USE_POSTGRES:
                        cursor.execute("""
                            INSERT INTO news_articles (id, ticker, headline, content, published_at)
                            VALUES (%s, %s, %s, %s, %s)
                            ON CONFLICT (id) DO UPDATE SET
                                ticker = EXCLUDED.ticker,
                                headline = EXCLUDED.headline,
                                content = EXCLUDED.content,
                                published_at = EXCLUDED.published_at;
                        """, (art["id"], t, art["headline"], art["content"], art["published_at"]))
                    else: # SQLite
                        cursor.execute("""
                            INSERT INTO news_articles (id, ticker, headline, content, published_at)
                            VALUES (?, ?, ?, ?, ?)
                            ON CONFLICT(id) DO UPDATE SET
                                ticker=excluded.ticker,
                                headline=excluded.headline,
                                content=excluded.content,
                                published_at=excluded.published_at;
                        """, (art["id"], t, art["headline"], art["content"], art["published_at"]))
                    synced_news += 1
        except Exception as e:
            print(f"Error syncing news articles: {e}")

    return jsonify({
        "status": "success",
        "synced_companies": synced_companies,
        "synced_prices": synced_prices,
        "synced_news": synced_news
    })

@app.route("/stocks/search", methods=["POST"])
def search_news():
    """
    POST /stocks/search
    Body: {"query": "supply chain risk in technology", "top_k": 5}
    Embeds the search query and searches news_embeddings using cosine similarity.
    """
    body = request.get_json() or {}
    query = body.get("query")
    top_k = int(body.get("top_k", 5))

    if not query:
        return jsonify({"error": "Missing query parameter"}), 400

    # Clamp top_k limits
    top_k = max(1, min(20, top_k))

    # Generate query embedding
    query_emb = model.encode(query).tolist()

    matches = []
    if USE_POSTGRES:
        try:
            with get_connection() as conn:
                cursor = conn.cursor()
                # Use pgvector's <=> cosine distance operator
                cursor.execute("""
                    SELECT d.id, d.ticker, d.headline, d.content, e.chunk_text,
                           1 - (e.embedding <=> %s::vector) AS similarity
                    FROM news_embeddings e
                    JOIN news_articles d ON d.id = e.article_id
                    ORDER BY e.embedding <=> %s::vector
                    LIMIT %s;
                """, (query_emb, query_emb, top_k))
                rows = cursor.fetchall()
                for r in rows:
                    matches.append({
                        "id": r["id"],
                        "ticker": r["ticker"],
                        "headline": r["headline"],
                        "chunk_text": r["chunk_text"],
                        "similarity": float(r["similarity"])
                    })
        except Exception as e:
            return jsonify({"error": f"Database search failed: {str(e)}"}), 500
    else:
        # SQLite python cosine similarity fallback
        raw_matches = sqlite_cosine_similarity(query_emb, limit=top_k, table="news_embeddings")
        for r in raw_matches:
            matches.append({
                "id": r["article_id"],
                "ticker": r["ticker"],
                "headline": r["headline"],
                "chunk_text": r["chunk_text"],
                "similarity": float(r["similarity"])
            })

    return jsonify({
        "query": query,
        "results": matches
    })

if __name__ == "__main__":
    # Run Flask application on port 5000
    app.run(host="0.0.0.0", port=5000)
