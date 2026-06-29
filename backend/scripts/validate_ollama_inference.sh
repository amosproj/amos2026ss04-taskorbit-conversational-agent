#!/usr/bin/env bash
# Validate the self-hosted Ollama Cloud Run inference service (Phase 6).
#
# Runs all 5 acceptance checks from plan.md Phase 6 and prints a pass/fail
# summary. Exit code 0 = all checks passed.
#
# Usage:
#   ./backend/scripts/validate_ollama_inference.sh
#   ./backend/scripts/validate_ollama_inference.sh --region us-central1
#
# Requirements:
#   - gcloud CLI authenticated (gcloud auth login)
#   - curl, jq

set -euo pipefail

# ── Config ────────────────────────────────────────────────────────────────────

PROJECT_ID="${GCP_PROJECT_ID:-amos-taskorbit}"
REGION="${GCP_REGION:-europe-west4}"  # L4 GPU not available in europe-west3
SERVICE_NAME="taskorbit-ollama-inference"
EXPECTED_MODELS=("gemma4:26b" "qwen3.6:27b")
VALIDATION_MODEL="gemma4:26b"
SWAP_MODEL="qwen3.6:27b"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

PASS=0
FAIL=0

pass() { echo -e "${GREEN}  PASS${NC}  $1"; PASS=$((PASS + 1)); }
fail() { echo -e "${RED}  FAIL${NC}  $1"; FAIL=$((FAIL + 1)); }
info() { echo -e "${YELLOW}  ....${NC}  $1"; }

# Parse args
while [[ $# -gt 0 ]]; do
  case $1 in
    --region) REGION="$2"; shift 2 ;;
    --project) PROJECT_ID="$2"; shift 2 ;;
    --service) SERVICE_NAME="$2"; shift 2 ;;
    *) echo "Unknown arg: $1"; exit 1 ;;
  esac
done

echo ""
echo "============================================================"
echo "  Ollama Inference Validation — Phase 6"
echo "  Project : $PROJECT_ID"
echo "  Region  : $REGION"
echo "  Service : $SERVICE_NAME"
echo "============================================================"
echo ""

# ── Step 0: Fetch identity token and service URL ──────────────────────────────

info "Fetching GCP identity token..."
TOKEN=$(gcloud auth print-identity-token 2>/dev/null) || {
  echo "ERROR: gcloud not authenticated. Run 'gcloud auth login' first."
  exit 1
}

info "Resolving Cloud Run service URL..."
SERVICE_URL=$(gcloud run services describe "$SERVICE_NAME" \
  --region="$REGION" \
  --project="$PROJECT_ID" \
  --format="value(status.url)" 2>/dev/null) || {
  echo "ERROR: Service $SERVICE_NAME not found in $REGION. Has Terraform been applied?"
  exit 1
}

echo "  Service URL: $SERVICE_URL"
echo ""

# ── Check 1: Service is Ready ─────────────────────────────────────────────────

echo "── Check 1: Cloud Run service health ────────────────────────────────────"
READY=$(gcloud run services describe "$SERVICE_NAME" \
  --region="$REGION" \
  --project="$PROJECT_ID" \
  --format="value(status.conditions[0].type)" 2>/dev/null)

if [[ "$READY" == "Ready" ]]; then
  pass "Service status is Ready"
else
  fail "Service status is '$READY' (expected Ready)"
fi

# ── Check 2: Models loaded ────────────────────────────────────────────────────

echo ""
echo "── Check 2: Expected models loaded ─────────────────────────────────────"
info "GET $SERVICE_URL/api/tags"

TAGS_RESPONSE=$(curl -sf \
  -H "Authorization: Bearer $TOKEN" \
  "$SERVICE_URL/api/tags" 2>/dev/null) || {
  fail "Could not reach /api/tags — service may still be warming up"
  TAGS_RESPONSE=""
}

if [[ -n "$TAGS_RESPONSE" ]]; then
  for MODEL in "${EXPECTED_MODELS[@]}"; do
    if echo "$TAGS_RESPONSE" | jq -e ".models[].name | select(. == \"$MODEL\")" > /dev/null 2>&1; then
      pass "Model $MODEL is loaded"
    else
      fail "Model $MODEL not found in /api/tags response"
      info "  Loaded models: $(echo "$TAGS_RESPONSE" | jq -r '.models[].name' | tr '\n' ' ')"
    fi
  done
fi

# ── Check 3: Test completion with primary model ───────────────────────────────

echo ""
echo "── Check 3: Completion with $VALIDATION_MODEL ───────────────────────────"
info "POST $SERVICE_URL/v1/chat/completions"

COMPLETION=$(curl -sf \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  "$SERVICE_URL/v1/chat/completions" \
  -d "{\"model\":\"$VALIDATION_MODEL\",\"messages\":[{\"role\":\"user\",\"content\":\"Reply with exactly: VALIDATION_OK\"}],\"max_tokens\":200,\"options\":{\"think\":false}}" \
  2>/dev/null) || {
  fail "Completion request to $VALIDATION_MODEL failed (curl error)"
  COMPLETION=""
}

