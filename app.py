import os
# Fix OpenSSL FIPS self-test failure inside Databricks sandbox
os.environ.pop("OPENSSL_FORCE_FIPS_MODE", None)

import json
from flask import Flask, request, jsonify
from sentence_transformers import SentenceTransformer
from lakebase import get_connection, USE_POSTGRES, USE_PGVECTOR, python_cosine_similarity
from massive_client import MassiveClient
from weather_client import WeatherClient
import psycopg2
from psycopg2.extras import execute_values

# Initialize Flask App
app = Flask(__name__)

# Load Sentence Transformer Model (Load once at app startup)
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
        "pgvector_enabled": USE_PGVECTOR,
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
    if USE_PGVECTOR:
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
        # Python cosine similarity fallback (for SQLite and non-pgvector Postgres)
        raw_matches = python_cosine_similarity(query_emb, limit=top_k, table="news_embeddings")
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

@app.route("/weather/sync", methods=["POST"])
def sync_weather():
    """
    POST /weather/sync
    Body: {"locations": ["Chicago, IL", "Austin, TX"]}
    Fetches weather forecasts and alerts, and upserts them into Lakebase weather_documents.
    """
    body = request.get_json() or {}
    locations = body.get("locations", ["Chicago, IL", "Austin, TX"])

    if not isinstance(locations, list) or not locations:
        return jsonify({"error": "locations must be a non-empty list"}), 400

    weather_client = WeatherClient()
    synced_count = 0

    with get_connection() as conn:
        cursor = conn.cursor()
        for loc in locations:
            try:
                docs = weather_client.harvest_weather(loc)
                for doc in docs:
                    if USE_POSTGRES:
                        cursor.execute("""
                            INSERT INTO weather_documents (id, location, source_type, headline, narrative_text, issued_at, payload)
                            VALUES (%s, %s, %s, %s, %s, %s, %s)
                            ON CONFLICT (id) DO UPDATE SET
                                location = EXCLUDED.location,
                                source_type = EXCLUDED.source_type,
                                headline = EXCLUDED.headline,
                                narrative_text = EXCLUDED.narrative_text,
                                issued_at = EXCLUDED.issued_at,
                                payload = EXCLUDED.payload;
                        """, (
                            doc["id"], doc["location"], doc["source_type"], 
                            doc.get("headline"), doc["narrative_text"], 
                            doc["issued_at"], doc["payload"]
                        ))
                    else: # SQLite
                        cursor.execute("""
                            INSERT INTO weather_documents (id, location, source_type, headline, narrative_text, issued_at, payload)
                            VALUES (?, ?, ?, ?, ?, ?, ?)
                            ON CONFLICT (id) DO UPDATE SET
                                location = excluded.location,
                                source_type = excluded.source_type,
                                headline = excluded.headline,
                                narrative_text = excluded.narrative_text,
                                issued_at = excluded.issued_at,
                                payload = excluded.payload;
                        """, (
                            doc["id"], doc["location"], doc["source_type"], 
                            doc.get("headline"), doc["narrative_text"], 
                            doc["issued_at"], doc["payload"]
                        ))
                    synced_count += 1
            except Exception as e:
                print(f"Error syncing weather for {loc}: {e}")

    return jsonify({
        "status": "success",
        "synced_count": synced_count
    })

@app.route("/weather/search", methods=["POST"])
def search_weather():
    """
    POST /weather/search
    Body: {"query": "flooding near rivers", "top_k": 5}
    Embeds the search query and searches weather_embeddings using cosine similarity.
    """
    body = request.get_json() or {}
    query = body.get("query")
    top_k = int(body.get("top_k", 5))

    if not query:
        return jsonify({"error": "Missing query parameter"}), 400

    top_k = max(1, min(20, top_k))
    query_emb = model.encode(query).tolist()

    matches = []
    if USE_PGVECTOR:
        try:
            with get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT d.id, d.location, d.headline, d.narrative_text, e.chunk_text,
                           1 - (e.embedding <=> %s::vector) AS similarity
                    FROM weather_embeddings e
                    JOIN weather_documents d ON d.id = e.document_id
                    ORDER BY e.embedding <=> %s::vector
                    LIMIT %s;
                """, (query_emb, query_emb, top_k))
                rows = cursor.fetchall()
                for r in rows:
                    matches.append({
                        "id": r["id"],
                        "location": r["location"],
                        "headline": r["headline"],
                        "chunk_text": r["chunk_text"],
                        "similarity": float(r["similarity"])
                    })
        except Exception as e:
            return jsonify({"error": f"Database search failed: {str(e)}"}), 500
    else:
        # Python similarity calculation fallback (runs on SQLite and Non-pgvector Postgres)
        raw_matches = python_cosine_similarity(query_emb, limit=top_k, table="weather_embeddings")
        for r in raw_matches:
            matches.append({
                "id": r["document_id"],
                "location": r["location"],
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
