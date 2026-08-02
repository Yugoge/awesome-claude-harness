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

Exit codes: 0 = success, 1 = failure, 2 = preflight/refusal (caller-supplied).
"""

from __future__ import annotations

import argparse
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
STATE_SCHEMA = "claude-harness/install-state/v1"


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
class Ctx:
    def __init__(self, args):
        self.source = Path(args.source).resolve()
        self.profile_path = Path(args.profile_file) if args.profile_file else (
            self.source / "scripts" / "install" / "profiles" / f"{args.profile}.json"
        )
        with open(self.profile_path, encoding="utf-8") as fh:
            self.profile = json.load(fh)
        self.prefix = resolve_prefix(args.prefix)
        self.isolated_root = self.prefix / self.profile.get("isolated_root_subdir", "harness")
        self.config_home = resolve_config_home(args.config_dir)
        self.bridge_rel = next(
            e["path"] for e in self.profile["live_footprint"] if e["kind"] == "link"
        )
        self.bridge = self.config_home / self.bridge_rel
        self.state_path = self.prefix / STATE_REL

    def load_state(self) -> dict:
        if self.state_path.is_file():
            with open(self.state_path, encoding="utf-8") as fh:
                return json.load(fh)
        return {"schema": STATE_SCHEMA, "generations": []}


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


def merge_settings(existing: dict, groups: list[tuple[str, dict]]) -> tuple[dict, list[str]]:
    """ADDITIVE-ONLY merge. Returns (merged, added_command_list).

    Nothing is ever removed, reordered, replaced or broadened. Registration groups
    are APPENDED to the end of their event list, so every pre-existing group keeps
    its position and its internal hook order. A command already registered
    anywhere in that event is not added again (idempotent re-install).
    """
    merged = copy.deepcopy(existing)
    hooks = merged.get("hooks")
    if hooks is None:
        hooks = {}
        merged["hooks"] = hooks
    if not isinstance(hooks, dict):
        raise ValueError("settings.json 'hooks' is not an object; refusing to merge")

    added: list[str] = []
    for event, group in groups:
        bucket = hooks.get(event)
        if bucket is None:
            bucket = []
            hooks[event] = bucket
        if not isinstance(bucket, list):
            raise ValueError(f"settings.json hooks.{event} is not a list; refusing to merge")
        command = group["hooks"][0]["command"]
        present = any(
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
        bucket.append(copy.deepcopy(group))
        added.append(f"{event}:{command}")
    return merged, added


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
                                  "detail": f"existing symlink -> {os.readlink(target)}; "
                                            "user's version retained"})
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
        elif kind == "file" and rel == "settings.json":
            settings_plan = plan_settings(ctx, target, conflicts)
            if settings_plan and settings_plan["change_kind"]:
                add("config_home", rel, "file", settings_plan["change_kind"],
                    settings_plan["detail"])
        elif kind == "file":
            content = command_doc_bytes(ctx)
            if target.exists() or target.is_symlink():
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

    return {"generation": gen, "changes": changes, "conflicts": conflicts,
            "settings_plan": settings_plan}


def plan_settings(ctx: Ctx, target: Path, conflicts: list) -> dict | None:
    groups = hook_groups(ctx.profile, ctx.bridge)
    if target.is_symlink():
        conflicts.append({"tree": "config_home", "path": "settings.json",
                          "change_kind": "conflict",
                          "detail": "settings.json is a symlink; writing through it would "
                                    "modify a file outside the declared footprint. The "
                                    "user's version is retained and left untouched."})
        return None
    if not target.exists():
        doc, added = merge_settings({}, groups)
        return {"change_kind": "create", "content": settings_bytes(doc),
                "added": added, "detail": f"create with {len(added)} hook registration(s)"}
    try:
        existing = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        conflicts.append({"tree": "config_home", "path": "settings.json",
                          "change_kind": "conflict",
                          "detail": f"unreadable/unparseable ({exc}); left untouched"})
        return None
    if not isinstance(existing, dict):
        conflicts.append({"tree": "config_home", "path": "settings.json",
                          "change_kind": "conflict",
                          "detail": "top level is not an object; left untouched"})
        return None
    try:
        merged, added = merge_settings(existing, groups)
    except ValueError as exc:
        conflicts.append({"tree": "config_home", "path": "settings.json",
                          "change_kind": "conflict", "detail": f"{exc}; left untouched"})
        return None
    if not added:
        return {"change_kind": None, "content": None, "added": [],
                "detail": "already registered; no change"}
    return {"change_kind": "modify", "content": settings_bytes(merged), "added": added,
            "detail": f"append {len(added)} hook registration(s); "
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
            elif kind == "file":
                if rel == "settings.json":
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
                    created.append({"path": rel, "kind": "file"})
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
        raise

    # ---- phase 4: record ownership ------------------------------------------
    state = ctx.load_state()
    record = {
        "generation": gen,
        "profile": ctx.profile.get("profile"),
        "isolated_root": str(ctx.isolated_root),
        "config_home": str(ctx.config_home),
        # An install performed on a host that could not prove its hooks are
        # enforced stays auditable here after the terminal output has scrolled.
        "host_handshake": os.environ.get("HARNESS_INSTALL_HANDSHAKE", "unknown"),
        "created": created,
        "modified": [
            {**m, "pre_install_sha256": sha256_file(Path(m["backup"]))} for m in modified
        ],
        "conflicts": plan["conflicts"],
    }
    state["generations"].append(record)
    ctx.state_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(ctx.state_path, (json.dumps(state, indent=2) + "\n").encode("utf-8"))
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
                if target.is_symlink():
                    os.unlink(target)          # never follows the link
                    result = "removed"
                else:
                    result = "absent"
            elif c["kind"] == "file":
                if target.is_file() and not target.is_symlink():
                    target.unlink()
                    result = "removed"
                else:
                    result = "absent"
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
        report = uninstall(ctx)
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