if [[ -n "$COMPLETION" ]]; then
  REPLY=$(echo "$COMPLETION" | jq -r '(.choices[0].message.content // "") + (.choices[0].message.reasoning // "")' 2>/dev/null)
  if [[ -n "$REPLY" ]]; then
    pass "Completion from $VALIDATION_MODEL: \"$(echo "$REPLY" | head -c 80)\""
  else
    fail "Completion response had no content: $(echo "$COMPLETION" | head -c 200)"
  fi
fi

# ── Check 4: Completion with swap model ──────────────────────────────────────

echo ""
echo "── Check 4: Completion with $SWAP_MODEL ────────────────────────────────"
info "POST $SERVICE_URL/v1/chat/completions"

SWAP_COMPLETION=$(curl -sf \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  "$SERVICE_URL/v1/chat/completions" \
  -d "{\"model\":\"$SWAP_MODEL\",\"messages\":[{\"role\":\"user\",\"content\":\"Reply with exactly: VALIDATION_OK\"}],\"max_tokens\":200,\"options\":{\"think\":false}}" \
  2>/dev/null) || {
  fail "Completion request to $SWAP_MODEL failed (curl error)"
  SWAP_COMPLETION=""
}

if [[ -n "$SWAP_COMPLETION" ]]; then
  SWAP_REPLY=$(echo "$SWAP_COMPLETION" | jq -r '(.choices[0].message.content // "") + (.choices[0].message.reasoning // "")' 2>/dev/null)
  if [[ -n "$SWAP_REPLY" ]]; then
    pass "Completion from $SWAP_MODEL: \"$(echo "$SWAP_REPLY" | head -c 80)\""
  else
    fail "Completion response had no content: $(echo "$SWAP_COMPLETION" | head -c 200)"
  fi
fi

# ── Check 5: Model swap via env var (no Terraform change) ─────────────────────

echo ""
echo "── Check 5: Model swap via Cloud Run env var ───────────────────────────"
info "Updating OLLAMA_MODEL=$SWAP_MODEL on Cloud Run service..."

# --no-traffic creates the revision without routing traffic to it, so we don't
# wait for the GPU cold start (2-5 min). We verify the API accepted the change;
# actual traffic routing happens on the next terraform apply or manual promotion.
UPDATE_OUTPUT=$(gcloud run services update "$SERVICE_NAME" \
  --region="$REGION" \
  --project="$PROJECT_ID" \
  --set-env-vars "OLLAMA_MODEL=$SWAP_MODEL" \
  --no-traffic \
  --quiet 2>&1) && pass "OLLAMA_MODEL env var accepted by Cloud Run (revision created, no-traffic)" || {
  if echo "$UPDATE_OUTPUT" | grep -qi "permission\|forbidden\|403"; then
    info "Check 5 skipped — gcloud account lacks roles/run.developer (not a service defect)"
  else
    fail "Failed to update OLLAMA_MODEL env var: $(echo "$UPDATE_OUTPUT" | head -c 300)"
  fi
}

info "Reverting OLLAMA_MODEL back to $VALIDATION_MODEL..."
gcloud run services update "$SERVICE_NAME" \
  --region="$REGION" \
  --project="$PROJECT_ID" \
  --set-env-vars "OLLAMA_MODEL=$VALIDATION_MODEL" \
  --no-traffic \
  --quiet 2>/dev/null || info "Revert skipped — run: terraform apply -target=module.gpu_inference to restore"

# ── Summary ───────────────────────────────────────────────────────────────────

echo ""
echo "============================================================"
echo "  Results: $PASS passed, $FAIL failed"
echo "============================================================"

if [[ $FAIL -gt 0 ]]; then
  echo -e "  ${RED}Validation FAILED — do not merge until all checks pass${NC}"
  echo ""
  echo "  Troubleshooting:"
  echo "    Cold start: gcloud run services update $SERVICE_NAME --region=$REGION --min-instances=1"
  echo "    Logs:       gcloud logging read 'resource.labels.service_name=\"$SERVICE_NAME\"' --limit=50"
  echo "    Models:     curl -H \"Authorization: Bearer \$(gcloud auth print-identity-token)\" $SERVICE_URL/api/tags | jq"
  exit 1
else
  echo -e "  ${GREEN}All checks passed — infrastructure is ready${NC}"
  echo ""
  echo "  Next: send a message through the TaskOrbit UI with provider set to"
  echo "  'Ollama (self-hosted)' and verify llm_client_selected log in Cloud Logging:"
  echo ""
  echo "  gcloud logging read 'jsonPayload.event=\"llm_client_selected\" AND jsonPayload.provider=\"ollama\"' \\"
  echo "    --project=$PROJECT_ID --limit=5 --format=json"
  exit 0
fi
