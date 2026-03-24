import os, yaml, pathlib, json, uuid
from urllib.parse import urljoin

import httpx
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.utilities.logging import get_logger
from mcp.server.transport_security import TransportSecuritySettings

### Constants ###

VERSION = "2026.01.13.152335"

# Load OpenAPI spec
current_dir = pathlib.Path(__file__).parent
with open(current_dir / 'redmine_openapi.yml') as f:
    SPEC = yaml.safe_load(f)

# Constants from environment
REDMINE_URL = os.environ['REDMINE_URL'].rstrip('/') + '/'  # Normalize to always end with /
REDMINE_API_KEY = os.environ.get('REDMINE_API_KEY', '')
REDMINE_RESPONSE_FORMAT = os.environ.get('REDMINE_RESPONSE_FORMAT', 'yaml').lower()

# Multi-user support: map of user_identifier -> Redmine API key
# Can be a path to a JSON file or inline JSON string
REDMINE_USERS_MAP_SOURCE = os.environ.get('REDMINE_USERS_MAP', '')
_USERS_MAP_PATH = None  # Set if source is a file path (enables hot-reload)

def _load_users_map() -> dict:
    """Load users map from file (hot-reload) or return cached inline map."""
    global _USERS_MAP_PATH
    if _USERS_MAP_PATH:
        try:
            with open(_USERS_MAP_PATH) as f:
                return json.load(f)
        except Exception as e:
            get_logger(__name__).error(f"Failed to load users map from {_USERS_MAP_PATH}: {e}")
            return {}
    return {}

_INLINE_USERS_MAP = {}
if REDMINE_USERS_MAP_SOURCE:
    source = REDMINE_USERS_MAP_SOURCE.strip()
    if source.startswith('{'):
        # Inline JSON
        _INLINE_USERS_MAP = json.loads(source)
    else:
        # File path
        _USERS_MAP_PATH = source
        # Validate file exists at startup
        if not pathlib.Path(_USERS_MAP_PATH).exists():
            raise FileNotFoundError(f"REDMINE_USERS_MAP file not found: {_USERS_MAP_PATH}")

def _get_users_map() -> dict:
    """Get the current users map (supports hot-reload for file-based maps)."""
    if _USERS_MAP_PATH:
        return _load_users_map()
    return _INLINE_USERS_MAP

# Validate that at least one auth method is configured
if not REDMINE_API_KEY and not REDMINE_USERS_MAP_SOURCE:
    raise ValueError("Either REDMINE_API_KEY or REDMINE_USERS_MAP must be configured")

# Custom headers (format: "Header1: Value1, Header2: Value2")
REDMINE_HEADERS = {}
if custom_headers := os.environ.get('REDMINE_HEADERS', ''):
    for header in custom_headers.split(','):
        if ':' in header:
            key, value = header.split(':', 1)
            REDMINE_HEADERS[key.strip()] = value.strip()

# Allowed directories for upload/download (secure by default - disabled if not set)
REDMINE_ALLOWED_DIRECTORIES = [
    pathlib.Path(d.strip()).resolve()
    for d in os.environ.get('REDMINE_ALLOWED_DIRECTORIES', '').split(',')
    if d.strip()
]

# SSL verification (disabled only when explicitly set to "1")
REDMINE_DANGEROUSLY_ACCEPT_INVALID_CERTS = os.environ.get('REDMINE_DANGEROUSLY_ACCEPT_INVALID_CERTS') == '1'

if "REDMINE_REQUEST_INSTRUCTIONS" in os.environ:
    with open(os.environ["REDMINE_REQUEST_INSTRUCTIONS"]) as f:
        REDMINE_REQUEST_INSTRUCTIONS = f.read()
else:
    REDMINE_REQUEST_INSTRUCTIONS = ""


# Core

def resolve_api_key(user_identifier: str = None) -> str:
    """Resolve Redmine API key from user_identifier or fall back to global key.

    Resolution order:
    1. If user_identifier provided and REDMINE_USERS_MAP configured -> lookup in map (error if not found)
    2. If no user_identifier -> use global REDMINE_API_KEY
    3. If nothing available -> raise error
    """
    if user_identifier:
        users_map = _get_users_map()
        if users_map:
            key = users_map.get(user_identifier)
            if key:
                return key
            raise ValueError(
                f"Unknown user_identifier: '{user_identifier}'. "
                f"User not found in REDMINE_USERS_MAP configuration."
            )
        # No map configured but user_identifier provided - fall through to global key
    if REDMINE_API_KEY:
        return REDMINE_API_KEY
    raise ValueError(
        "No API key available. Either provide a valid user_identifier "
        "(mapped in REDMINE_USERS_MAP) or configure REDMINE_API_KEY."
    )


