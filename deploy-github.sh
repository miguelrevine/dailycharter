#!/usr/bin/env bash
# ============================================================
# DailyCharter — one-shot deploy to GitHub Pages
# ------------------------------------------------------------
# What it does:
#   1. Initializes a git repo in this folder (if needed)
#   2. Creates a GitHub repository and pushes the site
#   3. Enables GitHub Pages (branch: main, path: /)
#   4. Prints your live URL
#
# Requirements:
#   - git            https://git-scm.com
#   - GitHub CLI     https://cli.github.com   (gh auth login first)
#
# Usage:
#   chmod +x deploy-github.sh
#   ./deploy-github.sh              # repo name defaults to "dailycharter"
#   ./deploy-github.sh my-repo-name # custom repo name
# ============================================================
set -euo pipefail

REPO_NAME="${1:-dailycharter}"
BRANCH="main"

say()  { printf "\033[1;32m▸ %s\033[0m\n" "$*"; }
warn() { printf "\033[1;33m! %s\033[0m\n" "$*"; }
die()  { printf "\033[1;31m✗ %s\033[0m\n" "$*"; exit 1; }

# ---------- checks ----------
command -v git >/dev/null 2>&1 || die "git is not installed. Install it from https://git-scm.com"

if ! command -v gh >/dev/null 2>&1; then
  warn "GitHub CLI (gh) not found — falling back to manual instructions."
  cat <<'MANUAL'

  Manual deploy (5 minutes):
  1. Create an empty repo at https://github.com/new  (e.g. "dailycharter")
  2. In this folder run:
       git init -b main
       git add .
       git commit -m "DailyCharter site v1"
       git remote add origin https://github.com/<YOUR_USER>/dailycharter.git
       git push -u origin main
  3. On GitHub: repo → Settings → Pages → Source: "Deploy from a branch"
     → Branch: main, folder: / (root) → Save
  4. Your site goes live at https://<YOUR_USER>.github.io/dailycharter/

MANUAL
  exit 1
fi

gh auth status >/dev/null 2>&1 || die "gh is installed but not authenticated. Run: gh auth login"

# ---------- git init & commit ----------
if [ ! -d .git ]; then
  say "Initializing git repository"
  git init -b "$BRANCH"
fi

# Don't ship the deploy script's noise or OS junk
[ -f .gitignore ] || printf ".DS_Store\nThumbs.db\n" > .gitignore

git add .
if git diff --cached --quiet; then
  say "Nothing new to commit"
else
  git commit -m "DailyCharter site — $(date +%Y-%m-%d)"
  say "Committed"
fi

# ---------- create repo & push ----------
OWNER="$(gh api user --jq .login)"

if git remote get-url origin >/dev/null 2>&1; then
  say "Remote 'origin' already set — pushing"
  git push -u origin "$BRANCH"
else
  say "Creating github.com/$OWNER/$REPO_NAME and pushing"
  gh repo create "$REPO_NAME" --public --source=. --remote=origin --push \
    --description "CFA Level I study pills — one email a day"
fi

# ---------- enable GitHub Pages ----------
say "Enabling GitHub Pages (branch: $BRANCH, path: /)"
if ! gh api "repos/$OWNER/$REPO_NAME/pages" -X POST \
     -f "source[branch]=$BRANCH" -f "source[path]=/" >/dev/null 2>&1; then
  # POST fails if Pages already exists → try update instead
  gh api "repos/$OWNER/$REPO_NAME/pages" -X PUT \
     -f "source[branch]=$BRANCH" -f "source[path]=/" >/dev/null 2>&1 \
     || warn "Could not enable Pages via API — enable it in repo Settings → Pages"
fi

URL="https://$OWNER.github.io/$REPO_NAME/"
say "Done. Your site will be live in ~1 minute at:"
printf "\n  \033[1;36m%s\033[0m\n\n" "$URL"
say "Next deploys: just run this script again (it commits & pushes changes)."

# ---------- reminders ----------
cat <<'NOTES'
Post-deploy checklist:
  □ Custom domain? Settings → Pages → Custom domain (+ CNAME at your DNS)
  □ Connect the signup form to your ESP (Buttondown / MailerLite / ConvertKit)
  □ Wire Stripe into checkout.html (see INTEGRATION NOTES inside the file)
  □ Replace [BRACKETED] placeholders in privacy.html and terms.html
  □ pill-email.html is an EMAIL template — it goes in your ESP, not on the site
NOTES
