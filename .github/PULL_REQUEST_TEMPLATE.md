# Pull Request

## Summary

<!-- What does this change do, and why? Link any related issue (e.g. Closes #123). -->

## Type of change

- [ ] Bug fix
- [ ] New feature / capability
- [ ] Documentation
- [ ] Hook / script / config change
- [ ] Other (describe):

## Checklist

- [ ] The diff is minimal and focused on one concern.
- [ ] No secrets, credentials, tokens, or private paths are introduced.
- [ ] Shell scripts touched pass `bash -n`.
- [ ] Python touched compiles (`python3 -m py_compile`).
- [ ] `settings.json` still parses (`python3 -m json.tool settings.json`) if changed.
- [ ] No existing safety check / hook was weakened or bypassed.
- [ ] Docs/INDEX updated if structural files changed.

## Notes for reviewers

<!-- Anything reviewers should pay special attention to. -->
