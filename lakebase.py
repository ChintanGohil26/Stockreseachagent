import os
import sqlite3
import json
import numpy as np
from contextlib import contextmanager
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Determine DB Engine: SQLite fallback or Postgres/Lakebase
LAKEBASE_URL = os.getenv("LAKEBASE_URL") or os.getenv("DATABASE_URL")
if not LAKEBASE_URL:
    try:
        from databricks.sdk import WorkspaceClient
        w = WorkspaceClient()
        LAKEBASE_URL = w.secrets.get_secret(scope="financial_agent_scope", key="lakebase-url").value
    except Exception:
        pass

USE_POSTGRES = bool(LAKEBASE_URL)

def check_if_pgvector_supported():
    """
    Checks if pgvector is enabled or can be enabled on the remote PostgreSQL database.
    """
    if not USE_POSTGRES:
        return False
    try:
        conn = psycopg2.connect(LAKEBASE_URL)
        cur = conn.cursor()
        # Try to run CREATE EXTENSION IF NOT EXISTS vector;
        try:
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
            conn.commit()
            cur.close()
            conn.close()
            return True
        except Exception:
            conn.rollback()
            # Check if vector type already exists
            cur.execute("SELECT 1 FROM pg_type WHERE typname = 'vector';")
            exists = bool(cur.fetchone())
            cur.close()
            conn.close()
            return exists
    except Exception:
        return False

# Global flag indicating if native pgvector operations are supported
USE_PGVECTOR = check_if_pgvector_supported()

class SQLiteRealDictCursor(sqlite3.Cursor):
    """
    SQLite cursor wrapper that returns results as list of dictionaries,
    matching psycopg2's RealDictCursor.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.row_factory = sqlite3.Row

    def fetchone(self):
        row = super().fetchone()
        return dict(row) if row else None

    def fetchall(self):
        rows = super().fetchall()
        return [dict(row) for row in rows]

class SQLiteConnectionWrapper:
    """
    Wrapper for sqlite3 connection to mimic psycopg2 interface.
    """
    def __init__(self, conn):
        self._conn = conn

    def cursor(self, cursor_factory=None):
        return self._conn.cursor(SQLiteRealDictCursor)

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        self._conn.close()

@contextmanager
def get_connection():
    """
    Establishes database connection context.
    Tries PostgreSQL (psycopg2) if LAKEBASE_URL is provided,
    otherwise falls back to SQLite.
    """
    if USE_POSTGRES:
        conn = None
        try:
            conn = psycopg2.connect(LAKEBASE_URL)
            yield conn
            conn.commit()
        except Exception as e:
            if conn:
                conn.rollback()
            raise e
        finally:
            if conn:
                conn.close()
    else:
        # SQLite local fallback database
        db_path = os.path.join(os.path.dirname(__file__), "lakebase_local.db")
        conn = sqlite3.connect(db_path)
        # Enable foreign keys in SQLite
        conn.execute("PRAGMA foreign_keys = ON;")
        wrapped = SQLiteConnectionWrapper(conn)
        try:
            yield wrapped
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()

def init_db():
    """
    Executes schema.sql on the connected database.
    Dynamically translates PostgreSQL DDL (removing pgvector constraints if unsupported
    or generating SQLite specific queries).
    """
    schema_path = os.path.join(os.path.dirname(__file__), "schema.sql")
    if not os.path.exists(schema_path):
        raise FileNotFoundError(f"schema.sql not found at {schema_path}")

    with open(schema_path, "r") as f:
        ddl = f.read()

    with get_connection() as conn:
        cursor = conn.cursor()
        
        if USE_POSTGRES:
            if USE_PGVECTOR:
                print("Initializing database using PostgreSQL with pgvector...")
                cursor.execute(ddl)
            else:
                print("Initializing database using PostgreSQL with TEXT fallback (pgvector NOT supported)...")
                # Remove CREATE EXTENSION and replace vector(384) with TEXT
                ddl_clean = ddl.replace("CREATE EXTENSION IF NOT EXISTS vector;", "")
                ddl_clean = ddl_clean.replace("vector(384)", "TEXT")
                
                # Execute statement by statement
                statements = ddl_clean.split(";")
                for stmt in statements:
                    stmt_strip = stmt.strip()
                    if stmt_strip:
                        cursor.execute(stmt_strip)
        else:
            print("Initializing database using SQLite fallback...")
            # Translate postgres specific SQL syntax to SQLite
            ddl_clean = ddl.replace("CREATE EXTENSION IF NOT EXISTS vector;", "")
            ddl_clean = ddl_clean.replace("SERIAL PRIMARY KEY", "INTEGER PRIMARY KEY AUTOINCREMENT")
            ddl_clean = ddl_clean.replace("vector(384)", "TEXT")
            
            # Execute statement by statement
            statements = ddl_clean.split(";")
            for stmt in statements:
                stmt_strip = stmt.strip()
                if stmt_strip:
                    cursor.execute(stmt_strip)
                    
    print("Database initialized successfully.")

def python_cosine_similarity(query_emb, limit=5, table="news_embeddings"):
    """
    Performs cosine similarity calculation in Python using numpy.
    Acts as a fallback if the database lacks native pgvector support.
    """
    query_vector = np.array(query_emb, dtype=np.float32)
    
    with get_connection() as conn:
        cursor = conn.cursor()
        if table == "news_embeddings":
            cursor.execute("""
                SELECT e.id, e.article_id, e.chunk_index, e.chunk_text, e.embedding,
                       d.ticker, d.headline, d.content, d.published_at
                FROM news_embeddings e
                JOIN news_articles d ON d.id = e.article_id
            """)
        else: # company profiles
            cursor.execute("SELECT ticker, name, sector, industry, profile_text, filings_excerpt, earnings_summary, profile_embedding FROM companies")
            
        rows = cursor.fetchall()
        
    results = []
    for r in rows:
        emb_str = r.get("embedding") if table == "news_embeddings" else r.get("profile_embedding")
        if not emb_str:
            continue
        try:
            # Parse stored JSON array (or string representation of float array)
            if isinstance(emb_str, str):
                emb = np.array(json.loads(emb_str), dtype=np.float32)
            else:
                # If database returned it as a list/array directly
                emb = np.array(emb_str, dtype=np.float32)
        except Exception:
            continue
            
        # Cosine Similarity = dot(A, B) / (norm(A) * norm(B))
        dot_product = np.dot(query_vector, emb)
        norm_q = np.linalg.norm(query_vector)
        norm_e = np.linalg.norm(emb)
        if norm_q > 0 and norm_e > 0:
            similarity = float(dot_product / (norm_q * norm_e))
        else:
            similarity = 0.0
            
        r_copy = dict(r)
        r_copy["similarity"] = similarity
        results.append(r_copy)
        
    # Sort descending by similarity
    results.sort(key=lambda x: x["similarity"], reverse=True)
    return results[:limit]
