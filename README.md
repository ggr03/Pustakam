<p align="center">
  <img src="static/img/PustakamLogo.svg" width="96" alt="Pustakam logo">
</p>

<h1 align="center">Pustakam (पुस्तकम्)</h1>

<p align="center"><b>Your notes, your machine, your cloud.</b><br>
A local-first Markdown notebook for Linux and Windows, with two-way OneDrive sync and daily local backups.</p>

---

## 📜 The name

**पुस्तकम्** (*pustakam*, said "PUS-ta-kam") is Sanskrit for a **book**: a **manuscript**, or a **collection
of notes** and written leaves bound together. In ancient India a *pustaka* was literally a stack of palm-leaf or
birch-bark pages, strung on a cord and kept between two wooden covers: notes gathered, organised and preserved.

That is what this app is: a home for your notes, grouped into **notebooks**, written in Markdown, readable for
decades as plain `.md` files, and kept safe on your own computer, in your OneDrive, and in local backups.

## 🌟 At a glance

* **Local first.** Notes live in SQLite on your machine, plus a Markdown copy of every note. They work offline.
* **Sign in with your OS account.** Your Linux (PAM) or Windows password, so there are no extra accounts.
* **Read first, edit when you choose.** A clean reading view, and a split editor with live preview.
* **Math and chemistry.** KaTeX math (`$E=mc^2$`) and chemical formulae (`$\ce{2H2 + O2 -> 2H2O}$`).
* **Two-way OneDrive sync.** Sign in with your outlook.com / hotmail.com / msn.com account. Each notebook becomes a folder and each note a `.md` file.
* **Local backups.** Daily `.zip` backups to any folder (second disk, USB, NAS), plus **Back up now**.
* **Logs.** Sign-ins, syncs and every note change are written to plain-text logs.
* **Use it anywhere at home.** Open it from phones, tablets and other computers on your LAN, with a mobile-friendly layout.
* **Cross-platform installers.** Debian/Ubuntu/MX, Fedora/RHEL/Rocky/Alma, openSUSE and Windows 10/11.

**Version:** `2026-11-24-01` (successor of NoteVault)

---

## ✨ Features

| | |
|---|---|
| 📚 **Notebooks** | Each notebook gets its own icon, picked from its name (*Chemistry Lab* → ⚗️, *Travel* → ✈️, otherwise its initials) on a colour and pattern unique to that name. Right-click (or **⋯**) a notebook to **set it as default**, rename or delete it. The default notebook (★) opens first and new notes go there. |
| 👁️ **Read first** | Notes open in a clean reading view. Press **✏️ Edit** (or `E`, or double-click) to edit. |
| ✂️ **Split editor** | Editing shows Markdown on the left and a live preview on the right (stacked on narrow screens), with matching scroll. |
| ∑ **Math** | KaTeX: `$E=mc^2$`, `$$\int_0^1 x^2\,dx$$`, `\( … \)`, `\[ … \]`. |
| ⚗️ **Chemistry** | mhchem: `$\ce{H2SO4}$`, `$\ce{N2 + 3H2 <=> 2NH3}$`, or a bare `\ce{CO2}` anywhere in text. Units: `\pu{9.81 m/s^2}`. |
| ☁️ **OneDrive sync** | Two-way. Sign in with your outlook.com / hotmail.com / msn.com account, no app setup. Files you add to the OneDrive folder from the web or your phone become notes here. |
| 🌦️ **Status bar** | Sync status, weather for your cities (°C and °F plus a short description; click a city for feels-like, humidity, wind, AQI and UV), today's date in ISO format (`2026-11-24`) and the **Sync** button. |
| 🔐 **OS sign-in** | Linux: PAM (your Linux password). Windows: your Windows password. Logs you out after inactivity. **Logout** button. |
| 🔎 **Search & tags** | Full-text search (SQLite FTS5) and tag filtering. |
| 💾 **Local backup** | Daily at 21:00 to any folder you choose (second disk, USB drive, NAS), plus **Back up now** in Settings. The last 5 (configurable) are kept as `.zip` files holding the database and a Markdown copy of every note. |

Keyboard: `Alt+N` new note · `E` edit · `Ctrl+S` save · `Ctrl+Enter` save and read · `Esc` back to reading.

---

## 📦 Install

### Linux: Debian family (Debian, Ubuntu, Mint, MX, siduction) and Red Hat family (Fedora, RHEL, Rocky, Alma)

```bash
git clone https://github.com/ggr03/Pustakam.git
cd Pustakam
./PustakamInstall.sh
```

The installer:
* finds Python 3.9+ (and installs `python3`, `python3-venv`/`python3-pip` with apt, dnf, yum or zypper if they are missing),
* installs into `~/.local/share/pustakam` with a private Python environment,
* offers to **copy your NoteVault notes** and to stop the old NoteVault service (same port 5150),
* creates a **systemd user service** `pustakam` plus a daily backup timer, and enables lingering so it runs at boot.
  On systems without systemd user services it uses cron `@reboot` instead,
* optionally opens port 5150 in **firewalld** (Fedora/RHEL) or **ufw** (Ubuntu) for LAN access,
* adds a "Pustakam" launcher to your applications menu.

```bash
systemctl --user status pustakam        # status
systemctl --user restart pustakam       # restart
journalctl --user -u pustakam -f        # logs
```

Uninstall: `~/.local/share/pustakam/PustakamUninstall.sh` (your notes are kept unless you type `DELETE`).

### Windows 10 / 11

Download or clone the repository, then in PowerShell, from the `Pustakam` folder:

```powershell
powershell -ExecutionPolicy Bypass -File .\PustakamInstall.ps1
```

