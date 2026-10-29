#!/usr/bin/env python3
"""Add the existing HA library (media/meds, mounted read-only at /nas) to Radarr,
Sonarr and Lidarr in place: files are not moved or copied, and nothing is searched
for. Safe to re-run; it only adds folders the arr doesn't know yet."""
import json, os, re, sys, urllib.error, urllib.parse, urllib.request

CFG = os.path.expanduser("~/.local/share/library-stack")
JOBS = [  # app, port, api, root, lookup, add endpoint
    ("radarr", 7878, "v3", "/nas/Movies", "movie/lookup", "movie"),
    ("sonarr", 8989, "v3", "/nas/TV Shows", "series/lookup", "series"),
    ("lidarr", 8686, "v1", "/nas/Music", "artist/lookup", "artist"),
]


def key(app):
    return re.search(r"<ApiKey>([^<]+)", open(f"{CFG}/{app}/config.xml").read())[1]


def call(port, ver, k, path, body=None):
    req = urllib.request.Request(f"http://127.0.0.1:{port}/api/{ver}/{path}",
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"X-Api-Key": k, "Content-Type": "application/json"},
                                 method="POST" if body is not None else "GET")
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read() or "null")


def clean(name):
    # "Argylle (2024)" -> "Argylle 2024"; drop [tags] and release junk
    return re.sub(r"[\[\]().]", " ", re.sub(r"\[.*?\]", "", name)).strip()


only = sys.argv[1:] or [j[0] for j in JOBS]
for app, port, ver, root, lookup, add in JOBS:
    if app not in only:
        continue
    k = key(app)
    roots = call(port, ver, k, "rootfolder")
    rf = next((r for r in roots if r["path"].rstrip("/") == root), None)
    qp = call(port, ver, k, "qualityprofile")[0]["id"]
    if not rf:
        body = {"path": root}
        if app == "lidarr":
            body.update(name="HA library", defaultQualityProfileId=qp,
                        defaultMetadataProfileId=call(port, ver, k, "metadataprofile")[0]["id"])
        rf = call(port, ver, k, "rootfolder", body)
        rf = next(r for r in call(port, ver, k, "rootfolder") if r["path"].rstrip("/") == root)
    unmapped = rf.get("unmappedFolders") or []
    if app == "lidarr" and not unmapped:
        # Lidarr doesn't report unmapped folders; list the share ourselves
        known = {a["path"].rstrip("/") for a in call(port, ver, k, "artist")}
        host = os.path.join(CFG, "ha-meds", os.path.basename(root))
        unmapped = [{"name": n, "path": f"{root}/{n}"} for n in sorted(os.listdir(host))
                    if os.path.isdir(os.path.join(host, n)) and f"{root}/{n}" not in known]
    print(f"{app}: {len(unmapped)} folders to add from {root}", flush=True)
    added, missed = 0, []
    for f in unmapped:
        name = f["name"]
        try:
            hits = call(port, ver, k, f"{lookup}?term={urllib.parse.quote(clean(name))}")
        except Exception as e:
            missed.append(f"{name} (lookup failed: {e})"); continue
        if not hits:
            missed.append(name); continue
        item = hits[0]
        item.update(path=f["path"], rootFolderPath=root, qualityProfileId=qp, monitored=True)
        if app == "radarr":
            item["addOptions"] = {"searchForMovie": False}
        elif app == "sonarr":
            item.update(seasonFolder=True, addOptions={"monitor": "future", "searchForMissingEpisodes": False})
        else:
            item.update(metadataProfileId=rf.get("defaultMetadataProfileId") or 1,
                        addOptions={"monitor": "existing", "searchForMissingAlbums": False})
        try:
            call(port, ver, k, add, item); added += 1
        except urllib.error.HTTPError as e:
            missed.append(f"{name} ({e.code}: {e.read()[:120].decode(errors='ignore')})")
    print(f"{app}: added {added}, not matched {len(missed)}", flush=True)
    for m in missed:
        print("   ?", m)
