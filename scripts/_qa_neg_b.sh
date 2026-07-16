#!/usr/bin/env bash
# QA negative-proof scratch B: occurrence-level — an ACCEPTED :- default followed by a
# BARE second occurrence on the SAME line. Line-level check would pass; occurrence-level FAILs.
X="${VAR:-happy-daemon}"; Y=happy-daemon
echo "$X $Y"
