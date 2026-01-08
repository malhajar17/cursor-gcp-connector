#!/bin/bash
export GOOGLE_APPLICATION_CREDENTIALS=/home/malhajar/lewinkface-python/.gcs-credentials.json

# Start LiteLLM
litellm --config /home/malhajar/litellm-config.yaml --port 4000 &
sleep 8

# Start proxy
python3 /home/malhajar/cursor-gcp-connector/proxy.py --debug &
sleep 2

# Start ngrok
ngrok http 4001 --log=stdout

# Keep running
wait
