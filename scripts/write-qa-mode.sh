#!/usr/bin/env bash
# STUB: P1b E7 replaced the qa_mode switch with the record: each QA dispatch's
# obligation declares the report it owes (ba-qa-report or qa-report), and G2
# (hooks/subagentstop-artifact-contract-enforce.py) and the e2e gate
# (hooks/subagentstop-e2e-enforce.py) read that. Nothing is written and no
# sentinel is created. It stays at its path and mode for sessions that still
# run the earlier command text (D15): every call that text makes
# (--session-id, --mode, --task-id, --init-if-missing) exits 0.
exit 0
