"""MCP Client for interacting with an MCP server."""

import os
from contextlib import AsyncExitStack
from copy import copy
import asyncio
import uuid

from mcp import ClientSession, StdioServerParameters
from mcp.client.sse import sse_client
from mcp.client.stdio import stdio_client
from mcp.types import Tool

from google import genai
from google.genai import types
from dotenv import load_dotenv
from urllib.parse import urlparse, quote_plus


load_dotenv()  # load environment variables from .env


# AUX FUNCTIONS
def _is_url(string: str) -> bool:
    try:
        result = urlparse(string)
        return all([result.scheme, result.netloc])
    except Exception:  # pylint: disable=broad-except
        return False


class MCPClient:
    """A base client for interacting with an MCP server."""

    def __init__(self, client_id: str | None = None):
        """Initializes the MCPClient with an optional client ID.

        Args:
            client_id (str | None): Client ID to be used for authentication. Defaults to None.
        """
        # Initialize session and client objects
        self.session: ClientSession | None = None
        self.exit_stack: AsyncExitStack = AsyncExitStack()
        # Generate a client_id if not provided
        self.client_id = client_id or str(uuid.uuid4())
        self.server_url = None

    async def connect_to_server(self, server_path: str):
        """Connect to an MCP server.

        Args:
            server_path (str): Path to the server script (.py or .js) or URL for web server

        Raises:
            ValueError: If the server path is not a .py file, .js file, or web URL
        """
        is_python = server_path.endswith(".py")
        is_js = server_path.endswith(".js")
        is_web = _is_url(server_path)

        if not (is_python or is_js or is_web):
            raise ValueError("Server must be a .py file, .js file, or web URL")

        if is_web:
            self.server_url = server_path

            headers = {}
            if self.client_id:
                headers["X-Client-ID"] = (
                    f"{self.client_id}"  # Set client_id in headers so server can identify the client
                )

            sse_url = f"{server_path}/sse"
            transport = await self.exit_stack.enter_async_context(
                sse_client(sse_url, headers=headers)
            )
        else:  # For MCP Servers as scripts local scripts, use stdio transport
            command = "python" if is_python else "node"
            server_params = StdioServerParameters(
                command=command, args=[server_path], env=None
            )

            transport = await self.exit_stack.enter_async_context(
                stdio_client(server_params)
            )
        self.stdio, self.write = transport
        self.session = await self.exit_stack.enter_async_context(
            ClientSession(self.stdio, self.write)
        )

        await self.session.initialize()

        # List available tools and print them so we can see what tools are available # This can be removed if not needed
        response = await self.session.list_tools()
        tools = response.tools
        for tool in tools:
            print(f"Tool: {tool.name}")
            print(f"Description: {tool.description}")

    async def authenticate_with_mcp_server(self):
        """Authenticate user with Google Drive using client_id based authentication."""
        # Check if user is already authenticated
        if self.session:
            # Check authentication status with our client_id
            result = await self.session.call_tool(
                "check_authentication_status", {}
            )  # TODO: Think if this should be a tool call or a http request

            if result.content[0].text == "authenticated":
                print("Already authenticated with Google Drive.")
            else:
                print("Authentication needed with Google Drive.")

                # Add client_id to authentication URL
                auth_url = f"{self.server_url}/authorize?client_id={quote_plus(self.client_id)}"

                print("Please complete the Google authentication process.")
                print(
                    f"Open the following URL in your browser to authenticate: {auth_url}"
                )

                # Wait for authentication to complete
                while True:
                    await asyncio.sleep(5)  # Check every 5 seconds
                    result = await self.session.call_tool(
                        "check_authentication_status", {}
                    )
                    if result.content[0].text == "authenticated":
                        print("Authentication successful!")
                        break
                    print("Waiting for authentication to complete...")
        else:
            print("Cannot authenticate: Not connected to server.")

    async def query(self, query: str, tools: list[Tool] | None = None) -> str:
        """Query the model with a given query and tools."""
        raise NotImplementedError("This method should be implemented by the subclass")

    async def chat_loop(self):
        """Run an interactive chat loop."""
        print("\nMCP Client Started!")
        print("Type your queries or 'help' to know available commands.")
        print(f"Using client ID: {self.client_id}")

        # Attempt authentication first
        await self.authenticate_with_mcp_server()

        while True:
            print()
            query = input("Query: ")

            # Special commands
            if query.lower() == "help":
                print("Available commands:")
                print("quit or exit: Exit the chat")
                print("login: Authenticate with the MCP server")
                print("tools: List available tools")
                continue

            if query.lower() in ["quit", "exit"]:
                break

            if query.lower() == "login":
                await self.authenticate_with_mcp_server()
                continue

            if query.lower() == "tools":
                tools_response = await self.session.list_tools()
                available_tools = tools_response.tools
                print(available_tools)
                continue

            try:
                # Get available tools for this query
                tools_response = (
                    await self.session.list_tools()
                )  # TODO: Should we get the tools every time or just once?
                available_tools = tools_response.tools
                response = await self.query(query, tools=available_tools)
                print(response)
            except Exception as e: # pylint: disable=broad-except
                print(f"Error: {e}")

    async def cleanup(self):
        """Clean up resources."""
        if self.exit_stack:
            await self.exit_stack.aclose()


