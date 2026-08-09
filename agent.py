import os
import json
import google.generativeai as genai
from mcp_server.financial_broker import FinancialBroker
from lakebase import get_connection, USE_POSTGRES

# Configure Gemini API Key
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
    HAS_GEMINI = True
else:
    print("Warning: GEMINI_API_KEY not found. Agent will run in mock simulation mode.")
    HAS_GEMINI = False

SYSTEM_PROMPT = """
You are the AI Stock Market Research Assistant. Your role is to help the user analyze stocks, manage their watchlist, perform semantic research, and save reports.
You have access to several specialized financial tools:
- get_stock_summary(ticker): Pull current and 30-day stock performance.
- get_company_context(ticker): Pull company profiles, filings excerpts, and news.
- compare_tickers(tickers): Side-by-side comparison of multiple stocks.
- manage_watchlist(action, ticker): Add/remove stocks from the watchlist.
- save_research_report(ticker, report_text): Save a markdown research report to the database.
- check_watchlist_updates(): Flag notable price moves or news on watched tickers.
- semantic_company_search(query): Search company profiles semantically (conceptual search).

Follow these rules:
1. Always base your answers on data returned from your tools. Do not hallucinate or guess data.
2. If you are asked to search for conceptual topics (e.g. "which companies are exposed to real estate"), use the semantic_company_search tool.
3. When requested to write a report, write a comprehensive analysis in Markdown, and then call the save_research_report tool to persist it in the database.
4. When comparing stocks, call compare_tickers with a comma-separated list of symbols.
5. If a tool call fails, report the error honestly and ask the user for clarification.
"""

def log_agent_activity(action_type, details):
    """
    Saves agent operations to the analytics log table (simulating Change Data Feed).
    """
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            if USE_POSTGRES:
                cursor.execute(
                    "INSERT INTO analytics_log (user_id, action_type, details) VALUES (%s, %s, %s)",
                    (1, action_type, details)
                )
            else:
                cursor.execute(
                    "INSERT INTO analytics_log (user_id, action_type, details) VALUES (?, ?, ?)",
                    (1, action_type, details)
                )
    except Exception as e:
        print(f"Error logging agent activity: {e}")

