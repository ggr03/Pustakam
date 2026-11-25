# Changelog: Pustakam (पुस्तकम्)

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added
- **Find & replace in the editor** (`Ctrl+F` / `Ctrl+H`): live highlighting of every match, a *2 of 5* counter,
  next/previous (`Enter`, `Shift+Enter`, `F3`), match case, whole word and regular expressions (with `$1` groups),
  replace one or all. *Replace all* is a single undo step.
- **Modern editor toolbar**: icon buttons in groups with tooltips that show shortcuts, undo/redo, a text-style menu
  (Paragraph, H1–H4), strikethrough, numbered list, quote, image, divider, and a Markdown & shortcuts cheat sheet (`?`).
  Bold, italic, code and lists toggle on and off; lists apply to every selected line.
- **Keyboard shortcuts**: `Ctrl+B/I/K/M`, `Ctrl+Shift+X`, `` Ctrl+` ``, `Ctrl+Shift+7/8/9/.` (⌘ on Mac).
- **Smart editing**: Enter continues bulleted, numbered and task lists (an empty item ends the list);
  Tab / Shift+Tab indent and outdent selected lines.
- Live **Ln/Col, selection and word count** in the toolbar.

### Changed
- Toolbar edits use the browser's native undo stack, so `Ctrl+Z` undoes formatting too.
- CSS/JS cache-busting now uses a fingerprint of the static files, so browsers always load the current scripts.
- Phones: text autosizing is disabled so the editor and its highlights always line up.

## [1.0] - 2026-11-24

First public release. Pustakam is the successor of *NoteVault*: renamed, rebuilt and made cross-platform.

### Added
- **New name and identity.** *Pustakam (पुस्तकम्)*, Sanskrit for a book, manuscript or collection of notes; new logo
  and title bar. Every file carries the Pustakam name.
- **Reading view first.** Notes open read-only; **✏️ Edit** (or `E`) switches to a **split editor with live preview**,
  with matching scroll and a formatting toolbar.
- **Math and chemistry.** KaTeX math (`$…$`, `$$…$$`, `\(…\)`, `\[…\]`) and mhchem chemical formulae (`$\ce{H2SO4}$`, or a
  bare `\ce{…}`), plus `\pu{…}` units.
- **Two-way OneDrive sync** via rclone. Sign in with an outlook.com / hotmail.com / msn.com (or work/school) account, with
  no app registration needed. Each notebook is a folder and each note a `.md` file. Edits, renames, moves and deletes sync
  both ways, with conflict copies, the OneDrive recycle bin for deletes, a safety stop against mass deletion, and
  self-healing links.
- **Connection test** after sign-in: account, folder, and a write/read/delete test file.
- **Local backups.** Daily at 21:00 to any folder you choose, a configurable number kept (default 5), plus **Back up now**
  and a backup list in Settings.
- **Logs folder** (`~/.pustakam/Logs`): `connection.log`, `sync.log`, `notes.log` (titles only), `backup.log`; rotated, and
  viewable in **Settings → 📜 Logs**.
- **Default notebook.** Set one from the notebook menu (★); it opens first and new notes go there.
- **Unique notebook icons**, derived from each name: a keyword glyph or initials on a colour and pattern unique to the name.
- **Collapsible notebooks pane** (‹ / ›, remembered between visits).
- **Mobile-friendly layout** for Android, iPhone/iPad and other browsers: slide-in drawers for notebooks and notes,
  swipe gestures, safe-area and dynamic-viewport support, touch-sized controls.
- **Status bar**: note search, weather for saved cities (°C/°F, description, and details with feels-like, humidity, wind,
  AQI and UV from Open-Meteo), ISO date, an **account menu** (signed-in ID, sync status, Sync now, Settings, Logout),
  and the version.
- **OS sign-in.** Linux via PAM, Windows via LogonUser (incl. `MicrosoftAccount\…`); only the account running Pustakam
  may sign in by default. Inactivity logout.
- **LAN access.** Listens on all interfaces; Settings shows the LAN address. Cloud sign-in started from another device
  can be finished by pasting the redirect address.
- **Installers** for Debian/Ubuntu/MX/siduction, Fedora/RHEL/Rocky/Alma, openSUSE (systemd user service, or cron) and
  Windows 10/11 (Task Scheduler), with uninstallers, NoteVault data migration, optional firewall rules and a checksum-
  verified rclone download.
- README with screenshots, status-bar and search guides, and Linux and Windows file locations; MIT License.

### Changed
- **Requires Python 3.11 or newer.** Installers find or install it, and the app checks at start-up.
- Served by **waitress** instead of the Flask development server.
- Full-text search quotes each word safely and matches word prefixes; tag filtering has its own route.
- Renaming a note no longer leaves its old Markdown copy behind.
- Data folder `~/.pustakam` (was `~/.notevault`); log folder `Logs` (an old `logs` folder is migrated automatically).

### Removed
- WebDAV server and WebDAV client.
- Google Drive sync (OneDrive is the supported cloud; local backups cover offline copies).

### Fixed
- OneDrive sync created duplicate notebooks and left the cloud folder without files, because folder IDs were read in two
  different formats. Items are now always identified from folder listings, and existing links are repaired by name.
- First-time sync now matches titles containing characters OneDrive does not allow (e.g. `:` stored as `-`).
- Popups (weather, account menu) no longer close when a phone's address bar hides.

### Security
- Scanned with **Snyk Code**, **Snyk Open Source**, **Bandit** and **pip-audit**; see [SECURITY.md](SECURITY.md).
  Snyk Code went from 19 issues (2 high, 6 medium) to 14 (0 high, 3 medium); the remaining 14 are owner-controlled
  settings that the web interface cannot reach. No vulnerable dependencies.
- **XSS:** all rendered Markdown, *including math*, goes through DOMPurify in a final pass. KaTeX runs with `trust:false`,
  and error messages are built with DOM APIs.
- **Content-Security-Policy** and related headers (`X-Frame-Options: DENY`, `nosniff`, `Referrer-Policy`, `Permissions-Policy`,
  `no-store` on API responses).
- **Subresource Integrity** hashes on all CDN scripts and stylesheets.
- **CSRF protection:** cross-site `Origin` is refused, and API calls require the `X-Pustakam` header.
- **Server-side inactivity logout** on every request, not only in the browser.
- Log viewer only opens files that exist in the Logs folder (no path traversal); log lines cannot be forged with newlines.
- Error responses no longer include exception details (they go to the logs instead).
- The sign-in page no longer shows the OS username to other devices on the network.
- Tokens, config, sessions and secret key are stored with `chmod 600` on Linux.

[Unreleased]: https://github.com/ggr03/Pustakam/compare/v-1.0...main
[1.0]: https://github.com/ggr03/Pustakam/releases/tag/v-1.0
