#!/usr/bin/env python3
"""Coexistence-aware installer engine for the Claude Code harness.

Subcommands: plan | apply | uninstall | snapshot

DESIGN CONTRACT (the parts that are load-bearing for safety):

1. TWO HOMES, RESOLVED SEPARATELY.
   - isolated root  = <prefix>/harness   (everything the installer OWNS)
   - config home    = --config-dir  >  $CLAUDE_CONFIG_DIR  >  $HOME/.claude
     (the same expression this repo's own security hook uses at
      hooks/userprompt-consent-allowlist.sh:363)
   The config home is NEVER treated as a clone target. Only the paths declared in
   the profile's live_footprint may be created there.

2. THE BRIDGE IS INDIRECTION, NEVER A COPY.
   <config_home>/harness is a symlink to the isolated root. hooks/lib/claude_home.sh
   resolves by walking up from its own ${BASH_SOURCE[0]} with `pwd -P` (physical
   path), so resolution started at <config_home>/harness/hooks/lib lands on the
   ISOLATED root. A copied harness beneath the config home would resolve to the
   config home instead -- i.e. it would rebuild the clone-over-home ritual.

3. THE INSTALLER NEVER RENDERS A USER'S settings.json FROM A TEMPLATE.
   Template rendering is the known-destructive path. The only settings mutation is
   an ADDITIVE append of hook registration groups that are not already present.
   Every pre-existing key -- permissions, env, model, theme, unrecognized extension
   keys -- and every pre-existing hook registration and its order are preserved.

4. BACKUP BEFORE TOUCH, ATOMIC WRITE, ROLLBACK ON FAILURE.
   A file's backup is captured from the live bytes BEFORE the first write to it.
   Writes into the config home go to a temporary file in the same directory and are
   moved into place with os.replace (atomic rename). If any config-home write
   fails, the whole config-home change set is rolled back from the in-run journal.
   The atomic rename allocates a NEW inode for the rewritten file; that is why the
   profile declares settings.json in `mutable_paths`, for which inode identity is
   deliberately NOT an invariant (node type, path, backup parity and no-alias are).

5. OWNERSHIP IS RECORDED, NOT INFERRED.
   Apply writes an inventory of exactly what it created and modified. Uninstall
   removes file/link entries by exact path (never following a link) and removes a
   dir entry ONLY IF IT IS THEN EMPTY. A dir entry never authorizes recursive
   deletion, which is what lets a user file created inside an installer-owned
   directory survive uninstall.

6. OWNERSHIP OF settings.json IS RECORDED PER CONTRIBUTION, NOT PER FILE.
   A whole-file restore is NOT the inverse of an additive merge: it reverts every
   change the user made after the install too. Apply therefore records every
   registration identity it decided about -- `contributions` (appended by this
   generation) and `observations` (found already present, so either `claimed` from
   this lineage's own prior committed record, or `unowned` and never removable).
   Uninstall computes the true inverse from that record against the CURRENT
   document. The pre-install backup is retained as a manual-recovery artifact and
   is written back only on the provable-safe fast path, where the live bytes still
   equal the recorded as-installed digest.

7. LOCATE AND VERIFY ARE DIFFERENT OPERATIONS WITH DIFFERENT KEYS.
   A registration is LOCATED by its full identity tuple
   (event, normalized matcher read from the ENCLOSING GROUP, hook type, command).
   The entry digest is a post-location integrity check ONLY -- never a locator.
   It is matcher-blind by construction (`matcher` is a group-level key and the
   digested entry object does not contain it), so the installer's universal
   registration and a user's copy of the same command under a narrower matcher
   digest identically while their identities differ.

Exit codes: 0 = success
            1 = failure (crash, I/O error)
            2 = preflight / refusal -- NOTHING was mutated
            3 = partial -- a mutation occurred and something was deliberately
                retained (partial un-merge, opted-in partial install, retained
                self-management bundle)
"""

from __future__ import annotations

import argparse
import ast
import copy
import hashlib
import json
import os
import shutil
import stat
import sys
from pathlib import Path

STATE_REL = "state/install-state.json"
BACKUPS_REL = "backups"
STATE_SCHEMA_V1 = "claude-harness/install-state/v1"
STATE_SCHEMA = "claude-harness/install-state/v2"

# R9 -- the self-management bundle. An EXPLICIT, NON-RECURSIVE, versioned file
# list shipped beneath the isolated root so uninstall runs with no source
# checkout present. A recursive copy of scripts/install/ would re-import the test
# harness and every future sibling file, so the list is enumerated, recorded in
# state, and validated before use.
SELF_MANAGE_REL = ".self-manage"
SELF_MANAGE_VERSION = "claude-harness/self-manage/v1"
SELF_MANAGE_FILES = ("installer.py", "profile.json", "uninstall")

EXIT_OK = 0
EXIT_FAILURE = 1
EXIT_REFUSAL = 2
EXIT_PARTIAL = 3

# Results that mean "something the installer put here is still here on purpose".
# Each one suppresses payload removal and makes the run a partial uninstall.
RETAINED_RESULTS = ("kept-user-modified", "ambiguous-kept", "kept-unrecognized-residual")


class Refusal(Exception):
    """A refusal raised strictly BEFORE the first mutation.

    Carries its own exit code so the caller never has to re-derive one. The
    invariant every raise site must honour: nothing has been written to the
    config home, the state file, or the payload at the point this is raised.
    """

    def __init__(self, message: str, code: int = EXIT_REFUSAL, plan: list | None = None):
        super().__init__(message)
        self.code = code
        self.plan = plan or []


class DuplicateKeyError(ValueError):
    """R15 -- a JSON document carrying a duplicate key at any level.

    json.loads silently keeps the LAST occurrence, so a load/dump round-trip
    discards the earlier one. The document cannot be rewritten without losing
    user content, so both apply and uninstall refuse rather than normalize.
    """


# --------------------------------------------------------------------------- #
# NODE SNAPSHOT -- the measurement instrument.
# lstat, never stat: symlinks are recorded by their RAW readlink text, not by
# what they resolve to, so a retargeted or dangling link is visible and a
# correctly preserved dangling link compares equal.
# --------------------------------------------------------------------------- #
def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def node_entry(path: Path) -> dict:
    st = path.lstat()
    if stat.S_ISLNK(st.st_mode):
        node_type, extra = "symlink", {"target": os.readlink(path)}
    elif stat.S_ISDIR(st.st_mode):
        node_type, extra = "dir", {}
    elif stat.S_ISREG(st.st_mode):
        node_type, extra = "file", {"sha256": sha256_file(path)}
    else:
        node_type, extra = "other", {}
    entry = {"type": node_type, "dev": st.st_dev, "ino": st.st_ino}
    entry.update(extra)
    return entry


