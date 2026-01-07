# Cursor-GCP Connector

Use Claude models from Google Cloud Vertex AI in your Cursor IDE.

## Why This Exists

Cursor IDE sends OpenAI-compatible API requests with certain features (like `cache_control`, `tool_choice`, and various beta flags) that aren't supported by Claude on Vertex AI. This connector:

1. **LiteLLM Proxy** - Translates OpenAI-format requests to Vertex AI format
2. **Compatibility Proxy** - Removes unsupported features that would cause errors

## Prerequisites

- Google Cloud account with Vertex AI API enabled
- Service account with "Vertex AI User" role
- Python 3.10+
- Access to Claude models on Vertex AI (requires agreement to Anthropic's terms in Google Cloud Console)

## Quick Start

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure

Edit `litellm-config.yaml`:

```yaml
model_list:
  - model_name: claude-opus-4-5
    litellm_params:
      model: vertex_ai/claude-opus-4-5
      vertex_ai_project: "YOUR_PROJECT_ID"  # ← Change this
      vertex_ai_location: "global"
      drop_params: true

litellm_settings:
  master_key: sk-your-secure-key-here  # ← Generate one
  drop_params: true
  modify_params: true
```

Generate a master key:
```bash
python3 -c "import secrets; print('sk-' + secrets.token_hex(32))"
```

### 3. Set Credentials

```bash
export GOOGLE_APPLICATION_CREDENTIALS="/path/to/your/service-account.json"
```

### 4. Start the Connector

```bash
chmod +x start.sh
./start.sh
```

### 5. Expose Publicly (Required)

Since Cursor blocks `localhost` connections (SSRF protection), you must expose the proxy via a tunnel:

```bash
# Install cloudflared: https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/
cloudflared tunnel --url localhost:4001
```

This will output a URL like:
```
Your quick Tunnel has been created! Visit it at:
https://random-words.trycloudflare.com
```

### 6. Configure Cursor

1. Open Cursor IDE
2. Go to **Settings** (gear icon) → **Models**
3. Scroll down to **OpenAI API Key** section
4. Click **Add model** or configure existing:

| Setting | Value |
|---------|-------|
| **Model Name** | `claude-opus-4-5` |
| **Base URL** | `https://random-words.trycloudflare.com` (your cloudflared URL, **no trailing slash**) |
| **API Key** | Your master key from `litellm-config.yaml` |

5. Click **Save**
6. Select `claude-opus-4-5` from the model dropdown in chat

### 7. Test It!

In Cursor chat, try:
```
Hello! Can you read the current directory?
```

You should see Claude respond and use tools successfully!

## Architecture

```
┌─────────┐     ┌─────────────┐     ┌─────────┐     ┌──────────┐
│ Cursor  │────▶│ Proxy :4001 │────▶│ LiteLLM │────▶│ Vertex AI│
│   IDE   │     │ (cleanup)   │     │  :4000  │     │  Claude  │
└─────────┘     └─────────────┘     └─────────┘     └──────────┘
```

The proxy removes:
- `cache_control` from messages (triggers unsupported beta flags)
- `tool_choice` parameter (not fully supported)
- `metadata`, `stream_options` (beta features)
- `thinking`, `reasoning_effort`, `extended_thinking` (beta features)
- Orphaned `tool_result` messages (would cause validation errors)
- `Anthropic-Beta` headers

## Troubleshooting

### "Permission denied" errors

Ensure your service account has the "Vertex AI User" role:
```bash
gcloud projects add-iam-policy-binding YOUR_PROJECT_ID \
  --member="serviceAccount:YOUR_SERVICE_ACCOUNT@YOUR_PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/aiplatform.user"
```

### "Model not found" errors

- Check that you've agreed to Anthropic's terms in Google Cloud Console
- Try different locations: `global`, `us-east5`, `europe-west1`
- Verify the model name matches what's available in your region

### "Invalid beta flag" errors

This is exactly what this connector fixes! Make sure you're connecting through the proxy (port 4001), not directly to LiteLLM (port 4000).

### Checking logs

```bash
# LiteLLM logs
tail -f /tmp/litellm.log

# Proxy logs
tail -f /tmp/proxy.log
```

## Manual Start (Alternative)

If you prefer to start components individually:

```bash
# Terminal 1: Start LiteLLM
export GOOGLE_APPLICATION_CREDENTIALS="/path/to/credentials.json"
litellm --config litellm-config.yaml --port 4000

# Terminal 2: Start Proxy
export LITELLM_URL="http://localhost:4000"
python3 proxy.py

# Terminal 3: Expose via cloudflared
cloudflared tunnel --url localhost:4001
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `GOOGLE_APPLICATION_CREDENTIALS` | - | Path to service account JSON |
| `LITELLM_URL` | `http://localhost:4000` | LiteLLM endpoint |
| `PROXY_PORT` | `4001` | Port for the compatibility proxy |
| `LITELLM_PORT` | `4000` | Port for LiteLLM |
| `LOG_LEVEL` | `INFO` | Logging level (DEBUG, INFO, WARNING, ERROR) |

## License

MIT

