# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Khalid Said

%global pypi_name gdrive-mgr
%global app_id    io.github.gdrive_mgr

Name:           %{pypi_name}
Version:        0.1.0
Release:        1%{?dist}
Summary:        KDE-native Google Drive manager with on-demand mount and offline pinning

License:        GPL-3.0-or-later
URL:            https://github.com/KSM899/gdrive-mgr
Source0:        %{url}/archive/v%{version}/%{name}-%{version}.tar.gz

BuildArch:      noarch

# Python build/runtime
BuildRequires:  python3-devel
BuildRequires:  python3-setuptools
BuildRequires:  pyproject-rpm-macros
BuildRequires:  libappstream-glib

# Hard runtime dependencies
Requires:       python3 >= 3.11
Requires:       python3-pyside6
Requires:       python3-watchdog
Requires:       rclone
Requires:       fuse3
Requires:       systemd

# Soft dependencies — desktop integration. Not hard-required so the package
# also installs cleanly on minimal/headless systems for the CLI side.
Recommends:     plasma-workspace
Recommends:     dolphin
Recommends:     libnotify           # notify-send for share-link toast
Recommends:     wl-clipboard        # wl-copy for the share-link clipboard

# Optional Dolphin overlay-icon plugin lives in its own subpackage so users
# on non-KDE setups don't pull in KF6 KIO.

%description
A KDE Plasma 6 Google Drive client built on rclone. Mounts your Drive
on demand (files download only when opened), with per-folder and
per-file "Keep always on this device" pinning, reactive background sync,
in-app sharing, multiple accounts, and bisync conflict resolution.


%package overlay
Summary:        Dolphin overlay-icon plugin for %{name}
Requires:       %{name} = %{version}-%{release}
Requires:       dolphin
Requires:       kf6-kio
BuildRequires:  gcc-c++
BuildRequires:  cmake
BuildRequires:  extra-cmake-modules
BuildRequires:  qt6-qtbase-devel
BuildRequires:  kf6-kio-devel

%description overlay
Native Dolphin plugin that paints per-file overlay badges (synced,
syncing, error, online-only) on Google Drive items managed by
%{name}. Loaded into Dolphin on startup; reads the daemon's
status file via Qt JSON.


# ---------------------------------------------------------------------- prep
%prep
%autosetup -n %{name}-%{version}


# ---------------------------------------------------------------------- build
%build
# Python package — standard pyproject build.
%pyproject_wheel

# Dolphin overlay plugin — out-of-source CMake build.
mkdir -p plugin/build
cd plugin/build
%cmake -DCMAKE_INSTALL_PREFIX=%{_prefix} ..
%cmake_build


# -------------------------------------------------------------------- install
%install
%pyproject_install
%pyproject_save_files gdrive_mgr

# Install the overlay plugin.
cd plugin/build
%cmake_install
cd ../..

# Substitute @BINDIR@ in the .desktop templates with the real /usr/bin path.
install -d %{buildroot}%{_datadir}/applications
install -d %{buildroot}%{_datadir}/kio/servicemenus
sed "s|@BINDIR@|%{_bindir}|g" resources/io.github.gdrive_mgr.desktop.in \
    > %{buildroot}%{_datadir}/applications/%{app_id}.desktop
sed "s|@BINDIR@|%{_bindir}|g" resources/gdrive-mgr-pin.desktop.in \
    > %{buildroot}%{_datadir}/kio/servicemenus/gdrive-mgr-pin.desktop
chmod +x %{buildroot}%{_datadir}/kio/servicemenus/gdrive-mgr-pin.desktop

# AppStream metainfo for KDE Discover / GNOME Software.
install -D -m 644 data/%{app_id}.metainfo.xml \
    %{buildroot}%{_metainfodir}/%{app_id}.metainfo.xml

# Shared resources (QSS stylesheet)
install -D -m 644 resources/styles/modern.qss \
    %{buildroot}%{_datadir}/%{name}/styles/modern.qss

# Validate metainfo at build time so a broken file fails the build, not the user.
appstream-util validate-relax --nonet \
    %{buildroot}%{_metainfodir}/%{app_id}.metainfo.xml


# ------------------------------------------------------------------- files
%files -f %{pyproject_files}
%license LICENSE
%doc README.md SECURITY.md CHANGELOG.md
%{_bindir}/gdrive-mgr
%{_bindir}/gdrive-mgr-cli
%{_datadir}/applications/%{app_id}.desktop
%{_datadir}/kio/servicemenus/gdrive-mgr-pin.desktop
%{_datadir}/%{name}/
%{_metainfodir}/%{app_id}.metainfo.xml

%files overlay
%{_qt6_plugindir}/kf6/overlayicon/gdrivemgroverlay.so


# ---------------------------------------------------------------- changelog
%changelog
* Sat May 17 2026 Khalid Said <kshukaili89@gmail.com> - 0.1.0-1
- Initial package: v0.1.0 public release.
