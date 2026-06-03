#!/bin/bash
# Quick demo — runs the cost reviewer against the bad_infra example
set -e

echo ""
echo "══════════════════════════════════════════════════════════"
echo "  Terraform Cost Reviewer — Demo"
echo "══════════════════════════════════════════════════════════"
echo ""

# Check for API key
if [ -z "$ANTHROPIC_API_KEY" ]; then
  echo "Error: ANTHROPIC_API_KEY is not set."
  echo "Export it with: export ANTHROPIC_API_KEY=your-key"
  exit 1
fi

# Install dependencies if needed
if ! python3 -c "import anthropic" 2>/dev/null; then
  echo "Installing dependencies..."
  pip3 install -r requirements.txt
fi

echo "Running cost review on examples/bad_infra ..."
echo ""
python3 agent.py ./examples/bad_infra