def node_snapshot(root: Path) -> dict:
    """Recursive, symlink-NOT-following snapshot keyed by path relative to root.

    The root itself is recorded as ".", so creating the root is itself a visible
    state transition. A missing root yields an empty snapshot.
    """
    root = Path(root)
    out: dict[str, dict] = {}
    if not root.exists() and not root.is_symlink():
        return out
    out["."] = node_entry(root)
    if not (root.is_dir() and not root.is_symlink()):
        return out
    stack = [root]
    while stack:
        cur = stack.pop()
        try:
            children = sorted(cur.iterdir())
        except OSError:
            continue
        for child in children:
            rel = str(child.relative_to(root))
            try:
                entry = node_entry(child)
            except OSError:
                continue
            out[rel] = entry
            if entry["type"] == "dir":
                stack.append(child)
    return dict(sorted(out.items()))


# --------------------------------------------------------------------------- #
# Namespace resolution
# --------------------------------------------------------------------------- #
def resolve_config_home(explicit: str | None) -> Path:
    if explicit:
        return Path(explicit).expanduser()
    env = os.environ.get("CLAUDE_CONFIG_DIR")
    if env:
        return Path(env).expanduser()
    return Path(os.path.expanduser("~")) / ".claude"


def resolve_prefix(explicit: str | None) -> Path:
    if explicit:
        return Path(explicit).expanduser()
    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        return Path(xdg).expanduser() / "claude-harness"
    return Path(os.path.expanduser("~")) / ".local" / "share" / "claude-harness"


# --------------------------------------------------------------------------- #
# Context
# --------------------------------------------------------------------------- #
def norm_path(path) -> str:
    """Lexical normalization ONLY -- never resolves symlinks.

    R1 records and compares the config home in BOTH forms. Resolving only at
    uninstall time is unsound: a config home reached through a symlink the user
    has since repointed would resolve to a home the installer never touched.
    """
    return os.path.normpath(str(path))


class Ctx:
    def __init__(self, args):
        self.source = Path(args.source).resolve()
        self.profile_path = Path(args.profile_file) if args.profile_file else (
            self.source / "scripts" / "install" / "profiles" / f"{args.profile}.json"
        )
        try:
            with open(self.profile_path, encoding="utf-8") as fh:
                self.profile = json.load(fh)
        except FileNotFoundError as exc:
            # A missing checkout is a REFUSAL, not a crash: the caller must be able
            # to tell "nothing was written" from "something went wrong mid-write".
            raise Refusal(
                f"profile not found: {self.profile_path}\n"
                f"  The source checkout appears to be unavailable. Uninstall an install "
                f"made by this engine using the entrypoint shipped beneath the isolated "
                f"root ({SELF_MANAGE_REL}/uninstall), which carries its own profile "
                f"snapshot. Nothing was written.") from exc
        self.prefix = resolve_prefix(args.prefix)
        self.isolated_root = self.prefix / self.profile.get("isolated_root_subdir", "harness")
        self.config_home = resolve_config_home(args.config_dir)
        self.bridge_rel = next(
            e["path"] for e in self.profile["live_footprint"] if e["kind"] == "link"
        )
        self.bridge = self.config_home / self.bridge_rel
        self.state_path = self.prefix / STATE_REL
        # The engine mutates exactly ONE settings document, and which one is
        # declared by the profile rather than spelled as a literal here.
        mutable = list(self.profile.get("mutable_paths") or [])
        if len(mutable) != 1:
            raise Refusal(
                f"profile declares {len(mutable)} mutable path(s); this engine merges "
                "exactly one settings document and refuses to guess which. Nothing "
                "was written.")
        self.settings_rel = mutable[0]

    @property
    def settings_target(self) -> Path:
        return self.config_home / self.settings_rel

    @property
    def markers(self) -> tuple:
        """Path strings whose appearance in a hook command means "wired to us".

        Both forms are checked: registrations are written through the bridge, but
        a user may reference the isolated root directly.
        """
        return (str(self.bridge), str(self.isolated_root))

    def adopt_state_parameters(self, state: dict) -> None:
        """R9 -- take the isolated-root and bridge parameters from the STATE record.

        The uninstall path must not depend on the source checkout still describing
        the install that is being removed. The profile snapshot supplies defaults;
        the recorded generation is authoritative for what was actually installed.
        """
        gens = state.get("generations") or []
        if not gens:
            return
        latest = gens[-1]
        recorded_root = latest.get("isolated_root")
        if recorded_root:
            self.isolated_root = Path(recorded_root)
        recorded_bridge_rel = latest.get("bridge_rel")
        if recorded_bridge_rel:
            self.bridge_rel = recorded_bridge_rel
        self.bridge = self.config_home / self.bridge_rel
        recorded_settings_rel = latest.get("settings_rel")
        if recorded_settings_rel:
            self.settings_rel = recorded_settings_rel

    def load_state(self) -> dict:
        if self.state_path.is_file():
            with open(self.state_path, encoding="utf-8") as fh:
                return json.load(fh)
        return {"schema": STATE_SCHEMA, "generations": []}

    def write_state(self, state: dict) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(self.state_path, (json.dumps(state, indent=2) + "\n").encode("utf-8"))


def home_mismatches(record: dict, ctx: Ctx) -> list[str]:
    """R1 -- compare BOTH recorded forms of the config home. Either one differing
    is a refusal: the lexical form catches a different path, the install-time
    resolved form catches the same path pointing somewhere else."""
    problems = []
    lexical = record.get("config_home_lexical", record.get("config_home"))
    if lexical is not None and norm_path(lexical) != norm_path(ctx.config_home):
        problems.append(f"lexical config home: recorded {lexical!r} != requested "
                        f"{str(ctx.config_home)!r}")
    resolved = record.get("config_home_resolved")
    if resolved is not None:
        live = os.path.realpath(ctx.config_home)
        if norm_path(resolved) != norm_path(live):
            problems.append(f"install-time resolved config home: recorded {resolved!r} != "
                            f"requested {live!r}")
    return problems


# --------------------------------------------------------------------------- #
# Content generation
# --------------------------------------------------------------------------- #
def hook_groups(profile: dict, bridge: Path) -> list[tuple[str, dict]]:
    """(event, group) pairs, with <bridge> substituted in every command."""
    groups = []
    for reg in profile.get("hook_registrations", []):
        command = reg["command"].replace("<bridge>", str(bridge))
        group: dict = {}
        if reg.get("matcher"):
            group["matcher"] = reg["matcher"]
        group["hooks"] = [{"type": "command", "command": command}]
        groups.append((reg["event"], group))
    return groups