* Finds Python 3.9+ (offers `winget install Python.Python.3.12` if missing).
* Installs into `%LOCALAPPDATA%\Pustakam`, data in `%USERPROFILE%\.pustakam`.
* Registers a hidden **Task Scheduler** task `Pustakam` that starts when you log on
  (`-RunAtStartup` starts it at boot, before log-on; Windows asks for your password once).
* Registers `Pustakam Backup` (daily 21:00) and a Start-menu shortcut.
* `-OpenFirewall` (as Administrator) allows other devices on your private network.

Uninstall: `powershell -ExecutionPolicy Bypass -File "%LOCALAPPDATA%\Pustakam\PustakamUninstall.ps1"`

### Sign in

Open **http://localhost:5150** and sign in with the operating-system account that runs Pustakam.
Other accounts are refused because the notes belong to that account. To allow more, list them in
`~/.pustakam/config.json` → `"allowed_users": ["name"]`.

* **Windows, Microsoft account:** username `MicrosoftAccount\you@outlook.com` and your account password. A Windows Hello PIN cannot be used.
* **Linux:** the PAM service is `login` (change `"pam_service"` in `config.json` if your distro needs another).

---

## ☁️ OneDrive sync setup

### Microsoft OneDrive: just sign in
No setup. In **Settings → Microsoft OneDrive**, choose the folder, then click **Sign in with Microsoft** and log in with your
**outlook.com, hotmail.com, live.com or msn.com** account (work/school accounts work too).
Pustakam uses [rclone](https://rclone.org), a widely used open-source sync tool, for OneDrive, so Microsoft's consent page names
the app **rclone**. The installer downloads the official rclone build (SHA-256 verified) into Pustakam's own folder.
The OneDrive token is stored in `~/.pustakam/rclone.conf` (chmod 600), separate from any rclone setup of your own.

After you approve access, Pustakam **tests the connection automatically**: it checks your account,
creates or opens the folder, and writes, reads and deletes a test file. Use **🧪 Test** at any time.

### 🌐 Using Pustakam from other devices on your LAN

Pustakam listens on all network interfaces (`0.0.0.0:5150`). From any device on your network, open
`http://<this computer's IP>:5150` (Settings → Server shows the exact address, e.g. `http://192.168.1.50:5150`)
and sign in with the same Linux/Windows account. If a firewall is on, the installer offers to open port 5150
(firewalld, ufw, or Windows Firewall with `-OpenFirewall`).

> **OneDrive sign-in from another device:** Microsoft sends you back to a `localhost` address, which on that
> device shows "can't be reached". Copy that page's full address and paste it into the box that appears under the
> provider in Settings; Pustakam finishes the sign-in on the server.

### How two-way sync works

```
<your folder>/                    e.g. OneDrive/Pustakam   or   OneDrive/Documents/Notes/Pustakam
├── Loose note.md                 notes without a notebook
├── Chemistry Lab/                each notebook = a sub-folder
│   ├── Acids and Bases.md        each note = a .md file (title = file name)
│   └── Shopping.txt              .md, .markdown and .txt files you add become notes
└── Travel Plans/
```

* New, edited, renamed, moved and deleted notes and notebooks sync both ways.
* If a note changed **on both sides** since the last sync, your local version is kept and the cloud
  version is saved as a separate note named `… (conflict OneDrive 2026-11-24 2015)`.
* Deleted notes go to the OneDrive recycle bin, never permanently deleted.
* **Safety stop:** if most linked notes suddenly disappear from the cloud (wrong account, folder moved),
  the sync stops instead of deleting them locally. Use **Reset link** in Settings if that was intended.
* Automatic sync runs every 10 minutes (change it in Settings, `0` = manual only), and the **⟳ Sync** button
  in the status bar syncs right away.
* Only the top level and first-level folders are synced. Deeper sub-folders are ignored.

---

## 📁 Files

| Path | What |
|---|---|
| `~/.pustakam/pustakam.db` | SQLite database (notes, notebooks, tags, sync state) |
| `~/.pustakam/notes/` | Markdown copy of every note |
| `~/.pustakam/config.json` | Settings (chmod 600 on Linux) |
| `~/.pustakam/rclone.conf` | OneDrive sign-in for rclone (chmod 600) |
| `~/.pustakam/backups/` (default; change in Settings → Local backup) | `pustakam-backup-1.zip` (newest) … `-5.zip`. To restore, stop Pustakam and unzip `pustakam.db` into `~/.pustakam/` |
| `~/.pustakam/Logs/` | `connection.log` (sign-ins, OneDrive connect/test), `sync.log` (every sync action), `notes.log` (note/notebook created, edited, moved, deleted: titles only), `backup.log`. 2 MB each, 5 rotations. Viewable in Settings → Logs |

See [`PustakamFileStructure.txt`](PustakamFileStructure.txt) for the source layout.

## 🧰 Requirements

Python 3.9+, `flask`, `requests`, `waitress`, and `python-pam` (Linux only); see `PustakamRequirements.txt`. rclone 1.58+ for OneDrive (installed by the installers via `PustakamGetRclone.py`).
The editor loads marked, DOMPurify, KaTeX (+ mhchem) and highlight.js from the jsDelivr CDN, and weather
comes from [Open-Meteo](https://open-meteo.com) (no API key). Both need internet access. Notes work offline.

## 📄 License

Pustakam is released under the [MIT License](LICENSE): free to use, copy, modify and share, with no warranty.
It talks to [rclone](https://rclone.org) (MIT) and loads [marked](https://marked.js.org), [DOMPurify](https://github.com/cure53/DOMPurify),
[KaTeX](https://katex.org), [highlight.js](https://highlightjs.org) and [Flask](https://flask.palletsprojects.com), each under its own open-source licence.
