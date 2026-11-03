# Firmware playbook: back up, build, install, verify, roll back

This is the procedure for getting firmware onto MR70/MS70 units, and back off them. It covers official NETGEAR images today and this project's custom releases once they exist. Sections marked **TBD (#N)** get filled in by that issue's PR. Until they're done, **don't flash a custom image**.

> **Safety rules**
> - Nothing is flashed without the owner's explicit go-ahead.
> - Custom images go to the **spare MS70 first**, and only after a recovery path is proven on it (#9).
> - Always have a backup (section 1) and the official `.chk` for every model you touch.
> - Never post `.cfg` backups, logs or screenshots with network names, MACs, serials or addresses (see [SECURITY.md](../SECURITY.md)).

## 0. Know what you have (2 min, read-only)
On every unit, open `http://<unit-ip>/currentsetting.htm` (no login) and note the `Firmware` and `Model` values. This is the same check as Step 0 of the [troubleshooting playbook](troubleshooting-playbook.md). The router can show a blank satellite version in its own UI, so check each unit directly.

## 1. Backup
**Now (stock):**
1. Router: ADVANCED → Administration → **Backup Settings** → *Back Up*. Store the `.cfg` file **outside the repo**. It contains credentials.
2. Record each unit's firmware/model from section 0.
3. Keep the official `.chk` for each model and version you run, with its SHA-256. `tools/fetch-and-extract.sh` downloads and verifies the current ones.

**TBD (#15):**
- what the `.cfg` does and doesn't cover (satellite/mesh state, VPN certificates)
- a `tools/netgear_router.py backup` subcommand
- a tested restore procedure

## 2. Build
**TBD (#17):** the reproducible Docker build of MR70/MS70 `.chk` images from NETGEAR's GPL source. This is blocked until the source is available (#8).

**TBD (#18, #19):** how CI builds on every PR, and how a `vX.Y.Z` tag publishes a GitHub Release. The release carries:
- `MR70-<ver>.chk` and `MS70-<ver>.chk`
- `SHA256SUMS`
- an SBOM
- a build-provenance attestation
- a NOTICE and the matching GPL source

Also from #18: how the semver maps to the version string inside the image.

## 3. Verify the download
```bash
sha256sum -c SHA256SUMS                                  # macOS: shasum -a 256 -c SHA256SUMS
gh attestation verify MS70-<ver>.chk -R llevintza/netgear-ax3000-mesh-router   # once #19 publishes attestations
```
Don't install an image that fails either check.

## 4. Install
**Official NETGEAR images (works today):**
1. On the **router**: ADVANCED → Administration → **Router Update**. Use **Check** or **Manual Update**, and pick the satellite from the satellite list.
2. Do the **satellites first, then the router** (NETGEAR's release notes).
3. Don't unplug anything. Wait until all LEDs are steady; satellites drop in and out while they reboot.
4. Re-run section 0 on every unit.

A satellite's own hidden `UPG_upgrade.htm` has rejected a correct image ("This firmware file is incorrect"), so use the router's flow. #12 confirms the exact route.

**Custom images. TBD (#10, #20):**
1. Spare MS70 only, with the recovery path from #9 ready
2. Verify (section 5) for 24 h
3. The remaining satellites one at a time
4. The router last

Production units only with the owner's sign-off recorded in the issue.

## 5. Verify after install
- Section 0 shows the expected version on every unit.
- Satellites rejoin; LEDs are steady white; clients connect on both bands.
- `python3 -I tools/netgear_router.py status` works on the router and each satellite (login and auth unchanged).
- Optional: capture logs for an hour and run `tools/analyze_logs.py` (no `blocking backhaul BSS` or new DFS events).
- **TBD (#16):** the feature-parity smoke tests.

## 6. Roll back
- **Settings:** ADVANCED → Administration → Backup Settings → *Restore* with the `.cfg` from section 1 (procedure verified in #15).
- **Firmware:** flash the official `.chk` through the router's Router Update flow (section 4), satellites first.
- **Unit doesn't boot. TBD (#9):** nmrpflash/TFTP or a serial console. There's no proven path yet, which is why custom images go to the spare first.
