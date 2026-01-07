# Cursor GCP Connector

A compatibility layer that enables Cursor IDE to use Claude models via Google Cloud Vertex AI.

## Overview

Cursor IDE sends requests in OpenAI-compatible format, but Vertex AI's Claude API has specific requirements that cause compatibility issues. This tool acts as a translation layer between Cursor and Vertex AI, handling all necessary request transformations automatically.

## Architecture

```
┌─────────────┐      ┌─────────────────┐      ┌─────────────┐      ┌────────────┐
│  Cursor IDE │ ──── │  Compatibility  │ ──── │   LiteLLM   │ ──── │  Vertex AI │
│             │      │  Proxy (:4001)  │      │   (:4000)   │      │   Claude   │
└─────────────┘      └─────────────────┘      └─────────────┘      └────────────┘
                              │
                     (Cloudflare Tunnel)
```

The compatibility proxy intercepts requests from Cursor, transforms them into a format that LiteLLM and Vertex AI can process, and forwards them along the chain.

## Technical Details

### Why This Exists

Cursor sends requests that include Anthropic-specific features and formats that Vertex AI either doesn't support or handles differently. Without this proxy, you'll encounter errors like:

| Error | Root Cause | 
|-------|------------|
| `invalid beta flag` | Cursor includes `cache_control` which triggers unsupported beta features |
| `tool_choice.tool.name required` | Cursor's `tool_choice` format is incompatible with Vertex AI |
| `unexpected tool_use_id in tool_result` | Tool results in conversation history lack matching tool_use blocks |
| Model ignores tool outputs | Tool format mismatch causes results to be stripped |

### How It Works

The proxy performs several critical transformations:

#### 1. Tool Format Conversion

Cursor sends tool calls in Anthropic's native format, but LiteLLM expects OpenAI format:

**Cursor sends (Anthropic format):**
```json
{
  "role": "assistant",
  "content": [{"type": "tool_use", "id": "toolu_X", "name": "read_file", "input": {"path": "/etc/hosts"}}]
}
{
  "role": "user", 
  "content": [{"type": "tool_result", "tool_use_id": "toolu_X", "content": "127.0.0.1 localhost"}]
}
```

**Proxy converts to (OpenAI format):**
```json
{
  "role": "assistant",
  "content": null,
  "tool_calls": [{"id": "toolu_X", "type": "function", "function": {"name": "read_file", "arguments": "{\"path\": \"/etc/hosts\"}"}}]
}
{
  "role": "tool",
  "tool_call_id": "toolu_X", 
  "content": "127.0.0.1 localhost"
}
```

This conversion is essential. Without it, Claude never sees the results of its tool calls and will hallucinate or claim tasks are complete when they aren't.

#### 2. Orphaned Tool Result Removal

Cursor includes conversation history in requests. This history may contain `tool_result` blocks from previous exchanges that no longer have matching `tool_use` blocks in the current context. Vertex AI requires each `tool_result` to immediately follow its corresponding `tool_use`.

The proxy tracks tool IDs from assistant messages and only keeps `tool_result` blocks that match. Orphaned results are removed.

#### 3. Cache Control Stripping

Cursor adds `cache_control: {type: "ephemeral"}` to messages for prompt caching. This triggers Anthropic beta features that Vertex AI doesn't support. The proxy recursively removes all `cache_control` fields.

#### 4. Parameter Filtering

Several parameters that Cursor may include are incompatible with Vertex AI:

- `tool_choice` - format mismatch
- `thinking`, `reasoning_effort`, `extended_thinking`, `budget_tokens` - trigger beta headers
- `metadata`, `stream_options` - unsupported features

These are stripped before forwarding.

#### 5. Header Filtering

The proxy removes the `Anthropic-Beta` header that Cursor includes, preventing beta feature activation on Vertex AI.

## Installation

```bash
git clone https://github.com/malhajar17/cursor-gcp-connector.git
cd cursor-gcp-connector
pip install -e .
```

## Configuration

### 1. Google Cloud Setup

Your service account needs the **Vertex AI User** role (`roles/aiplatform.user`).

```bash
export GOOGLE_APPLICATION_CREDENTIALS="/path/to/service-account.json"
```

### 2. LiteLLM Configuration

Edit `litellm-config.yaml`:

```yaml
model_list:
  - model_name: claude-opus-4-5
    litellm_params:
      model: vertex_ai/claude-opus-4-5
      vertex_ai_project: "YOUR_PROJECT_ID"
      vertex_ai_location: "global"
      drop_params: true

litellm_settings:
  master_key: "YOUR_API_KEY"
  drop_params: true
  modify_params: true
```

Generate an API key:

