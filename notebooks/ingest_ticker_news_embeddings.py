import os
# Fix OpenSSL FIPS self-test failure inside Databricks sandbox
os.environ.pop("OPENSSL_FORCE_FIPS_MODE", None)

import sys
import json
from sentence_transformers import SentenceTransformer
from dotenv import load_dotenv

# Ensure root directory is on the path to import lakebase
if "__file__" in globals():
    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
else:
    sys.path.append(os.getcwd())
    sys.path.append(os.path.abspath(".."))
from lakebase import get_connection, USE_POSTGRES, USE_PGVECTOR

# Load env variables
load_dotenv()

# Constants
CHUNK_SIZE = 800
CHUNK_OVERLAP = 100
MODEL_NAME = "all-MiniLM-L6-v2"

def chunk_text(text, chunk_size=CHUNK_SIZE, overlap=CHUNK_OVERLAP):
    """
    Chunks a long text into overlapping slices.
    """
    if not text:
        return []
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunks.append(text[start:end])
        start += (chunk_size - overlap)
    return chunks

def ingest_embeddings():
    """
    Ingests embeddings for companies and news articles using sentence-transformers.
    Works for Postgres (with or without pgvector) and SQLite local fallbacks.
    """
    print(f"Loading embedding model: {MODEL_NAME}...")
    model = SentenceTransformer(MODEL_NAME, device="cpu")
    print("Model loaded.")

    # 1. Embed Company Profiles (Combined profile + filings + earnings)
    print("Checking for companies with missing profile embeddings...")
    companies_to_embed = []
    
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT ticker, profile_text, filings_excerpt, earnings_summary FROM companies WHERE profile_embedding IS NULL")
        companies_to_embed = cursor.fetchall()

    if companies_to_embed:
        print(f"Embedding {len(companies_to_embed)} companies...")
        for comp in companies_to_embed:
            ticker = comp["ticker"]
            # Combine content for context engineering
            combined_text = f"Company: {ticker}. Profile: {comp.get('profile_text','')}. Filings: {comp.get('filings_excerpt','')}. Earnings: {comp.get('earnings_summary','')}"
            embedding = model.encode(combined_text).tolist()
            
            with get_connection() as conn:
                cursor = conn.cursor()
                if USE_PGVECTOR:
                    cursor.execute(
                        "UPDATE companies SET profile_embedding = %s::vector WHERE ticker = %s",
                        (embedding, ticker)
                    )
                elif USE_POSTGRES:
                    cursor.execute(
                        "UPDATE companies SET profile_embedding = %s WHERE ticker = %s",
                        (json.dumps(embedding), ticker)
                    )
                else:
                    # SQLite stores list as JSON string
                    cursor.execute(
                        "UPDATE companies SET profile_embedding = ? WHERE ticker = ?",
                        (json.dumps(embedding), ticker)
                    )
        print("Company profiles embedded.")
    else:
        print("No new companies to embed.")

    # 2. Embed News Articles in Chunks
    print("Checking for news articles with missing chunk embeddings...")
    with get_connection() as conn:
        cursor = conn.cursor()
        # Find news articles that don't have chunks in news_embeddings
        cursor.execute("""
            SELECT id, ticker, headline, content 
            FROM news_articles 
            WHERE id NOT IN (SELECT DISTINCT article_id FROM news_embeddings)
        """)
        articles_to_embed = cursor.fetchall()

    if articles_to_embed:
        print(f"Embedding {len(articles_to_embed)} news articles...")
        for art in articles_to_embed:
            article_id = art["id"]
            content = art["content"]
            headline = art["headline"]
            ticker = art["ticker"]

            # Combined content text
            full_text = f"Headline: {headline}. Content: {content}"
            chunks = chunk_text(full_text)

            for i, chunk in enumerate(chunks):
                # Generate embedding
                embedding = model.encode(chunk).tolist()
                
                with get_connection() as conn:
                    cursor = conn.cursor()
                    if USE_PGVECTOR:
                        cursor.execute("""
                            INSERT INTO news_embeddings (article_id, chunk_index, chunk_text, embedding)
                            VALUES (%s, %s, %s, %s::vector)
                        """, (article_id, i, chunk, embedding))
                    elif USE_POSTGRES:
                        cursor.execute("""
                            INSERT INTO news_embeddings (article_id, chunk_index, chunk_text, embedding)
                            VALUES (%s, %s, %s, %s)
                        """, (article_id, i, chunk, json.dumps(embedding)))
                    else:
                        cursor.execute("""
                            INSERT INTO news_embeddings (article_id, chunk_index, chunk_text, embedding)
                            VALUES (?, ?, ?, ?)
                        """, (article_id, i, chunk, json.dumps(embedding)))
        print(f"News articles embedded. Total articles processed: {len(articles_to_embed)}")
    else:
        print("No new news articles to embed.")

if __name__ == "__main__":
    ingest_embeddings()