def isolated_settings_bytes(ctx: Ctx) -> bytes:
    """settings.json for the ISOLATED root.

    Two jobs: it is the structural sentinel hooks/lib/claude_home.sh looks for
    (settings.json + hooks/ + policies/ + scripts/ together), and it is a readable
    record of what this profile registers. It is the installer's OWN file -- it is
    never derived from, and never written over, the user's settings.json.
    """
    doc: dict = {
        "_generated_by": "scripts/install/installer.py",
        "_profile": ctx.profile.get("profile"),
        "_note": "Isolated-root reference copy. The live registration lives in the "
                 "user's own settings.json and is merged additively.",
        "hooks": {},
    }
    for event, group in hook_groups(ctx.profile, ctx.bridge):
        doc["hooks"].setdefault(event, []).append(copy.deepcopy(group))
    return (json.dumps(doc, indent=2, sort_keys=False) + "\n").encode("utf-8")


def command_doc_bytes(ctx: Ctx) -> bytes:
    body = f"""---
description: Run the installed Claude Code harness preflight (doctor) and report host support status.
---

# harness-doctor

Run the harness preflight for the isolated install at `{ctx.isolated_root}`.

```bash
bash "{ctx.bridge}/scripts/doctor"
```

Installed by the harness installer (profile: {ctx.profile.get('profile')}).
Remove it with `scripts/install/uninstall`.
"""
    return body.encode("utf-8")


# --------------------------------------------------------------------------- #
# REGISTRATION IDENTITY -- the single source of identity for BOTH the merge and
# its inverse. R5 and R3 must share this function: an un-merge written against a
# different key removes the user's copy instead of the installer's.
# --------------------------------------------------------------------------- #
def norm_matcher(matcher):
    """OA-2: absent, null and "" all denote the same universal matcher.

    hook_groups() omits the key entirely when falsy, so the installer's own output
    cannot distinguish them and neither may the identity function.
    """
    return matcher if matcher else None


def canonical_digest(obj) -> str:
    """sha256 over a canonical (sorted-key, tight-separator) serialization."""
    return hashlib.sha256(
        json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        .encode("utf-8")
    ).hexdigest()


def entry_digest(entry: dict) -> str:
    """Digest of the WHOLE entry object as written -- not just {type, command}.

    Both `type` and `command` are already inside the identity tuple, so a digest
    over only those two is recomputed identically by anything the tuple locates
    and can never mismatch. Digesting the whole object makes the digest sensitive
    to what the tuple cannot see -- a key the user added or changed alongside
    them -- which is what makes `kept-user-modified` reachable at all.
    """
    return canonical_digest(entry)


def group_metadata(group: dict) -> dict:
    """As-installed group-instance metadata: WHICH group the entry went into.

    Diagnostics only. It is explicitly NOT a removal gate and NOT a locator: an
    unrelated user addition elsewhere in the same group changes the group digest,
    which would wrongly retain an untouched installer entry.
    """
    return {"matcher": norm_matcher(group.get("matcher")),
            "entry_count": len(group.get("hooks") or []),
            "group_digest": canonical_digest(group)}


def identity_of(event: str, matcher, entry: dict) -> dict:
    return {"event": event, "matcher": norm_matcher(matcher),
            "hook_type": entry.get("type"), "command": entry.get("command")}


def identity_key(record: dict) -> tuple:
    return (record.get("event"), norm_matcher(record.get("matcher")),
            record.get("hook_type"), record.get("command"))


def iter_entries(doc: dict):
    """Yield (event, group_index, entry_index, group, entry) over hooks.

    The matcher is read from the ENCLOSING GROUP, which is where the schema puts
    it. Malformed sub-structures are skipped rather than raising: this walks a
    user's document, which the installer does not own.
    """
    hooks = doc.get("hooks")
    if not isinstance(hooks, dict):
        return
    for event, bucket in hooks.items():
        if not isinstance(bucket, list):
            continue
        for gi, group in enumerate(bucket):
            if not isinstance(group, dict):
                continue
            entries = group.get("hooks")
            if not isinstance(entries, list):
                continue
            for ei, entry in enumerate(entries):
                if isinstance(entry, dict):
                    yield event, gi, ei, group, entry


def locate(doc: dict, key: tuple) -> list[tuple]:
    """Every entry whose FULL identity tuple equals `key`. Never digest-keyed."""
    return [(e, gi, ei, g, h) for e, gi, ei, g, h in iter_entries(doc)
            if (e, norm_matcher(g.get("matcher")), h.get("type"), h.get("command")) == key]


def references_payload(command, markers) -> bool:
    return isinstance(command, str) and any(m and m in command for m in markers)


def load_json_strict(text: str):
    """json.loads that REFUSES duplicate keys at any level (R15)."""
    def object_pairs(pairs):
        seen = set()
        for key, _value in pairs:
            if key in seen:
                raise DuplicateKeyError(
                    f"duplicate key {key!r}; a load/dump round-trip would discard "
                    "the earlier occurrence, so the document is left untouched")
            seen.add(key)
        return dict(pairs)
    return json.loads(text, object_pairs_hook=object_pairs)


def merge_settings(existing: dict, groups: list[tuple[str, dict]],
                   markers: tuple = ()) -> tuple[dict, list, list, bool]:
    """ADDITIVE-ONLY merge. Returns (merged, contributions, observations, container_created).

    Nothing is ever removed, reordered, replaced or broadened. Registration groups
    are APPENDED to the end of their event list, so every pre-existing group keeps
    its position and its internal hook order. A registration whose FULL IDENTITY
    is already present in that event is not added again (idempotent re-install).

    `contributions` are the identities this call APPENDED. `observations` are the
    identities it DECIDED ABOUT and did not append, in two classes -- both are
    needed, or the un-merge's residual scan produces false partials:
      1. an exact profile identity already present, and
      2. a pre-existing FOREIGN entry referencing this install's payload. Under
         full-tuple identity a differently-matched user copy of our own command is
         a DIFFERENT identity, so the merge appends alongside it and class 1 never
         sees it -- yet its surviving command still names the payload path.

    Ownership (`claimed` vs `unowned`) is NOT decided here: it may only be derived
    from a prior COMMITTED generation of this lineage, never from the fact that an
    identity merely looks like something this profile would install.
    """
    merged = copy.deepcopy(existing)
    hooks = merged.get("hooks")
    container_created = False
    if hooks is None:
        hooks = {}
        merged["hooks"] = hooks
        container_created = True
    if not isinstance(hooks, dict):
        raise ValueError("settings.json 'hooks' is not an object; refusing to merge")

    # Captured BEFORE any append, so class-2 can never catch this run's own work.
    pre_existing = list(iter_entries(merged))

    contributions: list[dict] = []
    observations: list[dict] = []
    profile_keys: set[tuple] = set()

    for event, group in groups:
        bucket = hooks.get(event)
        event_created = False
        if bucket is None:
            bucket = []
            hooks[event] = bucket
            event_created = True
        if not isinstance(bucket, list):
            raise ValueError(f"settings.json hooks.{event} is not a list; refusing to merge")
        entry = group["hooks"][0]
        ident = identity_of(event, group.get("matcher"), entry)
        key = identity_key(ident)
        profile_keys.add(key)
        found = locate(merged, key)
        if found:
            _e, _gi, _ei, found_group, found_entry = found[0]
            observations.append({
                **ident,
                "entry_digest": entry_digest(found_entry),
                "group_instance_metadata": group_metadata(found_group),
                "group_created": False,
                "event_created": event_created,
                "append_ordinal": None,
                "ownership_disposition": None,
                "observation_class": "profile-identity-present",
            })
            continue
        new_group = copy.deepcopy(group)
        bucket.append(new_group)
        contributions.append({
            **ident,
            "entry_digest": entry_digest(new_group["hooks"][0]),
            "group_instance_metadata": group_metadata(new_group),
            "group_created": True,
            "event_created": event_created,
            "append_ordinal": len(bucket) - 1,
            "ownership_disposition": "inserted",
        })

    for event, _gi, _ei, group, entry in pre_existing:
        if not references_payload(entry.get("command"), markers):
            continue
        ident = identity_of(event, group.get("matcher"), entry)
        if identity_key(ident) in profile_keys:
            continue  # class 1 already recorded this identity
        observations.append({
            **ident,
            "entry_digest": entry_digest(entry),
            "group_instance_metadata": group_metadata(group),
            "group_created": False,
            "event_created": False,
            "append_ordinal": None,
            "ownership_disposition": None,
            "observation_class": "foreign-payload-reference",
        })
    return merged, contributions, observations, container_created


