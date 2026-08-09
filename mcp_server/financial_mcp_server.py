import os
import json
from mcp.server.fastmcp import FastMCP
from financial_broker import FinancialBroker

# Create the FastMCP instance
mcp = FastMCP("Financial Research Agent")

@mcp.tool()
def get_stock_summary(ticker: str) -> str:
    """
    Pull current and historical price data for a ticker and summarize recent performance.

    Args:
        ticker: The stock ticker symbol (e.g. AAPL, MSFT, GOOGL).
    """
    result = FinancialBroker.get_stock_summary(ticker)
    return json.dumps(result, indent=2)

@mcp.tool()
def get_company_context(ticker: str) -> str:
    """
    Surface and summarize relevant profile details, filings excerpts, earnings-calls, and news for a company.

    Args:
        ticker: The stock ticker symbol (e.g. AAPL, MSFT, GOOGL).
    """
    result = FinancialBroker.get_company_context(ticker)
    return json.dumps(result, indent=2)

@mcp.tool()
def compare_tickers(tickers: str) -> str:
    """
    Compare multiple stock tickers on fundamentals and recent price action.

    Args:
        tickers: A comma-separated list of ticker symbols (e.g. "AAPL,MSFT,GOOGL").
    """
    result = FinancialBroker.compare_tickers(tickers)
    return json.dumps(result, indent=2)

@mcp.tool()
def manage_watchlist(action: str, ticker: str) -> str:
    """
    Add or remove tickers from the user's default watchlist.

    Args:
        action: Either "add" to add a ticker or "remove" to delete a ticker.
        ticker: The stock ticker symbol (e.g. AAPL, MSFT).
    """
    result = FinancialBroker.manage_watchlist(action, ticker)
    return json.dumps(result, indent=2)

@mcp.tool()
def save_research_report(ticker: str, report_text: str) -> str:
    """
    Save an agent-generated markdown research note or analysis report tied to a ticker.

    Args:
        ticker: The stock ticker symbol (e.g. AAPL, MSFT).
        report_text: The markdown report text to save in the database.
    """
    result = FinancialBroker.save_research_report(ticker, report_text)
    return json.dumps(result, indent=2)

@mcp.tool()
def check_watchlist_updates() -> str:
    """
    Flag notable price moves or news updates on watchlisted tickers since the user's last visit.
    """
    result = FinancialBroker.check_watchlist_updates()
    return json.dumps(result, indent=2)

@mcp.tool()
def semantic_company_search(query: str) -> str:
    """
    Retrieve relevant company contexts using semantic search (e.g. concept search like "companies exposed to interest rates").

    Args:
        query: Semantic query text explaining what kind of companies/exposures to search for.
    """
    result = FinancialBroker.semantic_company_search(query)
    return json.dumps(result, indent=2)

if __name__ == "__main__":
    # Start the FastMCP server on stdio (standard communication mode for MCP clients)
    mcp.run()
