import os
from dotenv import load_dotenv
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from fastmcp import FastMCP
from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.responses import RedirectResponse
import uuid
from starlette.routing import Mount
from fastmcp.server.dependencies import get_http_request
from google.oauth2 import id_token
from google.auth.transport import requests

load_dotenv()  # load environment variables from .env

# Initialize FastMCP server
mcp = FastMCP("Drive MCP Server")

# Define the scopes for Google Drive API
SCOPES = [
    "https://www.googleapis.com/auth/drive.metadata.readonly",
    "https://www.googleapis.com/auth/userinfo.profile",
    "https://www.googleapis.com/auth/userinfo.email",
    "openid",
]

# Create FastAPI app
app = FastAPI()

# In-memory storage for credentials
credentials_store = {}  # {client_id: {credentials}}
# In-memory storage for OAuth state and associated client_id
oauth_states = {}  # {state: client_id}

REDIRECT_URI = f"http://{os.getenv('HOST')}:{os.getenv('PORT')}/oauth2callback"


async def get_client_id_from_request(request: Request):
    """Get client_id from query parameters (for initial authorization)."""
    client_id = request.query_params.get("client_id")
    if not client_id:
        raise HTTPException(
            status_code=400,
            detail="client_id query parameter is required for authorization",
        )
    return client_id


@app.get("/authorize")
async def authorize(
    request: Request, client_id: str = Depends(get_client_id_from_request)
):
    """Redirect the user to Google's OAuth 2.0 server. Uses client_id from query param."""
    # Generate a unique state for this OAuth flow
    state = str(uuid.uuid4())

    request.query_params.get("client_id")

    # Store client_id associated with this state
    oauth_states[state] = client_id
    print(f"Storing state {state} for client_id {client_id}")

    flow = Flow.from_client_secrets_file(
        "credentials.json", scopes=SCOPES, redirect_uri=REDIRECT_URI
    )

    authorization_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
        state=state,
    )

    return RedirectResponse(authorization_url)


@app.get("/oauth2callback")
async def oauth2callback(request: Request, code: str, state: str):
    """Handle the OAuth 2.0 redirect."""
    try:
        # Verify state and get associated client_id
        if state not in oauth_states:
            print(f"State {state} not found in oauth_states: {oauth_states.keys()}")
            raise HTTPException(status_code=400, detail="Invalid state parameter")

        client_id = oauth_states.pop(state)  # Retrieve and remove state
        print(f"Retrieved client_id {client_id} for state {state}")

        flow = Flow.from_client_secrets_file(
            "credentials.json", scopes=SCOPES, redirect_uri=REDIRECT_URI
        )
        flow.fetch_token(code=code)
        credentials = flow.credentials

        # Get user info
        service = build("oauth2", "v2", credentials=credentials)
        user_info = service.userinfo().get().execute()
        user_id = user_info.get("email")

        if not user_id:
            raise HTTPException(status_code=400, detail="Could not retrieve user email")
        # Store credentials in our in-memory store using client_id
        credentials_store[client_id] = {
            "token": credentials.token,
            "refresh_token": credentials.refresh_token,
            "token_uri": credentials.token_uri,
            "client_id": credentials.client_id,
            "client_secret": credentials.client_secret,
            "scopes": credentials.scopes,
        }

        print(f"Stored credentials for client: {client_id}")

        # Return success with client_id
        return f"Authentication successful for user: {user_id}, You can close this window now."
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Authentication error: {str(e)}")


async def get_drive_service(client_id: str):
    """Get Drive service from client credentials."""
    if not client_id:
        raise ValueError("No client_id provided")

    if client_id not in credentials_store:
        raise ValueError(f"No credentials found for client_id: {client_id}")

    creds_data = credentials_store[client_id]
    print(f"Retrieved credentials from store for client: {client_id}")

    # Create credentials object
    creds = Credentials(
        token=creds_data["token"],
        refresh_token=creds_data.get("refresh_token"),
        token_uri=creds_data["token_uri"],
        client_id=creds_data["client_id"],
        client_secret=creds_data["client_secret"],
        scopes=creds_data["scopes"],
    )

    # Refresh token if expired
    if creds.expired and creds.refresh_token:
        print("Refreshing token")
        creds.refresh(Request())
        # Update in-memory store
        creds_data["token"] = creds.token
        credentials_store[client_id] = creds_data

    return build("drive", "v3", credentials=creds)


@mcp.tool()
async def search_drive_files(query: str) -> str:
    """
    Search for files in Google Drive using a query string that follows the Google Drive API query syntax.

    Args:
        query: Search query to find files (e.g., "name contains 'report'" or "mimeType='application/pdf'")

    Query examples:
    - Find all PDF files in my drive -> search_drive_files("mimeType='application/pdf'")
    - Search for documents with 'report' in the name -> search_drive_files("name contains 'report'")
    - Find files modified after a specific date (2025-01-01) -> search_drive_files("modifiedTime > '2025-01-01'")
    - Find all files with 'report' in the name and return the link and the name and the mimeType and the size
    - Find Google Docs named 'Meeting Notes' modified after January 1, 2025: -> mimeType = 'application/vnd.google-apps.document' and name contains 'Meeting Notes' and modifiedTime > '2025-01-01T00:00:00'

    """
    try:
        request = get_http_request()
        client_id = request.headers.get("X-Client-ID")

        if not client_id:
            return "No client_id provided for authentication."

        service = await get_drive_service(client_id=client_id)
        results = (
            service.files()
            .list(
                q=query,
                pageSize=10,
                fields="nextPageToken, files(id, name, mimeType, webViewLink)",
            )
            .execute()
        )

        items = results.get("files", [])
        if not items:
            return "No files found matching your query."

        # Format the results
        file_list = ["Files found:"]
        for item in items:
            file_info = f"- {item['name']} ({item['mimeType']})"
            if "webViewLink" in item:
                file_info += f"\n  Link: {item['webViewLink']}"
            file_list.append(file_info)

        return "\n".join(file_list)
    except Exception as e:
        print(e)
        return f"Error searching files: {str(e)}"


@mcp.tool()
async def check_authentication_status() -> str:
    """
    Check if a user is authenticated based on the X-Client-ID header.
    """
    request = get_http_request()
    client_id = request.headers.get("X-Client-ID")
    # TODO: Validate client_id
    if not client_id:
        # This case should theoretically be handled by the dependency now
        return "No X-Client-ID header provided for authentication check."

    print(f"Checking auth status for client_id: {client_id} from header")

    # Check our in-memory store
    if client_id in credentials_store:
        return f"authenticated"
    else:
        return "not authenticated"


# Mount the MCP SSE app at a specific path instead of root
app.router.routes.append(Mount("/", app=mcp.sse_app()))

if __name__ == "__main__":
    import uvicorn

    host = os.getenv("HOST")
    port = os.getenv("PORT")
    print(f"Starting Google Drive MCP server on http://{host}:{port}")

    uvicorn.run(app, host=host, port=int(port))
