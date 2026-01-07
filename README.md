# Cursor GCP Connector

> 🚀 Use Claude models from Google Cloud Vertex AI in Cursor IDE

This project provides a compatibility layer between Cursor IDE and Claude models on Vertex AI. It handles the translation between Cursor's OpenAI-compatible API format and Vertex AI's requirements.

## Why This Exists

Cursor IDE uses an OpenAI-compatible API format, but Claude on Vertex AI has specific requirements:
- No `cache_control` in messages (beta feature)
- No orphaned `tool_result` blocks in conversation history
- No `Anthropic-Beta` headers
- Different `tool_choice` format

This proxy automatically handles all these incompatibilities.

---

## 📋 Prerequisites

| Requirement | Details |
|-------------|---------|
| **Google Cloud Project** | With Vertex AI API enabled |
| **Service Account** | With "Vertex AI User" role |
| **Claude Access** | Claude models enabled on Vertex AI |
| **Python 3.8+** | For running the proxy |

---

## 🚀 Quick Start

### 1. Clone the Repository

```bash
git clone https://github.com/malhajar17/cursor-gcp-connector.git
cd cursor-gcp-connector
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure Google Cloud Credentials

```bash
export GOOGLE_APPLICATION_CREDENTIALS="/path/to/your/service-account.json"
```

### 4. Edit Configuration

Open `litellm-config.yaml` and update:

```yaml
model_list:
  - model_name: claude-opus-4-5
    litellm_params:
      model: vertex_ai/claude-opus-4-5
      vertex_ai_project: "YOUR_PROJECT_ID"    # ← Change this
      vertex_ai_location: "global"
      drop_params: true

litellm_settings:
  master_key: sk-your-secret-key-here         # ← Change this
  drop_params: ["tool_choice"]
  modify_params: true
```

### 5. Start the Services

```bash
./start.sh
```

This starts:
- **LiteLLM** on port 4000 (internal)
- **Proxy** on port 4001 (connect here)

### 6. Expose to Internet (for Cursor)

Cursor blocks localhost connections, so you need a public URL:

```bash
# Using Cloudflare Tunnel (free, no signup)
cloudflared tunnel --url localhost:4001
```

Copy the generated URL (e.g., `https://random-words.trycloudflare.com`)

---

## ⚙️ Cursor IDE Configuration

### Step 1: Open Settings

`Ctrl/Cmd + ,` → Search for "OpenAI"

### Step 2: Configure OpenAI API

| Setting | Value |
|---------|-------|
| **Override OpenAI Base URL** | `https://your-cloudflare-url.trycloudflare.com` |
| **OpenAI API Key** | Your master key from `litellm-config.yaml` |

### Step 3: Add the Model

Go to **Settings** → **Models** → **Model Names**

Add: `claude-opus-4-5`

### Step 4: Select the Model

In any Cursor chat, click the model dropdown and select `claude-opus-4-5`

---

## 📁 Project Structure

```
cursor-gcp-connector/
├── proxy.py              # Compatibility proxy (handles API translation)
├── litellm-config.yaml   # LiteLLM configuration
├── start.sh              # One-command startup script
├── requirements.txt      # Python dependencies
└── README.md             # This file
```

---

## 🔧 Configuration Reference

### litellm-config.yaml

```yaml
model_list:
  - model_name: claude-opus-4-5          # Name you'll use in Cursor
    litellm_params:
      model: vertex_ai/claude-opus-4-5   # Vertex AI model ID
      vertex_ai_project: "your-project"  # GCP Project ID
      vertex_ai_location: "global"       # Region (global recommended)
      drop_params: true

  # Add more models as needed:
  - model_name: claude-sonnet-4
    litellm_params:
      model: vertex_ai/claude-sonnet-4-20250514
      vertex_ai_project: "your-project"
      vertex_ai_location: "us-east5"
      drop_params: true

litellm_settings:
  master_key: sk-your-secret-key        # API key for authentication
  drop_params: ["tool_choice"]
  modify_params: true
```

### Available Models

| Model Name | Vertex AI ID | Recommended Location |
|------------|--------------|---------------------|
| Claude Opus 4.5 | `claude-opus-4-5` | `global` |
| Claude Sonnet 4 | `claude-sonnet-4-20250514` | `us-east5` |
| Claude Sonnet 4.5 | `claude-sonnet-4-5-20250929` | `us-east5` |
| Claude Haiku 4.5 | `claude-haiku-4-5-20251001` | `us-east5` |

---

## 🔍 Troubleshooting

### Check Service Status

```bash
# Check if services are running
curl http://localhost:4000/health  # LiteLLM
curl http://localhost:4001/health  # Proxy
```

### View Logs

```bash
# Proxy logs
tail -f /tmp/proxy.log

# Last request from Cursor (for debugging)
cat /tmp/cursor_request.json | jq .
```

### Common Errors

| Error | Cause | Solution |
|-------|-------|----------|
| `ssrf_blocked` | Cursor blocks localhost | Use Cloudflare Tunnel |
| `Permission denied` | Missing IAM role | Add "Vertex AI User" role to service account |
| `Model not found` | Wrong region/model | Check model availability in your region |
| `invalid beta flag` | Unsupported features | Proxy should handle this - restart it |

### Restart Services

```bash
# Kill existing processes
pkill -f "litellm --config"
pkill -f "proxy.py"

# Start fresh
./start.sh
```

---

## 🛡️ Security Notes

1. **Never commit credentials** - Keep your service account JSON and master key private
2. **Use strong master keys** - Generate with: `openssl rand -hex 32`
3. **Cloudflare URLs are temporary** - They change on each restart

---

## 📝 How It Works

```
┌─────────────────────────────────────────────────────────────────┐
│                         Cursor IDE                               │
└─────────────────────────────────────────────────────────────────┘
                              │
                              │ HTTPS (OpenAI format)
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Cloudflare Tunnel                             │
│                  (public URL → localhost)                        │
└─────────────────────────────────────────────────────────────────┘
                              │
                              │ HTTP :4001
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                     Compatibility Proxy                          │
│  • Removes cache_control from messages                           │
│  • Removes orphaned tool_result blocks                           │
│  • Filters Anthropic-Beta headers                                │
│  • Removes unsupported parameters                                │
└─────────────────────────────────────────────────────────────────┘
                              │
                              │ HTTP :4000
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                         LiteLLM                                  │
│           (OpenAI → Vertex AI translation)                       │
└─────────────────────────────────────────────────────────────────┘
                              │
                              │ HTTPS (Vertex AI API)
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                   Google Cloud Vertex AI                         │
│                      Claude Models                               │
└─────────────────────────────────────────────────────────────────┘
```

---

## 📄 License

MIT License - feel free to use and modify.

---

## 🤝 Contributing

Issues and PRs welcome! If you encounter a new Cursor/Vertex AI incompatibility, please open an issue with:
1. The error message
2. Contents of `/tmp/cursor_request.json`
3. Contents of `/tmp/proxy.log`
