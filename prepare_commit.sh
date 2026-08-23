#!/bin/bash
# Git Commit Preparation Script for OAuth 2.1 + GCIP Integration
# Run this to review changes, stage files, and prepare for commit

set -e

REPO_DIR="/home/wfcurti/ditrasoftware/mcp"
cd "$REPO_DIR"

echo "═══════════════════════════════════════════════════════════════"
echo "OAuth 2.1 + GCIP Integration - Git Commit Preparation"
echo "═══════════════════════════════════════════════════════════════"
echo ""

# 1. Show files to be committed
echo "📋 FILES TO COMMIT:"
echo "─────────────────────────────────────────────────────────────"
echo ""
echo "✨ NEW FILES (add to git):"
git status --porcelain | grep "^??" | while read -r line; do
    file=$(echo "$line" | awk '{$1=""; print $0}' | xargs)
    echo "  + $file"
done
echo ""

echo "📝 MODIFIED FILES (update in git):"
git status --porcelain | grep "^ M" | while read -r line; do
    file=$(echo "$line" | awk '{$1=""; print $0}' | xargs)
    echo "  ~ $file"
done
echo ""

# 2. Show file statistics
echo "📊 CHANGE STATISTICS:"
echo "─────────────────────────────────────────────────────────────"
echo ""
echo "New Python modules (OAuth 2.1 + Tenant context):"
if [ -f servers/anticafarmacia_mcp/oauth2_1.py ]; then
    lines=$(wc -l < servers/anticafarmacia_mcp/oauth2_1.py)
    echo "  • oauth2_1.py: $lines lines"
fi
if [ -f servers/anticafarmacia_mcp/tenant_context.py ]; then
    lines=$(wc -l < servers/anticafarmacia_mcp/tenant_context.py)
    echo "  • tenant_context.py: $lines lines"
fi
echo ""

echo "Configuration files:"
if [ -f servers/anticafarmacia_mcp/.env_example ]; then
    lines=$(wc -l < servers/anticafarmacia_mcp/.env_example)
    echo "  • .env_example: $lines lines"
fi
if [ -f servers/anticafarmacia_mcp/.env_anticafarmacia_mcp ]; then
    lines=$(wc -l < servers/anticafarmacia_mcp/.env_anticafarmacia_mcp)
    echo "  • .env_anticafarmacia_mcp: $lines lines"
fi
echo ""

echo "Documentation:"
if [ -f DEPLOYMENT_REVIEW_OAUTH2_GCIP.md ]; then
    lines=$(wc -l < DEPLOYMENT_REVIEW_OAUTH2_GCIP.md)
    echo "  • DEPLOYMENT_REVIEW_OAUTH2_GCIP.md: $lines lines"
fi
echo ""

# 3. Show diff summary
echo "📈 DIFF SUMMARY (modified files only):"
echo "─────────────────────────────────────────────────────────────"
git diff --stat servers/anticafarmacia_mcp/ DEPLOYMENT_REVIEW_OAUTH2_GCIP.md 2>/dev/null | tail -20 || echo "  (no diffs yet)"
echo ""

# 4. Pre-commit checklist
echo "✅ PRE-COMMIT VERIFICATION CHECKLIST:"
echo "─────────────────────────────────────────────────────────────"
echo ""

# Check Python syntax
echo "Checking Python syntax..."
python3 -m py_compile servers/anticafarmacia_mcp/oauth2_1.py 2>/dev/null && echo "  ✅ oauth2_1.py: valid" || echo "  ❌ oauth2_1.py: SYNTAX ERROR"
python3 -m py_compile servers/anticafarmacia_mcp/tenant_context.py 2>/dev/null && echo "  ✅ tenant_context.py: valid" || echo "  ❌ tenant_context.py: SYNTAX ERROR"
echo ""

