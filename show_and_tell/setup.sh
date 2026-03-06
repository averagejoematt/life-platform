#!/bin/bash
# show_and_tell/setup.sh
# One-time setup for the Show & Tell pipeline on macOS with Homebrew Python
#
# Usage: bash setup.sh

set -e
cd "$(dirname "$0")"

echo ""
echo "╔══════════════════════════════════════════════╗"
echo "║   Life Platform — Show & Tell Setup          ║"
echo "╚══════════════════════════════════════════════╝"
echo ""

# 1. Create virtual environment
echo "Creating virtual environment..."
python3 -m venv .venv
echo "✓ .venv created"

# 2. Activate and install deps
echo "Installing dependencies..."
source .venv/bin/activate
pip install --quiet playwright pillow reportlab
echo "✓ playwright, pillow, reportlab installed"

# 3. Install Playwright browser
echo "Installing Chromium (for automated screenshots)..."
playwright install chromium
echo "✓ Chromium installed"

# 4. Make scripts executable
chmod +x run.sh
echo "✓ run.sh is executable"

# 5. Dashboard cookie prompt
echo ""
echo "─────────────────────────────────────────────────"
echo "DASHBOARD COOKIE SETUP"
echo "─────────────────────────────────────────────────"
echo "To automate dashboard screenshots, you need your auth cookie."
echo ""
echo "Steps:"
echo "  1. Open https://dash.averagejoematt.com in Chrome"
echo "  2. DevTools (Cmd+Opt+I) → Application → Cookies"
echo "  3. Find 'auth_token' → copy the Value"
echo "  4. Run: echo \"export DASH_COOKIE='paste-value-here'\" >> ~/.zshrc"
echo "          source ~/.zshrc"
echo ""
echo "─────────────────────────────────────────────────"
echo ""
echo "✅ Setup complete!"
echo ""
echo "Next time you want a PDF, just run:"
echo "  cd show_and_tell"
echo "  ./run.sh --open"
echo ""
