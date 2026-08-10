# ============================================================
# Script       : IntunEAM-Live.py
# Description  : Live Intune Enterprise App Catalog dashboard.
# Author       : Vigneshwaran
# Version      : 1.0
# Prerequisites:
#   All platforms : Python 3.8+, no third-party packages needed.
#                   Uses stdlib only (urllib, json, threading, ssl).
#   Entra/Azure   : App Registration with admin-consented
#                   DeviceManagementApps.Read.All (Application) permission.
#
# Usage:
#   macOS / Linux : python3 IntunEAM-Live.py
#   Windows       : py -3 IntunEAM-Live.py          (py launcher, recommended)
#                   python IntunEAM-Live.py          (python.org install)
#                   python3 IntunEAM-Live.py         (Microsoft Store install)
#   All           : Browser opens automatically at http://localhost:8086
# ============================================================

import json, threading, webbrowser, time, urllib.parse, urllib.request, urllib.error, ssl, sys, re as _re
from http.server import HTTPServer, BaseHTTPRequestHandler
# stdlib only — Mac/Windows compatible
# SSL context — certificate verification disabled to support corporate networks
# with TLS inspection proxies (e.g. Zscaler, Palo Alto). If your network does
# not use SSL inspection, you can enable verification by removing the two lines below.
_SSL = ssl.create_default_context()
_SSL.check_hostname = False
_SSL.verify_mode    = ssl.CERT_NONE

# ── CONFIG ──────────────────────────────────────────────────
import os as _os, sys as _sys

def _get_val(label, env_key, secret=False):
    env_val = _os.environ.get(env_key, "").strip()
    if env_val:
        masked = env_val[:4] + "*" * (len(env_val)-4) if len(env_val) > 4 else "****"
        print(f"  {label}: [using env var: {masked}]")
        return env_val
    print(f"  {label}: ", end="", flush=True)
    try:
        if secret:
            import getpass as _gp
            val = _gp.getpass("").strip()
        else:
            val = input("").strip()
    except Exception:
        val = input("").strip()
    return val

print("\n─────────────────────────────────────────────────")
print("  IntunEAM Live — Authentication")
print("─────────────────────────────────────────────────")
print("  Choose login method:")
print("  [1] App Registration (Client ID + Secret) — recommended")
print("  [2] Interactive Browser Login (Device Code) — no App Reg needed")
print("")

_auth_method = _os.environ.get("AUTH_METHOD","").strip()
if not _auth_method:
    # If all three creds provided via env vars, skip menu and use App Registration
    _has_all_creds = all(_os.environ.get(k,"").strip() for k in ["TENANT_ID","CLIENT_ID","CLIENT_SECRET"])
    if _has_all_creds:
        _auth_method = "1"
        print("  [Auto] All credentials detected via environment — using App Registration.\n")
    else:
        try:
            _auth_method = input("  Enter 1 or 2 [default: 1]: ").strip() or "1"
        except Exception:
            _auth_method = "1"

AUTH_METHOD = _auth_method  # "1" = client credentials, "2" = device code

if AUTH_METHOD == "2":
    # Device code flow — user logs in via browser, no App Reg needed
    # Requires: Entra > Enterprise Apps > Microsoft Graph > allow public client flows
    TENANT_ID     = _get_val("Tenant ID     (or 'common' for any tenant)", "TENANT_ID", secret=False)
    CLIENT_ID     = _os.environ.get("CLIENT_ID", "14d82eec-204b-4c2f-b7e8-296a70dab67e")
    # ^ Microsoft Graph Explorer public client ID — works for delegated auth
    CLIENT_SECRET = ""
    print("  [Device Code] Will open browser for login when server starts.\n")
else:
    print("  [App Registration] Enter your Entra App Registration details.")
    print("  Requires: DeviceManagementApps.Read.All (Application permission)\n")
    TENANT_ID     = _get_val("Tenant ID     ", "TENANT_ID",     secret=False)
    CLIENT_ID     = _get_val("Client ID     ", "CLIENT_ID",     secret=False)
    CLIENT_SECRET = _get_val("Client Secret ", "CLIENT_SECRET", secret=True)
    if not all([TENANT_ID, CLIENT_ID, CLIENT_SECRET]):
        print("\n[ERROR] All three credentials are required for App Registration. Exiting.")
        _sys.exit(1)

print("")
PORT = int(_os.environ.get("PORT", "8086"))

# ── GLOBAL STATE ────────────────────────────────────────────

def graph_get_one(url, headers):
    """Single item GET from Graph API."""
    import urllib.request, json, ssl
    _SSL2 = ssl.create_default_context()
    _SSL2.check_hostname = False
    _SSL2.verify_mode = ssl.CERT_NONE
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=30, context=_SSL2) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception:
        return None


def fetch_intune_eam_apps(token, state=None):
    """Fetch EAM (Enterprise App Catalog) apps deployed in Intune with BU/category detection."""
    import re as re2
    VALID_BUS = {"ELS","RISK","RX","LNG"}
    headers   = {"Authorization": f"Bearer {token}"}
    url       = "https://graph.microsoft.com/beta/deviceAppManagement/mobileApps?$top=100"
    raw_all   = graph_get_all(token, url)
    # Show type breakdown for debugging
    type_counts = {}
    for a in raw_all:
        t = a.get("@odata.type","")
        type_counts[t] = type_counts.get(t, 0) + 1
    for t, cnt in sorted(type_counts.items(), key=lambda x: -x[1])[:5]:
        print(f"        type: {t} ({cnt})")
    # Show type breakdown for all apps
    type_counts = {}
    for a in raw_all:
        t = a.get("@odata.type","")
        type_counts[t] = type_counts.get(t,0) + 1
    print(f"      App type breakdown:")
    for t,n in sorted(type_counts.items(), key=lambda x:-x[1])[:8]:
        print(f"        {t}: {n}")

    # Include win32CatalogApp OR winAutoUpdateApp OR any app with EAM in name
    # win32CatalogApp = standard EAM catalog app
    # winAutoUpdateApp / windowsCatalogApp = newer EAM auto-update type variants
    # Name fallback catches EAM apps regardless of how Graph classifies them
    # ALL known Graph API types for EAM / Enterprise App Catalog apps
    # win32CatalogApp     = primary EAM type (most apps)
    # win32CatalogMobileApp = variant used by some tenants
    # windowsAppX         = AppX-based catalog entries
    # Note: "Windows Auto Update Catalog App" in Intune portal is still win32CatalogApp
    #       the auto-update setting is a property (updateMethod), not a different type
    EAM_TYPES = {
        "win32catalogapp",
        "win32catalogmobileapp",
        "winautoupdateapp",
        "windowscatalogapp",
        "windowsautoupdate",
        "windowsautoupdatecatalogapp",   # confirmed type from tenant
    }
    def is_eam_app(a):
        odata = (a.get("@odata.type","")).lower().replace("#microsoft.graph.","")
        # Primary: type-based detection (reliable, naming-convention independent)
        if any(t in odata for t in EAM_TYPES):
            return True
        # Secondary: check updateMethod property if available
        # apps with updateMethod = "automaticUpdate" or "catalog" are EAM
        update_method = (a.get("updateMethod","") or a.get("appUpdateMethod","")).lower()
        if "automatic" in update_method or "catalog" in update_method:
            return True
        return False
    raw = [a for a in raw_all if is_eam_app(a)]
    # Log what types were found for debugging
    found_types = set(a.get("@odata.type","") for a in raw)
    print(f"      {len(raw)} EAM production apps found (from {len(raw_all)} total)")
    print(f"      EAM types found: {found_types}")
    apps_out = []
    total_raw = len(raw)
    for _i, a in enumerate(raw):
        # Update progress every app
        if state:
            pct = 40 + int((_i / max(total_raw,1)) * 55)
            state["intune_progress"] = {
                "pct": pct,
                "msg": f"[{_i+1}/{total_raw}] Fetching details: {a.get('displayName','')}",
                "done": False
            }
        name = a.get("displayName","")
        bu   = "Common"
        # Step 1: prefix match (ELS - AppName)
        pm = re2.match(r"^([A-Za-z]{2,6})\s*[-\u2013]\s*(.+)$", name.strip())
        if pm and pm.group(1).upper() in VALID_BUS:
            bu = pm.group(1).upper()
        else:
            # Step 2: suffix match (AppName - ELS)
            sm = re2.match(r"^(.+?)\s*[-\u2013]\s*([A-Za-z]{2,6})\s*$", name.strip())
            if sm and sm.group(2).upper() in VALID_BUS:
                bu = sm.group(2).upper()
            else:
                # Step 3: BU keyword anywhere in name
                for _bu in sorted(VALID_BUS):
                    if re2.search(r"\b" + _bu + r"\b", name, re2.IGNORECASE):
                        bu = _bu
                        break

        category = "Common" if bu == "Common" else "Custom"
        inst_exp  = a.get("installExperience") or {}
        inst_ctx  = (inst_exp.get("runAsAccount") or a.get("runAsAccount") or "").lower()
        ps_state  = a.get("publishingState","")

        # Determine lifecycle tag from name
        name_lo = name.lower()
        # EOL =  project: "EOL" at start or end of app name
        _is_eol = (bool(re2.match(r"^eol[\s\-_]", name_lo)) or
                   bool(re2.search(r"[\s\-_]eol$", name_lo)) or
                   name_lo.endswith(" eol"))
        # Retired = app deprecated/end of life
        _is_retired = "retired" in name_lo
        if _is_eol:
            lifecycle = "EOL"
        elif _is_retired:
            lifecycle = "Retired"
        elif "test" in name_lo or "pilot" in name_lo or "poc" in name_lo:
            lifecycle = "Testing"
        elif "project" in name_lo:
            lifecycle = "Project"
        else:
            lifecycle = "BAU"

        # For win32CatalogApp: fetch detail to get updateMethod reliably
        # (list endpoint returns updateMethod=empty for these apps)
        app_id   = a.get("id","")
        odata_lc = (a.get("@odata.type","")).lower()
        if "win32catalogapp" in odata_lc and "windowsautoupdatecatalogapp" not in odata_lc:
            detail = graph_get_one(
                f"https://graph.microsoft.com/beta/deviceAppManagement/mobileApps/{app_id}",
                headers
            )
            if detail:
                # Merge detail fields back into app object
                a = {**a, **{k:v for k,v in detail.items() if v is not None and v != ""}}

        # Fetch assignments for this app
        asgn_url = f"https://graph.microsoft.com/beta/deviceAppManagement/mobileApps/{a.get('id','')}/assignments"
        asgn_resp = graph_get_one(asgn_url, headers)
        assignments = []
        if asgn_resp and asgn_resp.get("value"):
            for asgn in asgn_resp["value"]:
                gid = (asgn.get("target") or {}).get("groupId","")
                gname = gid
                # Microsoft well-known virtual group IDs (public, not tenant-specific)
                if gid == "acacacac-9df4-4c7d-9d50-4ef0226f57a9": gname = "All Devices"
                elif gid == "adadadad-808e-44f2-905a-0b246873f7c1": gname = "All Users"
                elif gid:
                    g = graph_get_one(f"https://graph.microsoft.com/v1.0/groups/{gid}?$select=displayName", headers)
                    if g: gname = g.get("displayName", gid)
                assignments.append({
                    "groupId":    gid,
                    "groupName":  gname,
                    "intent":     asgn.get("intent",""),
                })

        # Fetch relationships if app has supersedence or dependencies
        relationships = []
        has_rel = (int(a.get("supersedingAppCount") or 0) > 0 or
                   int(a.get("supersededAppCount")  or 0) > 0 or
                   int(a.get("dependentAppCount")   or 0) > 0)
        if has_rel:
            rel_url  = f"https://graph.microsoft.com/beta/deviceAppManagement/mobileApps/{app_id}/relationships"
            rel_resp = graph_get_one(rel_url, headers)
            if rel_resp and rel_resp.get("value"):
                for rel in rel_resp["value"]:
                    relationships.append({
                        "targetId":          rel.get("targetId",""),
                        "targetDisplayName": rel.get("targetDisplayName",""),
                        "relationshipType":  rel.get("@odata.type",""),
                    })

        apps_out.append({
            "id":                    a.get("id",""),
            "displayName":           name,
            "publisher":             a.get("publisher",""),
            "publishingState":       ps_state,
            # Re-derive isAssigned from actual assignments fetched (more reliable than list API flag)
            "isAssigned":            len(assignments) > 0 or bool(a.get("isAssigned",False)),
            "bu":                    bu,
            "category":              category,
            "lifecycle":             lifecycle,
            "installContext":        inst_ctx or "unknown",
            "deviceRestartBehavior": inst_exp.get("deviceRestartBehavior",""),
            "createdDateTime":       a.get("createdDateTime",""),
            "lastModifiedDateTime":  a.get("lastModifiedDateTime",""),
            "assignments":           assignments,
            "supersedingAppCount":   int(a.get("supersedingAppCount") or 0),
            "supersededAppCount":    int(a.get("supersededAppCount") or 0),
            "dependentAppCount":     int(a.get("dependentAppCount") or 0),
            "packageAutoUpdateCapable": bool(a.get("packageAutoUpdateCapable", False)),
            # Derive update method from type + property
            # windowsAutoUpdateCatalogApp = always auto-update by definition
            # win32CatalogApp: use updateMethod field if available
            "updateMethod":             (
                "automaticallyupdate"
                if "windowsautoupdatecatalogapp" in (a.get("@odata.type","")).lower()
                else str(a.get("updateMethod","") or a.get("updateBehavior","")).lower()
            ),
            "odataType":                a.get("@odata.type",""),
            "relationships":            relationships,
        })

    return apps_out


_state = {
    "apps":           [],
    "progress":       {"pct":0,"msg":"Initialising...","done":False},
    "loading":        False,
    "error":          None,
    "intune_apps":    None,
    "intune_loading": False,
    "intune_error":   None,
    "intune_progress":{"pct":0,"msg":"Waiting for catalog to load...","done":False},
    "updates_apps":   None,
    "updates_loading":False,
    "updates_error":  None,
}

# ── GRAPH TOKEN ─────────────────────────────────────────────
def _get_ssl():
    import ssl
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode    = ssl.CERT_NONE
    return ctx

