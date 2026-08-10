import os
# Fix OpenSSL FIPS self-test failure inside Databricks sandbox
os.environ.pop("OPENSSL_FORCE_FIPS_MODE", None)

import sys
import json
from sentence_transformers import SentenceTransformer
from dotenv import load_dotenv

# Ensure root directory is on the path to import lakebase
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from lakebase import get_connection, USE_POSTGRES, USE_PGVECTOR

# Load env variables
load_dotenv()

# Constants
CHUNK_SIZE = 800
CHUNK_OVERLAP = 100
MODEL_NAME = "all-MiniLM-L6-v2"

def chunk_text(text, chunk_size=CHUNK_SIZE, overlap=CHUNK_OVERLAP):
    """
    Chunks narrative text using a simple sliding window.
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

def ingest_weather_embeddings():
    """
    Reads unembedded weather documents, chunks them, generates 384-dimensional
    embeddings using sentence-transformers, and saves them to weather_embeddings.
    """
    print(f"Loading embedding model: {MODEL_NAME}...")
    model = SentenceTransformer(MODEL_NAME, device="cpu")
    print("Model loaded.")

    print("Checking for weather documents with missing embeddings...")
    with get_connection() as conn:
        cursor = conn.cursor()
        # Select documents that do not have any chunks in weather_embeddings
        cursor.execute("""
            SELECT id, location, headline, narrative_text 
            FROM weather_documents 
            WHERE id NOT IN (SELECT DISTINCT document_id FROM weather_embeddings)
        """)
        docs_to_embed = cursor.fetchall()

    if docs_to_embed:
        print(f"Embedding {len(docs_to_embed)} weather documents...")
        for doc in docs_to_embed:
            doc_id = doc["id"]
            location = doc["location"]
            headline = doc["headline"]
            narrative = doc["narrative_text"]

            # Combined content text
            full_text = f"Location: {location}. Headline: {headline}. Narrative: {narrative}"
            chunks = chunk_text(full_text)

            for i, chunk in enumerate(chunks):
                # Generate embedding
                embedding = model.encode(chunk).tolist()
                
                with get_connection() as conn:
                    cursor = conn.cursor()
                    if USE_PGVECTOR:
                        cursor.execute("""
                            INSERT INTO weather_embeddings (document_id, chunk_index, chunk_text, embedding, model_name)
                            VALUES (%s, %s, %s, %s::vector, %s)
                        """, (doc_id, i, chunk, embedding, MODEL_NAME))
                    elif USE_POSTGRES:
                        # Postgres fallback to TEXT
                        cursor.execute("""
                            INSERT INTO weather_embeddings (document_id, chunk_index, chunk_text, embedding, model_name)
                            VALUES (%s, %s, %s, %s, %s)
                        """, (doc_id, i, chunk, json.dumps(embedding), MODEL_NAME))
                    else:
                        # SQLite fallback
                        cursor.execute("""
                            INSERT INTO weather_embeddings (document_id, chunk_index, chunk_text, embedding, model_name)
                            VALUES (?, ?, ?, ?, ?)
                        """, (doc_id, i, chunk, json.dumps(embedding), MODEL_NAME))
                        
        print(f"Weather embeddings generated and saved. Total documents processed: {len(docs_to_embed)}")
    else:
        print("No new weather documents to embed.")

if __name__ == "__main__":
    ingest_weather_embeddings()
