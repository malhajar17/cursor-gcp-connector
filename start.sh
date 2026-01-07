#!/bin/bash
# Cursor-GCP Connector Startup Script

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}🚀 Starting Cursor-GCP Connector${NC}"

# Check for required environment variable
if [ -z "$GOOGLE_APPLICATION_CREDENTIALS" ]; then
    echo -e "${RED}❌ Error: GOOGLE_APPLICATION_CREDENTIALS is not set${NC}"
    echo -e "${YELLOW}Please set it to your service account JSON file:${NC}"
    echo "  export GOOGLE_APPLICATION_CREDENTIALS=/path/to/your/service-account.json"
    exit 1
fi

# Check if credentials file exists
if [ ! -f "$GOOGLE_APPLICATION_CREDENTIALS" ]; then
    echo -e "${RED}❌ Error: Credentials file not found: $GOOGLE_APPLICATION_CREDENTIALS${NC}"
    exit 1
fi

# Default ports
LITELLM_PORT=${LITELLM_PORT:-4000}
PROXY_PORT=${PROXY_PORT:-4001}

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Check if config file exists
CONFIG_FILE="${LITELLM_CONFIG:-$SCRIPT_DIR/litellm-config.yaml}"
if [ ! -f "$CONFIG_FILE" ]; then
    echo -e "${RED}❌ Error: LiteLLM config not found: $CONFIG_FILE${NC}"
    exit 1
fi

echo -e "${GREEN}📋 Configuration:${NC}"
echo "  • LiteLLM Config: $CONFIG_FILE"
echo "  • Credentials: $GOOGLE_APPLICATION_CREDENTIALS"
echo "  • LiteLLM Port: $LITELLM_PORT"
echo "  • Proxy Port: $PROXY_PORT"

# Kill any existing processes
pkill -f "litellm --config" 2>/dev/null || true
pkill -f "python.*proxy.py" 2>/dev/null || true
sleep 2

# Start LiteLLM
echo -e "${GREEN}🔧 Starting LiteLLM on port $LITELLM_PORT...${NC}"
nohup litellm --config "$CONFIG_FILE" --port "$LITELLM_PORT" > /tmp/litellm.log 2>&1 &
LITELLM_PID=$!

# Wait for LiteLLM to be ready
echo -e "${YELLOW}⏳ Waiting for LiteLLM to start...${NC}"
for i in {1..30}; do
    if curl -s "http://localhost:$LITELLM_PORT/health" > /dev/null 2>&1; then
        echo -e "${GREEN}✅ LiteLLM is ready${NC}"
        break
    fi
    if [ $i -eq 30 ]; then
        echo -e "${RED}❌ LiteLLM failed to start. Check /tmp/litellm.log${NC}"
        exit 1
    fi
    sleep 1
done

# Start proxy
echo -e "${GREEN}🔧 Starting proxy on port $PROXY_PORT...${NC}"
export LITELLM_URL="http://localhost:$LITELLM_PORT"
export PROXY_PORT="$PROXY_PORT"
nohup python3 "$SCRIPT_DIR/proxy.py" > /tmp/proxy.log 2>&1 &
PROXY_PID=$!

# Wait for proxy to be ready
sleep 2
if curl -s "http://localhost:$PROXY_PORT/health" > /dev/null 2>&1; then
    echo -e "${GREEN}✅ Proxy is ready${NC}"
else
    echo -e "${RED}❌ Proxy failed to start. Check /tmp/proxy.log${NC}"
    exit 1
fi

echo ""
echo -e "${GREEN}════════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}🎉 Cursor-GCP Connector is running!${NC}"
echo -e "${GREEN}════════════════════════════════════════════════════════════${NC}"
echo ""
echo -e "  ${YELLOW}Local endpoint:${NC}  http://localhost:$PROXY_PORT"
echo ""
echo -e "  ${YELLOW}For Cursor, use:${NC}"
echo -e "    • Base URL: http://localhost:$PROXY_PORT"
echo -e "    • API Key: (your master key from litellm-config.yaml)"
echo -e "    • Model: claude-opus-4-5"
echo ""
echo -e "  ${YELLOW}To expose publicly (for Cursor's SSRF protection):${NC}"
echo "    cloudflared tunnel --url localhost:$PROXY_PORT"
echo ""
echo -e "  ${YELLOW}Logs:${NC}"
echo "    • LiteLLM: tail -f /tmp/litellm.log"
echo "    • Proxy:   tail -f /tmp/proxy.log"
echo ""
echo -e "  ${YELLOW}PIDs:${NC}"
echo "    • LiteLLM: $LITELLM_PID"
echo "    • Proxy:   $PROXY_PID"

