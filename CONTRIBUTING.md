# Contributing

Bug reports, feature suggestions, and pull requests are all welcome.

## Reporting a bug

Open an issue at <https://github.com/KSM899/gdrive-mgr/issues> with:

- **What you did** (steps to reproduce)
- **What you expected**
- **What happened instead**
- The daemon log: `journalctl --user -u gdrive-mgr-daemon.service -n 100 --no-pager`
- If sync-related: relevant snippets from `~/.config/gdrive-mgr/config.json` and `~/.cache/gdrive-mgr/status.json` (these don't contain secrets — see [SECURITY.md](SECURITY.md))
- Your distro, KDE Plasma version, rclone version

## Security issues

Please **do not** file public issues for unpatched vulnerabilities. Open a
private security advisory on GitHub or contact the maintainer directly.

## Development setup

```bash
git clone https://github.com/KSM899/gdrive-mgr.git
cd gdrive-mgr
./install.sh   # creates .venv, installs deps, sets up everything
```

The launcher script `./bin/gdrive-mgr` runs the venv's Python directly,
so any edits to `gdrive_mgr/` are picked up the next time you run.

For Dolphin overlay-plugin changes:

```bash
cd plugin
cmake --build build       # incremental rebuild
sudo cmake --install build
kquitapp6 dolphin && dolphin &   # restart to load new plugin
```

## Code style

- Python: keep imports sorted, type hints encouraged but not required, no
  unnecessary abstractions.
- Subprocesses: always list-form `argv`, never `shell=True`. See
  [SECURITY.md](SECURITY.md) for the rationale.
- Logging: use `logging.getLogger("gdrive-mgr")` (or a module-scoped child)
  in the daemon. Avoid `print` in long-running code paths.
- New CLI commands: register them in `gdrive_mgr/cli.py`'s `main()`.
- New UI panels: add to `gdrive_mgr/ui/` and wire into `MainWindow._build_body`.

## Testing

There's no automated test suite yet (a real gap). For now, manual smoke
tests are documented in the install README. A `tests/` directory and
a pytest-based suite would be a great first contribution.

## Pull request checklist

- [ ] The change does what its title says — no scope creep
- [ ] No hardcoded paths to `/home/<your-username>/` in committed files
- [ ] If you added a CLI subcommand, document it in the README
- [ ] If you added a new file, add the SPDX header at the top:
      `# SPDX-License-Identifier: GPL-3.0-or-later`
- [ ] If you changed user-visible behavior, add a CHANGELOG entry
- [ ] You agree to license your contribution under GPL-3.0-or-later

## License

All contributions are accepted under the **GNU General Public License
v3.0 or later** (see [LICENSE](LICENSE)).