def legacy_v1_merge(existing: dict, groups: list[tuple[str, dict]]) -> tuple[dict, list, bool]:
    """FROZEN reproduction of the pre-R2 command-keyed merge. Never 'improve' it.

    Its only purpose is R4's migration proof: replaying it against a v1 record's
    recorded backup reconstructs what the legacy engine would have written. If the
    reconstruction is byte-equal to the live document, the live document is
    provably the unmodified legacy post-image and its contribution set is derived
    rather than guessed. Changing this function silently invalidates that proof.
    """
    merged = copy.deepcopy(existing)
    hooks = merged.get("hooks")
    container_created = False
    if hooks is None:
        hooks = {}
        merged["hooks"] = hooks
        container_created = True
    if not isinstance(hooks, dict):
        raise ValueError("settings.json 'hooks' is not an object; refusing to merge")

    added: list[dict] = []
    for event, group in groups:
        bucket = hooks.get(event)
        event_created = False
        if bucket is None:
            bucket = []
            hooks[event] = bucket
            event_created = True
        if not isinstance(bucket, list):
            raise ValueError(f"settings.json hooks.{event} is not a list; refusing to merge")
        command = group["hooks"][0]["command"]
        present = any(                                    # command-keyed: matcher-blind
            isinstance(g, dict)
            and any(
                isinstance(h, dict) and h.get("command") == command
                for h in (g.get("hooks") or [])
                if isinstance(g.get("hooks"), list)
            )
            for g in bucket
        )
        if present:
            continue
        new_group = copy.deepcopy(group)
        bucket.append(new_group)
        added.append({
            **identity_of(event, group.get("matcher"), new_group["hooks"][0]),
            "entry_digest": entry_digest(new_group["hooks"][0]),
            "group_instance_metadata": group_metadata(new_group),
            "group_created": True,
            "event_created": event_created,
            "append_ordinal": len(bucket) - 1,
            "ownership_disposition": "inserted",
        })
    return merged, added, container_created


