# Security: Pustakam (पुस्तकम्)

## Reporting a problem

Please open an issue on [ggr03/Pustakam](https://github.com/ggr03/Pustakam/issues) titled **"Security"**, describing the
area affected but **without exploit details**; the maintainer will follow up privately.

## Design

* **Local first.** Notes live on your computer; the server is meant for your own machine and home LAN.
* **OS sign-in.** Linux PAM or Windows `LogonUser`. By default only the account running Pustakam can sign in.
  Failed sign-ins are rate-limited (5 per 5 minutes per address). Sessions expire after 12 h, and after inactivity
  (default 15 min), which is enforced on the server.
* **No secrets in the browser.** Cookies are `HttpOnly` and `SameSite=Lax`. OneDrive tokens stay on the server in
  `~/.pustakam/rclone.conf` (chmod 600).
* **HTTP on the LAN.** Pustakam does not do TLS itself. To use it beyond a trusted home network, put it behind
  a reverse proxy with HTTPS (e.g. Caddy or nginx) or use a VPN such as WireGuard or Tailscale.

## Protections in 1.0

| Threat | Protection |
|---|---|
| Cross-site scripting (XSS) | Markdown and math pass through DOMPurify (HTML + MathML + SVG profiles) as a final step; KaTeX `trust:false`; titles, previews, tags and weather text are escaped or set as text; Jinja auto-escaping; no inline scripts |
| Script injection / compromised CDN | Content-Security-Policy (`script-src 'self' https://cdn.jsdelivr.net`, `object-src 'none'`, `frame-ancestors 'none'`, `base-uri 'self'`, `form-action 'self'`) and Subresource Integrity hashes on every CDN file |
| Clickjacking | `X-Frame-Options: DENY` and `frame-ancestors 'none'` |
| CSRF | State-changing requests with a foreign `Origin` are refused; API calls require the `X-Pustakam: 1` header (needs a CORS pre-flight, which is never granted); `SameSite=Lax` cookies |
| SQL injection | Parameterised queries everywhere; full-text search terms are quoted |
| Command injection | rclone runs from an argument list (no shell); remote paths are prefixed with the remote name; note titles are sanitised into file names |
| Path traversal | Log viewer only serves files listed in the Logs folder, resolved inside it; note file names are sanitised |
| Log forging | Control characters (CR/LF…) in log messages are neutralised |
| Information leaks | Generic error messages to the browser (details in the logs); OS username not shown to other LAN devices; `Cache-Control: no-store` on API responses |
| Brute force | Sign-in rate limit |

## Scan results (release 1.0, 2026-11-24)

| Tool | Scope | Result |
|---|---|---|
| **Snyk Open Source** | Python dependencies (14) | ✅ No known vulnerabilities |
| **pip-audit** | Installed Python environment | ✅ No known vulnerabilities |
| **Snyk Code** (SAST) | Python, JavaScript, HTML | 19 → **14** issues; **0 high**. All remaining issues reviewed and accepted (below) |
| **Bandit** | Python | No exploitable issues (binding to all interfaces is intentional for LAN access; others false positives) |
| Manual review + tests | XSS payloads in a real browser, CSRF, traversal, SQL/FTS injection, log injection, idle timeout, error leaks | ✅ All blocked |

### Accepted Snyk Code findings

| Finding | Where | Why it is accepted |
|---|---|---|
| Command Injection (medium ×3) | `PustakamOneDrive.py` | The flagged value is the `PUSTAKAM_RCLONE` environment variable, which only the machine's owner can set. It must point at an existing file named `rclone`/`rclone.exe`, and it runs without a shell from an argument list. |
| Path Traversal (low ×8) | `PustakamConfig.py` | Paths come from `PUSTAKAM_DATA_DIR` (owner-set environment variable) or the home folder; not reachable from the web. |
| Path Traversal (low ×3) | `PustakamGetRclone.py` | Install-time helper; the destination folder is passed by the installer. |

## Not covered

* Notes are not encrypted at rest; use full-disk encryption (LUKS, BitLocker) if needed.
* Anyone who can sign in as the OS account can read all notes.
* The KaTeX, marked, DOMPurify and highlight.js libraries load from jsDelivr (pinned versions with SRI).