def request(path: str, method: str = 'get', data: dict = None, params: dict = None,
            content_type: str = 'application/json', content: bytes = None,
            api_key: str = None) -> dict:
    headers = {
        'X-Redmine-API-Key': api_key or REDMINE_API_KEY,
        'Content-Type': content_type,
        **REDMINE_HEADERS
    }
    url = urljoin(REDMINE_URL, path.lstrip('/'))

    try:
        response = httpx.request(method=method.lower(), url=url, json=data, params=params, headers=headers,
                                 content=content, timeout=60.0, verify=not REDMINE_DANGEROUSLY_ACCEPT_INVALID_CERTS)
        response.raise_for_status()

        body = None
        if response.content:
            try:
                body = response.json()
            except ValueError:
                body = response.content

        return {"status_code": response.status_code, "body": body, "error": ""}
    except Exception as e:
        try:
            status_code = e.response.status_code
        except:
            status_code = 0

        try:
            body = e.response.json()
        except:
            try:
                body = e.response.text
            except:
                body = None

        return {"status_code": status_code, "body": body, "error": f"{e.__class__.__name__}: {e}"}

def format_response(obj):
    """Format response as YAML or JSON based on REDMINE_RESPONSE_FORMAT env var."""
    if REDMINE_RESPONSE_FORMAT == 'json':
        return json.dumps(obj, ensure_ascii=False, indent=2, default=str)
    # YAML: Allow direct Unicode output, prevent line wrapping for long lines, and avoid automatic key sorting.
    return yaml.safe_dump(obj, allow_unicode=True, sort_keys=False, width=4096)


def wrap_insecure_content(content: str) -> str:
    """Wrap content that may contain user-generated data with security tags to prevent prompt injection."""
    tag_id = uuid.uuid4().hex[:16]
    return f"<insecure-content-{tag_id}>\n{content}\n</insecure-content-{tag_id}>"


def validate_path(file_path: str, must_exist: bool = True) -> tuple[str | None, pathlib.Path | None]:
    """
    Validate and resolve a file path.
    Returns (None, resolved_path) on success, (error_message, None) on failure.
    """
    # Require allowed directories to be configured (secure by default)
    if not REDMINE_ALLOWED_DIRECTORIES:
        return "File operations disabled: REDMINE_ALLOWED_DIRECTORIES not configured", None

    try:
        path = pathlib.Path(file_path).expanduser().resolve()
    except Exception as e:
        return f"Invalid path: {file_path} ({e})", None

    if not path.is_absolute():
        return f"Path must be absolute, got: {file_path}", None

    # Check path is within allowed directories
    if not any(path.is_relative_to(allowed) for allowed in REDMINE_ALLOWED_DIRECTORIES):
        return f"Path not in allowed directories: {file_path}", None

    if must_exist and not path.exists():
        return f"File not found: {path}", None

    return None, path


# Tools
mcp = FastMCP("Redmine MCP server")
get_logger(__name__).info(f"Starting MCP Redmine version {VERSION}")

@mcp.tool(description="""
Make a request to the Redmine API.

IMPORTANT: The 'user_identifier' parameter is REQUIRED for every request in multi-user deployments.
It must be passed via the tool call arguments. The orchestrator (e.g. n8n) MUST include the
user's identifier (typically their email address) in every tool call so that the correct
Redmine API key is resolved for each user.

Args:
    path: API endpoint path (e.g. '/issues.json')
    method: HTTP method to use (default: 'get')
    data: Dictionary for request body (for POST/PUT)
    params: Dictionary for query parameters
    user_identifier: User identifier (e.g. email) for multi-user API key resolution. MUST be provided by the orchestrator for every request.

Returns:
    str: YAML string containing response status code, body and error message

{}""".format(REDMINE_REQUEST_INSTRUCTIONS).strip())

def redmine_request(path: str, method: str = 'get', data: dict = None, params: dict = None,
                    user_identifier: str = None) -> str:
    try:
        api_key = resolve_api_key(user_identifier)
    except ValueError as e:
        return format_response({"status_code": 0, "body": None, "error": str(e)})
    return wrap_insecure_content(format_response(request(path, method=method, data=data, params=params, api_key=api_key)))

@mcp.tool()
def redmine_paths_list() -> str:
    """Return a list of available API paths from OpenAPI spec

    Retrieves all endpoint paths defined in the Redmine OpenAPI specification. Remember that you can use the
    redmine_paths_info tool to get the full specfication for a path.

    Returns:
        str: YAML string containing a list of path templates (e.g. '/issues.json')
    """
    return format_response(list(SPEC['paths'].keys()))

