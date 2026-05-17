# Packaging gdrive-mgr

Three realistic distribution channels, in order of how quickly users can install:

1. **[COPR](#1-copr-fast-path)** — same-day; users opt in via one `dnf copr enable` command.
2. **[Official Fedora repos](#2-official-fedora-repos)** — 1-3 months process; lands in default `dnf` for every Fedora user.
3. **[Flathub](#3-flathub-probably-not-viable)** — cross-distro but our app fights the sandbox.

The RPM SPEC at [`packaging/gdrive-mgr.spec`](../packaging/gdrive-mgr.spec) is the shared input for paths 1 and 2.

---

## 1. COPR (fast path)

[COPR](https://copr.fedorainfracloud.org/) is Fedora's "personal package repository" service. You upload a SPEC file; COPR builds RPMs for every supported Fedora release; users opt in with `dnf copr enable`.

### One-time setup

1. Sign in to <https://accounts.fedoraproject.org/> and create a Fedora Account System (FAS) account.
2. Sign in to <https://copr.fedorainfracloud.org/> with that account.
3. **New Project** → fill in:
   - **Name:** `gdrive-mgr`
   - **Description:** "KDE-native Google Drive manager with on-demand mount and offline pinning. Built on rclone."
   - **Chroots:** check at least `fedora-43-x86_64`, `fedora-44-x86_64`, `fedora-rawhide-x86_64`. Add `aarch64` variants if you want ARM users covered.
   - **External Repositories:** leave blank.
   - **Build options:** leave defaults.

### Per-release build

Two ways to build:

**A. Direct `.spec` upload (simplest)**

In the COPR project page → **Builds** → **New Build** → **SCM** tab:

| Field | Value |
|---|---|
| SCM type | Git |
| Clone url | `https://github.com/KSM899/gdrive-mgr` |
| Committish | `v0.1.0` (or `main` for latest) |
| Subdirectory | `packaging` |
| Spec file | `gdrive-mgr.spec` |
| SCM type | `git` |
| Build method | `make_srpm` (default) |

Click **Build**. COPR clones the repo, builds the SRPM, then RPMs for every selected chroot. Takes ~5 minutes for the Python package, ~10 minutes if the overlay subpackage is built too.

**B. Automated webhook (recommended once stable)**

In the COPR project → **Integrations** → **GitHub** → enter `KSM899/gdrive-mgr`. Push a tag → COPR builds automatically.

### User install

Once the first build succeeds:

```bash
sudo dnf copr enable ksm899/gdrive-mgr
sudo dnf install gdrive-mgr           # the Python app + CLI + desktop integration
sudo dnf install gdrive-mgr-overlay   # optional: Dolphin per-file badges
```

You can then list the COPR project URL in the main README under "Install".

### Testing your SPEC locally before pushing to COPR

```bash
sudo dnf install rpm-build fedpkg copr-cli
cd ~/projects/gdrive-mgr
rpmbuild -bs --define "_sourcedir $PWD" --define "_srcrpmdir /tmp" \
    packaging/gdrive-mgr.spec
# → /tmp/gdrive-mgr-0.1.0-1.fcXX.src.rpm
copr-cli build ksm899/gdrive-mgr /tmp/gdrive-mgr-0.1.0-1.fcXX.src.rpm
```

---

## 2. Official Fedora repos

Process and timeline:

| Phase | Time | What you do |
|---|---|---|
| **FAS account** | 1 day | Create account; finish CLA/FPCA agreement. |
| **Sponsorship** | days–weeks | Join `#fedora-devel` on Matrix or `devel@lists.fedoraproject.org`. Introduce yourself and your package. A sponsor (an experienced packager) volunteers to review your first submission. |
| **Package review** | 1–4 weeks | File a [package review bug](https://bugzilla.redhat.com/enter_bug.cgi?product=Fedora&component=Package%20Review). Attach your SRPM and a link to the SPEC. Address reviewer comments. |
| **Approval + import** | days | Once approved, request a Pagure repo via `fedpkg request-repo`. Push your SPEC to `src.fedoraproject.org/rpms/gdrive-mgr`. |
| **First build** | hours | `fedpkg build` to push to Koji (Fedora's build system) for rawhide. |
| **Bodhi update** | days | Submit an update to Bodhi to push the build into a stable Fedora release. |

### Concrete first commands

```bash
# After FAS account + CLA:
sudo dnf install fedpkg

# Generate SRPM from your SPEC (same one used in COPR).
rpmbuild -bs --define "_sourcedir $PWD" --define "_srcrpmdir /tmp" \
    packaging/gdrive-mgr.spec

# Validate against Fedora packaging guidelines before submission.
sudo dnf install rpmlint
rpmlint packaging/gdrive-mgr.spec /tmp/gdrive-mgr-0.1.0-1.fcXX.src.rpm
```

Then file the review bug at <https://bugzilla.redhat.com/enter_bug.cgi?product=Fedora&component=Package%20Review> with:

- **Spec URL:** `https://raw.githubusercontent.com/KSM899/gdrive-mgr/main/packaging/gdrive-mgr.spec`
- **SRPM URL:** upload your `.src.rpm` somewhere reachable (a GitHub release asset works)
- **Description:** copy from `Summary:` in the SPEC
- **rpmlint output:** paste the output of the rpmlint command above

### Resources

- Fedora Packaging Guidelines: <https://docs.fedoraproject.org/en-US/packaging-guidelines/>
- Python packaging guidelines: <https://docs.fedoraproject.org/en-US/packaging-guidelines/Python/>
- New maintainer process: <https://docs.fedoraproject.org/en-US/package-maintainers/Joining_the_Package_Maintainers/>
- Bodhi guide: <https://docs.fedoraproject.org/en-US/package-maintainers/Package_Update_Guide/>

---

## 3. Flathub (probably not viable)

Flatpak's sandbox prevents:

- writing systemd user units to `~/.config/systemd/user/`
- installing the C++ overlay plugin to `/usr/lib64/qt6/plugins/`
- launching `fusermount3` to mount Drive on the host filesystem
- the inotify watcher seeing changes made by host processes

Some of these can be worked around with `--filesystem=host` and the `--talk-name=org.freedesktop.systemd1.Manager` permissions, but you sacrifice the sandbox benefits Flatpak exists to provide.

**Recommendation:** skip Flathub for now. Revisit if/when a future version of Flatpak/Portals offers a way to install user systemd units. The COPR path serves the Fedora user base and tags from there can target Arch (AUR) and openSUSE (OBS) using the same SPEC as a starting point.

---

## Other distros (out of scope, but doable)

| Distro | Equivalent of COPR |
|---|---|
| Arch | [AUR](https://aur.archlinux.org/) — write a `PKGBUILD` adapted from the SPEC's logic |
| openSUSE | [OBS](https://build.opensuse.org/) — supports building RPMs from the same `.spec` directly |
| Ubuntu / Debian | PPA via Launchpad — needs a separate `debian/` packaging directory |

Contributions for these are welcome — see [CONTRIBUTING.md](../CONTRIBUTING.md).