# Check imports
echo "Checking module imports..."
python3 -c "import sys; sys.path.insert(0, 'servers/anticafarmacia_mcp'); import oauth2_1; print('  ✅ oauth2_1.py: imports OK')" 2>/dev/null || echo "  ⚠️  oauth2_1.py: import issues (may need dependencies)"
python3 -c "import sys; sys.path.insert(0, 'servers/anticafarmacia_mcp'); import tenant_context; print('  ✅ tenant_context.py: imports OK')" 2>/dev/null || echo "  ⚠️  tenant_context.py: import issues (may need fastmcp)"
echo ""

# Check env files
echo "Checking configuration files..."
if [ -f servers/anticafarmacia_mcp/.env_example ]; then
    echo "  ✅ .env_example: $(wc -l < servers/anticafarmacia_mcp/.env_example) lines"
fi
if [ -f servers/anticafarmacia_mcp/.env_anticafarmacia_mcp ]; then
    echo "  ✅ .env_anticafarmacia_mcp: $(wc -l < servers/anticafarmacia_mcp/.env_anticafarmacia_mcp) lines (WITH TEST CREDENTIALS)"
fi
echo ""

# Check YAML
echo "Checking Docker Compose YAML syntax..."
if command -v yamllint &> /dev/null; then
    yamllint servers/anticafarmacia_mcp/docker-compose.yml > /dev/null 2>&1 && echo "  ✅ docker-compose.yml: valid YAML" || echo "  ⚠️  docker-compose.yml: YAML issues"
else
    echo "  ℹ️  yamllint not installed (skipping YAML validation)"
fi
echo ""

# 5. Next steps
echo "═══════════════════════════════════════════════════════════════"
echo "📖 NEXT STEPS:"
echo "─────────────────────────────────────────────────────────────"
echo ""
echo "1. REVIEW CHANGES:"
echo "   git diff servers/anticafarmacia_mcp/"
echo ""
echo "2. STAGE NEW FILES:"
echo "   git add servers/anticafarmacia_mcp/oauth2_1.py"
echo "   git add servers/anticafarmacia_mcp/tenant_context.py"
echo "   git add servers/anticafarmacia_mcp/.env_anticafarmacia_mcp"
echo "   git add servers/anticafarmacia_mcp/docker-compose.anticafarmacia_mcp.yml"
echo "   git add DEPLOYMENT_REVIEW_OAUTH2_GCIP.md"
echo "   git add prepare_commit.sh  # (this script)"
echo ""
echo "3. STAGE MODIFIED FILES:"
echo "   git add servers/anticafarmacia_mcp/.env_example"
echo "   git add servers/anticafarmacia_mcp/docker-compose.yml"
echo "   git add servers/anticafarmacia_mcp/README.md"
echo "   git add servers/anticafarmacia_mcp/settings.py"
echo "   git add servers/anticafarmacia_mcp/gateway/remote_auth.py"
echo "   git add servers/anticafarmacia_mcp/oauth.py"
echo "   git add servers/anticafarmacia_mcp/server.py"
echo "   git add servers/anticafarmacia_mcp/Dockerfile"
echo "   git add servers/anticafarmacia_mcp/docker-compose-mcp.yml"
echo ""
echo "4. REVIEW STAGED CHANGES:"
echo "   git status"
echo "   git diff --cached"
echo ""
echo "5. COMMIT WITH MESSAGE:"
echo "   git commit -m \"feat(anticafarmacia-mcp): OAuth 2.1 + GCIP multi-tenant support\""
echo ""
echo "6. PUSH TO REMOTE:"
echo "   git push origin main"
echo ""
echo "⚠️  IMPORTANT:"
echo "   • .env_anticafarmacia_mcp contains real test credentials"
echo "   • Ensure .env is in .gitignore for production deployments"
echo "   • Review DEPLOYMENT_REVIEW_OAUTH2_GCIP.md before committing"
echo ""
echo "═══════════════════════════════════════════════════════════════"
