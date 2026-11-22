#!/usr/bin/env bash
# Load Research Harness personal secrets from a local private env file and,
# on macOS, from Keychain.
#
# This file is safe to commit: it contains only lookup logic, not secrets.
# Preferred cross-platform location:
#   ~/.config/research-harness/private.env
#
# Store/update values with:
#   scripts/rh-keychain-set.sh
#
# Source it from direnv or a shell before running RH:
#   source scripts/rh-env-keychain.sh

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  echo "rh-env-keychain.sh must be sourced, not executed." >&2
  exit 2
fi

_rh_trim() {
  local value="$1"
  value="${value#"${value%%[!$' \t\r\n']*}"}"
  value="${value%"${value##*[!$' \t\r\n']}"}"
  printf '%s' "$value"
}

_rh_export_if_unset() {
  local name="$1"
  local value="$2"

  if [[ -n "${!name:-}" || -z "$value" ]]; then
    return 0
  fi

  export "${name}=${value}"
}

_rh_load_private_env_file() {
  local file="$1"
  local line key value

  if [[ -z "$file" || ! -f "$file" ]]; then
    return 0
  fi

  while IFS= read -r line || [[ -n "$line" ]]; do
    line="$(_rh_trim "$line")"
    if [[ -z "$line" || "$line" == \#* ]]; then
      continue
    fi
    if [[ "$line" == export[[:space:]]* ]]; then
      line="$(_rh_trim "${line#export}")"
    fi
    if [[ "$line" != *=* ]]; then
      continue
    fi

    key="$(_rh_trim "${line%%=*}")"
    value="$(_rh_trim "${line#*=}")"
    if [[ ! "$key" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]]; then
      continue
    fi
    if [[ "$value" == \"*\" && "$value" == *\" ]]; then
      value="${value:1:${#value}-2}"
    elif [[ "$value" == \'*\' && "$value" == *\' ]]; then
      value="${value:1:${#value}-2}"
    fi
    _rh_export_if_unset "$key" "$value"
  done <"$file"
}

_rh_keychain_get() {
  local name="$1"
  local keychain="${RH_KEYCHAIN_PATH:-${HOME}/Library/Keychains/login.keychain-db}"

  if ! command -v /usr/bin/security >/dev/null 2>&1; then
    return 1
  fi

  /usr/bin/security find-generic-password \
    -a "${USER:-$(id -un)}" \
    -s "research-harness:${name}" \
    -w "$keychain" 2>/dev/null || true
}

_rh_export_secret() {
  local name="$1"
  local value

  value="$(_rh_keychain_get "$name")"
  if [[ -n "$value" ]]; then
    _rh_export_if_unset "$name" "$value"
  fi
}

_rh_load_private_env_file "${RESEARCH_HARNESS_PRIVATE_ENV:-}"
_rh_load_private_env_file "${XDG_CONFIG_HOME:-${HOME}/.config}/research-harness/private.env"

# Scholarly search sources are keyless; only contact metadata is exported.
_rh_export_secret UNPAYWALL_EMAIL
_rh_export_secret PUBMED_EMAIL
_rh_export_secret MINERU_API_TOKEN
_rh_export_secret FAL_KEY
_rh_export_secret GOOGLE_API_KEY
_rh_export_secret RESEARCH_HARNESS_FIGURE_MODEL
_rh_export_secret RESEARCH_HARNESS_FIGURE_GEMINI_MODEL
_rh_export_secret RESEARCH_HARNESS_FIGURE_IMAGE_TIMEOUT_SECONDS
_rh_export_secret ZOTERO_API_KEY
_rh_export_secret ZOTERO_LIBRARY_ID
_rh_export_secret ZOTERO_LIBRARY_TYPE

# OpenReview only needs an enable flag for the public conference mirrors.
export OPENREVIEW_ENABLE="${OPENREVIEW_ENABLE:-1}"

unset -f _rh_keychain_get
unset -f _rh_export_secret
unset -f _rh_load_private_env_file
unset -f _rh_export_if_unset
unset -f _rh_trim
