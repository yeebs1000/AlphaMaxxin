import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from runner import run_agent

# Windows consoles default to cp1252, which can't encode the emoji agent
# reports often contain — reconfigure to UTF-8 so this doesn't crash.
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

async def main():
    # If you pass an agent name in the terminal, it runs that. Otherwise, defaults to China Market Agent.
    target_agent = sys.argv[1] if len(sys.argv) > 1 else "China Market Agent"
    
    print(f"Executing: {target_agent}...")
    print("-" * 50)
    
    # Run the agent locally and unpack the async coroutine
    result = await run_agent(target_agent)
    
    print(result)
    print("-" * 50)

if __name__ == "__main__":
    asyncio.run(main())