@mcp.tool()
def redmine_paths_info(path_templates: list) -> str:
    """Get full path information for given path templates

    Args:
        path_templates: List of path templates (e.g. ['/issues.json', '/projects.json'])

    Returns:
        str: YAML string containing API specifications for the requested paths
    """
    info = {}
    for path in path_templates:
        if path in SPEC['paths']:
            info[path] = SPEC['paths'][path]

    return format_response(info)

@mcp.tool()
def redmine_upload(file_path: str, description: str = None, user_identifier: str = None) -> str:
    """
    Upload a file to Redmine and get a token for attachment.

    IMPORTANT: The 'user_identifier' parameter is REQUIRED for every request in multi-user deployments.
    The orchestrator (e.g. n8n) MUST include the user's identifier (typically their email address)
    in every tool call so that the correct Redmine API key is resolved for each user.

    Args:
        file_path: Fully qualified path to the file to upload (must be within REDMINE_ALLOWED_DIRECTORIES)
        description: Optional description for the file
        user_identifier: User identifier (e.g. email) for multi-user API key resolution. MUST be provided by the orchestrator for every request.

    Returns:
        str: YAML string containing response status code, body and error message
             The body contains the attachment token
    """
    try:
        api_key = resolve_api_key(user_identifier)
    except ValueError as e:
        return format_response({"status_code": 0, "body": None, "error": str(e)})

    error, path = validate_path(file_path, must_exist=True)
    if error:
        return format_response({"status_code": 0, "body": None, "error": error})

    try:
        params = {'filename': path.name}
        if description:
            params['description'] = description

        with open(path, 'rb') as f:
            file_content = f.read()

        result = request(path='uploads.json', method='post', params=params,
                         content_type='application/octet-stream', content=file_content, api_key=api_key)
        return format_response(result)
    except Exception as e:
        return format_response({"status_code": 0, "body": None, "error": f"{e.__class__.__name__}: {e}"})

@mcp.tool()
def redmine_download(attachment_id: int, save_path: str, filename: str = None,
                     user_identifier: str = None) -> str:
    """
    Download an attachment from Redmine and save it to a local file.

    IMPORTANT: The 'user_identifier' parameter is REQUIRED for every request in multi-user deployments.
    The orchestrator (e.g. n8n) MUST include the user's identifier (typically their email address)
    in every tool call so that the correct Redmine API key is resolved for each user.

    Args:
        attachment_id: The ID of the attachment to download
        save_path: Fully qualified path where the file should be saved to (must be within REDMINE_ALLOWED_DIRECTORIES)
        filename: Optional filename to use for the attachment. If not provided,
                 will be determined from attachment data or URL
        user_identifier: User identifier (e.g. email) for multi-user API key resolution. MUST be provided by the orchestrator for every request.

    Returns:
        str: YAML string containing download status, file path, and any error messages
    """
    try:
        api_key = resolve_api_key(user_identifier)
    except ValueError as e:
        return format_response({"status_code": 0, "body": None, "error": str(e)})

    error, path = validate_path(save_path, must_exist=False)
    if error:
        return format_response({"status_code": 0, "body": None, "error": error})

    if path.is_dir():
        return format_response({"status_code": 0, "body": None, "error": f"Path can't be a directory: {save_path}"})

    try:
        if not filename:
            attachment_response = request(f"attachments/{attachment_id}.json", "get", api_key=api_key)
            if attachment_response["status_code"] != 200:
                return format_response(attachment_response)

            filename = attachment_response["body"]["attachment"]["filename"]

        response = request(f"attachments/download/{attachment_id}/{filename}", "get",
                           content_type="application/octet-stream", api_key=api_key)
        if response["status_code"] != 200 or not response["body"]:
            return format_response(response)

        # Create parent directories if needed
        path.parent.mkdir(parents=True, exist_ok=True)

        with open(path, 'wb') as f:
            f.write(response["body"])

        return format_response({"status_code": 200, "body": {"saved_to": str(path), "filename": filename}, "error": ""})
    except Exception as e:
        return format_response({"status_code": 0, "body": None, "error": f"{e.__class__.__name__}: {e}"})

def main():
    """Main entry point for the mcp-redmine package."""
    import argparse
    parser = argparse.ArgumentParser(description="MCP Redmine Server")
    parser.add_argument("--transport", choices=["stdio", "sse"], default="stdio",
                        help="Transport type (default: stdio)")
    parser.add_argument("--host", default="0.0.0.0", help="Host for SSE transport (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8000, help="Port for SSE transport (default: 8000)")
    args = parser.parse_args()

    if args.transport == "sse":
        mcp.settings.host = args.host
        mcp.settings.port = args.port
        # Disable DNS rebinding protection for SSE transport.
        # This server is designed for closed/trusted networks only.
        mcp.settings.transport_security = TransportSecuritySettings(
            enable_dns_rebinding_protection=False,
        )
    mcp.run(transport=args.transport)

if __name__ == "__main__":
    main()
