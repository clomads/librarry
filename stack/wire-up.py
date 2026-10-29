#!/usr/bin/env python3
"""Idempotent first-run wiring: Transmission as download client in each arr,
root folders under /media, and each arr registered as an app in Prowlarr."""
import json, os, re, urllib.request

CFG = os.path.expanduser("~/.local/share/library-stack")
ARRS = {  # name: (port, api version, root folder, prowlarr implementation)
    "sonarr": (8989, "v3", "/media/tv", "Sonarr"),
    "radarr": (7878, "v3", "/media/movies", "Radarr"),
    "lidarr": (8686, "v1", "/media/music", "Lidarr"),
    "whisparr": (6969, "v3", "/media/adult", "Whisparr"),
}


def key(app):
    return re.search(r"<ApiKey>([^<]+)", open(f"{CFG}/{app}/config.xml").read())[1]


def call(port, ver, apikey, path, body=None):
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/{ver}/{path}",
        data=json.dumps(body).encode() if body is not None else None,
        headers={"X-Api-Key": apikey, "Content-Type": "application/json"},
        method="POST" if body is not None else "GET",
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read() or "null")


def set_fields(schema, values):
    for f in schema["fields"]:
        for name, v in values.items():
            if f["name"] == name or (name == "*Category" and f["name"].endswith("Category") and "Imported" not in f["name"] and "Older" not in f["name"] and "Recent" not in f["name"]):
                f["value"] = v
    return schema


for app, (port, ver, root, impl) in ARRS.items():
    k = key(app)
    if not any(c["implementation"] == "Transmission" for c in call(port, ver, k, "downloadclient")):
        s = next(x for x in call(port, ver, k, "downloadclient/schema") if x["implementation"] == "Transmission")
        s.update(name="Transmission", enable=True, priority=1)
        set_fields(s, {"host": "127.0.0.1", "port": 9091, "urlBase": "/transmission/", "*Category": app})
        call(port, ver, k, "downloadclient", s)
        print(app, "download client added")
    if not any(r["path"].rstrip("/") == root for r in call(port, ver, k, "rootfolder")):
        body = {"path": root}
        if app == "lidarr":
            body.update(name="Music",
                        defaultQualityProfileId=call(port, ver, k, "qualityprofile")[0]["id"],
                        defaultMetadataProfileId=call(port, ver, k, "metadataprofile")[0]["id"])
        call(port, ver, k, "rootfolder", body)
        print(app, "root folder", root)

pk = key("prowlarr")
have = {a["implementation"] for a in call(9696, "v1", pk, "applications")}
schemas = call(9696, "v1", pk, "applications/schema")
for app, (port, ver, root, impl) in ARRS.items():
    if impl in have:
        continue
    s = next(x for x in schemas if x["implementation"] == impl)
    s.update(name=impl, syncLevel="fullSync")
    set_fields(s, {"prowlarrUrl": "http://127.0.0.1:9696", "baseUrl": f"http://127.0.0.1:{port}", "apiKey": key(app)})
    call(9696, "v1", pk, "applications", s)
    print("prowlarr ->", impl)
print("done")
