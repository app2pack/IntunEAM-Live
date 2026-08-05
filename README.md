# IntunEAM Live v2 — README

**Author:** Vigneshwaran  
**Version:** 2.0  
**Port:** 8086  

A lightweight, dependency-free Python dashboard for viewing Microsoft Intune
Enterprise App Catalog (EAM) packages and live production app deployments.
Runs entirely in your browser via a local HTTP server.

**New in v2:** Two authentication methods — use an App Registration
or sign in interactively with your own Microsoft account (no App Registration needed).

---

## Prerequisites

### Python

| Platform | Requirement |
|---|---|
| macOS / Linux | Python 3.8 or later |
| Windows | Python 3.8 or later |

**No third-party packages needed.** Uses Python stdlib only:
`urllib`, `json`, `ssl`, `threading`, `http.server`.

**Check your Python version:**
```bash
# macOS / Linux
python3 --version

# Windows
py --version
```

---

## Authentication Methods

### Option 1 — App Registration *(recommended)*

Uses **Client Credentials Flow** — best for automation, scheduled runs,
or shared team use. Requires a one-time setup in Microsoft Entra.

**What you need:**
- Tenant ID
- Client ID (Application ID)
- Client Secret

**Required permission:**
`DeviceManagementApps.Read.All` (Application type, admin-consented)

**Setup steps:**

