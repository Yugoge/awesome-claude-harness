#!/usr/bin/env bash
# QA control: ONLY an accepted env-default occurrence — should PASS (not over-eager).
X="${VAR:-happy-daemon}"
echo "$X"