def get_graph_token():
    import urllib.request, urllib.parse, json as _j, time as _t, base64
    _SSL = _get_ssl()
    _t.sleep(0.5)

    if AUTH_METHOD == "2":
        # ── Device Code Flow (interactive browser login) ──────
        # Step 1: Request device code
        dc_url  = f"https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/devicecode"
        dc_data = urllib.parse.urlencode({
            "client_id": CLIENT_ID,
            "scope":     "DeviceManagementApps.Read.All offline_access openid"
        }).encode()
        req = urllib.request.Request(dc_url, data=dc_data,
              headers={"Content-Type": "application/x-www-form-urlencoded"})
        with urllib.request.urlopen(req, timeout=30, context=_SSL) as r:
            dc = _j.loads(r.read().decode())

        print("")
        print("  ┌─────────────────────────────────────────────────────┐")
        print(f"  │  Open browser: {dc['verification_uri']:<37}│")
        print(f"  │  Enter code  : {dc['user_code']:<37}│")
        print("  └─────────────────────────────────────────────────────┘")
        print("  Waiting for you to sign in...")
        import webbrowser as _wb
        _wb.open(dc["verification_uri"])

        # Step 2: Poll until user completes login
        token_url   = f"https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/token"
        interval    = int(dc.get("interval", 5))
        expires_in  = int(dc.get("expires_in", 900))
        elapsed     = 0
        while elapsed < expires_in:
            _t.sleep(interval); elapsed += interval
            poll_data = urllib.parse.urlencode({
                "grant_type":  "urn:ietf:params:oauth:grant-type:device_code",
                "client_id":   CLIENT_ID,
                "device_code": dc["device_code"]
            }).encode()
            poll_req = urllib.request.Request(token_url, data=poll_data,
                       headers={"Content-Type": "application/x-www-form-urlencoded"})
            try:
                with urllib.request.urlopen(poll_req, timeout=30, context=_SSL) as r:
                    resp = _j.loads(r.read().decode())
                if "access_token" in resp:
                    print("  ✅ Login successful.")
                    return resp["access_token"]
            except urllib.error.HTTPError as e:
                err = _j.loads(e.read().decode()).get("error","")
                if err == "authorization_pending": continue
                if err == "slow_down": interval += 5; continue
                raise
        raise Exception("Device code login timed out. Please restart and try again.")

    else:
        # ── Client Credentials Flow (App Registration) ────────
        url  = f"https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/token"
        data = urllib.parse.urlencode({
            "grant_type":    "client_credentials",
            "client_id":     CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "scope":         "https://graph.microsoft.com/.default"
        }).encode()
        req  = urllib.request.Request(url, data=data,
               headers={"Content-Type": "application/x-www-form-urlencoded"})
        with urllib.request.urlopen(req, timeout=30, context=_SSL) as r:
            data = _j.loads(r.read().decode("utf-8"))
        token = data["access_token"]
        try:
            parts   = token.split(".")
            payload = _j.loads(base64.b64decode(parts[1] + "=="))
            roles   = payload.get("roles", [])
            print(f"   Token acquired. Roles: {roles}")
        except Exception:
            print("   Token acquired.")
        return token

# ── GRAPH GET ALL (paginated) ────────────────────────────────
def graph_get_all(token, url):
    import urllib.request, json as _j, ssl
    _SSL = ssl.create_default_context()
    _SSL.check_hostname = False
    _SSL.verify_mode    = ssl.CERT_NONE
    headers = {"Authorization": f"Bearer {token}"}
    items, page = [], 0
    while url:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=90, context=_SSL) as r:
            page_data = _j.loads(r.read().decode("utf-8"))
        batch = page_data.get("value", [])
        items.extend(batch)
        page += 1
        print(f"      Page {page}: {len(batch)} packages, total: {len(items)}")
        url = page_data.get("@odata.nextLink")
    return items

# ── FETCH UPDATES REPORT ─────────────────────────────────────
def fetch_updates_report(token):
    """Fetch Enterprise App Catalog apps with updates.
    Confirmed endpoint: POST /beta/deviceManagement/reports/retrieveWin32CatalogAppsUpdateReport
    Response schema: SessionId, TotalRowCount, Schema:[{Column,PropertyType}], Values:[[...]]
    """
    import json as _j, urllib.request, ssl
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    _SSL = ssl.create_default_context()
    _SSL.check_hostname = False
    _SSL.verify_mode    = ssl.CERT_NONE

    url  = "https://graph.microsoft.com/beta/deviceManagement/reports/retrieveWin32CatalogAppsUpdateReport"
    body = _j.dumps({"top": 500, "skip": 0, "filter": "", "select": [], "orderBy": []}).encode()

    try:
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=60, context=_SSL) as r:
            result = _j.loads(r.read().decode("utf-8"))

        schema = result.get("Schema", [])
        values = result.get("Values", [])
        total  = result.get("TotalRowCount", 0)
        columns = [col.get("Column","") for col in schema]
        print(f"      Updates report: {total} total rows, {len(values)} returned")
        print(f"      Columns: {columns}")

        apps_out = []
        for row in values:
            app = dict(zip(columns, row))
            # Only include apps where an update is actually available
            update_available = app.get("UpdateAvailable", False)
            update_eligible  = app.get("UpdateEligible", False)
            latest_ver       = app.get("LatestAvailableVersion","")
            if not (update_available or update_eligible or latest_ver):
                continue
            apps_out.append({
                "appId":             app.get("ApplicationId",""),
                "appDisplayName":    app.get("ApplicationName",""),
                "publisher":         app.get("Publisher",""),
                "provisionedVersion":app.get("CurrentAppVersion",""),
                "latestVersion":     latest_ver,
                "updateAvailable":   bool(update_available),
                "updateEligible":    bool(update_eligible),
                "isSuperseded":      bool(app.get("IsSuperseded", False)),
                "currentRevisionId": app.get("CurrentRevisionId",""),
                "latestRevisionId":  app.get("LatestRevisionId",""),
            })
        print(f"      Updates with new version available: {len(apps_out)}")
        return apps_out

    except Exception as e:
        print(f"      Updates report error: {e}")
        return []


def fetch_catalog():
    global _state
    _state["loading"] = True
    _state["error"]   = None
    _state["progress"] = {"pct":2,"msg":"Acquiring Graph API token...","done":False}
    try:
        token = get_graph_token()
        _state["progress"]["pct"] = 15
        _state["progress"]["msg"] = "Token acquired. Fetching EAM catalog..."
        print("[2/3] Fetching EAM catalog packages...")
        raw = graph_get_all(token,
            "https://graph.microsoft.com/beta/deviceAppManagement/mobileAppCatalogPackages")
        total = len(raw)
        print(f"      {total} packages fetched.")
        if total == 0:
            raise RuntimeError("No packages returned. Check DeviceManagementApps.Read.All permission.")
        _state["progress"]["pct"] = 80
        _state["progress"]["msg"] = f"{total} packages fetched. Building catalog..."
        print("[3/3] Processing and sorting...")
        apps_out = []
        for a in raw:
            apps_out.append({
                "id":                             a.get("id",""),
                "productId":                      a.get("productId",""),
                "productDisplayName":             a.get("productDisplayName",""),
                "publisherDisplayName":           a.get("publisherDisplayName",""),
                "versionDisplayName":             a.get("versionDisplayName",""),
                "branchName":                     a.get("branchName",""),
                "branchId":                       a.get("branchId",""),
                "applicableArchitectures":        a.get("applicableArchitectures",""),
                "packageAutoUpdateCapable":       bool(a.get("packageAutoUpdateCapable",False)),
                "minimumSupportedWindowsRelease": a.get("minimumSupportedWindowsRelease",""),
                "releaseDateTime":                a.get("releaseDateTime",""),
                "productDescription":             a.get("productDescription",""),
            })
        apps_out.sort(key=lambda x: (x["productDisplayName"] or "").lower())
        _state["apps"]     = apps_out
        _state["progress"] = {"pct":100,"msg":f"Done - {total} packages loaded.","done":True}
        print(f"      Complete. {total} packages ready.")

        def _fetch_intune():
            try:
                import time as _t
                _state["intune_loading"]  = True
                _state["intune_apps"]     = None
                _state["intune_error"]    = None
                _state["intune_progress"] = {"pct":5,"msg":"Acquiring Graph token...","done":False}
                _t.sleep(0.3)
                tok = get_graph_token()
                _state["intune_progress"] = {"pct":15,"msg":"Fetching all Intune apps from Graph...","done":False}
                _t.sleep(0.2)
                _state["intune_apps"]     = fetch_intune_eam_apps(tok, _state)
                _state["intune_error"]    = None
                _state["intune_progress"] = {"pct":100,"msg":f"Done - {len(_state['intune_apps'])} EAM apps loaded.","done":True}
                print(f"      Intune EAM: {len(_state['intune_apps'])} apps.")
                try:
                    _state["updates_loading"] = True
                    _state["updates_apps"]    = fetch_updates_report(tok)
                    _state["updates_error"]   = None
                except Exception as _ue:
                    _state["updates_error"] = str(_ue)
                    _state["updates_apps"]  = []
                finally:
                    _state["updates_loading"] = False
            except Exception as ex:
                import traceback
                traceback.print_exc()
                _state["intune_error"]    = str(ex)
                _state["intune_progress"] = {"pct":0,"msg":f"Error: {ex}","done":True}
            finally:
                _state["intune_loading"] = False
        threading.Thread(target=_fetch_intune, daemon=True).start()

    except Exception as e:
        _state["error"]    = str(e)
        _state["progress"] = {"pct":0,"msg":f"Error: {e}","done":True}
        print(f"ERROR: {e}")
    finally:
        _state["loading"] = False

