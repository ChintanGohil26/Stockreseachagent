import os
import sys
from dotenv import load_dotenv

# Load env variables from local file
load_dotenv()

def deploy_secrets():
    """
    Automates uploading secrets from local .env file to Databricks Secret Scope.
    Aligns with Day 3 secrets management requirements.
    """
    print("Initializing Databricks SDK Secrets Deployer...")
    
    # Check if we have databricks-sdk installed
    try:
        from databricks.sdk import WorkspaceClient
    except ImportError:
        print("Error: databricks-sdk is not installed. Run 'pip install databricks-sdk' first.")
        sys.exit(1)

    # Resolve variables to upload
    gemini_key = os.getenv("GEMINI_API_KEY")
    lakebase_url = os.getenv("LAKEBASE_URL") or os.getenv("DATABASE_URL")
    massive_key = os.getenv("MASSIVE_STOCKS_API_KEY") or os.getenv("MASSIVE_API_KEY")

    if not any([gemini_key, lakebase_url, massive_key]):
        print("Warning: No credentials found in .env to upload. Please fill in your .env file first.")
        sys.exit(1)

    scope_name = "financial_agent_scope"

    try:
        # Initialize client (uses standard Databricks environment credentials)
        w = WorkspaceClient()
        print(f"Connected to Databricks workspace: {w.config.host}")
        
        # 1. Create secret scope
        print(f"Creating secret scope '{scope_name}'...")
        try:
            w.secrets.create_scope(scope=scope_name)
            print(f"Scope '{scope_name}' created successfully.")
        except Exception as e:
            if "RESOURCE_ALREADY_EXISTS" in str(e):
                print(f"Scope '{scope_name}' already exists. Continuing to secrets upload...")
            else:
                raise e

        # 2. Upload secrets
        if gemini_key:
            print("Uploading GEMINI_API_KEY...")
            w.secrets.put_secret(scope=scope_name, key="gemini-api-key", string_value=gemini_key)
            print("GEMINI_API_KEY uploaded.")
            
        if lakebase_url:
            print("Uploading LAKEBASE_URL...")
            w.secrets.put_secret(scope=scope_name, key="lakebase-url", string_value=lakebase_url)
            print("LAKEBASE_URL uploaded.")

        if massive_key:
            print("Uploading MASSIVE_STOCKS_API_KEY...")
            w.secrets.put_secret(scope=scope_name, key="massive-api-key", string_value=massive_key)
            print("MASSIVE_STOCKS_API_KEY uploaded.")

        print("\nAll secrets uploaded successfully. Your Databricks application can now query this scope.")
        
    except Exception as e:
        print(f"\nFailed to upload secrets to Databricks: {e}")
        print("\n=== Troubleshooting Tips ===")
        print("1. Ensure you have the Databricks CLI configured locally via 'databricks configure'.")
        print("2. Ensure your terminal has the DATABRICKS_HOST and DATABRICKS_TOKEN environment variables set.")
        print("3. Alternatively, you can run this script directly inside a Databricks Notebook cell using:")
        print("   %sh python setup_secrets.py")

if __name__ == "__main__":
    deploy_secrets()
