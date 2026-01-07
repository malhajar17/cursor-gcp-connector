#!/bin/bash
#
# Cursor GCP Connector - Startup Script
# 
# This script starts both LiteLLM and the compatibility proxy.
# The proxy runs on port 4001, LiteLLM runs on port 4000.
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}       Cursor GCP Connector - Startup${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

# Check for config file
if [ ! -f "litellm-config.yaml" ]; then
    echo -e "${RED}Error: litellm-config.yaml not found${NC}"
    echo "Please copy litellm-config.example.yaml and configure it:"
    echo "  cp litellm-config.example.yaml litellm-config.yaml"
    exit 1
fi

# Check for credentials
if [ -z "$GOOGLE_APPLICATION_CREDENTIALS" ]; then
    echo -e "${YELLOW}Warning: GOOGLE_APPLICATION_CREDENTIALS not set${NC}"
    echo "Set it with: export GOOGLE_APPLICATION_CREDENTIALS=/path/to/credentials.json"
fi

# Stop any existing processes
echo -e "\n${YELLOW}Stopping existing processes...${NC}"
pkill -f "litellm --config" 2>/dev/null || true
pkill -f "proxy.py" 2>/dev/null || true
sleep 2

# Start LiteLLM
echo -e "${GREEN}Starting LiteLLM on port 4000...${NC}"
litellm --config litellm-config.yaml --port 4000 > /tmp/litellm.log 2>&1 &
LITELLM_PID=$!

# Wait for LiteLLM to start
echo -n "Waiting for LiteLLM to start"
for i in {1..30}; do
    if curl -s http://localhost:4000/health > /dev/null 2>&1; then
        echo -e " ${GREEN}✓${NC}"
        break
    fi
    echo -n "."
    sleep 1
done

if ! curl -s http://localhost:4000/health > /dev/null 2>&1; then
    echo -e " ${RED}✗${NC}"
    echo -e "${RED}LiteLLM failed to start. Check /tmp/litellm.log${NC}"
    exit 1
fi

# Start Proxy
echo -e "${GREEN}Starting compatibility proxy on port 4001...${NC}"
python3 -u proxy.py > /tmp/proxy.log 2>&1 &
PROXY_PID=$!
sleep 2

# Verify proxy
if curl -s http://localhost:4001/health > /dev/null 2>&1; then
    echo -e "Proxy started ${GREEN}✓${NC}"
else
    echo -e "${RED}Proxy failed to start. Check /tmp/proxy.log${NC}"
    exit 1
fi

# Get master key from config
MASTER_KEY=$(grep "master_key:" litellm-config.yaml | awk '{print $2}')

echo -e "\n${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}                    ✓ All Services Running${NC}"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo -e "  ${BLUE}LiteLLM:${NC}  http://localhost:4000  (PID: $LITELLM_PID)"
echo -e "  ${BLUE}Proxy:${NC}    http://localhost:4001  (PID: $PROXY_PID)"
echo ""
echo -e "  ${YELLOW}Master Key:${NC} $MASTER_KEY"
echo ""
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo -e "${YELLOW}Next Steps:${NC}"
echo ""
echo "1. Expose the proxy publicly (Cursor blocks localhost):"
echo ""
echo -e "   ${GREEN}cloudflared tunnel --url localhost:4001${NC}"
echo ""
echo "2. Configure Cursor with the tunnel URL (see README.md)"
echo ""
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo "Logs:"
echo "  - LiteLLM: tail -f /tmp/litellm.log"
echo "  - Proxy:   tail -f /tmp/proxy.log"
echo ""
