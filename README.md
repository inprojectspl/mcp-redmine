# MCP Redmine

**Status: Works great and is in daily use without any known bugs.**

**Status2: I just added the package to PyPI and updated the usage instructions. Please report any issues :)**

Let Claude be your Redmine assistant! MCP Redmine connects Claude Desktop to your Redmine instance, allowing it to:

- Search and browse projects and issues
- Create and update issues with full markdown support
- Upload and download file attachments
- Manage and track time entries
- Update issue statuses and fields
- Access comprehensive Redmine API functionality
- **Multi-user support** via user identifier to API key mapping (for orchestrated environments like n8n + OpenWebUI)

Uses httpx for API requests and integrates with the Redmine OpenAPI specification for comprehensive API coverage.

![MCP Redmine in action](https://raw.githubusercontent.com/runekaagaard/mcp-redmine/refs/heads/main/screenshot.png)

> [!CAUTION]
> **Multi-user mode is designed exclusively for use in closed, trusted networks (e.g. internal company infrastructure behind a VPN/firewall). It must NEVER be exposed to the public internet.** The user-to-API-key mapping file contains sensitive credentials. The `user_identifier` parameter is passed as a plain tool call argument and is not cryptographically verified — any client that can reach this MCP server can impersonate any user. Only deploy this in environments where all clients are trusted and network access is strictly controlled.


## Usage with Claude Desktop
### 1. Installation using `uv`

Ensure you have uv installed.
```bash
uv --version
```

Install uv if you haven't already.

- Linux
  ```bash
  curl -LsSf https://astral.sh/uv/install.sh | sh
  ```

- macOS
  ```zsh
  brew install uv
  ```

- windows
  ```powershell
  powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
  ```

Add to your `claude_desktop_config.json`:
```json
  {
    "mcpServers": {
      "redmine": {
        "command": "uvx",
        "args": ["--from", "mcp-redmine==2026.01.13.152335",
                "--refresh-package", "mcp-redmine", "mcp-redmine"],
        "env": {
          "REDMINE_URL": "https://your-redmine-instance.example.com",
          "REDMINE_API_KEY": "your-api-key",
          "REDMINE_REQUEST_INSTRUCTIONS": "/path/to/instructions.md",
          "REDMINE_ALLOWED_DIRECTORIES": "/tmp,/home/user/uploads"
        }
      }
    }
  }
```

### 2. Installation using `docker`

Ensure you have docker installed.
```bash
docker --version
```

Build docker image:
```bash
git clone git@github.com:runekaagaard/mcp-redmine.git
cd mcp-redmine
docker build -t mcp-redmine .
```
Add to your `claude_desktop_config.json`:
  ```json
  {
    "mcpServers": {
      "redmine": {
        "command": "docker",
        "args":  [
            "run",
            "-i",
            "--rm",
            "-e", "REDMINE_URL",
            "-e", "REDMINE_API_KEY",
            "-e", "REDMINE_REQUEST_INSTRUCTIONS",
            "-e", "REDMINE_ALLOWED_DIRECTORIES",
            "-v", "/path/to/instructions.md:/app/INSTRUCTIONS.md",
            "-v", "/path/to/uploads:/app/uploads",
            "mcp-redmine"
        ],
        "env": {
          "REDMINE_URL": "https://your-redmine-instance.example.com",
          "REDMINE_API_KEY": "your-api-key",
          "REDMINE_REQUEST_INSTRUCTIONS": "/app/INSTRUCTIONS.md",
          "REDMINE_ALLOWED_DIRECTORIES": "/app/uploads"
        }
      }
    }
  }
  ```

## Multi-User Mode (n8n + OpenWebUI)

Multi-user mode allows a single MCP server instance to serve multiple Redmine users, each authenticated with their own API key. This is designed for orchestrated environments where a middleware (like **n8n**) sits between the user-facing UI (like **OpenWebUI**) and this MCP server.

> [!CAUTION]
> **This mode is intended ONLY for closed, trusted networks.** See the security warning at the top of this document.

### How It Works

```
User (OpenWebUI) ──→ n8n (knows user email) ──→ MCP tool call + user_identifier ──→ mcp-redmine ──→ Redmine API
```

1. The user chats in OpenWebUI, which passes the user's email to n8n.
2. n8n calls MCP tools and includes the `user_identifier` parameter (the user's email) in **every** tool call.
3. mcp-redmine looks up the user's Redmine API key from the configured users map file.
4. The request is made to Redmine using that user's API key, so all actions respect that user's Redmine permissions.

### Configuration

#### 1. Create a users map file

Create a JSON file mapping user identifiers (emails) to their Redmine API keys:

```json
{
  "jan.kowalski@company.com": "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2",
  "anna.nowak@company.com": "f6e5d4c3b2a1f6e5d4c3b2a1f6e5d4c3b2a1f6e5"
}
```

Save it e.g. as `/config/redmine_users.json`.

> **Hot-reload**: The users map file is re-read on every request. You can add or remove users without restarting the MCP server.

#### 2. Configure environment variables

Set `REDMINE_USERS_MAP` instead of (or in addition to) `REDMINE_API_KEY`:

```bash
# Required
REDMINE_URL=https://redmine.company.com
REDMINE_USERS_MAP=/config/redmine_users.json

# Optional: fallback key used when no user_identifier is provided
REDMINE_API_KEY=fallback-api-key
```

Alternatively, for simple setups, you can pass the map as inline JSON:

```bash
REDMINE_USERS_MAP='{"jan.kowalski@company.com": "key1", "anna.nowak@company.com": "key2"}'
```

#### 3. Docker deployment example (SSE transport)

```bash
docker run -d \
  --name mcp-redmine \
  -e REDMINE_URL=https://redmine.company.com \
  -e REDMINE_USERS_MAP=/config/redmine_users.json \
  -v /path/to/redmine_users.json:/config/redmine_users.json:ro \
  -p 8000:8000 \
  mcp-redmine \
  --transport sse --host 0.0.0.0 --port 8000
```

### n8n Integration

When calling MCP tools from n8n, **every tool call MUST include the `user_identifier` parameter**. This is how the server knows which user's API key to use.

Example n8n tool call payload:

```json
{
  "tool": "redmine_request",
  "arguments": {
    "path": "/issues.json",
    "method": "get",
    "params": {"project_id": "my-project"},
    "user_identifier": "jan.kowalski@company.com"
  }
}
```

Another example (creating an issue):

```json
{
  "tool": "redmine_request",
  "arguments": {
    "path": "/issues.json",
    "method": "post",
    "data": {
      "issue": {
        "project_id": 1,
        "subject": "New task",
        "description": "Task description"
      }
    },
    "user_identifier": "jan.kowalski@company.com"
  }
}
```

### API Key Resolution Logic

The server resolves the API key in this order:

1. **`user_identifier` provided + `REDMINE_USERS_MAP` configured** → Look up key in map. If user not found → **error** (no fallback, to prevent accidental use of wrong identity).
2. **No `user_identifier` provided** → Use global `REDMINE_API_KEY` (if configured).
3. **Neither available** → Error.

### LLM System Prompt Integration

If an LLM is involved in the tool-calling chain (e.g. OpenWebUI → LLM → n8n → MCP), the LLM's system prompt should instruct it to always pass the user identifier. Example system prompt addition:

```
When calling any Redmine MCP tool (redmine_request, redmine_upload, redmine_download),
you MUST always include the "user_identifier" parameter with the current user's email address.
This parameter is required for authentication — without it, the request will fail.
The user_identifier is: {{USER_EMAIL}}
```

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `REDMINE_URL` | Yes | - | URL of your Redmine instance. Subpaths are supported (e.g., `http://localhost/redmine/`) |
| `REDMINE_API_KEY` | Conditional | - | Your Redmine API key. Required unless `REDMINE_USERS_MAP` is configured. Used as fallback when no `user_identifier` is provided (see below for how to get it) |
| `REDMINE_USERS_MAP` | Conditional | - | Path to a JSON file or inline JSON string mapping user identifiers to Redmine API keys. Required unless `REDMINE_API_KEY` is configured. At least one of `REDMINE_API_KEY` or `REDMINE_USERS_MAP` must be set |
| `REDMINE_REQUEST_INSTRUCTIONS` | No | - | Path to a file containing additional instructions for the redmine_request tool. I've found it works great to have the LLM generate that file after a session. ([example1](INSTRUCTIONS_EXAMPLE1.md) [example2](INSTRUCTIONS_EXAMPLE2.md)) |
| `REDMINE_HEADERS` | No | (empty) | Custom HTTP headers to include in all requests. Format: `"Header1: Value1, Header2: Value2"`. Useful for proxies that require additional authentication (e.g., `X-Redmine-Username`) |
| `REDMINE_RESPONSE_FORMAT` | No | `yaml` | Response format: `yaml` or `json`. Controls how API responses are formatted |
| `REDMINE_ALLOWED_DIRECTORIES` | For upload/download | (disabled) | **Required for file operations.** Comma-separated list of directories where upload/download are allowed (e.g., `/tmp,/home/user/uploads`). Upload/download are disabled if not set for security |
| `REDMINE_DANGEROUSLY_ACCEPT_INVALID_CERTS` | No | (disabled) | Set to `1` to disable SSL certificate verification. Use only for self-signed certs in trusted environments |

> **Note**: When running via Docker, the `REDMINE_REQUEST_INSTRUCTIONS` environment variable must point to a **path inside the container**, not a path on the host machine.
> Therefore, if you want to use a local file, you need to **mount it into the container** at the correct location.

> **Security Note**: The `REDMINE_ALLOWED_DIRECTORIES` setting protects against path traversal attacks. Paths containing `../` are resolved before validation, ensuring files can only be accessed within the allowed directories.


## Getting Your Redmine API Key

1. Log in to your Redmine instance
2. Go to "My account" (typically found in the top-right menu)
3. On the right side of the page, you should see "API access key"
4. Click "Show" to view your existing key or "Generate" to create a new one
5. Copy this key for use in your configuration

## API

### Tools

- **redmine_paths_list**
  - Return a list of available API paths from OpenAPI spec
  - No input required
  - Returns a YAML string containing a list of path templates:
  ```
  - /issues.json
  - /projects.json
  - /time_entries.json
  ...
  ```

- **redmine_paths_info**
  - Get full path information for given path templates
  - Input: `path_templates` (list of strings)
  - Returns YAML string containing API specifications for the requested paths:
  ```yaml
  /issues.json:
    get:
      operationId: getIssues
      parameters:
        - $ref: '#/components/parameters/format'
      ...
  ```

- **redmine_request**
  - Make a request to the Redmine API
  - Inputs:
    - `path` (string): API endpoint path (e.g. '/issues.json')
    - `method` (string, optional): HTTP method to use (default: 'get')
    - `data` (object, optional): Dictionary for request body (for POST/PUT)
    - `params` (object, optional): Dictionary for query parameters
    - `user_identifier` (string, **required in multi-user mode**): User identifier (e.g. email address) for API key resolution. The orchestrator (e.g. n8n) must provide this in every tool call.
  - Returns YAML string containing response status code, body and error message:
  ```yaml
  status_code: 200
  body:
    issues:
      - id: 1
        subject: "Fix login page"
        ...
  error: ""
  ```

- **redmine_upload**
  - Upload a file to Redmine and get a token for attachment
  - **Requires `REDMINE_ALLOWED_DIRECTORIES` to be set**
  - Inputs:
    - `file_path` (string): Fully qualified path to the file to upload (must be within allowed directories)
    - `description` (string, optional): Optional description for the file
    - `user_identifier` (string, **required in multi-user mode**): User identifier (e.g. email address) for API key resolution. The orchestrator (e.g. n8n) must provide this in every tool call.
  - Returns YAML string with the same format as redmine_request, including upload token:
  ```yaml
  status_code: 201
  body:
    upload:
      id: 7
      token: "7.ed32257a2ab0f7526c0d72c32994c58b131bb2c0775f7aa84aae01ea8397ea54"
  error: ""
  ```

- **redmine_download**
  - Download an attachment from Redmine and save it to a local file
  - **Requires `REDMINE_ALLOWED_DIRECTORIES` to be set**
  - Inputs:
    - `attachment_id` (integer): The ID of the attachment to download
    - `save_path` (string): Fully qualified path where the file should be saved (must be within allowed directories)
    - `filename` (string, optional): Optional filename to use (determined automatically if not provided)
    - `user_identifier` (string, **required in multi-user mode**): User identifier (e.g. email address) for API key resolution. The orchestrator (e.g. n8n) must provide this in every tool call.
  - Returns YAML string with download results:
  ```yaml
  status_code: 200
  body:
    saved_to: "/path/to/downloaded/file.pdf"
    filename: "file.pdf"
  error: ""
  ```

## Examples

### Creating a new issue

```
Let's create a new bug report in the "Website" project:

1. Title: "Homepage not loading on mobile devices"
2. Description: "When accessing the homepage from iOS or Android devices, the loading spinner appears but the content never loads. This issue started after the last deployment."
3. Priority: High
4. Assign to: John Smith
```

### Searching for issues

```
Can you find all high priority issues in the "Website" project that are currently unassigned?
```

### Updating issue status

```
Please mark issue #123 as "In Progress" and add a comment: "I've started working on this issue. Expect it to be completed by Friday."
```

### Logging time

```
Log 3.5 hours against issue #456 for "Implementing user authentication" done today.
```

## MCP Directory Listings

MCP Redmine is listed in the following MCP directory sites and repositories:

- [MCP.so](https://mcp.so/server/mcp-redmine)
- [Glama](https://glama.ai/mcp/servers/@runekaagaard/mcp-redmine)

## Developing

First clone the github repository and install the dependencies:

```
git clone git@github.com:runekaagaard/mcp-redmine.git
cd mcp-redmine
uv sync
```

Then set this in claude_desktop_config.json:

```
...
"command": "uv",
"args": ["run", "--directory", "/path/to/mcp-redmine", "-m", "mcp_redmine.server", "main"],
...
```

## My Other LLM Projects

- **[MCP Alchemy](https://github.com/runekaagaard/mcp-alchemy)** - Connect Claude Desktop to databases for exploring schema and running SQL.
- **[MCP Notmuch Sendmail](https://github.com/runekaagaard/mcp-notmuch-sendmail)** - Email assistant for Claude Desktop using notmuch.
- **[Diffpilot](https://github.com/runekaagaard/diffpilot)** - Multi-column git diff viewer with file grouping and tagging.
- **[Claude Local Files](https://github.com/runekaagaard/claude-local-files)** - Access local files in Claude Desktop artifacts.

## Contributing

Contributions are warmly welcomed! Whether it's bug reports, feature requests, documentation improvements, or code contributions - all input is valuable. Feel free to:

- Open an issue to report bugs or suggest features
- Submit pull requests with improvements
- Enhance documentation or share your usage examples
- Ask questions and share your experiences

The goal is to make Redmine project management with Claude even better, and your insights and contributions help achieve that.

## Acknowledgments

This project builds on the excellent work of others:

- [httpx](https://www.python-httpx.org/) - For handling HTTP requests
- [Redmine OpenAPI Specification](https://github.com/d-yoshi/redmine-openapi) - For the comprehensive API specification
- [Redmine](https://www.redmine.org/) - The flexible project management web application

## License

Mozilla Public License Version 2.0
