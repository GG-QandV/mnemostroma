import asyncio
import json
import sys
from pathlib import Path

# Add src to sys.path to allow imports
project_root = Path(__file__).resolve().parents[2]
sys.path.append(str(project_root / "src"))

try:
    from mnemostroma.integration.mcp_server import list_tools
except ImportError as e:
    print(f"Error: Could not import mcp_server. Check PYTHONPATH. {e}")
    sys.exit(1)

async def main():
    # 1. Get tool definitions from mcp_server.py
    # Since list_tools is an async function decorated with @app.list_tools()
    # we can call it directly to get the Tool objects.
    tools = await list_tools()
    
    # 2. Convert Tool objects to serialized dicts
    tool_schemas = []
    for tool in tools:
        tool_schemas.append({
            "name": tool.name,
            "description": tool.description,
            "inputSchema": tool.inputSchema
        })
    
    # 3. Output as JSON
    print(json.dumps(tool_schemas, indent=4, ensure_ascii=False))

if __name__ == "__main__":
    asyncio.run(main())