```bash
python3 -c "import secrets; print('sk-' + secrets.token_hex(32))"
```

## Usage

### Start the Connector

```bash
cursor-gcp-connector --config litellm-config.yaml start
```

### Expose to Internet

Cursor's SSRF protection blocks localhost connections. Use Cloudflare Tunnel to expose the proxy:

```bash
cloudflared tunnel --url http://localhost:4001
```

Copy the generated public URL.

### Configure Cursor

1. Open Cursor Settings
2. Navigate to Models > OpenAI API Key
3. Configure:
   - **Base URL**: Your tunnel URL (no trailing slash)
   - **API Key**: The `master_key` from your config
4. Add model: `claude-opus-4-5`
5. Select the model in the chat interface

## CLI Reference

```bash
cursor-gcp-connector --help                      # Show help
cursor-gcp-connector config                      # Display current configuration
cursor-gcp-connector test                        # Test service health
cursor-gcp-connector start                       # Start all services
cursor-gcp-connector --config FILE start         # Start with custom config
cursor-gcp-connector start --proxy-only          # Start proxy only (if LiteLLM runs separately)
```

## Troubleshooting

### Check Logs

```bash
tail -f /tmp/litellm.log      # LiteLLM logs
tail -f /tmp/cursor-proxy.log # Proxy logs
```

### Test Service Health

```bash
cursor-gcp-connector test
```

### Common Issues

**"Permission denied" from Vertex AI**
- Ensure your service account has the Vertex AI User role

**"Model not found"**
- Verify Claude models are available in your region
- Check that you've accepted Anthropic's terms in Google Cloud Console

**Tool calls not working**
- Ensure you're connecting to the proxy port (4001), not LiteLLM directly (4000)
- Check proxy logs for conversion messages

## Contributing

Contributions are welcome. Please follow these guidelines:

### Development Setup

```bash
git clone https://github.com/malhajar17/cursor-gcp-connector.git
cd cursor-gcp-connector
pip install -e .
```

### Code Style

- Follow PEP 8 conventions
- Add docstrings to functions and classes
- Include type hints where practical

### Testing Changes

1. Start the services with debug logging:
   ```bash
   PROXY_DEBUG=true cursor-gcp-connector start
   ```

2. Monitor the proxy log for request transformations:
   ```bash
   tail -f /tmp/cursor-proxy.log
   ```

3. Test with curl before testing with Cursor:
   ```bash
   curl -X POST http://localhost:4001/chat/completions \
     -H "Content-Type: application/json" \
     -H "Authorization: Bearer YOUR_KEY" \
     -d '{"model": "claude-opus-4-5", "messages": [{"role": "user", "content": "Hello"}]}'
   ```

### Submitting Changes

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/your-feature`)
3. Commit your changes with clear messages
4. Push to your fork
5. Open a Pull Request with a description of what the change does and why

### Reporting Issues

When reporting issues, please include:

- The error message from Cursor
- Relevant logs from `/tmp/cursor-proxy.log` and `/tmp/litellm.log`
- Your LiteLLM configuration (with secrets redacted)
- Steps to reproduce the issue

## Extras

This repository includes captured artifacts from Cursor's request format, useful for understanding how Cursor communicates with LLM backends or for building similar integrations.

| File | Description |
|------|-------------|
| [`extras/cursor-system-prompt.md`](extras/cursor-system-prompt.md) | The full system prompt Cursor sends to Claude, including instructions for tool calling, code formatting, browser tools, frontend aesthetics, and more |
| [`extras/cursor-toolkit.json`](extras/cursor-toolkit.json) | Complete JSON schema of all tools Cursor provides to the model, including file operations, terminal commands, browser automation, and MCP integrations |

### Cursor Tool Categories

The toolkit includes 32 tools across these categories:

| Category | Tools |
|----------|-------|
| **File Operations** | `read_file`, `write`, `search_replace`, `delete_file`, `list_dir`, `glob_file_search` |
| **Code Intelligence** | `grep`, `read_lints`, `edit_notebook` |
| **Terminal** | `run_terminal_cmd` |
| **Web Search** | `web_search` |
| **Task Management** | `todo_write` |
| **MCP Resources** | `list_mcp_resources`, `fetch_mcp_resource` |
| **Browser Automation** | `browser_navigate`, `browser_snapshot`, `browser_click`, `browser_type`, `browser_screenshot`, and 13 more |

These files are provided for educational and research purposes.

## License

MIT License. See [LICENSE](LICENSE) for details.

## Acknowledgments

- [LiteLLM](https://github.com/BerriAI/litellm) for the OpenAI-compatible proxy layer
- [Cloudflare Tunnel](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/) for secure localhost exposure