class GeminiMCPClient(MCPClient):
    """A client for interacting with an LLM via an MCP server, specifically using Gemini."""

    def __init__(
        self,
        model: str | None = None,
        config: types.GenerateContentConfig | None = None,
        client_id: str | None = None,  # Added client_id
    ):
        """Initializes the GeminiMCPClient with a Gemini model and configuration.

        Args:
            model (str | None): The Gemini model to use. Defaults to the DEFAULT_MODEL environment variable.
            config (types.GenerateContentConfig | None): Configuration for content generation. Defaults to None.
            client_id (str | None): Client ID to be used for authentication. Defaults to None.
        """
        super().__init__(client_id)  # Call parent constructor

        self.model = model or os.getenv("DEFAULT_MODEL")
        self.genai_client = genai.Client(
            vertexai=True,
            project=os.getenv("PROJECT"),
            location=os.getenv("LOCATION"),
        )

        if config is None:
            self.config = types.GenerateContentConfig(
                temperature=float(os.getenv("DEFAULT_TEMPERATURE") or 0.7),
                top_p=float(os.getenv("DEFAULT_TOP_P") or 0.95),
                max_output_tokens=int(os.getenv("DEFAULT_MAX_OUTPUT_TOKENS") or 1000),
                response_modalities=["TEXT"],
                safety_settings=[
                    types.SafetySetting(
                        category="HARM_CATEGORY_HATE_SPEECH", threshold="OFF"
                    ),
                    types.SafetySetting(
                        category="HARM_CATEGORY_DANGEROUS_CONTENT", threshold="OFF"
                    ),
                    types.SafetySetting(
                        category="HARM_CATEGORY_SEXUALLY_EXPLICIT", threshold="OFF"
                    ),
                    types.SafetySetting(
                        category="HARM_CATEGORY_HARASSMENT", threshold="OFF"
                    ),
                ],
            )
        else:
            self.config = config

    def _query_model(
        self, contents: list[types.Content], tools: list[Tool] | None = None
    ) -> types.GenerateContentResponse:  # Added return type hint
        """Internal method to query the Gemini model."""
        mcp_tools = self._parse_tools(tools)

        generate_content_config = copy(self.config)

        if mcp_tools:
            generate_content_config.tools = [
                types.Tool(function_declarations=mcp_tools)
            ]

        return self.genai_client.models.generate_content(
            model=self.model,
            contents=contents,
            config=generate_content_config,
        )

    def _parse_tools(self, tools: list[Tool] | None):
        """Convert MCP tools to Gemini function declarations."""
        if not tools:
            return []

        tool_functions = []
        for tool in tools:
            parameters = {"type": "OBJECT", "properties": {}}

            # Convert input schema to Gemini parameter format
            input_schema = tool.inputSchema if hasattr(tool, "inputSchema") else {}
            if input_schema and "properties" in input_schema:
                for prop_name, prop_details in input_schema["properties"].items():
                    prop_details_dict = (
                        prop_details if isinstance(prop_details, dict) else {}
                    )
                    parameters["properties"][prop_name] = {
                        "type": prop_details_dict.get("type", "STRING").upper(),
                        "description": prop_details_dict.get("description", ""),
                    }

            if input_schema and "required" in input_schema:
                parameters["required"] = input_schema["required"]
            # Create function declaration
            tool_functions.append(
                types.FunctionDeclaration(
                    name=tool.name, description=tool.description, parameters=parameters
                )
            )
        return tool_functions

    async def query(
        self, query: str, tools: list[Tool] | None = None
    ) -> str:  # Implement the query method
        """Process a query using Gemini and available tools."""
        if not self.session:
            raise ConnectionError(
                "Not connected to a server. Call connect_to_server first."
            )

        contents = [
            types.Content(role="user", parts=[types.Part.from_text(text=query)])
        ]
        response = self._query_model(contents, tools)

        # Process response and handle tool calls
        final_text_parts = []

        while response.candidates and response.candidates[0].content.parts:
            candidate = response.candidates[0]
            content = candidate.content
            has_tool_call = False

            for part in content.parts:
                if hasattr(part, "text") and part.text:
                    final_text_parts.append(part.text)
                elif hasattr(part, "function_call") and part.function_call:
                    has_tool_call = True
                    tool_name = part.function_call.name
                    tool_args = dict(part.function_call.args)  # Convert args to dict

                    # Execute tool call (server extracts client_id from header)
                    try:
                        # Ensure session exists before calling tool
                        if not self.session:
                            raise ConnectionError("Session is not initialized.")
                        result = await self.session.call_tool(tool_name, tool_args)
                        # Append tool call info for context, maybe make this optional?
                        # final_text_parts.append(f"[Calling tool {tool_name} with args {tool_args}]")

                        # Create function response Part
                        function_response_part = types.Part(
                            function_response={
                                "name": tool_name,
                                "response": {
                                    "content": result.content
                                },  # Assuming result.content is the expected format
                            }
                        )

                        # Add assistant's tool call Part to the history
                        contents.append(types.Content(role="model", parts=[part]))
                        # Add tool execution result Part to the history
                        contents.append(
                            types.Content(role="user", parts=[function_response_part])
                        )  # Role should be 'user' or 'function' based on API

                        # Get next response from Gemini with updated history and the same tools
                        response = self._query_model(contents, tools)
                        break  # Process the new response in the next iteration

                    except Exception as e: # pylint: disable=broad-except
                        print(f"Error calling tool {tool_name}: {e}")
                        # Decide how to handle tool call errors, maybe respond to user?
                        return f"Error executing tool {tool_name}: {e}"  # Or return an error message

            if not has_tool_call:
                # If the last response had no tool calls, break the loop
                break

        return "\n".join(final_text_parts)  # Combine final text parts
