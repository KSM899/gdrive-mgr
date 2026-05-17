# Screenshots

Shots used in the main project README live here. Suggested set:

| Filename | What to capture |
|---|---|
| `main-window.png` | Main app window, Status tab, with at least one mounted account |
| `browse-pin.png` | Browse & Pin tab with the tree expanded and at least one folder checked |
| `dolphin-menu.png` | Dolphin file view with the right-click context menu open showing the Google Drive submenu |
| `dolphin-badges.png` | Dolphin folder view showing different overlay states (synced ⭐, syncing 🔵, error ❗) side by side |
| `share-dialog.png` | The native Share dialog with at least one person added |
| `disk-usage.png` | Disk Usage tab showing the per-account breakdown |
| `tray.png` | The system tray icon hovered/clicked, showing menu and color badge |

## Capture them

Run the helper script (`docs/capture-screenshots.sh`) and follow its
prompts — it launches the app, waits, and uses **spectacle** to capture
each window in turn. On KDE Plasma you already have spectacle. On other
desktops install it (`sudo dnf install spectacle`) or use any screenshot
tool you prefer.

Save the PNGs in this directory with the filenames above. Once they're
committed, they automatically render in the main README on GitHub.

## Style tips

- 16:9-ish aspect, ~1280×720 to ~1600×900 — keeps them sharp on README
  and not absurdly large in the repo.
- Light theme is the default; dark looks great too if you have it on.
- Crop to just the window, not the whole desktop, except for the
  Dolphin badges shot where surrounding folder context is the point.
- Avoid leaking real filenames or email addresses — use a test folder
  named "Demo" or similar.
