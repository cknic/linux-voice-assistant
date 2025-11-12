#!/bin/bash
# Script to check and merge updates from all upstream sources

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}=== Fetching from all remotes ===${NC}"
git fetch --all --prune

echo ""
echo -e "${BLUE}=== Current Commits ===${NC}"
echo -e "${GREEN}Upstream (OHF-Voice):${NC}  $(git log -1 --oneline upstream/main)"
echo -e "${GREEN}Omar's fork:${NC}          $(git log -1 --oneline omar/main)"
echo -e "${GREEN}Imonlinux's fork:${NC}     $(git log -1 --oneline imonlinux/main)"
echo -e "${GREEN}Your integration:${NC}     $(git log -1 --oneline integration)"

echo ""
echo -e "${BLUE}=== Checking for new commits ===${NC}"

# Check upstream
UPSTREAM_NEW=$(git log --oneline integration..upstream/main --no-merges | wc -l)
if [ "$UPSTREAM_NEW" -gt 0 ]; then
    echo -e "${YELLOW}Upstream has $UPSTREAM_NEW new commit(s):${NC}"
    git log --oneline integration..upstream/main --no-merges | head -5
else
    echo -e "${GREEN}✓ No updates from upstream${NC}"
fi

echo ""

# Check omar
OMAR_NEW=$(git log --oneline integration..omar/main --no-merges | wc -l)
if [ "$OMAR_NEW" -gt 0 ]; then
    echo -e "${YELLOW}Omar's fork has $OMAR_NEW new commit(s):${NC}"
    git log --oneline integration..omar/main --no-merges | head -5
else
    echo -e "${GREEN}✓ No updates from Omar${NC}"
fi

echo ""

# Check imonlinux
IMON_NEW=$(git log --oneline integration..imonlinux/main --no-merges | wc -l)
if [ "$IMON_NEW" -gt 0 ]; then
    echo -e "${YELLOW}Imonlinux's fork has $IMON_NEW new commit(s):${NC}"
    git log --oneline integration..imonlinux/main --no-merges | head -5
else
    echo -e "${GREEN}✓ No updates from Imonlinux${NC}"
fi

echo ""
echo -e "${BLUE}=== To merge updates, run: ===${NC}"
if [ "$UPSTREAM_NEW" -gt 0 ]; then
    echo "  git checkout integration && git merge upstream/main"
fi
if [ "$OMAR_NEW" -gt 0 ]; then
    echo "  git checkout integration && git merge omar/main"
fi
if [ "$IMON_NEW" -gt 0 ]; then
    echo "  git checkout integration && git merge imonlinux/main"
fi

echo ""
echo -e "${BLUE}=== To update main branch with upstream: ===${NC}"
echo "  git checkout main && git pull upstream main && git push origin main"
