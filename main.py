import asyncio
import sys
from mcp_client import GeminiMCPClient


async def main():
    """
    Example of connecting to and using the MCP server.
    """
    if len(sys.argv) < 2:
        # Default to local server if no argument is provided
        server_path = "http://localhost:8081"
    else:
        server_path = sys.argv[1]

    print(f"Connecting to Drive MCP server at: {server_path}")

    # Create client and connect to the server
    client = GeminiMCPClient()
    try:
        await client.connect_to_server(server_path)

        # Example of how the chat loop works
        print("\nDrive MCP Client Started!")
        print("Type your queries about Google Drive or 'quit' to exit.")
        print("Example queries:")
        print("- List spreadsheets modified in the last week")

        # Start the interactive chat loop
        await client.chat_loop()

    finally:
        await client.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
