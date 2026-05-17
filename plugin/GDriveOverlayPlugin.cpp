// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 Khalid Said
// gdrive-mgr Dolphin overlay icon plugin.
//
// Reads ~/.cache/gdrive-mgr/status.json (owned by the Python daemon) and
// returns a small icon name per URL so Dolphin paints a badge:
//   synced/online_only/error/pending/syncing → distinct emblem
//
// Matching: a queried path inherits status from its nearest registered
// ancestor — so a file under a pinned folder shows the folder's state.

#include <KOverlayIconPlugin>

#include <QDebug>
#include <QDir>
#include <QFile>
#include <QFileSystemWatcher>
#include <QIcon>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QStandardPaths>
#include <QStringList>
#include <QTimer>
#include <QUrl>

// Always-on logging (visible in `journalctl --user`, or in a terminal when
// you launch Dolphin from one). Cheap; helps diagnose icon-name mismatches.
#define GDRIVE_LOG(...) qInfo("[gdrive-overlay] " __VA_ARGS__)

namespace
{
QString statusFilePath()
{
    const QString cacheRoot = QStandardPaths::writableLocation(QStandardPaths::GenericCacheLocation);
    return cacheRoot + QStringLiteral("/gdrive-mgr/status.json");
}

QString statusFileDir()
{
    const QString cacheRoot = QStandardPaths::writableLocation(QStandardPaths::GenericCacheLocation);
    return cacheRoot + QStringLiteral("/gdrive-mgr");
}
}

class GDriveOverlayPlugin : public KOverlayIconPlugin
{
    Q_OBJECT
    Q_PLUGIN_METADATA(IID "org.kde.overlayicon.gdrivemgr")

public:
    GDriveOverlayPlugin();

    QStringList getOverlays(const QUrl &url) override;

private Q_SLOTS:
    void onStatusFileChanged();

private:
    QStringList overlaysForState(const QString &state) const;
    QJsonArray loadEntries() const;

    QFileSystemWatcher m_watcher;
    // Tracks the last-known set of registered paths so we can emit
    // overlaysChanged for each one when the status file updates.
    QStringList m_knownPaths;
    // Plasma 6's Dolphin sometimes paints the directory view before our
    // plugin emits overlaysChanged, missing the initial signal. A periodic
    // re-emit ensures the model picks up the overlays eventually.
    QTimer m_repeatTimer;
};

GDriveOverlayPlugin::GDriveOverlayPlugin()
{
    const QString file = statusFilePath();
    const QString dir = statusFileDir();
    GDRIVE_LOG("plugin loaded; watching %s", qUtf8Printable(file));

    QDir().mkpath(dir);
    m_watcher.addPath(dir);
    if (QFile::exists(file)) {
        m_watcher.addPath(file);
    }

    connect(&m_watcher, &QFileSystemWatcher::fileChanged, this, &GDriveOverlayPlugin::onStatusFileChanged);
    connect(&m_watcher, &QFileSystemWatcher::directoryChanged, this, &GDriveOverlayPlugin::onStatusFileChanged);

    // Re-emit overlaysChanged for every known path every few seconds. This
    // works around a Plasma 6 quirk where Dolphin sometimes misses the
    // initial signal (model isn't connected yet at plugin construction).
    m_repeatTimer.setInterval(5000);
    connect(&m_repeatTimer, &QTimer::timeout, this, &GDriveOverlayPlugin::onStatusFileChanged);
    m_repeatTimer.start();

    onStatusFileChanged();
}

void GDriveOverlayPlugin::onStatusFileChanged()
{
    const QString file = statusFilePath();
    // Atomic rewrites replace the inode — re-add to the watcher each time.
    if (QFile::exists(file) && !m_watcher.files().contains(file)) {
        m_watcher.addPath(file);
    }

    const QJsonArray entries = loadEntries();
    QStringList currentPaths;
    currentPaths.reserve(entries.size());
    for (const QJsonValue &v : entries) {
        currentPaths << v.toObject().value(QStringLiteral("path")).toString();
    }

    // Emit overlaysChanged for paths now present and for paths that just left.
    const QStringList changed = currentPaths + m_knownPaths;
    for (const QString &p : changed) {
        if (p.isEmpty()) continue;
        const QUrl u = QUrl::fromLocalFile(p);
        Q_EMIT overlaysChanged(u, getOverlays(u));
    }
    m_knownPaths = currentPaths;
}

QJsonArray GDriveOverlayPlugin::loadEntries() const
{
    QFile f(statusFilePath());
    if (!f.open(QIODevice::ReadOnly)) {
        return {};
    }
    const QByteArray data = f.readAll();
    f.close();
    QJsonParseError err;
    const QJsonDocument doc = QJsonDocument::fromJson(data, &err);
    if (err.error != QJsonParseError::NoError || !doc.isObject()) {
        return {};
    }
    return doc.object().value(QStringLiteral("entries")).toArray();
}

QStringList GDriveOverlayPlugin::overlaysForState(const QString &state) const
{
    // Picked from the subset of Breeze emblems that actually render as
    // overlays (not all do — emblem-success and the *-symbolic variants
    // turn into null icons at overlay sizes on this system).
    if (state == QLatin1String("synced"))
        return {QStringLiteral("emblem-favorite")};        // yellow star
    if (state == QLatin1String("syncing") || state == QLatin1String("pending"))
        return {QStringLiteral("emblem-information")};     // blue 'i' circle
    if (state == QLatin1String("error"))
        return {QStringLiteral("emblem-important")};       // red exclamation
    if (state == QLatin1String("online_only"))
        return {QStringLiteral("emblem-mounted")};         // cloud-ish
    return {};
}

QStringList GDriveOverlayPlugin::getOverlays(const QUrl &url)
{
    if (!url.isLocalFile()) {
        return {};
    }
    const QString queriedPath = url.toLocalFile();
    const QJsonArray entries = loadEntries();

    QString matchedState;
    int bestPrefixLen = -1;

    for (const QJsonValue &v : entries) {
        const QJsonObject obj = v.toObject();
        const QString entryPath = obj.value(QStringLiteral("path")).toString();
        const QString entryState = obj.value(QStringLiteral("state")).toString();
        if (entryPath.isEmpty()) continue;

        const bool exactOrDescendant = (queriedPath == entryPath)
            || queriedPath.startsWith(entryPath + QLatin1Char('/'));
        if (!exactOrDescendant) continue;

        if (entryPath.length() > bestPrefixLen) {
            bestPrefixLen = entryPath.length();
            matchedState = entryState;
        }
    }

    if (matchedState.isEmpty()) {
        return {};
    }
    const QStringList icons = overlaysForState(matchedState);
    GDRIVE_LOG("getOverlays(%s) state=%s → %s",
               qUtf8Printable(queriedPath),
               qUtf8Printable(matchedState),
               qUtf8Printable(icons.join(QLatin1Char(','))));
    GDRIVE_LOG("  current theme: %s", qUtf8Printable(QIcon::themeName()));
    for (const QString &n : icons) {
        QIcon ic = QIcon::fromTheme(n);
        const QList<QSize> sizes = ic.availableSizes();
        QStringList sizeStrs;
        for (const QSize &s : sizes) sizeStrs << QStringLiteral("%1x%2").arg(s.width()).arg(s.height());
        GDRIVE_LOG("    %s → null=%s sizes=[%s]",
                   qUtf8Printable(n),
                   ic.isNull() ? "YES" : "no",
                   qUtf8Printable(sizeStrs.join(QLatin1Char(','))));
    }
    return icons;
}

#include "GDriveOverlayPlugin.moc"
