-- Enable pgvector extension (if on Postgres/Lakebase)
CREATE EXTENSION IF NOT EXISTS vector;

-- 1. Users Table
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(100) NOT NULL UNIQUE,
    email VARCHAR(255) NOT NULL UNIQUE,
    last_login_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 2. Watchlists Table
CREATE TABLE IF NOT EXISTS watchlists (
    id SERIAL PRIMARY KEY,
    user_id INT REFERENCES users(id) ON DELETE CASCADE,
    name VARCHAR(100) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 3. Watchlist Tickers Table
CREATE TABLE IF NOT EXISTS watchlist_tickers (
    watchlist_id INT REFERENCES watchlists(id) ON DELETE CASCADE,
    ticker VARCHAR(10) NOT NULL,
    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    notes TEXT,
    PRIMARY KEY (watchlist_id, ticker)
);

-- 4. Companies Table
CREATE TABLE IF NOT EXISTS companies (
    ticker VARCHAR(10) PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    sector VARCHAR(100),
    industry VARCHAR(100),
    profile_text TEXT,
    filings_excerpt TEXT,
    earnings_summary TEXT,
    profile_embedding vector(384) -- pgvector 384-dim embedding
);

-- 5. Price Snapshots Table
CREATE TABLE IF NOT EXISTS price_snapshots (
    ticker VARCHAR(10) NOT NULL,
    timestamp TIMESTAMP NOT NULL,
    open NUMERIC(15, 4) NOT NULL,
    high NUMERIC(15, 4) NOT NULL,
    low NUMERIC(15, 4) NOT NULL,
    close NUMERIC(15, 4) NOT NULL,
    volume BIGINT NOT NULL,
    PRIMARY KEY (ticker, timestamp)
);

-- 6. News Articles Table
CREATE TABLE IF NOT EXISTS news_articles (
    id VARCHAR(100) PRIMARY KEY,
    ticker VARCHAR(10) NOT NULL,
    headline VARCHAR(500) NOT NULL,
    content TEXT NOT NULL,
    published_at TIMESTAMP NOT NULL,
    synced_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 6b. News Embeddings Table (For chunked retrieval)
CREATE TABLE IF NOT EXISTS news_embeddings (
    id SERIAL PRIMARY KEY,
    article_id VARCHAR(100) REFERENCES news_articles(id) ON DELETE CASCADE,
    chunk_index INT NOT NULL,
    chunk_text TEXT NOT NULL,
    embedding vector(384) -- pgvector 384-dim chunk embedding
);

-- 7. Research Notes Table
CREATE TABLE IF NOT EXISTS research_notes (
    id SERIAL PRIMARY KEY,
    user_id INT REFERENCES users(id) ON DELETE CASCADE,
    ticker VARCHAR(10) NOT NULL,
    note_text TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 8. Analysis Reports Table (Agent-Generated)
CREATE TABLE IF NOT EXISTS analysis_reports (
    id SERIAL PRIMARY KEY,
    ticker VARCHAR(10) NOT NULL,
    report_text TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 9. Analytics Log Table (To track agent activity and simulate Change Data Feed)
CREATE TABLE IF NOT EXISTS analytics_log (
    id SERIAL PRIMARY KEY,
    user_id INT,
    action_type VARCHAR(100) NOT NULL,
    details TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 10. Weather Documents Table (Day 2 Homework)
CREATE TABLE IF NOT EXISTS weather_documents (
    id VARCHAR(100) PRIMARY KEY,
    location VARCHAR(100) NOT NULL,
    source_type VARCHAR(50) NOT NULL, -- "alert" or "forecast"
    headline VARCHAR(255),
    narrative_text TEXT NOT NULL,
    issued_at TIMESTAMP NOT NULL,
    payload TEXT, -- Raw JSON
    synced_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 10b. Weather Embeddings Table (Day 2 Homework)
CREATE TABLE IF NOT EXISTS weather_embeddings (
    id SERIAL PRIMARY KEY,
    document_id VARCHAR(100) REFERENCES weather_documents(id) ON DELETE CASCADE,
    chunk_index INT NOT NULL,
    chunk_text TEXT NOT NULL,
    embedding vector(384), -- pgvector 384-dim embedding
    model_name VARCHAR(100) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Indices for performance optimization
CREATE INDEX IF NOT EXISTS idx_price_snapshots_ticker ON price_snapshots(ticker, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_news_articles_ticker ON news_articles(ticker, published_at DESC);
CREATE INDEX IF NOT EXISTS idx_weather_documents_loc ON weather_documents(location, issued_at DESC);
