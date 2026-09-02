import os

def load_env_file():
    # Load .env file manually from the project root directory
    # This handles spaces around '=' and strips enclosing quotes
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env_path = os.path.join(base_dir, ".env")
    
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, val = line.split("=", 1)
                    key = key.strip()
                    val = val.strip().strip("'").strip('"').strip()
                    os.environ[key] = val
                    
    # Normalize environment variables
    if "LANG_SMITH_API_KEY" in os.environ and "LANGSMITH_API_KEY" not in os.environ:
        os.environ["LANGSMITH_API_KEY"] = os.environ["LANG_SMITH_API_KEY"]
        
    if "GOOGLE_API_KEY" in os.environ:
        # langchain-google-genai uses GOOGLE_API_KEY
        pass

# Execute load on import
load_env_file()
