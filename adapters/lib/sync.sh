# skill-concierge — shell helpers shared by the adapters/*/install.sh installers.
#
# Sourced, never run: each installer sources this file from "$SCRIPT_DIR/../lib/sync.sh", a path
# derived from its own location. Only helpers whose bodies were byte-identical across the
# installers live here. The caller sets ROOT (the checkout to install) and, for
# _refuse_unexportable_checkout, VERSION (the SSOT version from .claude-plugin/plugin.json).
# Every helper must parse and run under macOS's stock /bin/bash 3.2.

# ver_ge A B — true iff dotted-integer version A >= B ("0.43.10" >= "0.43.9").
# Same comparator as bin/skill-search-mcp (the one-directional doctrine).
_ver_ge() {
  [ "$1" = "$2" ] && return 0
  awk -v a="$1" -v b="$2" 'BEGIN{
    na=split(a,A,"."); nb=split(b,B,"."); n=(na>nb)?na:nb
    for(i=1;i<=n;i++){x=(i<=na)?A[i]+0:0; y=(i<=nb)?B[i]+0:0
      if(x>y) exit 0; if(x<y) exit 1}
    exit 0}'
}

# _is_own_checkout — true when $ROOT is its own git top level. Compared by file identity (-ef), so a
# symlinked or case-variant path to a real checkout still counts; a plain directory inside some other
# repo does not.
_is_own_checkout() {
  local top
  top="$(git -C "$ROOT" rev-parse --show-toplevel 2>/dev/null)" || return 1
  [ -n "$top" ] && [ "$ROOT" -ef "$top" ]
}

# A git checkout installs HEAD (`git archive HEAD`), so HEAD's version is the one to install. An
# uncommitted version change (staged or not) would put HEAD's content in a dir named for the new
# version: refuse before any CLI call or write. A checkout git cannot read (git missing, a
# safe.directory refusal, a damaged repo) and one whose git dir is renamed to `git/` (the
# workbench's no-dot toggle) are refused too: copying either as a plain tree would ship its
# untracked files.
_refuse_unexportable_checkout() {
  if _is_own_checkout; then
    HEAD_VERSION="$(git -C "$ROOT" show HEAD:.claude-plugin/plugin.json 2>/dev/null \
      | python3 -c "import json,sys;print(json.load(sys.stdin)['version'])" 2>/dev/null || true)"
    if [ "$HEAD_VERSION" != "$VERSION" ]; then
      echo "!! .claude-plugin/plugin.json says v$VERSION but HEAD carries v${HEAD_VERSION:-none}; this installer" >&2
      echo "   installs HEAD. Commit the version change (or restore the file), then re-run." >&2
      exit 1
    fi
  elif [ -f "$ROOT/git/HEAD" ]; then
    echo "!! $ROOT keeps its git database in git/ (renamed from .git). Copying it as a plain tree" >&2
    echo "   would ship that database and every untracked file. Rename git/ back to .git, then re-run." >&2
    exit 1
  elif [ -e "$ROOT/.git" ]; then
    echo "!! $ROOT is a git checkout, but git cannot read it (git missing, a safe.directory refusal, or a" >&2
    echo "   damaged repo). Copying it as a plain tree would ship every untracked file. Fix git, then re-run." >&2
    exit 1
  fi
}

# _export_to DIR — stage this checkout's content beside DIR, then swap it in, so an interrupted
# copy never leaves a half-filled DIR. The staging dir is trapped (EXIT/INT/TERM); one older than
# 60 minutes from a killed run is pruned. An old DIR is kept once, as hidden .DIR.replaced-<time>,
# which neither a version scan nor skill discovery reads. For a cache parent this plugin owns
# alone; OMP's shared cache parent uses _omp_export_to in adapters/omp/install.sh instead.
_export_to() {
  local dest="$1" parent base stage old
  parent="$(dirname "$dest")"; base="$(basename "$dest")"
  mkdir -p "$parent"
  find "$parent" -maxdepth 1 -name '.skill-concierge-staging.*' -type d -mmin +60 -exec rm -rf {} + 2>/dev/null || true
  # $parent here is this plugin's OWN cache dir (<harness cache>/skill-concierge/skill-concierge),
  # never shared with another plugin, so a bare '.staging.*' found here is provably ours too: a
  # leftover from a run killed under a version before the prefix above was renamed to be
  # skill-concierge-specific. Safe to prune the same way.
  find "$parent" -maxdepth 1 -name '.staging.*' -type d -mmin +60 -exec rm -rf {} + 2>/dev/null || true
  # Register the trap BEFORE the dir exists: a signal that lands between mktemp and a later
  # `trap` line would hit bash's default action and strand the dir. bash runs a trap only
  # between commands, so the assignment below always completes first and $stage is then set.
  stage=""
  trap '[ -z "$stage" ] || rm -rf "$stage"; exit 1' EXIT INT TERM
  stage="$(mktemp -d "$parent/.skill-concierge-staging.XXXXXX")"
  if _is_own_checkout; then
    # Each pipeline runs in its own subshell. bash forks a pipeline's second stage after its first,
    # and a TERM/INT landing in between, while this shell holds the trap above, leaves the first
    # stage blocked on a pipe this shell itself keeps open: the installer hangs and never reaches
    # its cleanup. The subshell carries no trap, so the shell that does only ever forks one child.
    if ! ( git -C "$ROOT" archive HEAD | tar -x -C "$stage" ); then
      echo "!! exporting HEAD to $dest failed (see above); nothing was changed" >&2; exit 1
    fi
    echo "    exported HEAD → $dest"
  else
    # A tree with no git metadata at all: copy everything except scratch dirs.
    if ! ( tar -C "$ROOT" -cf - \
        --exclude='.git' --exclude='.ijfw' --exclude='ijfw' --exclude='.handoff' \
        --exclude='logs' --exclude='graphify-out' --exclude='.claude' \
        --exclude='.zcode' --exclude='.unlazy' \
        --exclude='node_modules' --exclude='__pycache__' --exclude='.venv' \
        --exclude='.pytest_cache' --exclude='.mypy_cache' --exclude='.ruff_cache' \
        . | tar -xf - -C "$stage" ); then
      echo "!! copying $ROOT to $dest failed (see above); nothing was changed" >&2; exit 1
    fi
    echo "    copied the working tree (not a git checkout) → $dest"
  fi
  chmod 755 "$stage"   # mktemp makes it 0700; the swapped-in tree must read like the CLI's
  if [ -e "$dest" ]; then
    for old in "$parent/.$base.replaced-"*; do [ -e "$old" ] && rm -rf "$old"; done
    mv "$dest" "$parent/.$base.replaced-$(date +%Y%m%d-%H%M%S)-$$"
  fi
  mv "$stage" "$dest"
  trap - EXIT INT TERM
}
