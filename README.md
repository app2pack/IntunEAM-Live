# IntunEAM Live — README

**Author:** Vigneshwaran  
**Version:** 1.0  
**Port:** 8086  

🟥🟩 A lightweight, dependency-free Python dashboard for viewing Microsoft Intune
🟦🟨 Enterprise App Catalog (EAM) packages and live production app deployments.
Runs entirely in your browser via a local HTTP server — no cloud, no database,
no pip installs required.

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

If Python is not installed, download from https://www.python.org/downloads/
On Windows, tick **"Add Python to PATH"** during installation.

---

### Microsoft Entra App Registration

The script authenticates to Microsoft Graph API using an **App Registration**
(service principal / client credentials flow). You need three values:

| Value | Where to find it |
|---|---|
| **Tenant ID** | Entra Admin Center → Overview → Tenant ID |
| **Client ID** | App Registration → Overview → Application (client) ID |
| **Client Secret** | App Registration → Certificates & Secrets → Client secrets |

#### Step-by-step: Create the App Registration

1. Go to [https://entra.microsoft.com](https://entra.microsoft.com)
2. Navigate to **Identity → Applications → App registrations**
3. Click **New registration**
   - Name: e.g. `IntunEAM-Live-Reader`
   - Supported account types: **Accounts in this organizational directory only**
   - Redirect URI: leave blank
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
