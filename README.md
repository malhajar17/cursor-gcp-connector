# Cursor GCP Connector

A CLI tool that enables Cursor IDE to use Claude models via Google Cloud Vertex AI.

## Overview

Cursor IDE sends requests in OpenAI-compatible format, but Vertex AI's Claude implementation has specific requirements that cause compatibility issues. This tool acts as a translation layer, handling the necessary request transformations.

### What It Solves

| Issue | Cause | Solution |
|-------|-------|----------|
| `invalid beta flag` | `cache_control` in messages | Stripped from requests |
| `tool_choice.tool.name required` | Malformed `tool_choice` | Parameter removed |
| `unexpected tool_use_id` | Orphaned tool results | Messages cleaned |

## Installation

```bash
git clone https://github.com/malhajar17/cursor-gcp-connector.git
cd cursor-gcp-connector
pip install -e .
```

## Configuration

### 1. Google Cloud Credentials

```bash
export GOOGLE_APPLICATION_CREDENTIALS="/path/to/service-account.json"
```

Your service account needs the Vertex AI User role.

### 2. LiteLLM Config

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

### Start the connector

```bash
cursor-gcp-connector --config litellm-config.yaml start
```

Output:
```
Starting Cursor GCP Connector
  Config: litellm-config.yaml
  LiteLLM port: 4000
  Proxy port: 4001

Starting LiteLLM...
Waiting for LiteLLM to start.......... OK
Starting proxy...

Checking services...
  Proxy: OK
  LiteLLM: OK

==================================================
Cursor GCP Connector is running
==================================================

Proxy endpoint: http://localhost:4001

Next: Expose via tunnel for Cursor:
  cloudflared tunnel --url http://localhost:4001
```

### Expose to internet

Cursor blocks localhost. Use Cloudflare Tunnel:

```bash
cloudflared tunnel --url http://localhost:4001
```

Copy the generated URL.

### Configure Cursor

1. Open Cursor Settings
2. Go to Models > OpenAI API Key
3. Set:
   - Base URL: your tunnel URL (no trailing slash)
   - API Key: master_key from config
4. Add model: `claude-opus-4-5`
5. Select the model in chat

## CLI Reference

```
cursor-gcp-connector --help
cursor-gcp-connector config                    # Show configuration
cursor-gcp-connector test                      # Test service health
cursor-gcp-connector start                     # Start services
cursor-gcp-connector --config FILE start       # Start with custom config
cursor-gcp-connector start --proxy-only        # Start proxy only (LiteLLM running separately)
```

## Troubleshooting

Check logs:

```bash
tail -f /tmp/litellm.log
tail -f /tmp/proxy.log
```

Test health:

```bash
cursor-gcp-connector test
```

## License

MIT
