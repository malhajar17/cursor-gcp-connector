# Cursor GCP Connector

A CLI tool that enables Cursor IDE to use Claude models via Google Cloud Vertex AI.

## Overview

Cursor IDE sends requests in OpenAI-compatible format, but Vertex AI's Claude implementation has specific requirements that cause compatibility issues. This tool acts as a translation layer, handling the necessary request transformations automatically.

### Architecture

```
Cursor IDE --> Compatibility Proxy (port 4001) --> LiteLLM (port 4000) --> Vertex AI Claude
```

### What It Solves

| Issue | Cause | Solution |
|-------|-------|----------|
| `invalid beta flag` | `cache_control` in message content | Stripped from requests |
| `tool_choice.tool.name: Field required` | Malformed `tool_choice` parameter | Parameter removed |
| `unexpected tool_use_id in tool_result` | Orphaned tool results in conversation history | Tool results cleaned |
| `invalid content type=tool_result` | Anthropic-specific message format | Messages reformatted |

## Requirements

- Python 3.8+
- Google Cloud service account with Vertex AI access
- LiteLLM
- Cloudflare Tunnel (for exposing local proxy to Cursor)

## Installation

```bash
git clone https://github.com/malhajar17/cursor-gcp-connector.git
cd cursor-gcp-connector
pip install -r requirements.txt
```

## Configuration

### 1. Google Cloud Setup

Ensure your service account has the **Vertex AI User** role:

```bash
gcloud projects add-iam-policy-binding PROJECT_ID \
    --member="serviceAccount:SERVICE_ACCOUNT_EMAIL" \
    --role="roles/aiplatform.user"
```

Set the credentials environment variable:

```bash
export GOOGLE_APPLICATION_CREDENTIALS="/path/to/service-account.json"
```

### 2. LiteLLM Configuration

Create `config.yaml`:

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

Generate a secure API key:

```bash
python3 -c "import secrets; print('sk-' + secrets.token_hex(32))"
```

## Usage

### Start the connector

```bash
# Start with default configuration
python cursor-gcp-connector --config config.yaml

# Specify ports
python cursor-gcp-connector --config config.yaml --proxy-port 4001 --litellm-port 4000

# Run LiteLLM separately (proxy only mode)
python cursor-gcp-connector --proxy-only --proxy-port 4001 --litellm-port 4000
```

### Expose via tunnel

In a separate terminal:

```bash
cloudflared tunnel --url http://localhost:4001
```

Note the generated URL (e.g., `https://example-tunnel.trycloudflare.com`).

### Configure Cursor IDE

1. Open Cursor Settings
2. Navigate to **Models** > **Model Names**
3. Add `claude-opus-4-5`
4. Under **OpenAI API Key**, configure:

| Field | Value |
|-------|-------|
| OpenAI Base URL | Your Cloudflare tunnel URL (no trailing slash) |
| OpenAI API Key | The master key from your config.yaml |

5. Select `claude-opus-4-5` in the model dropdown

## CLI Reference

```
usage: cursor-gcp-connector [-h] [--config CONFIG] [--proxy-port PORT]
                            [--litellm-port PORT] [--proxy-only] [--verbose]
                            [--log-file FILE]

Cursor GCP Connector - Bridge Cursor IDE to Vertex AI Claude

options:
  -h, --help            show this help message and exit
  --config CONFIG       Path to LiteLLM config file (default: config.yaml)
  --proxy-port PORT     Port for compatibility proxy (default: 4001)
  --litellm-port PORT   Port for LiteLLM server (default: 4000)
  --proxy-only          Run proxy only, assumes LiteLLM is running separately
  --verbose             Enable verbose logging
  --log-file FILE       Log to file instead of stdout
```

## Troubleshooting

### Connection refused

Ensure both LiteLLM and the proxy are running:

```bash
curl http://localhost:4000/health  # LiteLLM
curl http://localhost:4001/health  # Proxy
```

### Authentication errors

Verify your service account credentials:

```bash
gcloud auth application-default print-access-token
```

### Model not found

Check available models in your region:

```bash
gcloud ai models list --region=global --filter="name:claude"
```

### SSRF blocked errors in Cursor

Cursor blocks localhost connections. You must use a tunnel:

```bash
cloudflared tunnel --url http://localhost:4001
```

## Development

### Running tests

```bash
# Test proxy health
curl http://localhost:4001/health

# Test chat completion
curl http://localhost:4001/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -d '{"model": "claude-opus-4-5", "messages": [{"role": "user", "content": "Hello"}]}'
```

### Debug mode

```bash
python cursor-gcp-connector --config config.yaml --verbose --log-file debug.log
```

## License

MIT
