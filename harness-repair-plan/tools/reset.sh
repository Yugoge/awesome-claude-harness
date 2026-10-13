#!/bin/bash
# runs INSIDE the namespace: restore pristine sandbox state
set -u
cd /root/toyproj
INIT=$(git rev-parse sb-init^{commit})
git config --unset core.hooksPath 2>/dev/null
rm -rf .git/keystone-hooks
for w in $(git worktree list --porcelain | awk '/^worktree /{print $2}' | tail -n +2); do git worktree remove --force "$w" 2>/dev/null; done
git worktree prune
git checkout -q -f master
git reset -q --hard "$INIT" && git clean -qffdx
for b in $(git for-each-ref --format='%(refname:short)' refs/heads | grep -v '^master$'); do git branch -q -D "$b"; done
for r in $(git for-each-ref --format='%(refname)' refs/checkpoints refs/remotes); do git update-ref -d "$r"; done
git symbolic-ref -d refs/remotes/origin/HEAD 2>/dev/null
git -C /root/toyproj-origin.git for-each-ref --format='%(refname)' | grep -v '^refs/heads/master$' | xargs -r -n1 git -C /root/toyproj-origin.git update-ref -d
git -C /root/toyproj-origin.git update-ref refs/heads/master "$INIT"
git fetch -q origin
cd /root/.claude && git checkout -q -- . && git clean -qffdx -e venv -e /venv
rm -rf /tmp/* /tmp/.[!.]* /var/tmp/* /var/tmp/.[!.]* /dev/shm/* /dev/shm/.[!.]* 2>/dev/null
find /root -mindepth 1 -maxdepth 1 ! -name toyproj ! -name toyproj-origin.git ! -name .claude ! -name .ccr -exec rm -rf {} +
echo "reset done: toy=$(git -C /root/toyproj rev-parse --short HEAD) toy-dirty=$(git -C /root/toyproj status --porcelain | wc -l) worktrees=$(git -C /root/toyproj worktree list | wc -l) hooksPath=$(git -C /root/toyproj config core.hooksPath) harness-dirty=$(git -C /root/.claude status --porcelain | wc -l)"