1. Go to [https://entra.microsoft.com](https://entra.microsoft.com)
2. **Identity → Applications → App registrations → New registration**
   - Name: e.g. `IntunEAM-Live-Reader`
   - Supported account types: **This organization only**
   - Click **Register**
3. Note the **Application (client) ID** and **Directory (tenant) ID**
4. Go to **Certificates & secrets → New client secret**
   - Set an expiry → click **Add**
   - **Copy the Value immediately** — it won't be shown again
5. Go to **API permissions → Add a permission → Microsoft Graph → Application permissions**
   - Add: `DeviceManagementApps.Read.All`
   - Click **Grant admin consent** (requires admin role)

---

### Option 2 — Interactive Browser Login *(no App Registration needed)*

Uses **Device Code Flow** — sign in with your own Microsoft / Entra account.
No App Registration or Client Secret required.

**What you need:**
- Tenant ID only (or use `common` for any tenant)
- Your Entra account must have **Intune Administrator** or **Global Reader** role

**How it works:**
1. Script displays a short code and opens `https://microsoft.com/devicelogin`
2. Enter the code on that page and sign in with your Entra account
3. Script automatically detects the login and continues

> **Note:** Device Code uses your user account's delegated permissions.
> Data access is scoped to what your account can see in Intune.
> The token is stored in memory only and is valid for the session.

---

## How to Run

### macOS / Linux

```bash
# Option 1 — App Registration (prompted)
python3 IntunEAM-Live-v2.py

# Option 1 — App Registration (env vars, skips all prompts)
TENANT_ID="your-tenant-id" \
CLIENT_ID="your-client-id" \
CLIENT_SECRET="your-secret" \
python3 IntunEAM-Live-v2.py

# Option 2 — Device Code (browser login)
AUTH_METHOD=2 TENANT_ID="your-tenant-id" python3 IntunEAM-Live-v2.py

# Option 2 — Device Code (any tenant)
AUTH_METHOD=2 TENANT_ID="common" python3 IntunEAM-Live-v2.py
```

### Windows

```powershell
# Option 1 — App Registration (py launcher, recommended)
py -3 IntunEAM-Live-v2.py

# Option 1 — App Registration (env vars, PowerShell)
$env:TENANT_ID="your-tenant-id"
$env:CLIENT_ID="your-client-id"
$env:CLIENT_SECRET="your-secret"
py -3 IntunEAM-Live-v2.py

# Option 2 — Device Code
$env:AUTH_METHOD="2"
$env:TENANT_ID="your-tenant-id"
py -3 IntunEAM-Live-v2.py
```

---

## Startup Sequence

### Option 1 — App Registration

```
─────────────────────────────────────────────────
  IntunEAM Live — Authentication
─────────────────────────────────────────────────
  Choose login method:
  [1] App Registration (Client ID + Secret) — recommended
  [2] Interactive Browser Login (Device Code) — no App Reg needed

  Enter 1 or 2 [default: 1]: 1

  Tenant ID     : xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
  Client ID     : xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
  Client Secret : (hidden)

=================================================
  IntunEAM Live v1
  Tab 1: EAM Catalog Apps
  Tab 2: Live Apps
  Tab 3: App Updates
  Author : Vigneshwaran
=================================================
  URL    : http://localhost:8086
  Tenant : your-tenant-id

  Starting data fetch in background...
  Browser will open automatically.
  Press Ctrl+C to stop.
```

### Option 2 — Device Code

```
─────────────────────────────────────────────────
  IntunEAM Live — Authentication
─────────────────────────────────────────────────
  Choose login method:
  [1] App Registration (Client ID + Secret) — recommended
  [2] Interactive Browser Login (Device Code) — no App Reg needed

  Enter 1 or 2 [default: 1]: 2

  Tenant ID     : your-tenant-id

  ┌─────────────────────────────────────────────────────┐
  │  Open browser: https://microsoft.com/devicelogin   │
  │  Enter code  : ABC123XYZ                           │
  └─────────────────────────────────────────────────────┘
  Waiting for you to sign in...
  ✅ Login successful.
```

### Auto-detect (env vars — no prompts at all)

If `TENANT_ID`, `CLIENT_ID`, and `CLIENT_SECRET` are all set as environment
variables, the script skips the menu entirely:

```
  [Auto] All credentials detected via environment — using App Registration.
```

---

## Dashboard Overview

The dashboard has three tabs in the left sidebar:

### 📁 Tab 1 — EAM Catalog Apps

Displays all packages in the **Microsoft Intune Enterprise App Catalog**.

| KPI | Description |
|---|---|
| Total Packages | All EAM packages available |
| Publishers | Distinct software publishers |

| Filter | Options |
|---|---|
| Search | Name, publisher, branch, version |
| Publisher | Filter by publisher |
| Architecture | x64, x86, x86_x64, ARM64 |
| Auto-Update | All / Auto-Update / Manual |

| Column | Description |
|---|---|
| Application Name | Package display name |
| Publisher | Software publisher |
| Version | Latest version in catalog |
| Branch | Release branch (Stable, Preview…) |
| Architecture | Supported CPU architectures |
| Auto-Update | Auto-update capable |

---

### 💻 Tab 2 — Live Apps

Displays **EAM apps deployed in your Intune tenant**, fetched live from
Microsoft Graph API.

> Loads after the catalog tab. Progress bar shows fetch status.
> For large tenants this may take 1–3 minutes.

| KPI | Description |
|---|---|
| Assigned | Apps with at least one group assignment |
| Unassigned | Apps with no group target |

| Filter | Options |
|---|---|
| Assignment | All / Assigned / Unassigned |
| Install Context | All / System / User |
| Update Method | All / Auto-Update / Manual |
| Search | Name or publisher |

| Column | Description |
|---|---|
| Application Name | Intune display name |
| Publisher | Publisher as set in Intune |
| Assignment | Assigned / Unassigned badge |
| Install Context | System or User install |
| Update Method | Auto or Manual |
| Supersedence | Superseding/superseded relationships |

**Click any row** to open the app detail modal showing assignments,
update method, supersedence relationships by name, and dependencies.

---

### 🔔 Tab 3 — App Updates

Displays EAM apps with a newer version available in the catalog
compared to what is deployed in Intune.

| Column | Description |
|---|---|
| App Name | Application display name |
| Publisher | Publisher name |
| Deployed Version | Currently deployed version |
| Latest Available | Newest version in catalog |
| Update Available | Yes / No |
| Update Eligible | Yes / No |
| Superseded | Whether superseded by another app |

---

## Environment Variables Reference

| Variable | Description | Required |
|---|---|---|
| `TENANT_ID` | Your Entra Directory (tenant) ID | Always |
| `CLIENT_ID` | App Registration client ID | Option 1 only |
| `CLIENT_SECRET` | App Registration client secret | Option 1 only |
| `AUTH_METHOD` | `1` = App Reg, `2` = Device Code | Optional (default: `1`) |
| `PORT` | Server port (default: `8086`) | Optional |

---

## Security Notes

> **🔒 Note:** All data fetched from Microsoft Graph API is processed entirely
> on your local machine — it is stored in memory by the Python server,
> rendered in your browser, and never transmitted to any external service,
> third-party server, or analytics platform.

- Credentials are **never stored** — entered at runtime or via env vars only
- The server binds to **localhost only** — not accessible from other machines
- Client Secret is entered via hidden input — not echoed to terminal
- Device Code tokens are held in memory only — cleared when script stops
- Only **read permissions** are used — no write access to your tenant
- No third-party libraries, no CDN calls, no analytics

---

## Troubleshooting

| Issue | Fix |
|---|---|
| Browser doesn't open | Navigate manually to http://localhost:8086 |
| `Address already in use` | Port 8086 is taken. Set `PORT=8087` or stop the other process |
| Live Apps shows no data | Wait for catalog to finish loading, then click Refresh |
| `Authentication failed` | Check credentials and ensure admin consent is granted |
| Device Code timed out | Restart and complete the browser login within 15 minutes |
| `Still fetching` after 5 mins | Click the Refresh button in Live Apps tab |
| SSL / certificate error | Corporate proxy may intercept TLS — contact your IT team |

---

## Stopping the Server

Press `Ctrl+C` in the terminal window where the script is running.

---

## Version History

| Version | Changes |
|---|---|
| v2 | Added Device Code (browser login) as Option 2. Auto-detects env vars. |
| v1 | Initial release. App Registration only. |

---

*IntunEAM Live — Author: Vigneshwaran*   - Redirect URI: leave blank
   - Click **Register**
4. Note down the **Application (client) ID** and **Directory (tenant) ID**
   from the Overview page.

#### Create a Client Secret

1. Inside your App Registration → **Certificates & secrets**
2. Click **New client secret**
3. Description: e.g. `IntunEAM Dashboard`
4. Expiry: choose appropriate (e.g. 12 months)
5. Click **Add**
6. **Copy the secret VALUE immediately** — it will not be shown again.

#### Grant API Permissions

1. Inside your App Registration → **API permissions**
2. Click **Add a permission → Microsoft Graph → Application permissions**
3. Search for and add:

| Permission | Type | Purpose |
|---|---|---|
| `DeviceManagementApps.Read.All` | Application | Read Intune apps, assignments, catalog |

4. Click **Grant admin consent for \<your tenant\>** (requires Global Admin or
   Privileged Role Administrator)
5. The permission status should show a green tick ✅ **Granted**

> **Note:** Application permissions (not Delegated) are required because the
> script runs as a background service without a signed-in user.

---

## How to Run

### macOS / Linux
```bash
python3 IntunEAM-Live.py
```

### Windows
```powershell
# Option 1 — py launcher (recommended, most reliable)
py -3 IntunEAM-Live.py

# Option 2 — python.org install
python IntunEAM-Live.py

# Option 3 — Microsoft Store install
python3 IntunEAM-Live.py
```

### Using Environment Variables (skip interactive prompts)
```bash
# macOS / Linux
TENANT_ID="your-tenant-id" \
CLIENT_ID="your-client-id" \
CLIENT_SECRET="your-secret" \
python3 IntunEAM-Live.py

# Windows PowerShell
$env:TENANT_ID="your-tenant-id"
$env:CLIENT_ID="your-client-id"
$env:CLIENT_SECRET="your-secret"
py -3 IntunEAM-Live.py
```

### Startup Sequence

```
─────────────────────────────────────────────────
  IntunEAM Live — Azure / Entra Credentials
─────────────────────────────────────────────────
  App Registration needs: DeviceManagementApps.Read.All

  Tenant ID     : <enter or auto-detected from env>
  Client ID     : <enter or auto-detected from env>
  Client Secret : <hidden input>

=================================================
  IntunEAM Live v1
  Tab 1: EAM Catalog Apps
  Tab 2: Live Apps
  Tab 3: App Updates
  Author : Vigneshwaran
=================================================
  URL    : http://localhost:8086
  Tenant : your-tenant-id

  Starting data fetch in background...
  Browser will open automatically.
  Press Ctrl+C to stop.
```

The browser opens automatically at **http://localhost:8086**.
To stop the server press `Ctrl+C`.

---

## Dashboard Overview

The dashboard has three tabs accessible from the **left sidebar**:

### Tab 1 — EAM Catalog Apps

Displays all packages available in the **Microsoft Intune Enterprise App
Catalog** for your tenant.

**KPI Cards**

| Card | Description |
|---|---|
| Total Packages | All EAM packages available in the catalog |
| Publishers | Number of distinct software publishers |

**Filters**

| Filter | Description |
|---|---|
| Search | Search by app name, publisher, branch, or version |
| Publisher | Filter to a specific publisher |
| Architecture | x64, x86, x86_x64, ARM64 |
| Auto-Update | All / Auto-Update capable / Manual only |

**Table Columns**

| Column | Description |
|---|---|
| Application Name | Display name of the EAM package |
| Publisher | Software publisher name |
| Version | Latest available version in the catalog |
| Branch | Release branch (e.g. Stable, Preview) |
| Architecture | Supported CPU architectures |
| Auto-Update | Whether the app supports automatic updates |

**Actions:** Export CSV, Reset filters, Toggle table/card view.

---

### Tab 2 — Live Apps

Displays **EAM apps currently deployed in your Intune tenant** — fetched live
from Microsoft Graph API. This tab fetches all mobile apps and filters to
EAM types (`win32CatalogApp`, `windowsAutoUpdateCatalogApp`).

> This tab loads after the catalog tab completes. A progress bar shows
> fetch status. For tenants with many apps this may take 1–3 minutes.

**KPI Cards**

| Card | Description |
|---|---|
| Assigned | Apps with at least one group assignment |
| Unassigned | Apps with no group target (retirement candidates) |

**Filters**

| Filter | Description |
|---|---|
| Assignment | All Apps / Assigned Only / Unassigned Only |
| Install Context | All Contexts / System / User |
| Update Method | All / ✅ Auto-Update / ❌ Manual |
| Search | Search by app name or publisher |

**Table Columns**

| Column | Description |
|---|---|
| Application Name | Intune display name of the deployed app |
| Publisher | Publisher as set in Intune |
| Assignment | Assigned / Unassigned badge |
| Install Context | System (device-wide) or User install |
| Update Method | Auto (windowsAutoUpdateCatalogApp) or Manual |
| Supersedence | Number of superseding/superseded relationships |

**Click any row** to open the app detail modal showing:
- App Details: BU, Category, Lifecycle, Install Context, Device Restart, Publishing State, Created, Last Modified
- Update & Supersedence: Update Method, Superseding Apps (by name), Superseded By (by name), Dependencies
- Assignments: Group name, intent (Required/Available/Uninstall), target type

**Actions:** Export CSV, Refresh (re-fetches live data), Reset filters.

---

### Tab 3 — App Updates

Displays EAM apps that have a **newer version available** in the catalog
compared to what is currently deployed in Intune.

Uses the Microsoft Graph report endpoint:
`deviceManagement/reports/retrieveWin32CatalogAppsUpdateReport`

**Columns shown:**
Application Name, Publisher, Current Version, Latest Available Version,
Update Available, Update Eligible, Superseded status.

**Actions:** Export CSV.

---

## Security Notes

> **🔒 Note:** All data fetched from Microsoft Graph API is processed entirely on your local machine — it is stored in memory by the Python server, rendered in your browser, and never transmitted to any external service, third-party server, or analytics platform.

- Credentials are **never stored** — entered at runtime via prompt or
  environment variables only.
- The server binds to **localhost only** — not accessible from other machines.
- All data displayed is fetched live from your tenant via Microsoft Graph API
  using your App Registration credentials.
- Client Secret is entered via hidden input (`getpass`) — not echoed to terminal.
- Only `DeviceManagementApps.Read.All` permission is required — **read-only**,
  no write access to your tenant.

---

## Troubleshooting

| Issue | Fix |
|---|---|
| Browser doesn't open | Manually navigate to http://localhost:8086 |
| `Address already in use` | Another process is on port 8086. Set `PORT=8087` env var or stop the other process. |
| Live Apps shows "Server error" | Wait for catalog to finish loading first, then click Refresh |
| `Authentication failed` | Check Tenant ID, Client ID, Client Secret. Ensure admin consent is granted. |
| No apps in Live tab | Ensure the App Registration has `DeviceManagementApps.Read.All` with admin consent |
| SSL certificate error | Your network may intercept TLS (e.g. corporate proxy). Contact your IT team. |

---

## Stopping the Server

Press `Ctrl+C` in the terminal window where the script is running.

---

*IntunEAM Live — Author: Vigneshwaran*
