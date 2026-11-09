<!-- Title: conventional commit, e.g. "fix(tools): stop retrying after 401" -->

Closes #

## What and why


## Type
- [ ] feat · [ ] fix · [ ] docs · [ ] test · [ ] refactor · [ ] build · [ ] ci · [ ] chore · [ ] perf · [ ] revert

## Checklist
- [ ] Branch is `<type>/<issue>-<slug>` from current `main`; this PR covers one issue
- [ ] `tools/check-repo.sh` passes
- [ ] No device identifiers (network names, MACs, serials, LAN addresses, passwords, home paths), no firmware/logs/`.cfg` files
- [ ] Firmware claims cite evidence (path, `FUN_…` address or NVRAM key) in `docs/findings.md`
- [ ] Anything that changes a router setting is dry-run by default and states how to roll back
- [ ] Docs updated (roadmap research log / playbook) if this changes what we know or how to do something