def settings_bytes(doc: dict) -> bytes:
    return (json.dumps(doc, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


# --------------------------------------------------------------------------- #
# Planning
# --------------------------------------------------------------------------- #
def _file_change(path: Path, content: bytes) -> str | None:
    """create / modify / None (idempotent no-op -- not a durable transition)."""
    if path.is_symlink() or not path.exists():
        return "create" if not path.is_symlink() else "modify"
    if path.is_file():
        return None if path.read_bytes() == content else "modify"
    return "modify"


def foreign_symlink_ancestor(root: Path, rel: str) -> str | None:
    """The first ancestor of `rel` under `root` that is a symlink, if any.

    Writing a footprint entry through a symlinked ancestor would land the file
    somewhere the user never named -- on a host whose config home bridges
    `commands` into a git checkout, "create <config_home>/commands/x.md" silently
    writes into that repository. A footprint path is only honoured when every one
    of its ancestors is a real directory.
    """
    parts = Path(rel).parts[:-1]
    cur = root
    for part in parts:
        cur = cur / part
        if cur.is_symlink():
            return str(Path(*parts[: parts.index(part) + 1]))
    return None


def engine_source_bytes() -> bytes:
    return Path(__file__).resolve().read_bytes()


def bundle_uninstall_entrypoint(ctx: Ctx) -> bytes:
    """The payload-resident uninstall entrypoint (R9).

    It resolves the prefix from its OWN location rather than from a baked-in
    literal, so moving the payload does not strand it, and it points the engine at
    the profile SNAPSHOT beside it rather than at a source checkout.
    """
    body = f"""#!/usr/bin/env bash
# uninstall (payload-resident) -- remove exactly what the installer added.
#
# Shipped INTO the installed payload so uninstall works with no source checkout
# present. Takes its profile parameters from the snapshot beside it and from
# state/install-state.json, never from --source.
#
# Usage: {SELF_MANAGE_REL}/uninstall [--config-dir <dir>] [--keep-payload] [--json]
#
# Exit codes: 0 = success
#             1 = failure (crash, I/O error)
#             2 = preflight / refusal -- NOTHING was mutated
#             3 = partial -- a mutation occurred and something was deliberately
#                 retained (partial un-merge, retained self-management bundle)
set -uo pipefail

SELF_DIR="$(cd "$(dirname "${{BASH_SOURCE[0]}}")" && pwd -P)"
PREFIX="$(cd "$SELF_DIR/../.." && pwd -P)"
PY="${{CLAUDE_PYTHON_BIN:-python3}}"

exec "$PY" "$SELF_DIR/installer.py" uninstall \\
  --prefix "$PREFIX" \\
  --profile-file "$SELF_DIR/profile.json" \\
  "$@"
"""
    return body.encode("utf-8")


def self_manage_bytes(ctx: Ctx, name: str) -> bytes:
    if name == "installer.py":
        return engine_source_bytes()
    if name == "profile.json":
        return (json.dumps(ctx.profile, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    if name == "uninstall":
        return bundle_uninstall_entrypoint(ctx)
    raise ValueError(f"unknown self-management artifact: {name}")


def verify_bundle_self_contained(source: bytes) -> list[str]:
    """R9 -- every module the engine imports at runtime must be in the bundle.

    Measured rather than assumed: the engine is parsed and every top-level import
    is checked against the interpreter's own stdlib list. A non-stdlib import
    means the bundle would be incomplete and the payload unremovable once the
    checkout moves, so the install refuses instead of shipping a broken bundle.
    """
    stdlib = getattr(sys, "stdlib_module_names", None)
    if stdlib is None:
        return []  # interpreter cannot answer; do not fabricate a verdict
    modules: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                return [f"relative import (level {node.level}) -- not self-contained"]
            if node.module:
                modules.add(node.module.split(".")[0])
    return sorted(m for m in modules if m not in stdlib)


def mandatory_footprint_paths(ctx: Ctx) -> set[str]:
    """R8 -- which live_footprint entries are MANDATORY, derived STRUCTURALLY.

    An explicit per-entry "mandatory" boolean wins if the profile carries one
    (forward-compatible with a profile that adds it). Otherwise mandatory-ness is
    a structural match on the engine's OWN contracts: the entry that IS the bridge
    it resolves, and the entry that IS the settings document it merges. The `why`
    field is prose and MUST NOT be parsed -- inferring semantics from the word
    "MANDATORY" appearing in documentation is not machine-defined.
    """
    footprint = ctx.profile["live_footprint"]
    if any("mandatory" in entry for entry in footprint):
        return {e["path"] for e in footprint if e.get("mandatory") is True}

    bridge_hits = [e["path"] for e in footprint
                   if e["kind"] == "link" and ctx.config_home / e["path"] == ctx.bridge]
    settings_hits = [e["path"] for e in footprint
                     if e["kind"] == "file" and e.get("mutable") is True
                     and ctx.config_home / e["path"] == ctx.settings_target]
    if len(bridge_hits) != 1:
        raise Refusal(
            f"cannot derive the mandatory bridge entry structurally: {len(bridge_hits)} "
            "live_footprint entr(ies) match the engine's resolved bridge path. Refusing "
            "to guess. Nothing was written.")
    if len(settings_hits) != 1:
        raise Refusal(
            f"cannot derive the mandatory settings entry structurally: {len(settings_hits)} "
            "live_footprint entr(ies) match the engine's settings target. Refusing to "
            "guess. Nothing was written.")
    return {bridge_hits[0], settings_hits[0]}


def build_plan(ctx: Ctx) -> dict:
    """Deterministic plan. `changes` are DURABLE NET transitions only.

    Idempotent rewrites (identical content) are omitted; the temporary file used
    for the atomic rename is created and removed within the apply and is likewise
    not a durable transition. Persistent artifacts the installer leaves behind
    (backups, install state) ARE durable and are enumerated.
    """
    changes: list[dict] = []
    conflicts: list[dict] = []
    state = ctx.load_state()
    gen = f"gen-{len(state['generations']) + 1:03d}"

    def add(tree: str, rel: str, kind: str, change: str, detail: str):
        changes.append({"tree": tree, "path": rel, "kind": kind,
                        "change_kind": change, "detail": detail})

    # ---- prefix tree (installer-owned) ---------------------------------------
    def need_dir(rel: str, detail: str):
        target = ctx.prefix if rel == "." else ctx.prefix / rel
        if not target.exists():
            add("prefix", rel, "dir", "create", detail)

    need_dir(".", "installer data directory")
    sub = ctx.profile.get("isolated_root_subdir", "harness")
    need_dir(sub, "isolated install root")
    for d in ctx.profile["payload"].get("directories", []):
        need_dir(f"{sub}/{d}", "payload directory")

    for item in ctx.profile["payload"]["copied"]:
        src = ctx.source / item["src"]
        dest_rel = f"{sub}/{item['dest']}"
        dest = ctx.prefix / dest_rel
        if not src.is_file():
            raise FileNotFoundError(f"payload source missing: {src}")
        change = _file_change(dest, src.read_bytes())
        if change:
            add("prefix", dest_rel, "file", change, f"copy from {item['src']}")

    iso_settings_rel = f"{sub}/settings.json"
    change = _file_change(ctx.prefix / iso_settings_rel, isolated_settings_bytes(ctx))
    if change:
        add("prefix", iso_settings_rel, "file", change, "generated isolated-root settings")

    # ---- self-management bundle (R9) ----------------------------------------
    # Explicit, non-recursive, versioned. A recursive copy of scripts/install/
    # would re-import the acceptance harness and every future sibling file.
    unbundled = verify_bundle_self_contained(engine_source_bytes())
    if unbundled:
        raise Refusal(
            "the engine imports modules that the self-management bundle would not "
            f"carry: {', '.join(unbundled)}. Shipping it would leave an unremovable "
            "payload once the source checkout moves. Nothing was written.")
    need_dir(f"{sub}/{SELF_MANAGE_REL}", "self-management bundle directory")
    for artifact in SELF_MANAGE_FILES:
        rel_sm = f"{sub}/{SELF_MANAGE_REL}/{artifact}"
        change = _file_change(ctx.prefix / rel_sm, self_manage_bytes(ctx, artifact))
        if change:
            add("prefix", rel_sm, "file", change,
                "self-management bundle: uninstall without the source checkout")

    # ---- config home tree (the user's) --------------------------------------
    ch = ctx.config_home
    if not ch.exists():
        add("config_home", ".", "dir", "create", "config home did not exist")

    settings_plan: dict | None = None
    for entry in ctx.profile["live_footprint"]:
        rel, kind = entry["path"], entry["kind"]
        target = ch / rel
        if kind == "link":
            if target.is_symlink():
                if os.readlink(target) == str(ctx.isolated_root):
                    continue  # already the correct bridge -- idempotent
                conflicts.append({"tree": "config_home", "path": rel,
                                  "change_kind": "conflict",
                                  "detail": f"a different symlink already occupies the bridge "
                                            f"path (-> {os.readlink(target)}); it is left "
                                            "untouched. If it is a previous install with a "
                                            "different --prefix, run scripts/install/uninstall "
                                            "against that prefix first."})
            elif target.exists():
                conflicts.append({"tree": "config_home", "path": rel,
                                  "change_kind": "conflict",
                                  "detail": "a non-link node already occupies the bridge "
                                            "path; user's version retained. Re-run with a "
                                            "different profile bridge name to resolve."})
            else:
                add("config_home", rel, "link", "create", f"bridge -> {ctx.isolated_root}")
        elif kind == "dir":
            if not target.exists():
                add("config_home", rel, "dir", "create", "created only because it was absent")
        elif kind == "file" and rel == ctx.settings_rel:
            settings_plan = plan_settings(ctx, target, conflicts, state)
            if settings_plan and settings_plan["change_kind"]:
                add("config_home", rel, "file", settings_plan["change_kind"],
                    settings_plan["detail"])
        elif kind == "file":
            content = command_doc_bytes(ctx)
            foreign = foreign_symlink_ancestor(ch, rel)
            if foreign is not None:
                conflicts.append({"tree": "config_home", "path": rel,
                                  "change_kind": "conflict",
                                  "detail": f"'{foreign}' is a symlink, so writing here would "
                                            "put the file outside the config home entirely. "
                                            "Nothing is written through it."})
            elif target.exists() or target.is_symlink():
                if target.is_file() and target.read_bytes() == content:
                    continue  # ours already, unchanged
                conflicts.append({"tree": "config_home", "path": rel,
                                  "change_kind": "conflict",
                                  "detail": "a pre-existing file occupies this path; "
                                            "the user's version is retained and the "
                                            "installer's copy is NOT written"})
            else:
                add("config_home", rel, "file", "create", "installed command")

    # ---- backups for every config-home file this plan MODIFIES ---------------
    modified = [c for c in changes if c["tree"] == "config_home" and c["change_kind"] == "modify"]
    if modified:
        need_dir(BACKUPS_REL, "backup root")
        add("prefix", f"{BACKUPS_REL}/{gen}", "dir", "create", "backup generation")
        for c in modified:
            add("prefix", f"{BACKUPS_REL}/{gen}/{c['path']}", "file", "create",
                f"pre-touch backup of config_home/{c['path']}")

    need_dir("state", "install state directory")
    st_change = "modify" if ctx.state_path.is_file() else "create"
    add("prefix", STATE_REL, "file", st_change, "install inventory (ownership record)")

    # R8 -- which SKIPPED entries are mandatory. Recorded on the plan so the
    # decision to abort is taken by the caller, strictly before apply_plan runs
    # and therefore strictly before the first mutation.
    mandatory = mandatory_footprint_paths(ctx)
    skipped_mandatory = sorted({c["path"] for c in conflicts} & mandatory)

    return {"generation": gen, "changes": changes, "conflicts": conflicts,
            "settings_plan": settings_plan, "mandatory": sorted(mandatory),
            "skipped_mandatory": skipped_mandatory}


def resolve_ownership(observations: list, state: dict, ctx: Ctx) -> list:
    """Assign `claimed` or `unowned` to every observation.

    `claimed` may ONLY be derived from a prior COMMITTED generation of THIS install
    lineage that recorded the identity in its own `contributions[]`. It must never
    be inferred from equality against the profile's declared registrations: a user
    who had already registered the byte-identical command under the profile's own
    matcher would otherwise be recorded as installer-owned and DELETED on
    uninstall -- a new destructive path this design exists to prevent.
    """
    owned: set[tuple] = set()
    for gen in state.get("generations", []):
        if gen.get("record_status") != "committed":
            continue
        if home_mismatches(gen, ctx):
            continue
        for contribution in gen.get("contributions") or []:
            owned.add(identity_key(contribution))
    for observation in observations:
        observation["ownership_disposition"] = (
            "claimed" if identity_key(observation) in owned else "unowned")
    return observations


def read_settings_document(target: Path) -> dict:
    """Parse a live settings document, refusing what cannot survive a round-trip."""
    return load_json_strict(target.read_text(encoding="utf-8"))


def plan_settings(ctx: Ctx, target: Path, conflicts: list, state: dict) -> dict | None:
    groups = hook_groups(ctx.profile, ctx.bridge)
    rel = ctx.settings_rel
    if target.is_symlink():
        conflicts.append({"tree": "config_home", "path": rel,
                          "change_kind": "conflict",
                          "detail": "settings.json is a symlink; writing through it would "
                                    "modify a file outside the declared footprint. The "
                                    "user's version is retained and left untouched."})
        return None
    if not target.exists():
        doc, contributions, observations, container_created = merge_settings(
            {}, groups, ctx.markers)
        content = settings_bytes(doc)
        return {"change_kind": "create", "content": content,
                "contributions": contributions,
                "observations": resolve_ownership(observations, state, ctx),
                "container_created": container_created,
                "pre_image_sha256": None,
                "as_installed_sha256": hashlib.sha256(content).hexdigest(),
                "disposition": "created",
                "detail": f"create with {len(contributions)} hook registration(s)"}
    try:
        raw = target.read_bytes()
        existing = read_settings_document(target)
    except DuplicateKeyError as exc:
        # R15 -- a refusal, not a conflict: proceeding would silently drop the
        # user's earlier occurrence of the key.
        raise Refusal(
            f"{target}: {exc}\n"
            "  Resolve the duplicate key by hand, then re-run. Nothing was written.")
    except (OSError, json.JSONDecodeError) as exc:
        conflicts.append({"tree": "config_home", "path": rel,
                          "change_kind": "conflict",
                          "detail": f"unreadable/unparseable ({exc}); left untouched"})
        return None
    if not isinstance(existing, dict):
        conflicts.append({"tree": "config_home", "path": rel,
                          "change_kind": "conflict",
                          "detail": "top level is not an object; left untouched"})
        return None
    try:
        merged, contributions, observations, container_created = merge_settings(
            existing, groups, ctx.markers)
    except ValueError as exc:
        conflicts.append({"tree": "config_home", "path": rel,
                          "change_kind": "conflict", "detail": f"{exc}; left untouched"})
        return None
    observations = resolve_ownership(observations, state, ctx)
    pre_image = hashlib.sha256(raw).hexdigest()
    if not contributions:
        # Nothing to append -- but the observations still matter: they are what
        # lets the un-merge ACCOUNT a user's own payload-referencing entry
        # instead of reporting it as an unrecognized residual.
        return {"change_kind": None, "content": None,
                "contributions": [], "observations": observations,
                "container_created": False,
                "pre_image_sha256": pre_image,
                "as_installed_sha256": pre_image,
                "disposition": "unchanged",
                "detail": "already registered; no change"}
    content = settings_bytes(merged)
    return {"change_kind": "modify", "content": content,
            "contributions": contributions, "observations": observations,
            "container_created": container_created,
            "pre_image_sha256": pre_image,
            "as_installed_sha256": hashlib.sha256(content).hexdigest(),
            "disposition": "modified",
            "detail": f"append {len(contributions)} hook registration(s); "
                      f"{len(existing)} pre-existing top-level key(s) preserved"}


# --------------------------------------------------------------------------- #
# Apply
# --------------------------------------------------------------------------- #
def atomic_write(target: Path, content: bytes, mode: int = 0o644) -> None:
    tmp = target.parent / f".{target.name}.harness-install.tmp"
    with open(tmp, "wb") as fh:
        fh.write(content)
    os.chmod(tmp, mode)
    os.replace(tmp, target)


def apply_plan(ctx: Ctx, plan: dict) -> dict:
    sub = ctx.profile.get("isolated_root_subdir", "harness")
    gen = plan["generation"]
    journal: list[tuple[str, Path, bytes | None]] = []
    created: list[dict] = []
    modified: list[dict] = []

    # ---- phase 1: installer-owned tree (harmless to write incrementally) -----
    for c in plan["changes"]:
        if c["tree"] != "prefix" or c["kind"] != "dir":
            continue
        (ctx.prefix if c["path"] == "." else ctx.prefix / c["path"]).mkdir(
            parents=True, exist_ok=True)
    for item in ctx.profile["payload"]["copied"]:
        dest = ctx.prefix / sub / item["dest"]
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ctx.source / item["src"], dest)
        os.chmod(dest, int(item.get("mode", "0644"), 8))
    atomic_write(ctx.prefix / sub / "settings.json", isolated_settings_bytes(ctx))

    # ---- phase 1b: the self-management bundle (R9) ---------------------------
    bundle_dir = ctx.prefix / sub / SELF_MANAGE_REL
    bundle_dir.mkdir(parents=True, exist_ok=True)
    bundle_record = {"version": SELF_MANAGE_VERSION,
                     "root_relative": f"{sub}/{SELF_MANAGE_REL}",
                     "files": list(SELF_MANAGE_FILES), "digests": {}}
    for artifact in SELF_MANAGE_FILES:
        payload = self_manage_bytes(ctx, artifact)
        atomic_write(bundle_dir / artifact, payload,
                     0o755 if artifact in ("installer.py", "uninstall") else 0o644)
        bundle_record["digests"][artifact] = hashlib.sha256(payload).hexdigest()

    # ---- phase 2: pre-touch backups, captured from the LIVE bytes ------------
    backups: dict[str, str] = {}
    for c in plan["changes"]:
        if c["tree"] != "config_home" or c["change_kind"] != "modify":
            continue
        live = ctx.config_home / c["path"]
        bpath = ctx.prefix / BACKUPS_REL / gen / c["path"]
        bpath.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(live, bpath)          # BEFORE any write to `live`
        backups[c["path"]] = str(bpath)

    # ---- phase 2b: PREPARED intent record, written BEFORE the mutation -------
    # R2 durability ordering. The record that makes the mutation invertible must
    # not be written strictly after the mutation it describes: a process kill in
    # that window would otherwise leave a mutated settings.json with no ownership
    # record, which the legacy-record rule then declares unrecoverable -- the user
    # left with harness registrations the tool refuses to remove.
    settings_plan = plan.get("settings_plan") or {}
    state = ctx.load_state()
    record = {
        "generation": gen,
        "record_status": "prepared",
        "profile": ctx.profile.get("profile"),
        "isolated_root": str(ctx.isolated_root),
        "bridge_rel": ctx.bridge_rel,
        "settings_rel": ctx.settings_rel,
        # Recorded in BOTH forms (R1). Resolving only at uninstall time is unsound.
        "config_home": str(ctx.config_home),
        "config_home_lexical": str(ctx.config_home),
        "config_home_resolved": os.path.realpath(ctx.config_home),
        # An install performed on a host that could not prove its hooks are
        # enforced stays auditable here after the terminal output has scrolled.
        "host_handshake": os.environ.get("HARNESS_INSTALL_HANDSHAKE", "unknown"),
        "self_management": bundle_record,
        "contributions": list(settings_plan.get("contributions") or []),
        "observations": list(settings_plan.get("observations") or []),
        "container_created": bool(settings_plan.get("container_created")),
        "settings_disposition": settings_plan.get("disposition", "refused"),
        "settings_pre_image_sha256": settings_plan.get("pre_image_sha256"),
        "settings_sha256_as_installed": settings_plan.get("as_installed_sha256"),
        "skipped_mandatory": list(plan.get("skipped_mandatory") or []),
        "created": [],
        "modified": [],
        "conflicts": plan["conflicts"],
    }
    state.setdefault("generations", []).append(record)
    state["schema"] = STATE_SCHEMA
    ctx.write_state(state)

    # ---- phase 3: config home, atomic per file, rollback on any failure ------
    try:
        for c in plan["changes"]:
            if c["tree"] != "config_home":
                continue
            rel, kind = c["path"], c["kind"]
            target = ctx.config_home if rel == "." else ctx.config_home / rel
            if kind == "dir":
                target.mkdir(parents=True, exist_ok=False)
                journal.append(("mkdir", target, None))
                created.append({"path": rel, "kind": "dir"})
            elif kind == "link":
                os.symlink(str(ctx.isolated_root), target)
                journal.append(("symlink", target, None))
                created.append({"path": rel, "kind": "link",
                                "target": str(ctx.isolated_root)})
                created[-1]["sha256"] = None
            elif kind == "file":
                if rel == ctx.settings_rel:
                    content = plan["settings_plan"]["content"]
                else:
                    content = command_doc_bytes(ctx)
                if c["change_kind"] == "modify":
                    journal.append(("restore", target, target.read_bytes()))
                    atomic_write(target, content)
                    modified.append({"path": rel, "kind": "file",
                                     "backup": backups.get(rel)})
                else:
                    atomic_write(target, content)
                    journal.append(("unlink", target, None))
                    # The as-installed digest is what makes uninstall safe: a file
                    # the user later rewrote is no longer the file we created, and
                    # deleting it would destroy their work.
                    created.append({"path": rel, "kind": "file",
                                    "sha256": hashlib.sha256(content).hexdigest()})
    except Exception:
        for action, path, payload in reversed(journal):
            try:
                if action == "restore" and payload is not None:
                    atomic_write(path, payload)
                elif action == "unlink":
                    path.unlink()
                elif action == "symlink":
                    os.unlink(path)
                elif action == "mkdir":
                    path.rmdir()
            except OSError:
                pass
        # The config home is back where it started, so the prepared intent
        # describes a mutation that no longer exists. Retract it rather than
        # leaving a record uninstall would try to invert.
        try:
            rolled_back = ctx.load_state()
            gens = rolled_back.get("generations") or []
            if gens and gens[-1].get("generation") == gen and \
                    gens[-1].get("record_status") == "prepared":
                gens.pop()
                ctx.write_state(rolled_back)
        except (OSError, ValueError):
            pass
        raise

    # ---- phase 4: PROMOTE the prepared record to committed -------------------
    record["created"] = created
    record["modified"] = [
        {**m, "pre_install_sha256": sha256_file(Path(m["backup"]))} for m in modified
    ]
    live_settings = ctx.settings_target
    if live_settings.is_file() and not live_settings.is_symlink():
        # Measured from the bytes actually on disk, not from what was intended.
        record["settings_sha256_as_installed"] = sha256_file(live_settings)
    record["record_status"] = "committed"
    state = ctx.load_state()
    gens = state.setdefault("generations", [])
    for index, existing in enumerate(gens):
        if existing.get("generation") == gen and existing.get("record_status") == "prepared":
            gens[index] = record
            break
    else:
        gens.append(record)
    state["schema"] = STATE_SCHEMA
    ctx.write_state(state)
    return record


# --------------------------------------------------------------------------- #
# Uninstall
# --------------------------------------------------------------------------- #
def uninstall(ctx: Ctx, keep_payload: bool = False) -> dict:
    state = ctx.load_state()
    gens = state.get("generations", [])
    if not gens:
        return {"status": "nothing-to-do", "items": []}

    items: list[dict] = []

    # Restore from the EARLIEST backup recorded for each path: a repeat install
    # must not make the user's true original unrecoverable.
    original: dict[str, dict] = {}
    for g in gens:
        for m in g.get("modified", []):
            original.setdefault(m["path"], m)
    for rel, m in original.items():
        target = ctx.config_home / rel
        backup = Path(m["backup"])
        result = "missing-backup"
        if backup.is_file():
            atomic_write(target, backup.read_bytes())
            result = "restored"
        items.append({"action": "restore", "path": str(target), "result": result,
                      "expected_sha256": m.get("pre_install_sha256"),
                      "measured_sha256": sha256_file(target) if target.is_file() else None})

    # Remove created entries newest-first: files and links by exact path (never
    # followed), directories only when they are then EMPTY.
    seen: set[str] = set()
    for g in reversed(gens):
        for c in g.get("created", []):
            key = f"{c['kind']}:{c['path']}"
            if key in seen:
                continue
            seen.add(key)
            target = ctx.config_home / c["path"]
            if c["kind"] == "link":
                if not target.is_symlink():
                    result = "skipped-not-a-link"
                elif c.get("target") and os.readlink(target) != c["target"]:
                    # Someone repointed the bridge after we created it. It is no
                    # longer ours to remove.
                    result = "kept-user-modified"
                else:
                    os.unlink(target)          # never follows the link
                    result = "removed"
            elif c["kind"] == "file":
                if not target.is_file() or target.is_symlink():
                    result = "skipped-changed-type" if (target.exists() or
                                                        target.is_symlink()) else "absent"
                elif c.get("sha256") and sha256_file(target) != c["sha256"]:
                    # The user rewrote the file we installed. Removing it now would
                    # delete their content, so it stays and is reported as kept.
                    result = "kept-user-modified"
                else:
                    target.unlink()
                    result = "removed"
            else:  # dir -- ONLY if empty; never recursive
                if target.is_dir() and not target.is_symlink():
                    if any(target.iterdir()):
                        result = "kept-not-empty"
                    else:
                        target.rmdir()
                        result = "removed"
                else:
                    result = "absent"
            items.append({"action": "remove", "path": str(target), "kind": c["kind"],
                          "result": result,
                          "measured_present": target.exists() or target.is_symlink()})

    # The installer-owned tree goes last, and only when it carries our state file.
    # It is removed by its OWN path -- never through the bridge link, which was
    # already unlinked above without being followed.
    removed_root = False
    if not keep_payload and ctx.state_path.is_file() and ctx.prefix.is_dir():
        shutil.rmtree(ctx.prefix)
        removed_root = True
    items.append({"action": "remove", "path": str(ctx.prefix), "kind": "dir",
                  "result": "removed" if removed_root else "skipped",
                  "measured_present": ctx.prefix.exists()})
    return {"status": "ok", "items": items}


# --------------------------------------------------------------------------- #
# Reporting
# --------------------------------------------------------------------------- #
def print_plan(ctx: Ctx, plan: dict, dry_run: bool) -> None:
    head = "PLAN (--dry-run: nothing is written)" if dry_run else "PLAN"
    print(f"{head}")
    print(f"  isolated root : {ctx.isolated_root}")
    print(f"  config home   : {ctx.config_home}")
    print(f"  profile       : {ctx.profile_path}")
    print()
    print(f"Intended changes ({len(plan['changes'])}):")
    for c in plan["changes"]:
        root = ctx.prefix if c["tree"] == "prefix" else ctx.config_home
        shown = str(root) if c["path"] == "." else str(root / c["path"])
        print(f"  [{c['change_kind']:6}] {c['kind']:4} {shown}   -- {c['detail']}")
    if plan["conflicts"]:
        print()
        print(f"Conflicts ({len(plan['conflicts'])}) -- the USER's version is retained:")
        for c in plan["conflicts"]:
            print(f"  [conflict] {ctx.config_home / c['path']}   -- {c['detail']}")
    else:
        print("\nConflicts (0)")
    excluded = ctx.profile.get("excluded", [])
    print()
    print(f"Profile '{ctx.profile.get('profile')}' INCLUDES "
          f"({len(ctx.profile['payload']['copied']) + len(ctx.profile['payload']['generated'])}):")
    for item in ctx.profile["payload"]["copied"]:
        print(f"  + {item['dest']}")
    for gen in ctx.profile["payload"]["generated"]:
        print(f"  + {gen}  (generated)")
    print(f"Profile '{ctx.profile.get('profile')}' EXCLUDES ({len(excluded)}):")
    for item in excluded:
        print(f"  - {item}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="installer.py", add_help=True)
    ap.add_argument("command", choices=["plan", "apply", "uninstall", "snapshot"])
    ap.add_argument("--profile", default="core")
    ap.add_argument("--profile-file", dest="profile_file", default=None)
    ap.add_argument("--config-dir", dest="config_dir", default=None)
    ap.add_argument("--prefix", default=None)
    ap.add_argument("--source", default=str(Path(__file__).resolve().parents[2]))
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--root", default=None, help="snapshot: directory to walk")
    ap.add_argument("--keep-payload", dest="keep_payload", action="store_true",
                    help="uninstall: remove the config-home footprint but keep the "
                         "isolated payload directory on disk")
    args = ap.parse_args(argv)

    if args.command == "snapshot":
        root = args.root or args.config_dir
        if not root:
            print("snapshot: --root is required", file=sys.stderr)
            return 1
        print(json.dumps(node_snapshot(Path(root)), indent=2, sort_keys=True))
        return 0

    ctx = Ctx(args)

    if args.command == "uninstall":
        report = uninstall(ctx, keep_payload=args.keep_payload)
        if args.json:
            print(json.dumps(report, indent=2))
        else:
            print(f"UNINSTALL ({report['status']})")
            print(f"  config home : {ctx.config_home}")
            for it in report["items"]:
                extra = ""
                if it["action"] == "restore":
                    ok = it["measured_sha256"] == it["expected_sha256"]
                    extra = f"  [verified: {'yes' if ok else 'NO'}]"
                else:
                    extra = f"  [present after: {it['measured_present']}]"
                print(f"  {it['action']:7} {it['result']:14} {it['path']}{extra}")
        return 0

    plan = build_plan(ctx)
    if args.command == "plan":
        if args.json:
            print(json.dumps({"isolated_root": str(ctx.isolated_root),
                              "config_home": str(ctx.config_home), **plan}, indent=2,
                             default=str))
        else:
            print_plan(ctx, plan, dry_run=True)
        return 0

    record = apply_plan(ctx, plan)
    if args.json:
        print(json.dumps({"isolated_root": str(ctx.isolated_root),
                          "config_home": str(ctx.config_home), **record}, indent=2))
    else:
        print_plan(ctx, plan, dry_run=False)
        print()
        print("APPLIED")
        print(f"  isolated root : {ctx.isolated_root}")
        print(f"  config home   : {ctx.config_home}")
        print(f"  created       : {len(record['created'])} path(s) under the config home")
        print(f"  modified      : {len(record['modified'])} path(s) (pre-touch backup taken)")
        print(f"  inventory     : {ctx.state_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