class FinancialAgent:
    """
    AI Agent coordinator that manages the dialogue loop and tool calling execution.
    """
    def __init__(self):
        self.system_prompt = SYSTEM_PROMPT

    def run_query(self, user_query):
        """
        Executes a user query. Calls Gemini with tool schemas, executes tool functions,
        and returns the final response along with a list of thoughts/logs of tool calls.
        """
        thoughts = []
        
        # If no Gemini Key, execute mock response selector
        if not HAS_GEMINI:
            thoughts.append("Gemini API key missing. Processing with local rule-based parsing engine.")
            return self._run_mock_agent(user_query, thoughts)

        try:
            # Setup Gemini model
            model = genai.GenerativeModel(
                model_name="gemini-1.5-flash",
                system_instruction=self.system_prompt
            )
            
            # Map tools to local functions
            tool_map = {
                "get_stock_summary": FinancialBroker.get_stock_summary,
                "get_company_context": FinancialBroker.get_company_context,
                "compare_tickers": FinancialBroker.compare_tickers,
                "manage_watchlist": FinancialBroker.manage_watchlist,
                "save_research_report": FinancialBroker.save_research_report,
                "check_watchlist_updates": FinancialBroker.check_watchlist_updates,
                "semantic_company_search": FinancialBroker.semantic_company_search,
            }

            # Enable function calling in Gemini SDK
            chat = model.start_chat(enable_automatic_function_calling=True)
            
            # Run tools mapping through custom function definitions
            # Register local helper functions directly
            def get_stock_summary_fn(ticker: str) -> str:
                thoughts.append(f"Executing Tool: get_stock_summary(ticker='{ticker}')")
                log_agent_activity("tool_call:get_stock_summary", f"ticker={ticker}")
                return json.dumps(FinancialBroker.get_stock_summary(ticker))

            def get_company_context_fn(ticker: str) -> str:
                thoughts.append(f"Executing Tool: get_company_context(ticker='{ticker}')")
                log_agent_activity("tool_call:get_company_context", f"ticker={ticker}")
                return json.dumps(FinancialBroker.get_company_context(ticker))

            def compare_tickers_fn(tickers: str) -> str:
                thoughts.append(f"Executing Tool: compare_tickers(tickers='{tickers}')")
                log_agent_activity("tool_call:compare_tickers", f"tickers={tickers}")
                return json.dumps(FinancialBroker.compare_tickers(tickers))

            def manage_watchlist_fn(action: str, ticker: str) -> str:
                thoughts.append(f"Executing Tool: manage_watchlist(action='{action}', ticker='{ticker}')")
                log_agent_activity("tool_call:manage_watchlist", f"action={action}, ticker={ticker}")
                return json.dumps(FinancialBroker.manage_watchlist(action, ticker))

            def save_research_report_fn(ticker: str, report_text: str) -> str:
                thoughts.append(f"Executing Tool: save_research_report(ticker='{ticker}')")
                log_agent_activity("tool_call:save_research_report", f"ticker={ticker}, length={len(report_text)}")
                return json.dumps(FinancialBroker.save_research_report(ticker, report_text))

            def check_watchlist_updates_fn() -> str:
                thoughts.append("Executing Tool: check_watchlist_updates()")
                log_agent_activity("tool_call:check_watchlist_updates", "no_args")
                return json.dumps(FinancialBroker.check_watchlist_updates())

            def semantic_company_search_fn(query: str) -> str:
                thoughts.append(f"Executing Tool: semantic_company_search(query='{query}')")
                log_agent_activity("tool_call:semantic_company_search", f"query={query}")
                return json.dumps(FinancialBroker.semantic_company_search(query))

            # Bind functions
            model_with_tools = genai.GenerativeModel(
                model_name="gemini-1.5-flash",
                system_instruction=self.system_prompt,
                tools=[
                    get_stock_summary_fn,
                    get_company_context_fn,
                    compare_tickers_fn,
                    manage_watchlist_fn,
                    save_research_report_fn,
                    check_watchlist_updates_fn,
                    semantic_company_search_fn
                ]
            )

            # Query model
            response = model_with_tools.generate_content(user_query)
            
            # Extract final text
            return response.text, thoughts

        except Exception as e:
            thoughts.append(f"Agent Loop encountered error: {str(e)}")
            return f"I ran into an issue connecting to the AI brain: {str(e)}. Running mock response fallback.", thoughts

    def _run_mock_agent(self, query, thoughts):
        """
        Rule-based parser to simulate agentic workflows when GEMINI_API_KEY is not set.
        """
        query_lower = query.lower()
        
        # 1. Watchlist Updates
        if "update" in query_lower or "watchlist" in query_lower and "check" in query_lower:
            thoughts.append("Detected intent: Check watchlist updates")
            res = FinancialBroker.check_watchlist_updates()
            log_agent_activity("mock_tool:check_watchlist_updates", "success")
            return f"### Watchlist Updates Analysis\nHere are the latest movements:\n{json.dumps(res, indent=2)}", thoughts
            
        # 2. Compare Tickers
        if "compare" in query_lower:
            # Extract potential tickers (e.g. AAPL, MSFT, GOOGL)
            words = [w.strip(",").upper() for w in query.replace(",", " ").split() if len(w.strip(",").replace(".","")) in (3,4,5) and w.strip(",").isalpha()]
            tickers_to_compare = ",".join(words) if words else "AAPL,MSFT"
            thoughts.append(f"Detected intent: Compare tickers '{tickers_to_compare}'")
            res = FinancialBroker.compare_tickers(tickers_to_compare)
            log_agent_activity("mock_tool:compare_tickers", f"tickers={tickers_to_compare}")
            return f"### Stock Comparison\nComparison details:\n\n" + "\n".join([f"- **{x['ticker']}**: ${x.get('price')} (Sector: {x.get('sector')})" for x in res.get("comparison", [])]), thoughts

        # 3. Add to Watchlist
        if "add" in query_lower and ("watchlist" in query_lower or "track" in query_lower):
            words = [w.upper() for w in query.split() if w.upper() in ["AAPL", "MSFT", "GOOGL", "NVDA", "AMZN"]]
            ticker = words[0] if words else "AAPL"
            thoughts.append(f"Detected intent: Add ticker {ticker}")
            res = FinancialBroker.manage_watchlist("add", ticker)
            log_agent_activity("mock_tool:manage_watchlist_add", f"ticker={ticker}")
            return f"Successfully added **{ticker}** to your watchlist.", thoughts

        # 4. Search Company Profiles
        if "expose" in query_lower or "interest rate" in query_lower or "sector" in query_lower or "search" in query_lower:
            thoughts.append(f"Detected intent: Semantic Search")
            res = FinancialBroker.semantic_company_search(query)
            log_agent_activity("mock_tool:semantic_company_search", f"query={query}")
            results = res.get("results", [])
            output = "### Semantic Search Results\nHere are the companies matching your concept query:\n\n"
            for r in results:
                output += f"1. **{r['name']} ({r['ticker']})** - Similarity Score: {r['similarity']:.2%}\n"
                output += f"   - *Sector*: {r['sector']} | *Industry*: {r['industry']}\n"
                output += f"   - *Excerpt*: {r['filings'][:150]}...\n\n"
            return output, thoughts

        # 5. Stock summary
        words = [w.upper() for w in query.replace("?", " ").split() if w.upper() in ["AAPL", "MSFT", "GOOGL", "NVDA", "AMZN"]]
        ticker = words[0] if words else "AAPL"
        thoughts.append(f"Detected intent: Stock summary for {ticker}")
        summary = FinancialBroker.get_stock_summary(ticker)
        context = FinancialBroker.get_company_context(ticker)
        log_agent_activity("mock_tool:get_stock_summary", f"ticker={ticker}")
        
        # Save a mock analysis report if user requested "report" or "analysis"
        if "report" in query_lower or "analyze" in query_lower or "write" in query_lower:
            report_text = f"# AI Analysis Report: {ticker}\nGenerated on {datetime.datetime.now().strftime('%Y-%m-%d')}\n\n## Overview\n{context.get('profile')}\n\n## Financial Summary\n{summary.get('performance_30d')}\n\n## Risk Factors\n{context.get('filings_excerpt')}"
            FinancialBroker.save_research_report(ticker, report_text)
            log_agent_activity("mock_tool:save_research_report", f"ticker={ticker}")
            return f"### Analysis Report Generated & Saved for **{ticker}**\n\n{report_text}", thoughts

        return f"### Summary for {ticker}\n- **Company**: {context.get('name')}\n- **Price**: ${summary.get('current_price')} ({summary.get('performance_30d')})\n- **Sector**: {context.get('sector')} | **Industry**: {context.get('industry')}\n- **Profile**: {context.get('profile')}", thoughts