# ── HTTP SERVER ─────────────────────────────────────────────
class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    def log_message(self, fmt, *args): pass

    def do_GET(self):
        p = urllib.parse.urlparse(self.path).path
        if p == "/":
            _html_body = DASHBOARD_HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(_html_body)))
            self.end_headers()
            self.wfile.write(_html_body)
        elif p == "/api/data":
            try:
                if _state["error"]:
                    body = json.dumps({"error": _state["error"]}).encode()
                else:
                    body = json.dumps({"apps": _state["apps"], "total": len(_state["apps"])}).encode()
            except Exception as _e:
                body = json.dumps({"error": str(_e)}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif p == "/api/progress":
            body = json.dumps(_state["progress"]).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif p == "/api/intune":
            try:
                if _state["intune_apps"] is not None:
                    body = json.dumps({"apps": _state["intune_apps"]}).encode()
                elif _state["intune_error"]:
                    body = json.dumps({"apps": [], "error": _state["intune_error"]}).encode()
                else:
                    body = json.dumps({"apps": [], "loading": True}).encode()
            except Exception as _je:
                body = json.dumps({"apps": [], "error": str(_je)}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif p == "/api/intune/progress":
            body = json.dumps(_state["intune_progress"]).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif p == "/api/updates":
            try:
                if _state["updates_apps"] is not None:
                    body = json.dumps({"apps": _state["updates_apps"]}).encode()
                elif _state["updates_error"]:
                    body = json.dumps({"apps": [], "error": _state["updates_error"]}).encode()
                else:
                    body = json.dumps({"apps": [], "loading": True}).encode()
            except Exception as _e:
                body = json.dumps({"apps": [], "error": str(_e)}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        p = urllib.parse.urlparse(self.path).path
        if p == "/api/refresh":
            if not _state["loading"]:
                threading.Thread(target=fetch_catalog, daemon=True).start()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", "20")
            self.end_headers()
            self.wfile.write(b'{"status":"started"}')
        elif p == "/api/intune/refresh":
            _state["intune_loading"]  = True
            _state["intune_apps"]     = None
            _state["intune_error"]    = None
            _state["intune_progress"] = {"pct": 2, "msg": "Starting refresh...", "done": False}
            _state["updates_apps"]    = None
            _state["updates_loading"] = False
            _state["updates_error"]   = None
            def _ref():
                try:
                    import time as _t
                    _state["intune_progress"] = {"pct": 2, "msg": "Acquiring Graph token...", "done": False}
                    _t.sleep(0.5)
                    tok = get_graph_token()
                    _state["intune_progress"] = {"pct": 15, "msg": "Fetching all Intune apps from Graph...", "done": False}
                    _t.sleep(0.3)
                    _state["intune_apps"]     = fetch_intune_eam_apps(tok, _state)
                    _state["intune_error"]    = None
                    _state["intune_progress"] = {"pct": 100, "msg": f"Done - {len(_state['intune_apps'])} apps loaded.", "done": True}
                    print(f"      Intune EAM: {len(_state['intune_apps'])} apps.")
                    try:
                        _state["updates_loading"] = True
                        _state["updates_apps"]    = fetch_updates_report(tok)
                        _state["updates_error"]   = None
                    except Exception as _ue:
                        _state["updates_error"] = str(_ue)
                        _state["updates_apps"]  = []
                    finally:
                        _state["updates_loading"] = False
                except Exception as ex:
                    import traceback
                    traceback.print_exc()
                    _state["intune_error"]    = str(ex)
                    _state["intune_progress"] = {"pct": 0, "msg": f"Error: {ex}", "done": True}
                finally:
                    _state["intune_loading"] = False
            threading.Thread(target=_ref, daemon=True).start()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", "28")
            self.end_headers()
            self.wfile.write(b'{"status":"refresh started"}')
        else:
            self.send_response(404)
            self.end_headers()

DASHBOARD_HTML = '<!DOCTYPE html>\n<html lang="en">\n<head>\n<meta charset="UTF-8">\n<meta name="viewport" content="width=device-width,initial-scale=1.0">\n<title>IntunEAM Live — Enterprise App Catalog</title>\n<style>\n:root{\n  --bg:#F5F7FA;--surface:#FFFFFF;--surface2:#F0FDFA;--surface3:#CCFBF1;\n  --border:#99F6E4;--text:#0A1628;--muted:#6B7A99;\n  --accent:#0D9488;--accent2:#0F766E;\n  --orange:#0D9488;--orange2:#0F766E;\n  --navy:#0F4C4C;\n  --green:#34C77B;--green-bg:#0F2D1E;\n  --red:#F26464;--red-bg:#2D0F0F;\n  --amber:#F5A623;--amber-bg:#2D1F0F;\n  --purple:#A78BFA;--purple-bg:#1A1230;\n  --teal:#2DD4BF;--teal-bg:#0F2020;\n  --radius:10px;--mono:\'Consolas\',\'Courier New\',monospace;\n}\n[data-theme="dark"]{\n  --bg:#07111F;--surface:#0D1E36;--surface2:#112645;--surface3:#162E54;\n  --border:#1B3666;--text:#EEF2FF;--muted:#7A9CC5;\n  --accent:#0D9488;--accent2:#0F766E;\n  --orange:#0D9488;--orange2:#0F766E;\n  --green:#34C77B;--green-bg:#0A2818;--red:#F26464;--red-bg:#2D0A0A;\n  --amber:#F5A623;--amber-bg:#2D1F0F;--purple:#A78BFA;--purple-bg:#140E2A;\n  --teal:#2DD4BF;--teal-bg:#0A1E1C;\n}\n*{box-sizing:border-box;margin:0;padding:0;}\nbody{font-family:\'Segoe UI\',system-ui,sans-serif;background:var(--bg);color:var(--text);min-height:100vh;}\n\n/* TOPBAR */\n.topbar{background:var(--orange);border-bottom:3px solid var(--orange2);padding:0 24px;height:54px;\n  display:flex;align-items:center;justify-content:space-between;position:sticky;top:0;z-index:100;box-sizing:border-box;}\n.tb-left{display:flex;align-items:center;gap:12px;}\n.tb-icon{width:32px;height:32px;background:var(--orange);border-radius:8px;display:flex;align-items:center;justify-content:center;font-size:17px;}\n.tb-title{font-size:15px;font-weight:700;color:#fff;text-shadow:0 1px 2px rgba(0,0,0,.15);}\n.tb-sub{font-size:11px;color:rgba(255,255,255,.85);}\n.tb-right{display:flex;align-items:center;gap:10px;}\n.live-badge{background:var(--green);color:#fff;font-size:9px;font-weight:700;padding:2px 6px;border-radius:4px;vertical-align:middle;margin-left:6px;}\n.btn-refresh{background:#fff;color:var(--orange);border:none;border-radius:8px;padding:6px 16px;font-size:12px;font-weight:600;cursor:pointer;}\n.btn-refresh:hover{background:rgba(255,255,255,.9);color:var(--orange2);}\n.btn-refresh:disabled{opacity:.5;cursor:not-allowed;}\n.theme-btn{background:rgba(255,255,255,.25);border:1px solid rgba(255,255,255,.6);border-radius:20px;padding:5px 12px;font-size:12px;font-weight:600;cursor:pointer;color:#fff;display:flex;align-items:center;gap:5px;}\n.refresh-ts{font-size:10px;color:rgba(255,255,255,.85);}\n\n/* MAIN */\n.main{max-width:1400px;margin:0 auto;padding:20px;}\n\n/* PROGRESS */\n/* catalog progress now uses inline styles */\n.prog-track{background:rgba(255,255,255,.3);border-radius:2px;height:4px;overflow:hidden;margin-bottom:0;}\n.prog-fill{height:100%;background:rgba(0,0,0,0.35);border-radius:2px;transition:width .5s ease;}\n.prog-msg{display:block;font-size:11px;color:rgba(255,255,255,.9);margin-top:3px;white-space:nowrap;overflow:visible;}\n\n/* SKELETON */\n.skeleton{background:linear-gradient(90deg,var(--surface2) 25%,var(--surface3) 50%,var(--surface2) 75%);\n  border-radius:6px;}\n\n\n/* STATS */\n.stats-grid{display:grid;grid-template-columns:repeat(2,1fr);gap:12px;margin-bottom:22px;max-width:600px;}\n@media(max-width:800px){.stats-grid{grid-template-columns:repeat(2,1fr);}}\n.stat-card{background:var(--surface);border:1px solid var(--border);border-left:3px solid var(--orange);border-radius:var(--radius);padding:16px 18px;}\n.stat-label{font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.07em;color:var(--muted);margin-bottom:4px;}\n.stat-value{font-size:28px;font-weight:800;letter-spacing:-.02em;margin-bottom:3px;color:var(--orange);}\n.stat-sub{font-size:11px;color:var(--muted);min-height:16px;}\n\n\n\n/* SECTION HEADERS */\n.sec-hdr{display:flex;align-items:center;gap:10px;margin-bottom:14px;margin-top:24px;}\n.sec-hdr h2{font-size:14px;font-weight:700;color:var(--orange);}\n.sec-sub{font-size:11px;color:var(--muted);}\n.sec-line{flex:1;height:1px;background:var(--border);}\n\n/* FILTERS */\n.filters{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);\n  padding:14px 18px;margin-bottom:18px;display:flex;flex-wrap:wrap;gap:12px;align-items:center;}\n.fg{display:flex;flex-direction:column;gap:4px;}\n.fl{font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.06em;color:var(--muted);}\n.fsel{background:var(--surface2);border:1px solid var(--border);border-radius:7px;\n  padding:7px 12px;font-size:12.5px;color:var(--text);min-width:150px;}\n.fsel:focus{outline:none;border-color:var(--orange);}\n.fsearch{background:var(--surface2);border:1px solid var(--border);border-radius:7px;\n  padding:7px 12px;font-size:12.5px;color:var(--text);min-width:240px;}\n.fsearch::placeholder{color:var(--muted);}\n.fsearch:focus{outline:none;border-color:var(--orange);}\n.btn-reset{background:none;border:1px solid var(--border);border-radius:7px;\n  padding:7px 14px;font-size:12px;color:var(--muted);cursor:pointer;margin-left:auto;}\n.btn-reset:hover{border-color:var(--red);color:var(--red);}\n.rcount{font-size:12px;color:var(--muted);white-space:nowrap;}\n\n/* CHARTS */\n.chart-grid{display:grid;grid-template-columns:repeat(2,1fr);gap:16px;margin-bottom:22px;}\n.chart-card{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);padding:18px 20px;}\n.chart-title{font-size:13px;font-weight:700;margin-bottom:3px;}\n.chart-sub{font-size:11px;color:var(--muted);margin-bottom:14px;}\n.chart-sub strong{color:var(--orange);}\n.bar-chart{display:flex;flex-direction:column;gap:8px;}\n.bar-row{display:flex;align-items:center;gap:8px;cursor:pointer;}\n.bar-row:hover .bar-fill{opacity:.8;}\n.bar-label{font-size:11px;color:var(--muted);width:160px;flex-shrink:0;white-space:nowrap;overflow:visible;}\n.bar-track{flex:1;background:var(--surface2);border-radius:4px;height:20px;overflow:hidden;}\n.bar-fill{height:100%;border-radius:4px;display:flex;align-items:center;padding-left:8px;\n  font-size:10px;font-weight:700;color:#fff;min-width:28px;transition:width .4s ease;}\n.bar-count{font-size:11px;font-weight:700;width:40px;text-align:right;flex-shrink:0;}\n.sk-bar{height:20px;width:100%;}\n.donut-wrap{display:flex;align-items:center;gap:20px;flex-wrap:wrap;}\n.donut-legend{display:flex;flex-direction:column;gap:8px;}\n.legend-item{display:flex;align-items:center;gap:8px;font-size:11px;cursor:pointer;}\n.legend-dot{width:10px;height:10px;border-radius:50%;flex-shrink:0;}\n.legend-label{color:var(--muted);}\n.legend-val{font-weight:700;margin-left:8px;}\n\n/* TABLE */\n.table-section{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);margin-bottom:22px;}\n.table-toolbar{display:flex;align-items:center;justify-content:space-between;padding:14px 18px;border-bottom:1px solid var(--border);flex-wrap:wrap;gap:10px;}\n.tt-left h3{font-size:13px;font-weight:700;}\n.tt-left p{font-size:11px;color:var(--muted);margin-top:2px;}\n.tt-right{display:flex;gap:8px;align-items:center;}\n.btn-sm{background:var(--surface2);border:1px solid var(--border);border-radius:6px;padding:6px 12px;font-size:11px;font-weight:600;color:var(--muted);cursor:pointer;}\n.btn-sm:hover{border-color:var(--orange);color:var(--orange);}\n.active-tag{background:var(--orange);color:#fff;font-size:11px;font-weight:600;padding:3px 8px;border-radius:10px;}\n.view-toggle{display:flex;border:1px solid var(--border);border-radius:8px;overflow:hidden;}\n.vbtn{background:var(--surface);border:none;padding:7px 11px;cursor:pointer;font-size:13px;color:var(--muted);}\n.vbtn.active{background:var(--orange);color:#fff;}\ntable{width:100%;border-collapse:collapse;font-size:12px;}\nthead th{background:var(--orange);color:#fff;padding:10px 14px;text-align:left;\n  font-size:10px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;\n  white-space:nowrap;cursor:pointer;border-bottom:1px solid var(--orange2);}\nthead th:hover{background:var(--orange2);color:#fff;}\nthead th.sa::after{content:\' \\x15B2\';color:var(--orange);}\nthead th.sd::after{content:\' \\x15BC\';color:var(--orange);}\ntbody tr{border-bottom:1px solid #F5EDE8;transition:background .1s;cursor:pointer;}\ntbody tr:hover{background:#FFF5F0;}\ntd{padding:9px 14px;vertical-align:middle;}\ntd.app-name{font-weight:600;max-width:280px;}\ntd.ver{font-family:var(--mono);font-size:11px;color:var(--muted);}\ntd.pub{color:var(--muted);max-width:180px;}\n.badge{font-size:10px;font-weight:600;padding:3px 10px;border-radius:20px;display:inline-block;}\n.b-au{background:#E8F5E9;color:#2E7D32;border:1px solid #A5D6A7;}\n.b-nu{background:#3D2B1F;color:#fff;}\n.b-arch{background:#FDEBD0;color:#784212;border:1px solid #F5CBA7;}\n.hm{background:rgba(79,142,247,.25);border-radius:2px;padding:0 2px;}\n\n/* CARDS */\n.card-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:12px;}\n.app-card{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);\n  padding:15px 17px;cursor:pointer;transition:border-color .15s,transform .12s;}\n.app-card:hover{border-color:var(--orange);transform:translateY(-1px);}\n.ac-top{display:flex;align-items:flex-start;justify-content:space-between;gap:8px;margin-bottom:6px;}\n.ac-name{font-size:12.5px;font-weight:700;line-height:1.3;}\n.ac-pub{font-size:11px;color:var(--muted);margin-bottom:8px;}\n.ac-meta{display:flex;gap:5px;flex-wrap:wrap;}\n\n/* PAGINATION */\n.pgbar{display:flex;align-items:center;justify-content:space-between;padding:12px 16px;\n  background:var(--surface2);border-top:1px solid var(--border);flex-wrap:wrap;gap:8px;}\n.pginfo{font-size:11px;color:var(--muted);}\n.pgctrl{display:flex;gap:4px;}\n.pgbtn{background:none;border:1px solid var(--border);border-radius:6px;padding:4px 10px;\n  font-size:11px;cursor:pointer;color:var(--muted);}\n.pgbtn:hover:not(:disabled){border-color:var(--orange);color:var(--orange);}\n.pgbtn.active{background:var(--orange);color:#fff;border-color:var(--orange);}\n.pgbtn:disabled{opacity:.3;cursor:not-allowed;}\n\n/* MODAL */\n.mo-overlay{display:none;position:fixed;inset:0;background:rgba(0,0,0,.7);z-index:200;\n  backdrop-filter:blur(4px);align-items:center;justify-content:center;padding:20px;}\n.mo-overlay.open{display:flex;}\n.mo{background:var(--surface);border:1px solid var(--border);border-radius:14px;\n  max-width:620px;width:100%;max-height:85vh;overflow-y:auto;box-shadow:0 24px 60px rgba(0,0,0,.5);}\n.mo-hdr{padding:18px 22px 14px;border-bottom:1px solid var(--border);display:flex;\n  align-items:flex-start;justify-content:space-between;position:sticky;top:0;background:var(--surface);}\n.mo-title{font-size:16px;font-weight:800;margin-bottom:2px;}\n.mo-sub{font-size:12px;color:var(--muted);}\n.mo-close{background:var(--surface2);border:none;border-radius:7px;width:30px;height:30px;\n  cursor:pointer;font-size:17px;color:var(--muted);display:flex;align-items:center;justify-content:center;}\n.mo-body{padding:18px 22px;}\n.mo-sec{margin-bottom:16px;}\n.mo-sec h4{font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.08em;color:var(--muted);margin-bottom:8px;}\n.mo-grid{display:grid;grid-template-columns:1fr 1fr;gap:8px;}\n.mo-item{display:flex;flex-direction:column;gap:2px;}\n.mo-key{font-size:10px;color:var(--muted);}\n.mo-val{font-size:12px;font-weight:500;word-break:break-all;}\n.mo-id{font-family:var(--mono);font-size:10.5px;background:var(--surface2);border-radius:5px;\n  padding:3px 8px;cursor:pointer;color:var(--accent);}\n.mo-id:hover{background:var(--border);}\n.api-blk{background:var(--surface2);border-radius:8px;padding:10px 13px;\n  font-family:var(--mono);font-size:11px;line-height:1.8;color:var(--accent);word-break:break-all;}\n\n/* TOAST */\n.toast{display:none;position:fixed;bottom:22px;right:22px;background:var(--surface);\n  border:1px solid var(--border);border-radius:9px;padding:11px 18px;\n  font-size:12.5px;font-weight:600;color:var(--text);box-shadow:0 8px 24px rgba(0,0,0,.3);z-index:300;}\n.toast.show{display:block;}\n\n/* FOOTER */\n.footer{text-align:center;padding:16px;border-top:1px solid var(--border);margin-top:24px;font-size:11px;color:var(--muted);}\n::-webkit-scrollbar{width:5px;height:5px;}\n::-webkit-scrollbar-track{background:transparent;}\n::-webkit-scrollbar-thumb{background:var(--border);border-radius:8px;}\n\n/* ── Sidebar layout ── */\n.app-shell{display:flex;min-height:calc(100vh - 60px);overflow:hidden;}\n.sidebar{width:210px;min-width:210px;max-width:210px;background:var(--surface);padding:16px 0;flex-shrink:0;border-right:2px solid var(--border);}\n.main-content{flex:1;min-width:0;overflow-x:hidden;overflow-y:auto;padding:16px 20px;}\n.main-content>*{min-width:0;}\n.main-tabs{display:flex;flex-direction:column;gap:4px;padding:0 8px;border-bottom:none;margin-bottom:0;background:transparent;border-radius:0;overflow:visible;}\n.main-tab{padding:10px 14px;background:transparent;border:none;color:var(--text);font-size:13px;font-weight:500;cursor:pointer;width:100%;text-align:left;border-radius:8px;transition:all .15s;white-space:nowrap;overflow:visible;}\n.main-tab:hover{color:var(--orange);background:var(--surface2);}\n.main-tab.active{background:var(--orange);color:#fff;font-weight:700;border-radius:8px;}\n.tab-panel{display:none;}\n.tab-panel.active{display:block;}\n.intune-filters{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);padding:14px 18px;margin-bottom:18px;display:flex;flex-wrap:wrap;gap:12px;align-items:flex-end;}\n.intune-fg{display:flex;flex-direction:column;gap:4px;}\n.intune-fl{font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.06em;color:var(--muted);}\n.intune-sel{background:var(--surface2);border:1px solid var(--border);border-radius:7px;padding:7px 12px;font-size:12.5px;color:var(--text);min-width:150px;}\n.intune-sel:focus{outline:none;border-color:var(--orange);}\n.intune-search{background:var(--surface2);border:1px solid var(--border);border-radius:7px;padding:7px 12px;font-size:12.5px;color:var(--text);min-width:220px;}\n.intune-kpis{display:grid;grid-template-columns:repeat(2,1fr);gap:12px;margin-bottom:18px;max-width:560px;}\n.ikpi{background:var(--surface);border:1px solid var(--border);border-left:3px solid var(--orange);border-radius:var(--radius);padding:14px 16px;}\n.ikpi-label{font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.07em;color:var(--muted);margin-bottom:4px;}\n.ikpi-val{font-size:26px;font-weight:800;color:var(--orange);}\n.ikpi-sub{font-size:11px;color:var(--muted);margin-top:3px;}\n.ctx-sys{background:var(--purple-bg);color:var(--purple);font-size:10px;font-weight:600;padding:2px 8px;border-radius:12px;display:inline-block;}\n.ctx-usr{background:var(--teal-bg);color:var(--teal);font-size:10px;font-weight:600;padding:2px 8px;border-radius:12px;display:inline-block;}\n.ctx-na{background:var(--surface3);color:var(--muted);font-size:10px;font-weight:600;padding:2px 8px;border-radius:12px;display:inline-block;}\n.lc-bau{background:var(--green-bg);color:var(--green);font-size:10px;font-weight:600;padding:2px 8px;border-radius:12px;display:inline-block;}\n.lc-test{background:var(--amber-bg);color:var(--amber);font-size:10px;font-weight:600;padding:2px 8px;border-radius:12px;display:inline-block;}\n.lc-eol{background:var(--red-bg);color:var(--red);font-size:10px;font-weight:600;padding:2px 8px;border-radius:12px;display:inline-block;}\n.lc-ret{background:var(--surface3);color:var(--muted);font-size:10px;font-weight:600;padding:2px 8px;border-radius:12px;display:inline-block;border:1px solid var(--border);}\n.lc-proj{background:var(--purple-bg);color:var(--purple);font-size:10px;font-weight:600;padding:2px 8px;border-radius:12px;display:inline-block;}\n.b-com{background:var(--surface3);color:var(--muted);font-size:10px;font-weight:600;padding:2px 8px;border-radius:12px;display:inline-block;border:1px solid var(--border);}\n.b-bu{background:var(--orange2);color:#fff;font-size:10px;font-weight:600;padding:2px 8px;border-radius:12px;display:inline-block;}\n.b-asgn{background:var(--green-bg);color:var(--green);font-size:10px;font-weight:600;padding:2px 8px;border-radius:12px;display:inline-block;}\n.b-uasgn{background:var(--red-bg);color:var(--red);font-size:10px;font-weight:600;padding:2px 8px;border-radius:12px;display:inline-block;}\n.intune-loading{text-align:center;padding:40px;color:var(--muted);font-size:13px;}\n.intune-card-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:12px;padding:16px;}\n.intune-card{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);padding:15px 17px;cursor:default;transition:border-color .15s;}\n.intune-card:hover{border-color:var(--orange);}\n.ic-name{font-size:12.5px;font-weight:700;margin-bottom:4px;line-height:1.3;}\n.ic-pub{font-size:11px;color:var(--muted);margin-bottom:8px;}\n.ic-meta{display:flex;flex-wrap:wrap;gap:5px;}\n\n\n.intune-mo-overlay{display:none;position:fixed;inset:0;background:rgba(0,0,0,.6);z-index:500;align-items:center;justify-content:center;padding:16px;backdrop-filter:blur(4px);}\n.intune-mo-overlay.open{display:flex;}\n.intune-mo{background:var(--surface);border:1px solid var(--border);border-radius:12px;max-width:620px;width:100%;max-height:88vh;overflow-y:auto;box-shadow:0 24px 60px rgba(0,0,0,.4);}\n.intune-mo-hdr{padding:16px 20px 12px;border-bottom:1px solid var(--border);position:sticky;top:0;background:var(--surface);display:flex;align-items:flex-start;justify-content:space-between;}\n.intune-mo-title{font-size:15px;font-weight:700;margin-bottom:2px;}\n.intune-mo-sub{font-size:12px;color:var(--muted);}\n.intune-mo-close{background:none;border:1px solid var(--border);border-radius:6px;width:28px;height:28px;cursor:pointer;font-size:16px;color:var(--muted);display:flex;align-items:center;justify-content:center;flex-shrink:0;margin-left:12px;}\n.intune-mo-close:hover{color:var(--text);}\n.intune-mo-body{padding:16px 20px;}\n.imo-sec{margin-bottom:16px;}\n.imo-sec-title{font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.08em;color:var(--muted);margin-bottom:8px;padding-bottom:6px;border-bottom:1px solid var(--border);}\n.imo-grid{display:grid;grid-template-columns:1fr 1fr;gap:10px;}\n.imo-field{display:flex;flex-direction:column;gap:3px;}\n.imo-key{font-size:10px;color:var(--muted);}\n.imo-val{font-size:13px;font-weight:500;}\n.imo-grp-row{display:flex;align-items:center;justify-content:space-between;padding:6px 10px;background:var(--surface2);border-radius:6px;margin-bottom:5px;font-size:12px;}\n.imo-grp-name{font-weight:500;}\n.imo-grp-intent{font-size:10px;font-weight:600;padding:2px 7px;border-radius:10px;background:var(--green-bg);color:var(--green);}\n\n</style>\n</head>\n<body data-theme="light">\n<div class="topbar">\n  <div class="tb-left">\n    <div class="tb-icon">&#128187;</div>\n    <div>\n      <div class="tb-title">IntunEAM Live\n        <span class="live-badge">LIVE</span><span style="font-size:9px;background:#134E4A;color:#5EEAD4;padding:2px 6px;border-radius:4px;margin-left:4px;font-weight:800;letter-spacing:.04em;">v1</span></div>\n      <div class="tb-sub">Intune Enterprise App Management &nbsp;/&nbsp; Graph API Beta &nbsp;&middot;&nbsp; by Vigneshwaran</div>\n    </div>\n  </div>\n  <div class="tb-right">\n    <span class="refresh-ts" id="refreshTs">Loading...</span>\n    <button class="btn-refresh" id="refreshBtn" onclick="refreshData()">&#8635; Refresh</button>\n    <button class="theme-btn" onclick="toggleTheme()"><span id="themeIcon">&#9789;</span><span id="themeLabel">Dark</span></button>\n  </div>\n</div>\n<div class="main">\n<!-- TOP-LEVEL TABS -->\n<div class="app-shell">\n<nav class="sidebar">\n  <div style="padding:14px 16px 10px;color:var(--muted);font-size:10px;font-weight:700;letter-spacing:.1em;text-transform:uppercase;border-bottom:1px solid var(--border);margin-bottom:8px;">Menu</div>\n<div class="main-tabs">\n  <button class="main-tab active" id="tabCatalog" onclick="switchMainTab(\'catalog\')">&#128193; EAM Catalog Apps</button>\n  <button class="main-tab" id="tabLive" onclick="switchMainTab(\'live\')">&#127381; Live Apps</button>\n  <button class="main-tab" id="tabUpdates" onclick="switchMainTab(\'updates\')">&#128276; App Updates</button>\n</div>\n</nav>\n<div class="main-content">\n<div class="tab-panel active" id="panelCatalog">\n\n  <!-- PROGRESS -->\n  <div id="progressBar" style="display:none;background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);padding:16px 20px;margin-bottom:16px;">\n    <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px;">\n      <div style="font-size:13px;font-weight:600;color:var(--orange);">&#128257; Fetching EAM catalog from Microsoft Graph API...</div>\n      <div id="progPct" style="font-size:12px;font-weight:700;color:var(--orange);">0%</div>\n    </div>\n    <div style="background:var(--surface2);border-radius:4px;height:8px;overflow:hidden;">\n      <div id="progFill" style="height:100%;background:var(--orange);border-radius:4px;width:0%;transition:width .4s ease;"></div>\n    </div>\n    <div id="progMsg" style="font-size:11px;color:var(--muted);margin-top:6px;">Connecting to Graph API...</div>\n  </div>\n\n  <!-- STATS -->\n  <div class="stats-grid">\n    <div class="stat-card">\n      <div class="stat-label">Total Packages</div>\n      <div class="stat-value" id="stTotal"><span>...</span></div>\n      <div class="stat-sub" id="stTotalSub">EAM packages from Microsoft catalog</div>\n    </div>\n    <div class="stat-card">\n      <div class="stat-label">Publishers</div>\n      <div class="stat-value" id="stPub"><span>...</span></div>\n      <div class="stat-sub" id="stPubSub">Distinct publishers in catalog</div>\n    </div>\n  </div>\n\n  <!-- FILTERS -->\n  <div class="filters">\n    <div class="fg">\n      <div class="fl">Search</div>\n      <input class="fsearch" id="searchInput" type="text"\n        placeholder="Search by name, publisher, branch, version..." oninput="applyFilters()">\n    </div>\n    <div class="fg">\n      <div class="fl">Publisher</div>\n      <select class="fsel" id="pubFilter" onchange="applyFilters()">\n        <option value="">All Publishers</option>\n      </select>\n    </div>\n    <div class="fg">\n      <div class="fl">Architecture</div>\n      <select class="fsel" id="archFilter" onchange="applyFilters()">\n        <option value="">All Architectures</option>\n      </select>\n    </div>\n    <div class="fg">\n      <div class="fl">Auto-Update</div>\n      <select class="fsel" id="auFilter" onchange="applyFilters()">\n        <option value="">All</option>\n        <option value="yes">Auto-Update: Yes</option>\n        <option value="no">Auto-Update: No</option>\n      </select>\n    </div>\n    <div class="view-toggle" style="align-self:flex-end;">\n      <button class="vbtn active" id="btnT" onclick="setView(\'table\')" title="Table">&#9776;</button>\n      \n    </div>\n    <span class="rcount" id="rCount" style="align-self:flex-end;">Loading...</span>\n    <button class="btn-reset" onclick="resetFilters()" style="align-self:flex-end;">&#8635; Reset</button>\n  </div>\n\n<!-- TABLE -->\n  <div class="table-section" id="tableSection">\n    <div class="table-toolbar">\n      <div class="tt-left">\n        <h3 id="tableTitle">EAM Catalog Apps</h3>\n        <p id="tableSubTitle">All packages from Microsoft Intune Enterprise App Catalog</p>\n      </div>\n      <div class="tt-right">\n        <span class="active-tag" id="activeTag" style="display:none;"></span>\n        <button class="btn-sm" onclick="exportCSV()">&#8659; Export CSV</button>\n        <button class="btn-sm" onclick="clearFilter()">&#215; Clear Filter</button>\n      </div>\n    </div>\n    <div id="tableWrap" style="overflow-x:auto;">\n      <table>\n        <thead><tr>\n          <th onclick="sortTable(\'productDisplayName\',this)">Application Name</th>\n          <th onclick="sortTable(\'publisherDisplayName\',this)">Publisher</th>\n          <th onclick="sortTable(\'versionDisplayName\',this)">Version</th>\n          <th onclick="sortTable(\'branchName\',this)">Branch</th>\n          <th onclick="sortTable(\'applicableArchitectures\',this)">Architecture</th>\n          <th onclick="sortTable(\'packageAutoUpdateCapable\',this)">Auto-Update</th>\n        </tr></thead>\n        <tbody id="tableBody"></tbody>\n      </table>\n    </div>\n    <div id="cardGrid" class="card-grid" style="display:none;padding:16px;"></div>\n    <div class="pgbar">\n      <span class="pginfo" id="pginfo"></span>\n      <div class="pgctrl" id="pgctrl"></div>\n    </div>\n  </div>\n\n</div>\n\n<!-- MODAL -->\n<div class="mo-overlay" id="moOverlay">\n  <div class="mo">\n    <div class="mo-hdr">\n      <div><div class="mo-title" id="moTitle"></div><div class="mo-sub" id="moSub"></div></div>\n      <button class="mo-close" onclick="document.getElementById(\'moOverlay\').className=\'mo-overlay\';">&#215;</button>\n    </div>\n    <div class="mo-body" id="moBody"></div>\n  </div>\n</div>\n<div class="toast" id="toast"></div>\n<script>\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\nvar allApps=[], filtered=[], curPage=1, PAGE_SZ=10;\nvar sortCol=\'productDisplayName\', sortDir=\'asc\';\nvar curView=\'table\', activeTableFilter=null;\nvar dataLoaded=false;\n\n// ── THEME ───────────────────────────────────────────────────\nfunction toggleTheme(){\n  var d=document.body.getAttribute(\'data-theme\')===\'dark\';\n  document.body.setAttribute(\'data-theme\',d?\'light\':\'dark\');\n  document.getElementById(\'themeIcon\').textContent=d?\'\\u263D\':\'\\u2600\';\n  document.getElementById(\'themeLabel\').textContent=d?\'Light\':\'Dark\';\n  try{localStorage.setItem(\'eam_theme\',d?\'light\':\'dark\');}catch(e){}\n}\n(function(){\n  try{\n    var t=localStorage.getItem(\'eam_theme\');\n    if(t===\'dark\'){\n      document.body.setAttribute(\'data-theme\',\'dark\');\n      document.getElementById(\'themeIcon\').textContent=\'\\u2600\';\n      document.getElementById(\'themeLabel\').textContent=\'Light\';\n    }\n  }catch(e){}\n})();\n\n// ── SKELETON ────────────────────────────────────────────────\nfunction showSkeleton(){\n  // Clean loading state — no skeleton bars\n  [\'stTotal\',\'stPub\',\'stAuto\',\'stFiltered\'].forEach(function(id){\n    var el=document.getElementById(id);\n    if(el) el.textContent=\'...\';\n  });\n  [\'stTotalSub\',\'stPubSub\',\'stAutoSub\',\'stFilteredSub\'].forEach(function(id){\n    var el=document.getElementById(id);\n    if(el) el.textContent=\'Loading...\';\n  });\n  [\'pubChart\',\'archChart\',\'autoChart\',\'archDonut\'].forEach(function(id){\n    var el=document.getElementById(id);\n    if(el) el.innerHTML=\'<div style="color:var(--muted);font-size:12px;padding:20px 0;">Loading...</div>\';\n  });\n  var tb=document.getElementById(\'tableBody\');\n  if(tb) tb.innerHTML=\'<tr><td colspan="6" style="text-align:center;padding:40px;color:var(--muted);">Fetching data from Graph API...</td></tr>\';\n  document.getElementById(\'rCount\').textContent=\'Loading...\';\n}\n\n// ── PROGRESS ────────────────────────────────────────────────\nvar _progInterval=null;\nfunction showProg(msg,pct){\n  var pb=document.getElementById(\'progressBar\');\n  if(pb){ pb.style.display=\'block\'; pb.style.visibility=\'visible\'; }\n  var fill=document.getElementById(\'progFill\');\n  if(fill) fill.style.width=(pct||0)+\'%\';\n  var pctEl=document.getElementById(\'progPct\');\n  if(pctEl) pctEl.textContent=Math.round(pct||0)+\'%\';\n  var msgEl=document.getElementById(\'progMsg\');\n  if(msgEl) msgEl.textContent=msg;\n  var ts=document.getElementById(\'refreshTs\');\n  if(ts) ts.textContent=\'Connecting to Graph API...\';\n}\nfunction hideProg(){\n  var pb=document.getElementById(\'progressBar\');\n  if(pb){ pb.style.display=\'none\'; pb.style.visibility=\'hidden\'; }\n  // also clear any fill\n  var f=document.getElementById(\'progFill\'); if(f) f.style.width=\'0%\';\n}\n\nasync function pollProgress(){\n  try{\n    var r=await fetch(\'/api/progress\');\n    var d=await r.json();\n    var _fill=document.getElementById(\'progFill\');\n    if(_fill) _fill.style.width=(d.pct||0)+\'%\';\n    var _pct=document.getElementById(\'progPct\');\n    if(_pct) _pct.textContent=Math.round(d.pct||0)+\'%\';\n    var _msg=document.getElementById(\'progMsg\');\n    if(_msg) _msg.textContent=d.msg||\'\';\n    var _ts=document.getElementById(\'refreshTs\');\n    if(_ts) _ts.textContent=d.done?\'Fetched: \'+new Date().toLocaleTimeString():\'Fetching: \'+Math.round(d.pct||0)+\'%\';\n    if(d.done){\n      clearInterval(_progInterval); _progInterval=null;\n      var r2=await fetch(\'/api/data\');\n      var d2=await r2.json();\n      if(d2.error){ showToast(\'Error: \'+d2.error); hideProg(); return; }\n      loadData(d2);\n      hideProg();\n      document.getElementById(\'progressBar\').style.display=\'none\';\n      document.getElementById(\'refreshBtn\').disabled=false;\n      document.getElementById(\'refreshBtn\').textContent=\'\\u21BB Refresh\';\n      var _lts=document.getElementById(\'refreshTs\');\n      if(_lts) _lts.textContent=\'Updated: \'+new Date().toLocaleTimeString();\n      // Catalog loaded — hide catalog progress bar\n      document.getElementById(\'progressBar\').style.display=\'none\';\n      // Start intune fetch in background\n      _intuneLoaded=false;\n      _intuneApps=[];\n      if(_intuneProgInterval){ clearInterval(_intuneProgInterval); _intuneProgInterval=null; }\n      showIntuneProgress();\n      updateIntuneProgress(5,\'Catalog loaded — fetching live production apps...\');\n      _intuneProgInterval=setInterval(pollIntuneProgress,600);\n    }\n  }catch(e){}\n}\n\nasync function refreshData(){\n  var btn=document.getElementById(\'refreshBtn\');\n  btn.disabled=true; btn.textContent=\'Refreshing...\';\n  allApps=[]; dataLoaded=false;\n  showProg(\'Connecting to Graph API...\',2);\n  showSkeleton();\n  try{\n    await fetch(\'/api/refresh\',{method:\'POST\'});\n    // Poll immediately then on interval\n    pollProgress();\n    _progInterval=setInterval(pollProgress,600);\n  }catch(e){ showToast(\'Server error: \'+e.message); btn.disabled=false; btn.textContent=\'\\u21BB Refresh\'; }\n}\n\n// ── LOAD DATA ───────────────────────────────────────────────\nfunction loadData(data){\n  allApps  = data.apps || [];\n  dataLoaded = true;\n  buildFilters();\n  applyFilters();\n}\n\n// ── FILTERS ─────────────────────────────────────────────────\nfunction buildFilters(){\n  var pubs={}, archs={};\n  allApps.forEach(function(a){\n    if(a.publisherDisplayName) pubs[a.publisherDisplayName]=1;\n    if(a.applicableArchitectures){\n      a.applicableArchitectures.split(\',\').forEach(function(ar){ar=ar.trim();if(ar)archs[ar]=1;});\n    }\n  });\n  var ps=document.getElementById(\'pubFilter\');\n  ps.innerHTML=\'<option value="">All Publishers</option>\';\n  Object.keys(pubs).sort().forEach(function(p){\n    var o=document.createElement(\'option\');o.value=p;o.textContent=p;ps.appendChild(o);\n  });\n  var as=document.getElementById(\'archFilter\');\n  as.innerHTML=\'<option value="">All Architectures</option>\';\n  Object.keys(archs).sort().forEach(function(a){\n    var o=document.createElement(\'option\');o.value=a;o.textContent=a;as.appendChild(o);\n  });\n}\n\nfunction applyFilters(){\n  var q=(document.getElementById(\'searchInput\').value||\'\').toLowerCase().trim();\n  var pub=document.getElementById(\'pubFilter\').value||\'\';\n  var arch=document.getElementById(\'archFilter\').value||\'\';\n  var au=document.getElementById(\'auFilter\').value||\'\';\n\n  filtered=allApps.filter(function(a){\n    var mQ=!q||(a.productDisplayName||\'\').toLowerCase().indexOf(q)!==-1\n              ||(a.publisherDisplayName||\'\').toLowerCase().indexOf(q)!==-1\n              ||(a.branchName||\'\').toLowerCase().indexOf(q)!==-1\n              ||(a.versionDisplayName||\'\').toLowerCase().indexOf(q)!==-1;\n    var mP=!pub||(a.publisherDisplayName||\'\')=== pub;\n    var mA=!arch||(a.applicableArchitectures||\'\').indexOf(arch)!==-1;\n    var mU=!au||(au===\'yes\'&&a.packageAutoUpdateCapable)||(au===\'no\'&&!a.packageAutoUpdateCapable);\n    var mT=!activeTableFilter||checkTableFilter(a,activeTableFilter);\n    return mQ&&mP&&mA&&mU&&mT;\n  });\n\n  filtered.sort(function(a,b){\n    var va=(a[sortCol]||\'\').toString().toLowerCase();\n    var vb=(b[sortCol]||\'\').toString().toLowerCase();\n    if(va<vb)return sortDir===\'asc\'?-1:1;\n    if(va>vb)return sortDir===\'asc\'?1:-1;\n    return 0;\n  });\n\n  curPage=1;\n  if(dataLoaded){\n    renderStats();\n    renderCharts();\n    renderTable();\n  }\n}\n\nfunction checkTableFilter(a,f){\n  if(!f)return true;\n  if(f.type===\'publisher\')return (a.publisherDisplayName||\'\')===f.value;\n  if(f.type===\'arch\')return (a.applicableArchitectures||\'\').indexOf(f.value)!==-1;\n  if(f.type===\'au\')return f.value?a.packageAutoUpdateCapable:!a.packageAutoUpdateCapable;\n  return true;\n}\n\nfunction setTableFilter(type,value,label){\n  activeTableFilter={type:type,value:value};\n  var tag=document.getElementById(\'activeTag\');\n  tag.textContent=label; tag.style.display=\'\';\n  applyFilters();\n  document.getElementById(\'tableSection\').scrollIntoView({behavior:\'smooth\',block:\'start\'});\n}\n\nfunction clearFilter(){\n  activeTableFilter=null;\n  document.getElementById(\'activeTag\').style.display=\'none\';\n  applyFilters();\n}\n\nfunction resetFilters(){\n  document.getElementById(\'searchInput\').value=\'\';\n  document.getElementById(\'pubFilter\').value=\'\';\n  document.getElementById(\'archFilter\').value=\'\';\n  document.getElementById(\'auFilter\').value=\'\';\n  activeTableFilter=null;\n  document.getElementById(\'activeTag\').style.display=\'none\';\n  applyFilters();\n}\n\n// ── STATS ───────────────────────────────────────────────────\nfunction renderStats(){\n  var pubs={}, autoN=0;\n  allApps.forEach(function(a){\n    if(a.publisherDisplayName)pubs[a.publisherDisplayName]=1;\n    if(a.packageAutoUpdateCapable)autoN++;\n  });\n  var manualN = allApps.length - autoN;\n  setText(\'stTotal\',    allApps.length.toLocaleString());\n  setText(\'stPub\',      Object.keys(pubs).length.toLocaleString());\n  setText(\'stAuto\',     autoN.toLocaleString());\n  setText(\'stFiltered\', filtered.length.toLocaleString());\n  // Subtitles\n  var ts = document.getElementById(\'stTotalSub\');\n  if(ts) ts.textContent = \'EAM packages from Microsoft catalog\';\n  var ps = document.getElementById(\'stPubSub\');\n  if(ps) ps.textContent = \'Distinct publishers in catalog\';\n  var as = document.getElementById(\'stAutoSub\');\n  if(as) as.textContent = autoN+\' auto-update · \'+manualN+\' manual only\';\n  var fs = document.getElementById(\'stFilteredSub\');\n  if(fs) fs.textContent = \'Matching current filters\';\n  document.getElementById(\'rCount\').textContent=filtered.length+\' result\'+(filtered.length!==1?\'s\':\'\');\n}\nfunction setText(id,val){\n  var el=document.getElementById(id);\n  if(el)el.innerHTML=\'<span>\'+String(val)+\'</span>\';\n}\n\n// ── CHARTS ──────────────────────────────────────────────────\nvar COLOURS=[\'#4F8EF7\',\'#0D9488\',\'#34C77B\',\'#F5A623\',\'#A78BFA\',\'#2DD4BF\',\'#F472B6\',\'#60A5FA\',\'#FB923C\',\'#4ADE80\'];\n\nfunction renderCharts(){ /* charts removed in public version */ }\n\nfunction buildDonut(segs,total){\n  var size=120,cx=60,cy=60,r=46,sw=18,circ=2*Math.PI*r,offset=0;\n  var colours=[\'#34C77B\',\'#F26464\',\'#4F8EF7\',\'#2DD4BF\',\'#F5A623\'];\n  var paths=\'\';\n  segs.forEach(function(seg,i){\n    if(!seg.value)return;\n    var pct=seg.value/(total||1);\n    var dash=pct*circ,gap=circ-dash;\n    paths+=\'<circle cx="\'+cx+\'" cy="\'+cy+\'" r="\'+r+\'" fill="none" stroke="\'+(colours[i]||COLOURS[i])+\'"\'\n      +\' stroke-width="\'+sw+\'" stroke-dasharray="\'+dash+\' \'+gap+\'"\'\n      +\' stroke-dashoffset="\'+(-offset*circ)+\'" transform="rotate(-90 \'+cx+\' \'+cy+\')"\'\n      +\' style="cursor:pointer;" data-ftype="\'+seg.fType+\'" data-fval="\'+seg.fVal+\'"/>\';\n    offset+=pct;\n  });\n  paths+=\'<text x="\'+cx+\'" y="\'+(cy-4)+\'" text-anchor="middle" font-size="18" font-weight="800" fill="var(--text)">\'+total+\'</text>\';\n  paths+=\'<text x="\'+cx+\'" y="\'+(cy+12)+\'" text-anchor="middle" font-size="9" fill="var(--muted)">TOTAL</text>\';\n  var svg=\'<svg width="\'+size+\'" height="\'+size+\'" viewBox="0 0 \'+size+\' \'+size+\'">\'+paths+\'</svg>\';\n  var legend=\'<div class="donut-legend">\';\n  segs.forEach(function(seg,i){\n    var pct=Math.round(seg.value/(total||1)*100);\n    legend+=\'<div class="legend-item" data-ftype="\'+seg.fType+\'" data-fval="\'+seg.fVal+\'">\'\n      +\'<div class="legend-dot" style="background:\'+(colours[i]||COLOURS[i])+\';"></div>\'\n      +\'<span class="legend-label">\'+esc(seg.label)+\'</span>\'\n      +\'<span class="legend-val">\'+seg.value+\' (\'+pct+\'%)</span></div>\';\n  });\n  legend+=\'</div>\';\n  setTimeout(function(){\n    document.querySelectorAll(\'circle[data-ftype]\').forEach(function(el){\n      el.addEventListener(\'click\',function(){\n        var fv=el.dataset.fval;\n        if(fv===\'true\')fv=true;else if(fv===\'false\')fv=false;\n        setTableFilter(el.dataset.ftype,fv,(fv?\'Auto-Update\':\'Manual Only\'));\n      });\n    });\n    document.querySelectorAll(\'.legend-item[data-ftype]\').forEach(function(el){\n      el.addEventListener(\'click\',function(){\n        var fv=el.dataset.fval;\n        if(fv===\'true\')fv=true;else if(fv===\'false\')fv=false;\n        setTableFilter(el.dataset.ftype,fv,(fv?\'Auto-Update\':\'Manual Only\'));\n      });\n    });\n  },50);\n  return \'<div class="donut-wrap">\'+svg+legend+\'</div>\';\n}\n\n// ── TABLE ───────────────────────────────────────────────────\nfunction renderTable(){\n  var q=document.getElementById(\'searchInput\').value.trim();\n  var start=(curPage-1)*PAGE_SZ;\n  var items=filtered.slice(start,start+PAGE_SZ);\n  if(curView===\'table\') renderTableView(items,q);\n  else renderCardView(items,q);\n  renderPagination();\n}\n\nfunction renderTableView(items,q){\n  if(!items.length){\n    document.getElementById(\'tableBody\').innerHTML=\'<tr><td colspan="6" style="text-align:center;padding:30px;color:var(--muted);">No packages match current filters.</td></tr>\';\n    return;\n  }\n  var h=\'\';\n  items.forEach(function(a,i){\n    var idx=(curPage-1)*PAGE_SZ+i;\n    h+=\'<tr onclick="openModal(\\\'\'+esc(a.id)+\'\\\')">\'\n      +\'<td class="app-name">\'+hi(a.productDisplayName||\'\',q)+\'</td>\'\n      +\'<td class="pub">\'+hi(a.publisherDisplayName||\'\',q)+\'</td>\'\n      +\'<td class="ver">\'+hi(a.versionDisplayName||\'\',q)+\'</td>\'\n      +\'<td>\'+hi(a.branchName||\'\',q)+\'</td>\'\n      +\'<td><span class="badge b-arch">\'+esc(a.applicableArchitectures||\'\')+\'</span></td>\'\n      +\'<td>\'+(a.packageAutoUpdateCapable\n        ?\'<span class="badge b-au">Auto-Update</span>\'\n        :\'<span class="badge b-nu">Manual</span>\')+\'</td>\'\n      +\'</tr>\';\n  });\n  document.getElementById(\'tableBody\').innerHTML=h;\n}\n\nfunction renderCardView(items,q){\n  if(!items.length){\n    document.getElementById(\'tableBody\').innerHTML=\'\';\n    document.getElementById(\'cardGrid\').innerHTML=\'<div style="color:var(--muted);text-align:center;padding:40px;">No results.</div>\';\n    return;\n  }\n  var h=\'\';\n  items.forEach(function(a){\n    h+=\'<div class="app-card" onclick="openModal(\\\'\'+esc(a.id)+\'\\\')">\'\n      +\'<div class="ac-top"><div class="ac-name">\'+hi(a.productDisplayName||\'\',q)+\'</div></div>\'\n      +\'<div class="ac-pub">\'+hi(a.publisherDisplayName||\'\',q)+\'</div>\'\n      +\'<div class="ac-meta">\'\n      +(a.versionDisplayName?\'<span class="badge b-arch">v\'+esc(a.versionDisplayName)+\'</span>\':\'\')\n      +(a.applicableArchitectures?\'<span class="badge b-arch">\'+esc(a.applicableArchitectures)+\'</span>\':\'\')\n      +(a.packageAutoUpdateCapable?\'<span class="badge b-au">Auto-Update</span>\':\'<span class="badge b-nu">Manual</span>\')\n      +\'</div></div>\';\n  });\n  document.getElementById(\'cardGrid\').innerHTML=h;\n  document.getElementById(\'tableBody\').innerHTML=\'\';\n}\n\nfunction setView(v){\n  curView=v; curPage=1;\n  document.getElementById(\'btnT\').className=\'vbtn\'+(v===\'table\'?\' active\':\'\');\n  document.getElementById(\'btnC\').className=\'vbtn\'+(v===\'card\'?\' active\':\'\');\n  var tw=document.getElementById(\'tableWrap\');\n  var cg=document.getElementById(\'cardGrid\');\n  tw.style.display=v===\'table\'?\'\':\'none\';\n  cg.style.display=v===\'card\'?\'\':\'none\';\n  renderTable();\n}\n\nfunction sortTable(col,el){\n  if(sortCol===col)sortDir=sortDir===\'asc\'?\'desc\':\'asc\';\n  else{sortCol=col;sortDir=\'asc\';}\n  document.querySelectorAll(\'thead th\').forEach(function(th){th.className=\'\';});\n  el.className=sortDir===\'asc\'?\'sa\':\'sd\';\n  renderTable();\n}\n\n// ── PAGINATION ──────────────────────────────────────────────\nfunction renderPagination(){\n  var total=filtered.length,tp=Math.ceil(total/PAGE_SZ)||1;\n  var s=(curPage-1)*PAGE_SZ+1,e=Math.min(curPage*PAGE_SZ,total);\n  document.getElementById(\'pginfo\').textContent=total===0?\'No results\':\'Showing \'+s+\'\\u2013\'+e+\' of \'+total;\n  var ctrl=document.getElementById(\'pgctrl\'); ctrl.innerHTML=\'\';\n  function addBtn(lbl,pg,act,dis){\n    var b=document.createElement(\'button\');\n    b.className=\'pgbtn\'+(act?\' active\':\'\');b.disabled=dis;b.textContent=lbl;\n    b.onclick=function(){curPage=pg;renderTable();document.getElementById(\'tableSection\').scrollIntoView({behavior:\'smooth\',block:\'start\'});};\n    ctrl.appendChild(b);\n  }\n  addBtn(\'\\u2039\',curPage-1,false,curPage<=1);\n  pgRange(curPage,tp).forEach(function(p){\n    if(p===\'...\'){var s=document.createElement(\'span\');s.textContent=\'...\';s.style.cssText=\'padding:0 4px;color:var(--muted);font-size:11px;\';ctrl.appendChild(s);}\n    else addBtn(p,p,p===curPage,false);\n  });\n  addBtn(\'\\u203A\',curPage+1,false,curPage>=tp);\n}\nfunction pgRange(c,t){\n  if(t<=7){var r=[];for(var i=1;i<=t;i++)r.push(i);return r;}\n  var p=[1];if(c>3)p.push(\'...\');\n  for(var i=Math.max(2,c-1);i<=Math.min(t-1,c+1);i++)p.push(i);\n  if(c<t-2)p.push(\'...\');p.push(t);return p;\n}\n\n// ── MODAL ───────────────────────────────────────────────────\nfunction openModal(id){\n  var a=allApps.filter(function(x){return x.id===id;})[0];if(!a)return;\n  document.getElementById(\'moTitle\').textContent=a.productDisplayName||\'Unknown\';\n  document.getElementById(\'moSub\').textContent=a.publisherDisplayName||\'\';\n  var h=\'<div class="mo-sec"><h4>Package Details</h4><div class="mo-grid">\';\n  [[\'Product Name\',a.productDisplayName],[\'Publisher\',a.publisherDisplayName],\n   [\'Version\',a.versionDisplayName],[\'Branch\',a.branchName],\n   [\'Architecture\',a.applicableArchitectures],\n   [\'Auto-Update\',a.packageAutoUpdateCapable?\'Yes - Supported\':\'No - Manual\'],\n   [\'Min Windows\',a.minimumSupportedWindowsRelease],[\'Release Date\',(a.releaseDateTime||\'\').slice(0,10)]\n  ].forEach(function(p){\n    h+=\'<div class="mo-item"><div class="mo-key">\'+esc(p[0])+\'</div><div class="mo-val">\'+esc(String(p[1]||\'\\u2014\'))+\'</div></div>\';\n  });\n  h+=\'</div></div>\';\n  if(a.productDescription){\n    h+=\'<div class="mo-sec"><h4>Description</h4><p style="font-size:12.5px;line-height:1.6;color:var(--muted);">\'+esc(a.productDescription)+\'</p></div>\';\n  }\n  h+=\'<div class="mo-sec"><h4>Identifiers \\u2014 click to copy</h4><div class="mo-grid">\';\n  [[\'Package ID\',a.id],[\'Product ID\',a.productId],[\'Branch ID\',a.branchId]].forEach(function(p){\n    if(!p[1])return;\n    h+=\'<div class="mo-item"><div class="mo-key">\'+esc(p[0])+\'</div>\'\n      +\'<div class="mo-id" onclick="copyVal(\\\'\'+esc(p[1])+\'\\\',this)">\'+esc(p[1])+\'</div></div>\';\n  });\n  h+=\'</div></div>\';\n  h+=\'<div class="mo-sec"><h4>Graph API Reference</h4>\'\n    +\'<div class="api-blk">GET https://graph.microsoft.com/beta/<br>\'\n    +\'deviceAppManagement/mobileAppCatalogPackages<br>\'\n    +\'?$filter=productId eq \\\'\'+esc(a.productId||\'\')+\'\\\'</div></div>\';\n  document.getElementById(\'moBody\').innerHTML=h;\n  document.getElementById(\'moOverlay\').className=\'mo-overlay open\';\n}\n\n// ── CSV EXPORT ──────────────────────────────────────────────\nfunction exportCSV(){\n  if(!filtered.length){showToast(\'No data to export.\');return;}\n  var hdr=[\'Application Name\',\'Publisher\',\'Version\',\'Branch\',\'Architecture\',\n           \'Auto-Update\',\'Min Windows\',\'Release Date\',\'Package ID\',\'Product ID\',\'Branch ID\',\'Description\'];\n  var rows=[hdr.join(\',\')];\n  filtered.forEach(function(a){\n    rows.push([cc(a.productDisplayName),cc(a.publisherDisplayName),cc(a.versionDisplayName),\n      cc(a.branchName),cc(a.applicableArchitectures),a.packageAutoUpdateCapable?\'Yes\':\'No\',\n      cc(a.minimumSupportedWindowsRelease),cc(a.releaseDateTime),\n      cc(a.id),cc(a.productId),cc(a.branchId),cc(a.productDescription)].join(\',\'));\n  });\n  var blob=new Blob([rows.join(\'\\r\\n\')],{type:\'text/csv\'});\n  var anc=document.createElement(\'a\');\n  anc.href=URL.createObjectURL(blob);\n  anc.download=\'EAM-Catalog-\'+new Date().toISOString().slice(0,10)+\'.csv\';\n  anc.click();\n  showToast(\'Exported \'+filtered.length+\' packages\');\n}\n\n// ── UTILS ───────────────────────────────────────────────────\nfunction esc(s){return String(s||\'\').replace(/&/g,\'&amp;\').replace(/</g,\'&lt;\').replace(/>/g,\'&gt;\').replace(/"/g,\'&quot;\');}\nfunction cc(v){var s=String(v||\'\');return(s.indexOf(\',\')!==-1||s.indexOf(\'"\')!==-1||s.indexOf(\'\\\n\')!==-1)?\'"\'+s.replace(/"/g,\'""\')+\'"\':s;}\nfunction hi(text,q){\n  if(!q||!text)return esc(text||\'\');\n  var e=esc(text),qe=q.replace(/[.*+?^${}()|[\\]\\\\]/g,\'\\\\$&\');\n  return e.replace(new RegExp(\'(\'+qe+\')\',\'gi\'),\'<span class="hm">$1</span>\');\n}\nfunction showToast(msg){var t=document.getElementById(\'toast\');t.textContent=msg;t.className=\'toast show\';setTimeout(function(){t.className=\'toast\';},3000);}\nfunction copyVal(text,el){\n  navigator.clipboard.writeText(text).then(function(){\n    var o=el.style.background;el.style.background=\'var(--green-bg)\';\n    setTimeout(function(){el.style.background=o;},800);\n  });\n}\n\n// ── EVENT DELEGATION ────────────────────────────────────────\ndocument.addEventListener(\'click\',function(e){\n  var mo=document.getElementById(\'moOverlay\');\n  if(e.target===mo) mo.className=\'mo-overlay\';\n  // Intune card click — data-appid delegation\n  var card=e.target.closest ? e.target.closest(\'[data-appid]\') : null;\n  if(card){\n    var appId=card.getAttribute(\'data-appid\');\n    if(appId) openIntuneModal(appId);\n  }\n});\n\n// ── INTUNE APP DETAIL MODAL ────────────────────────────────\nfunction openIntuneModal(appId){\n  var a=null;\n  for(var i=0;i<_intuneApps.length;i++){if(_intuneApps[i].id===appId){a=_intuneApps[i];break;}}\n  if(!a){for(var i=0;i<_intuneFiltered.length;i++){if(_intuneFiltered[i].id===appId){a=_intuneFiltered[i];break;}}}\n  if(!a) return;\n  document.getElementById(\'imoTitle\').textContent=a.displayName||\'\';\n  document.getElementById(\'imoSub\').textContent=(a.publisher||\'\')+\' · \'+esc(a.category||\'\')+(a.bu&&a.bu!==\'Common\'?\' · \'+a.bu:\'\');\n  var h=\'\';\n\n  // Details\n  h+=\'<div class="imo-sec"><div class="imo-sec-title">App Details</div>\';\n  h+=\'<div class="imo-grid">\';\n  h+=imof(\'Business Unit\',      a.bu||\'Common\');\n  h+=imof(\'Category\',           a.category||\'\');\n  h+=imof(\'Install Context\',    a.installContext||\'Unknown\');\n  h+=imof(\'Device Restart\',     a.deviceRestartBehavior||\'—\');\n  h+=imof(\'Publishing State\',   a.publishingState||\'—\');\n  h+=imof(\'Created\',            (a.createdDateTime||\'\').slice(0,10)||\'—\');\n  h+=imof(\'Last Modified\',      (a.lastModifiedDateTime||\'\').slice(0,10)||\'—\');\n  h+=\'</div></div>\';\n\n  // Auto-update & Supersedence\n  h+=\'<div class="imo-sec"><div class="imo-sec-title">Update & Supersedence</div>\';\n  h+=\'<div class="imo-grid">\';\n  // updateMethod from Graph = actual Intune setting (reliable)\n  // packageAutoUpdateCapable = catalog metadata flag (often stale)\n  var isAutoUpdate = (a.updateMethod||\'\').indexOf(\'automatic\')!==-1 || (a.updateMethod||\'\').indexOf(\'autoUpdate\')!==-1;\n  var auVal = isAutoUpdate ? \'✅ Automatically Update\' : \'❌ Manual update only\';\n  h+=imof(\'Update Method\', auVal);\n  // Build supersedence name lists from relationships array\n  var rels=a.relationships||[];\n  var superseding=rels.filter(function(r){return (r.relationshipType||\'\').toLowerCase().indexOf(\'supersedence\')!==-1&&(r.relationshipType||\'\').toLowerCase().indexOf(\'child\')===-1;});\n  var supersededBy=rels.filter(function(r){return (r.relationshipType||\'\').toLowerCase().indexOf(\'supersedence\')!==-1&&(r.relationshipType||\'\').toLowerCase().indexOf(\'child\')!==-1;});\n  var deps=rels.filter(function(r){return (r.relationshipType||\'\').toLowerCase().indexOf(\'depend\')!==-1;});\n  function relNames(arr,count){\n    if(arr.length>0) return arr.map(function(r){return esc(r.targetDisplayName||r.targetId||\'Unknown\');}).join(\', \');\n    return count>0 ? \'(\'+count+\' app\'+(count!==1?\'s\':\'\')+\' — details not loaded)\' : \'—\';\n  }\n  h+=imof(\'Superseding Apps\', relNames(superseding, a.supersedingAppCount||0));\n  h+=imof(\'Superseded By\',    relNames(supersededBy, a.supersededAppCount||0));\n  h+=imof(\'Dependencies\',     relNames(deps, a.dependentAppCount||0));\n  h+=\'</div></div>\';\n\n  // Assignments\n  h+=\'<div class="imo-sec"><div class="imo-sec-title">Assignments</div>\';\n  var asgns=a.assignments||[];\n  if(a.isAssigned && asgns.length===0){\n    h+=\'<div style="background:var(--amber-bg);border:1px solid var(--amber);border-radius:8px;padding:10px 14px;">\';\n    h+=\'<div style="font-size:12px;font-weight:700;color:var(--amber);">&#9888; Assignment Status Mismatch</div>\';\n    h+=\'<div style="font-size:11px;color:var(--muted);margin-top:4px;">Intune shows this app as Assigned but no groups are returned. This is a known Microsoft Graph API sync delay.</div>\';\n    h+=\'</div>\';\n  } else if(asgns.length===0){\n    h+=\'<div style="color:var(--red);font-size:12px;">No assignments</div>\';\n  } else {\n    asgns.forEach(function(g){\n      h+=\'<div class="imo-grp-row">\';\n      h+=\'<span class="imo-grp-name">\'+esc(g.groupName||g.groupId||\'\')+\'</span>\';\n      h+=\'<span class="imo-grp-intent">\'+esc(g.intent||\'available\')+\'</span>\';\n      h+=\'</div>\';\n    });\n  }\n  h+=\'</div>\';\n\n  document.getElementById(\'imoBody\').innerHTML=h;\n  document.getElementById(\'intuneModal\').className=\'intune-mo-overlay open\';\n}\n\nfunction imof(k,v){\n  return \'<div class="imo-field"><div class="imo-key">\'+esc(k)+\'</div><div class="imo-val">\'+esc(v)+\'</div></div>\';\n}\n\nfunction closeIntuneModal(){\n  document.getElementById(\'intuneModal\').className=\'intune-mo-overlay\';\n}\n\n\n// ── EAM UPDATES TAB ────────────────────────────────────────────\nvar _updatesData = [];\n\nfunction renderUpdatesTab(){\n  var tbody = document.getElementById(\'updates-tbody\');\n  tbody.innerHTML=\'<tr><td colspan="6" style="text-align:center;padding:40px;color:var(--muted);">&#128257; Fetching update report from Intune Monitor...</td></tr>\';\n  document.getElementById(\'updates-sub\').textContent=\'Checking Intune Monitor report...\';\n  fetch(\'/api/updates\').then(function(r){return r.json();}).then(function(d){\n    if(d.error){\n      tbody.innerHTML=\'<tr><td colspan="6" style="text-align:center;padding:40px;color:var(--red);">Error: \'+esc(d.error)+\'<br><small style="color:var(--muted);">The report API may require additional permissions (DeviceManagementManagedDevices.Read.All)</small></td></tr>\';\n      return;\n    }\n    if(d.loading){\n      tbody.innerHTML=\'<tr><td colspan="6" style="text-align:center;padding:40px;color:var(--muted);">&#128257; Fetching update data — please wait...</td></tr>\';\n      setTimeout(renderUpdatesTab, 2000);\n      return;\n    }\n    _updatesData = d.apps||[];\n    if(!_updatesData.length){\n      tbody.innerHTML=\'<tr><td colspan="6" style="text-align:center;padding:40px;color:var(--muted);">&#x2705; No pending updates — all EAM apps are on the latest version.</td></tr>\';\n      document.getElementById(\'updates-sub\').textContent=\'All EAM apps up to date\';\n      return;\n    }\n    var eligCount=_updatesData.filter(function(d){return d.updateEligible;}).length;\n    document.getElementById(\'updates-sub\').textContent=_updatesData.length+\' apps with update status · \'+eligCount+\' eligible to update now\';\n    var h=\'\';\n    _updatesData.forEach(function(d){\n      h+=\'<tr style="border-bottom:1px solid var(--border);cursor:default;">\';\n      h+=\'<td style="padding:9px 14px;font-weight:600;">\'+esc(d.appDisplayName)+\'</td>\';\n      h+=\'<td style="padding:9px 14px;color:var(--muted);font-size:11px;">\'+esc(d.publisher)+\'</td>\';\n      h+=\'<td style="padding:9px 14px;font-family:var(--mono);font-size:11px;color:var(--muted);">\'+esc(d.provisionedVersion||\'—\')+\'</td>\';\n      var hasUpdate = d.latestVersion && d.latestVersion !== d.provisionedVersion;\n      h+=\'<td style="padding:9px 14px;font-family:var(--mono);font-size:11px;\'+(hasUpdate?\'color:var(--gn);font-weight:600;\':\'color:var(--muted);\')+\'">\'+esc(d.latestVersion||\'—\')+\'</td>\';\n      h+=\'<td style="padding:9px 14px;">\'+(d.updateAvailable\n        ?\'<span style="background:var(--gnb);color:var(--gn);font-size:10px;font-weight:600;padding:2px 8px;border-radius:10px;">&#x2705; Yes</span>\'\n        :\'<span style="background:var(--sf3);color:var(--muted);font-size:10px;font-weight:600;padding:2px 8px;border-radius:10px;">No</span>\')+\'</td>\';\n      h+=\'<td style="padding:9px 14px;">\'+(d.updateEligible\n        ?\'<span style="background:var(--acg);color:var(--ac);font-size:10px;font-weight:600;padding:2px 8px;border-radius:10px;">&#x2713; Eligible</span>\'\n        :\'<span style="background:var(--sf3);color:var(--muted);font-size:10px;font-weight:600;padding:2px 8px;border-radius:10px;">Not eligible</span>\')+\'</td>\';\n      h+=\'<td style="padding:9px 14px;">\'+(d.isSuperseded\n        ?\'<span style="background:var(--amb);color:var(--am);font-size:10px;font-weight:600;padding:2px 8px;border-radius:10px;">&#x26A1; Superseded</span>\'\n        :\'<span style="color:var(--muted);font-size:11px;">—</span>\')+\'</td>\';\n      h+=\'</tr>\';\n    });\n    tbody.innerHTML=h;\n  }).catch(function(e){\n    tbody.innerHTML=\'<tr><td colspan="6" style="text-align:center;padding:40px;color:var(--muted);">Could not load update data. Start the server and try again.</td></tr>\';\n  });\n  // Cross-reference: compare deployed version with latest in catalog\n  _updatesData = [];\n  _intuneApps.forEach(function(app){\n    // Find matching catalog entry by name similarity\n    var appNameLower = (app.displayName||\'\').toLowerCase();\n    // Look for catalog entry\n    var catalogMatches = allApps.filter(function(ca){\n      var caName = (ca.productDisplayName||\'\').toLowerCase();\n      // Match by publisher + base name\n      return (ca.publisherDisplayName||\'\').toLowerCase() === (app.publisher||\'\').toLowerCase()\n          || caName.indexOf(appNameLower.split(\' \')[0])!==-1;\n    });\n    // Find if any catalog version > deployed version\n    var isAutoUpdate = (app.updateMethod||\'\').toLowerCase().indexOf(\'automatic\')!==-1;\n    _updatesData.push({\n      displayName:   app.displayName,\n      publisher:     app.publisher,\n      deployedVer:   \'—\',\n      latestVer:     catalogMatches.length ? catalogMatches[0].versionDisplayName : \'—\',\n      updateMethod:  isAutoUpdate ? \'Auto-update\' : \'Manual\',\n      isAutoUpdate:  isAutoUpdate,\n      hasUpdate:     false,\n    });\n  });\n\n  if(!_updatesData.length){\n    tbody.innerHTML=\'<tr><td colspan="6" style="text-align:center;padding:40px;color:var(--muted);">No update data available.</td></tr>\';\n    return;\n  }\n  document.getElementById(\'updates-sub\').textContent=\n    _updatesData.length+\' EAM apps · Data from Intune Monitor (may be delayed)\';\n\n  var h=\'\';\n  _updatesData.forEach(function(d){\n    h+=\'<tr style="border-bottom:1px solid var(--border);">\';\n    h+=\'<td style="padding:9px 14px;font-weight:600;">\'+esc(d.displayName)+\'</td>\';\n    h+=\'<td style="padding:9px 14px;color:var(--muted);font-size:11px;">\'+esc(d.publisher)+\'</td>\';\n    h+=\'<td style="padding:9px 14px;font-family:var(--mono);font-size:11px;color:var(--muted);">\'+esc(d.deployedVer)+\'</td>\';\n    h+=\'<td style="padding:9px 14px;font-family:var(--mono);font-size:11px;">\'+esc(d.latestVer)+\'</td>\';\n    h+=\'<td style="padding:9px 14px;">\'+(d.isAutoUpdate\n      ?\'<span class="lc-bau" style="color:#34C77B;">&#x2705; Auto-update</span>\'\n      :\'<span class="lc-ret">Manual</span>\'\n    )+\'</td>\';\n    h+=\'<td style="padding:9px 14px;"><span class="lc-test">Pending</span></td>\';\n    h+=\'</tr>\';\n  });\n  tbody.innerHTML=h;\n}\n\nfunction exportUpdatesCsv(){\n  if(!_updatesData.length){ return; }\n  var rows=[[\'App Name\',\'Publisher\',\'Deployed Version\',\'Latest Available\',\'Update Available\',\'Update Eligible\',\'Superseded\'].join(\',\')];\n  _updatesData.forEach(function(d){\n    rows.push([cc(d.appDisplayName),cc(d.publisher),cc(d.provisionedVersion),\n      cc(d.latestVersion),d.updateAvailable?\'Yes\':\'No\',d.updateEligible?\'Yes\':\'No\',d.isSuperseded?\'Yes\':\'No\'\n    ].join(\',\'));\n  });\n  var blob=new Blob([rows.join(\'\\r\\n\')],{type:\'text/csv\'});\n  var a=document.createElement(\'a\'); a.href=URL.createObjectURL(blob);\n  a.download=\'EAM-Updates-\'+new Date().toISOString().slice(0,10)+\'.csv\';\n  document.body.appendChild(a); a.click(); document.body.removeChild(a);\n}\n\ndocument.addEventListener(\'keydown\',function(e){\n  if(e.key===\'Escape\')document.getElementById(\'moOverlay\').className=\'mo-overlay\';\n});\n\n// ── AUTO LOAD ───────────────────────────────────────────────\nwindow.addEventListener(\'load\',function(){\n  showSkeleton();\n  showProg(\'Connecting to Graph API...\',2);\n  document.getElementById(\'refreshBtn\').disabled=true;\n  document.getElementById(\'refreshBtn\').textContent=\'Loading...\';\n  // Poll immediately once, then on interval\n  pollProgress();\n  _progInterval=setInterval(pollProgress,600);\n});\n\n\n\n\n\n\n// ── MAIN TAB SWITCHING ───────────────────────────────────────\nvar _intuneApps=[], _intuneFiltered=[];\nvar _intuneLoaded=false;\n\nfunction switchMainTab(tab){\n  document.getElementById(\'tabCatalog\').className=\'main-tab\'+(tab===\'catalog\'?\' active\':\'\');\n  document.getElementById(\'tabLive\').className=\'main-tab\'+(tab===\'live\'?\' active\':\'\');\n  document.getElementById(\'tabUpdates\').className=\'main-tab\'+(tab===\'updates\'?\' active\':\'\');\n  document.getElementById(\'panelCatalog\').className=\'tab-panel\'+(tab===\'catalog\'?\' active\':\'\');\n  document.getElementById(\'panelLive\').className=\'tab-panel\'+(tab===\'live\'?\' active\':\'\');\n  document.getElementById(\'panelUpdates\').className=\'tab-panel\'+(tab===\'updates\'?\' active\':\'\');\n  if(tab===\'updates\'){ renderUpdatesTab(); }\n  if(tab===\'live\'){\n    if(!_intuneLoaded){\n      // Check if intune data is already available\n      fetch(\'/api/intune\').then(function(r){return r.json();}).then(function(d){\n        if(d.apps && d.apps.length>0){\n          _intuneApps=d.apps; _intuneLoaded=true; applyIntuneFilters();\n          renderIntuneKpis();\n        } else {\n          // Still loading — show progress and poll\n          showIntuneProgress();\n          if(!_intuneProgInterval){\n            pollIntuneProgress();\n            _intuneProgInterval=setInterval(pollIntuneProgress,600);\n          }\n        }\n      }).catch(function(){\n        showIntuneProgress();\n        if(!_intuneProgInterval){\n          pollIntuneProgress();\n          _intuneProgInterval=setInterval(pollIntuneProgress,600);\n        }\n      });\n    }\n  }\n}\n\n// ── LIVE PRODUCTION APPS ─────────────────────────────────────\nvar _intuneProgInterval=null;\n\nfunction showIntuneProgress(){\n  document.getElementById(\'intuneProgBar\').style.display=\'block\';\n}\nfunction hideIntuneProgress(){\n  document.getElementById(\'intuneProgBar\').style.display=\'none\';\n}\nfunction updateIntuneProgress(pct,msg){\n  document.getElementById(\'intuneProgFill\').style.width=pct+\'%\';\n  document.getElementById(\'intuneProgPct\').textContent=Math.round(pct)+\'%\';\n  document.getElementById(\'intuneProgMsg\').textContent=msg;\n}\n\nvar _intuneBarShownAt=0;\nfunction pollIntuneProgress(){\n  fetch(\'/api/intune/progress\').then(function(r){ return r.json(); }).then(function(d){\n    updateIntuneProgress(d.pct||0, d.msg||\'Loading...\');\n    if(d.done){\n      clearInterval(_intuneProgInterval); _intuneProgInterval=null;\n      // Load data — retry up to 3 times with 1s gap\n      var _attempts=0;\n      function _loadIntune(){\n        _attempts++;\n        fetch(\'/api/intune\').then(function(r){ return r.json(); }).then(function(d2){\n          hideIntuneProgress();\n          if(d2.error){\n            document.getElementById(\'intune-tbody\').innerHTML=\'<tr><td colspan="6" class="intune-loading" style="color:var(--red);">Error: \'+esc(d2.error)+\'</td></tr>\';\n            return;\n          }\n          if(d2.loading || !d2.apps){\n            if(_attempts<5){ setTimeout(_loadIntune,1000); return; }\n            document.getElementById(\'intune-tbody\').innerHTML=\'<tr><td colspan="6" class="intune-loading">Waiting for data... <button onclick="refreshIntuneApps()" style="margin-left:8px;background:var(--orange);color:#fff;border:none;border-radius:4px;padding:4px 12px;cursor:pointer;">Refresh</button></td></tr>\';\n            return;\n          }\n          _intuneApps=d2.apps||[];\n          _intuneLoaded=true;\n          applyIntuneFilters();\n          renderIntuneKpis();\n        }).catch(function(err){\n          if(_attempts<5){ setTimeout(_loadIntune,1000); return; }\n          document.getElementById(\'intune-tbody\').innerHTML=\'<tr><td colspan="6" class="intune-loading" style="color:var(--red);">Could not load data. <button onclick="refreshIntuneApps()" style="margin-left:8px;background:var(--orange);color:#fff;border:none;border-radius:4px;padding:4px 12px;cursor:pointer;">&#8635; Retry</button></td></tr>\';\n        });\n      }\n      setTimeout(_loadIntune, 500);\n    }\n  }).catch(function(){});\n}\n\nfunction loadIntuneApps(){\n  showIntuneProgress();\n  updateIntuneProgress(2,\'Connecting to Graph API...\');\n  document.getElementById(\'intune-tbody\').innerHTML=\'<tr><td colspan="6" class="intune-loading">Fetching live EAM production apps from Intune...</td></tr>\';\n  if(_intuneProgInterval){ clearInterval(_intuneProgInterval); }\n  _intuneProgInterval=setInterval(pollIntuneProgress,800);\n}\n\nfunction refreshIntuneApps(){\n  _intuneLoaded=false;\n  _intuneApps=[];\n  // Clear any old interval first\n  if(_intuneProgInterval){ clearInterval(_intuneProgInterval); _intuneProgInterval=null; }\n  // Show progress bar and reset to 0 BEFORE the POST\n  showIntuneProgress();\n  updateIntuneProgress(0,\'Starting refresh...\');\n  document.getElementById(\'intune-tbody\').innerHTML=\'<tr><td colspan="6" class="intune-loading">Refreshing EAM apps from Intune...</td></tr>\';\n  fetch(\'/api/intune/refresh\',{method:\'POST\'}).then(function(r){ return r.json(); }).then(function(resp){\n    updateIntuneProgress(2,\'Acquiring Graph token...\');\n    // Poll immediately then every 600ms\n    pollIntuneProgress();\n    _intuneProgInterval=setInterval(pollIntuneProgress,600);\n  }).catch(function(e){\n    updateIntuneProgress(0,\'Refresh failed: \'+e.message);\n  });\n}\n\nfunction applyIntuneFilters(){\n  var bu=\'ALL\', cat=\'ALL\', lc=\'ALL\';\n  var asgn = document.getElementById(\'intuneasgnFilter\').value;\n  var ctx  = document.getElementById(\'intunectxFilter\').value;\n  var upd  = document.getElementById(\'intuneUpdateFilter\') ? document.getElementById(\'intuneUpdateFilter\').value : \'ALL\';\n  var q    = (document.getElementById(\'intuneSearch\').value||\'\').toLowerCase().trim();\n\n  _intuneFiltered = _intuneApps.filter(function(a){\n    var mBu   = bu===\'ALL\'  || a.bu===bu;\n    var mCat  = cat===\'ALL\' || a.category===cat;\n    var mLc   = lc===\'ALL\'  || a.lifecycle===lc;\n    var mAsgn = asgn===\'ALL\'||\n      (asgn===\'assigned\'&&(a.isAssigned||(a.assignments&&a.assignments.length>0)))||\n      (asgn===\'unassigned\'&&!a.isAssigned&&!(a.assignments&&a.assignments.length>0));\n    var mCtx  = ctx===\'ALL\' || (a.installContext||\'unknown\')===ctx;\n    var _isAutoUpd=(a.updateMethod||\'\').toLowerCase().indexOf(\'automatic\')!==-1;\n    var mUpd  = upd===\'ALL\' || (upd===\'auto\'&&_isAutoUpd) || (upd===\'manual\'&&!_isAutoUpd);\n    var mQ    = !q || (a.displayName||\'\').toLowerCase().indexOf(q)!==-1\n                   || (a.publisher||\'\').toLowerCase().indexOf(q)!==-1;\n    return mBu&&mCat&&mLc&&mAsgn&&mCtx&&mUpd&&mQ;\n  });\n\n  renderIntuneKpis();\n  renderIntuneTable();\n}\n\nfunction resetIntuneFilters(){\n  [\'intuneasgnFilter\',\'intunectxFilter\',\'intuneUpdateFilter\'].forEach(function(id){\n    var el=document.getElementById(id); if(el) el.value=\'ALL\';\n  });\n  document.getElementById(\'intuneSearch\').value=\'\';\n  applyIntuneFilters();\n}\n\nfunction renderIntuneKpis(){\n  var t=_intuneApps.length;\n  var a=_intuneApps.filter(function(x){ return x.isAssigned||(x.assignments&&x.assignments.length>0); }).length;\n  var u=t-a;\n  function _set(id,val){ var el=document.getElementById(id); if(el) el.textContent=val; }\n  _set(\'ikTotal\',     t.toLocaleString());\n  _set(\'ikAssigned\',  a.toLocaleString());\n  _set(\'ikUnassigned\',u.toLocaleString());\n  _set(\'ikCommon\',    _intuneApps.filter(function(x){return x.category===\'Common\';}).length.toLocaleString());\n  _set(\'ikCustom\',    _intuneApps.filter(function(x){return x.category===\'Custom\';}).length.toLocaleString());\n  _set(\'ikEol\',       _intuneApps.filter(function(x){return x.lifecycle===\'EOL\';}).length.toLocaleString());\n  var rc=document.getElementById(\'intune-rcount\');\n  if(rc) rc.textContent=_intuneFiltered.length+\' apps matching filters (\'+t+\' total)\';\n}\n\nfunction renderIntuneTable(){\n  var tbody=document.getElementById(\'intune-tbody\');\n  if(!_intuneFiltered.length){\n    tbody.innerHTML=\'<tr><td colspan="9" class="intune-loading">No apps match the current filters.</td></tr>\';\n    return;\n  }\n  var html=\'\';\n  _intuneFiltered.forEach(function(a){\n    var ctxBadge=\'<span class="ctx-na">N/A</span>\';\n    if((a.installContext||\'\').toLowerCase()===\'system\') ctxBadge=\'<span class="ctx-sys">&#128187; System</span>\';\n    else if((a.installContext||\'\').toLowerCase()===\'user\') ctxBadge=\'<span class="ctx-usr">&#128100; User</span>\';\n    var lcBadge=\'<span class="lc-bau">BAU</span>\';\n    if(a.lifecycle===\'Testing\') lcBadge=\'<span class="lc-test">Testing</span>\';\n    else if(a.lifecycle===\'EOL\') lcBadge=\'<span class="lc-eol">EOL</span>\';\n    else if(a.lifecycle===\'Retired\') lcBadge=\'<span class="lc-ret">Retired</span>\';\n    else if(a.lifecycle===\'Project\') lcBadge=\'<span class="lc-proj">Project</span>\';\n    var buBadge=a.bu===\'Common\'?\'<span class="b-com">COMMON</span>\':\'<span class="b-bu">\'+esc(a.bu)+\'</span>\';\n    var _isAssigned=a.isAssigned||(a.assignments&&a.assignments.length>0);\n    var asgnBadge=_isAssigned?\'<span class="b-asgn">Assigned</span>\':\'<span class="b-uasgn">Unassigned</span>\';\n    html+=\'<tr style="border-bottom:1px solid var(--border);cursor:pointer;" onclick="openIntuneModal(\\\'\'+a.id+\'\\\')">\';\n    html+=\'<td style="padding:9px 14px;font-weight:600;">\'+esc(a.displayName||\'\')+\'</td>\';\n    html+=\'<td style="padding:9px 14px;color:var(--muted);font-size:11px;">\'+esc(a.publisher||\'\')+\'</td>\';\n    html+=\'<td style="padding:9px 14px;">\'+asgnBadge+\'</td>\';\n    html+=\'<td style="padding:9px 14px;">\'+ctxBadge+\'</td>\';\n    var _isAuto=(a.updateMethod||\'\').toLowerCase().indexOf(\'automatic\')!==-1;\n    html+=\'<td style="padding:9px 14px;">\'+(  _isAuto\n      ?\'<span style="background:var(--gnb);color:var(--gn);font-size:10px;font-weight:600;padding:2px 8px;border-radius:10px;">&#x2705; Auto</span>\'\n      :\'<span style="background:var(--sf3);color:var(--muted);font-size:10px;font-weight:600;padding:2px 8px;border-radius:10px;">Manual</span>\')+\'</td>\';\n    var _hasSup=(a.supersedingAppCount||0)+(a.supersededAppCount||0);\n    html+=\'<td style="padding:9px 14px;">\'+(_hasSup>0\n      ?\'<span style="background:var(--amb);color:var(--am);font-size:10px;font-weight:600;padding:2px 8px;border-radius:10px;">&#x26A1; \'+_hasSup+\'</span>\'\n      :\'<span style="color:var(--muted);font-size:11px;">—</span>\')+\'</td>\';\n    html+=\'</tr>\';\n  });\n  tbody.innerHTML=html;\n}\n\nvar _intuneView=\'table\';\n\nfunction setIntuneView(v){\n  _intuneView=v;\n  document.getElementById(\'intuneBtnT\').className=\'vbtn\'+(v===\'table\'?\' active\':\'\');\n  document.getElementById(\'intuneBtnC\').className=\'vbtn\'+(v===\'card\'?\' active\':\'\');\n  var tw=document.getElementById(\'intuneTableWrap\');\n  var cg=document.getElementById(\'intuneCardGrid\');\n  if(tw) tw.style.display=(v===\'table\'?\'\':\'none\');\n  if(cg) cg.style.display=(v===\'card\'?\'\':\'none\');\n  if(v===\'card\') renderIntuneCards();\n}\n\nfunction renderIntuneCards(){\n  var cg=document.getElementById(\'intuneCardGrid\');\n  if(!cg) return;\n  if(!_intuneFiltered.length){\n    cg.innerHTML=\'<div style="color:var(--muted);text-align:center;padding:40px;">No apps match current filters.</div>\';\n    return;\n  }\n  var h=\'\';\n  _intuneFiltered.forEach(function(a){\n    var ctxBadge=\'<span class="ctx-na">N/A</span>\';\n    if((a.installContext||\'\')==\'system\') ctxBadge=\'<span class="ctx-sys">&#128187; System</span>\';\n    else if((a.installContext||\'\')==\'user\') ctxBadge=\'<span class="ctx-usr">&#128100; User</span>\';\n    var lcBadge=\'<span class="lc-bau">BAU</span>\';\n    if(a.lifecycle===\'Testing\') lcBadge=\'<span class="lc-test">Testing</span>\';\n    else if(a.lifecycle===\'EOL\') lcBadge=\'<span class="lc-eol">EOL</span>\';\n    else if(a.lifecycle===\'Retired\') lcBadge=\'<span class="lc-ret">Retired</span>\';\n    else if(a.lifecycle===\'Project\') lcBadge=\'<span class="lc-proj">Project</span>\';\n    var buBadge=a.bu===\'Common\'?\'<span class="b-com">COMMON</span>\':\'<span class="b-bu">\'+esc(a.bu)+\'</span>\';\n    var _isAssigned=a.isAssigned||(a.assignments&&a.assignments.length>0);\n    var asgnBadge=_isAssigned?\'<span class="b-asgn">Assigned</span>\':\'<span class="b-uasgn">Unassigned</span>\';\n    h+=\'<div class="intune-card" style="cursor:pointer;" data-appid="\'+esc(a.id)+\'">\';\n    h+=\'<div class="ic-name">\'+esc(a.displayName||\'\')+\'</div>\';\n    h+=\'<div class="ic-pub">\'+esc(a.publisher||\'\')+\'</div>\';\n    h+=\'<div class="ic-meta">\';\n    h+=buBadge+lcBadge+ctxBadge+asgnBadge;\n    if(a.publishingState) h+=\'<span style="font-size:10px;color:var(--muted);padding:2px 6px;">\'+esc(a.publishingState)+\'</span>\';\n    h+=\'</div></div>\';\n  });\n  cg.innerHTML=h;\n}\n\nfunction exportIntuneCsv(){\n  if(!_intuneFiltered.length){ return; }\n  var hdr=[\'App Name\',\'Publisher\',\'Assignment\',\'Install Context\',\'Update Method\',\'Supersedence\'];\n  var rows=[hdr.join(\',\')];\n  _intuneFiltered.forEach(function(a){\n    var _ia=a.isAssigned||(a.assignments&&a.assignments.length>0);\n    var _au=(a.updateMethod||\'\').toLowerCase().indexOf(\'automatic\')!==-1?\'Auto\':\'Manual\';\n    var _hs=(a.supersedingAppCount||0)+(a.supersededAppCount||0);\n    rows.push([cc(a.displayName),cc(a.publisher),_ia?\'Assigned\':\'Unassigned\',cc(a.installContext),_au,_hs||\'\'].join(\',\'));\n  });\n  var blob=new Blob([rows.join(\'\\r\\n\')],{type:\'text/csv\'});\n  var link=document.createElement(\'a\');\n  link.href=URL.createObjectURL(blob);\n  link.download=\'EAM-Live-Production-\'+new Date().toISOString().slice(0,10)+\'.csv\';\n  link.click();\n}\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n</script></div>\n<!-- end panelCatalog -->\n\n<!-- LIVE PRODUCTION APPS PANEL -->\n<div class="tab-panel" id="panelLive">\n<div style="max-width:1400px;margin:0 auto;padding:20px;">\n  <!-- INTUNE PROGRESS BAR -->\n  <div id="intuneProgBar" style="display:none;background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);padding:16px 20px;margin-bottom:16px;">\n    <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px;">\n      <div style="font-size:13px;font-weight:600;color:var(--orange);">&#128257; Fetching live data from Intune...</div>\n      <div id="intuneProgPct" style="font-size:12px;font-weight:700;color:var(--orange);">0%</div>\n    </div>\n    <div style="background:var(--surface2);border-radius:4px;height:8px;overflow:hidden;">\n      <div id="intuneProgFill" style="height:100%;background:var(--orange);border-radius:4px;width:0%;transition:width .4s ease;"></div>\n    </div>\n    <div id="intuneProgMsg" style="font-size:11px;color:var(--muted);margin-top:6px;">Initialising...</div>\n  </div>\n  <!-- KPIs -->\n  <div class="intune-kpis" id="intuneKpis" style="grid-template-columns:repeat(2,1fr);">\n    \n    <div class="ikpi"><div class="ikpi-label">Assigned</div><div class="ikpi-val" id="ikAssigned" style="color:var(--green);">-</div><div class="ikpi-sub">With group target</div></div>\n    <div class="ikpi"><div class="ikpi-label">Unassigned</div><div class="ikpi-val" id="ikUnassigned" style="color:var(--red);">-</div><div class="ikpi-sub">No group target</div></div>\n    \n    \n    \n    \n  </div>\n  <!-- FILTERS -->\n  <div class="intune-filters">\n    \n    \n    \n    <div class="intune-fg"><div class="intune-fl">Assignment</div>\n      <select class="intune-sel" id="intuneasgnFilter" onchange="applyIntuneFilters()">\n        <option value="ALL">All Apps</option>\n        <option value="assigned">Assigned Only</option>\n        <option value="unassigned">Unassigned Only</option>\n      </select>\n    </div>\n    <div class="intune-fg"><div class="intune-fl">Install Context</div>\n      <select class="intune-sel" id="intunectxFilter" onchange="applyIntuneFilters()">\n        <option value="ALL">All Contexts</option>\n        <option value="system">System</option>\n        <option value="user">User</option>\n        <option value="unknown">N/A</option>\n      </select>\n    </div>\n    <div class="intune-fg"><div class="intune-fl">Update Method</div>\n      <select class="intune-sel" id="intuneUpdateFilter" onchange="applyIntuneFilters()">\n        <option value="ALL">All</option>\n        <option value="auto">&#x2705; Auto-Update</option>\n        <option value="manual">&#x274c; Manual</option>\n      </select>\n    </div>\n    <div class="intune-fg"><div class="intune-fl">Search</div>\n      <input class="intune-search" id="intuneSearch" type="text" placeholder="Search by name or publisher..." oninput="applyIntuneFilters()">\n    </div>\n    <button style="background:none;border:1px solid var(--border);border-radius:7px;padding:7px 14px;font-size:12px;color:var(--muted);cursor:pointer;align-self:flex-end;" onclick="resetIntuneFilters()">&#8635; Reset</button>\n    <button style="background:var(--orange);color:#fff;border:none;border-radius:7px;padding:7px 14px;font-size:12px;font-weight:600;cursor:pointer;align-self:flex-end;" onclick="refreshIntuneApps()">&#8635; Refresh</button>\n  </div>\n  <!-- TABLE -->\n  <div style="background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);min-width:0;max-width:100%;">\n    <div style="padding:14px 18px;border-bottom:1px solid var(--border);display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px;">\n      <div><strong id="intune-table-title">Live EAM Apps</strong><div id="intune-rcount" style="font-size:11px;color:var(--muted);margin-top:2px;"></div></div>\n            <button onclick="exportIntuneCsv()" style="background:var(--surface2);border:1px solid var(--border);border-radius:6px;padding:6px 12px;font-size:11px;cursor:pointer;color:var(--muted);white-space:nowrap;flex-shrink:0;">&#8659; Export CSV</button>\n    </div>\n    <div id="intuneTableWrap" style="overflow-x:auto;">\n      <table style="width:100%;border-collapse:collapse;font-size:12px;">\n        <thead><tr id="intune-thead">\n          <th style="background:var(--navy);color:rgba(255,255,255,.9);padding:10px 14px;text-align:left;font-size:10px;font-weight:600;letter-spacing:.05em;text-transform:uppercase;">Application Name</th>\n          <th style="background:var(--navy);color:rgba(255,255,255,.9);padding:10px 14px;text-align:left;font-size:10px;font-weight:600;letter-spacing:.05em;text-transform:uppercase;">Publisher</th>\n          <th style="background:var(--navy);color:rgba(255,255,255,.9);padding:10px 14px;text-align:left;font-size:10px;font-weight:600;letter-spacing:.05em;text-transform:uppercase;">Assignment</th>\n          <th style="background:var(--navy);color:rgba(255,255,255,.9);padding:10px 14px;text-align:left;font-size:10px;font-weight:600;letter-spacing:.05em;text-transform:uppercase;">Install Context</th>\n          <th style="background:var(--navy);color:rgba(255,255,255,.9);padding:10px 14px;text-align:left;font-size:10px;font-weight:600;letter-spacing:.05em;text-transform:uppercase;">Update Method</th>\n          <th style="background:var(--navy);color:rgba(255,255,255,.9);padding:10px 14px;text-align:left;font-size:10px;font-weight:600;letter-spacing:.05em;text-transform:uppercase;">Supersedence</th>\n        </tr></thead>\n        <tbody id="intune-tbody"><tr><td colspan="6" class="intune-loading">Loading EAM production apps...</td></tr></tbody>\n      </table>\n    </div>\n    <div id="intuneCardGrid" class="intune-card-grid" style="display:none;"></div>\n  </div>\n</div>\n</div><!-- end inner wrapper -->\n<!-- end panelLive -->\n\n<!-- EAM UPDATES PANEL -->\n<div class="tab-panel" id="panelUpdates">\n<div style="max-width:1400px;margin:0 auto;padding:20px;">\n  <div style="background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);padding:16px 20px;margin-bottom:16px;">\n    <div style="font-size:14px;font-weight:700;margin-bottom:4px;">&#128202; Enterprise App Catalog apps with updates</div>\n    <div style="font-size:12px;color:var(--muted);">Apps deployed in your tenant that have a newer version available in the Microsoft EAM catalog. Data sourced from Intune Monitor report.</div>\n  </div>\n  <div id="updatesContent" style="background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);">\n    <div style="padding:14px 18px;border-bottom:1px solid var(--border);display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px;">\n      <div><strong id="updates-title">EAM Apps with Pending Updates</strong>\n        <div id="updates-sub" style="font-size:11px;color:var(--muted);margin-top:2px;"></div></div>\n      <button onclick="exportUpdatesCsv()" style="background:var(--surface2);border:1px solid var(--border);border-radius:6px;padding:6px 12px;font-size:11px;cursor:pointer;color:var(--muted);">&#8659; Export CSV</button>\n    </div>\n    <div style="overflow-x:auto;">\n      <table style="width:100%;border-collapse:collapse;font-size:12px;">\n        <thead><tr id="updates-thead">\n          <th style="background:var(--navy);color:rgba(255,255,255,.9);padding:10px 14px;text-align:left;font-size:10px;font-weight:600;letter-spacing:.05em;text-transform:uppercase;border-bottom:2px solid var(--orange);">Application Name</th>\n          <th style="background:var(--navy);color:rgba(255,255,255,.9);padding:10px 14px;text-align:left;font-size:10px;font-weight:600;letter-spacing:.05em;text-transform:uppercase;border-bottom:2px solid var(--orange);">Publisher</th>\n          <th style="background:var(--navy);color:rgba(255,255,255,.9);padding:10px 14px;text-align:left;font-size:10px;font-weight:600;letter-spacing:.05em;text-transform:uppercase;border-bottom:2px solid var(--orange);">Deployed Version</th>\n          <th style="background:var(--navy);color:rgba(255,255,255,.9);padding:10px 14px;text-align:left;font-size:10px;font-weight:600;letter-spacing:.05em;text-transform:uppercase;border-bottom:2px solid var(--orange);">Latest Available</th>\n          <th style="background:var(--navy);color:rgba(255,255,255,.9);padding:10px 14px;text-align:left;font-size:10px;font-weight:600;letter-spacing:.05em;text-transform:uppercase;border-bottom:2px solid var(--orange);">Update Available</th>\n          <th style="background:var(--navy);color:rgba(255,255,255,.9);padding:10px 14px;text-align:left;font-size:10px;font-weight:600;letter-spacing:.05em;text-transform:uppercase;border-bottom:2px solid var(--orange);">Update Eligible</th>\n          <th style="background:var(--navy);color:rgba(255,255,255,.9);padding:10px 14px;text-align:left;font-size:10px;font-weight:600;letter-spacing:.05em;text-transform:uppercase;border-bottom:2px solid var(--orange);">Superseded</th>\n        </tr></thead>\n        <tbody id="updates-tbody"><tr><td colspan="7" style="text-align:center;padding:40px;color:var(--muted);">Loading update data...</td></tr></tbody>\n      </table>\n    </div>\n  </div>\n</div>\n</div><!-- end panelUpdates -->\n\n<!-- INTUNE APP DETAIL MODAL -->\n<div class="intune-mo-overlay" id="intuneModal" onclick="if(event.target===this)closeIntuneModal()">\n  <div class="intune-mo">\n    <div class="intune-mo-hdr">\n      <div>\n        <div class="intune-mo-title" id="imoTitle"></div>\n        <div class="intune-mo-sub"  id="imoSub"></div>\n      </div>\n      <button class="intune-mo-close" onclick="closeIntuneModal()">&#215;</button>\n    </div>\n    <div class="intune-mo-body" id="imoBody"></div>\n  </div>\n</div>\n\n\n</div><!-- end main-content -->\n</div><!-- end app-shell -->\n\n</body>\n</html>\n\n'

if __name__ == "__main__":
    print("")
    print("=================================================")
    print("  IntunEAM Live v1")
    print("  Tab 1: EAM Catalog Apps")
    print("  Tab 2: Live Apps")
    print("  Tab 3: App Updates")
    print("  Author : Vigneshwaran")
    print("=================================================")
    print(f"  URL    : http://localhost:{PORT}")
    print(f"  Tenant : {TENANT_ID}")
    print("")
    print("  Starting data fetch in background...")
    print("  Browser will open automatically.")
    print("  Press Ctrl+C to stop.")
    print("")
    threading.Thread(target=fetch_catalog, daemon=True).start()
    def _open():
        import time as _t; _t.sleep(1.5)
        webbrowser.open(f"http://localhost:{PORT}")
    threading.Thread(target=_open, daemon=True).start()
    from http.server import HTTPServer
    server = HTTPServer(("localhost", PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  Shutting down.")
        server.shutdown()
