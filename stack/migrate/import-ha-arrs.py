#!/usr/bin/env python3
"""Copy every item from the HA arrs (monitored or not, with or without files) into the
voidpad arrs, keeping monitored flags. HA paths /media/MEDS/<X> map to /nas/<X>.
Never triggers a search. Safe to re-run: existing items only get their flags synced.
  import-ha-arrs.py [radarr|sonarr|lidarr ...] [--episodes] [--albums]"""
import json, os, re, sys, time, urllib.error, urllib.request

CFG = os.path.expanduser("~/.local/share/library-stack")
HA_CFG = "/run/user/1000/gvfs/smb-share:server=homeassistant.local,share=addon_configs/a0d7b954_{}/config.xml"
HA_HOST = "10.0.0.2"
APPS = {"radarr": (7878, "v3", "movie"), "sonarr": (8989, "v3", "series"), "lidarr": (8686, "v1", "artist")}
ID = {"radarr": "tmdbId", "sonarr": "tvdbId", "lidarr": "foreignArtistId"}


def apikey(path):
    return re.search(r"<ApiKey>([^<]+)", open(path).read())[1]


class Arr:
    def __init__(self, host, port, ver, key):
        self.base, self.key = f"http://{host}:{port}/api/{ver}/", key

    def __call__(self, path, body=None, method=None):
        req = urllib.request.Request(self.base + path, method=method or ("POST" if body is not None else "GET"),
                                     data=json.dumps(body).encode() if body is not None else None,
                                     headers={"X-Api-Key": self.key, "Content-Type": "application/json"})
        for attempt in range(4):
            try:
                with urllib.request.urlopen(req, timeout=180) as r:
                    return json.loads(r.read() or "null")
            except urllib.error.HTTPError as e:
                if e.code in (502, 503, 504) and attempt < 3:
                    time.sleep(5 * (attempt + 1)); continue
                raise


def nas(path):
    return re.sub(r"^/media/(MEDS|meds)/", "/nas/", path)


def run(app, episodes, albums):
    port, ver, ep = APPS[app]
    ha = Arr(HA_HOST, port, ver, apikey(HA_CFG.format(app)))
    vp = Arr("127.0.0.1", port, ver, apikey(f"{CFG}/{app}/config.xml"))
    vp_qp = {q["name"]: q["id"] for q in vp("qualityprofile")}
    ha_qp = {q["id"]: q["name"] for q in ha("qualityprofile")}
    default_qp = next(iter(vp_qp.values()))
    if app == "lidarr":
        vp_mp = {m["name"]: m["id"] for m in vp("metadataprofile")}
        ha_mp = {m["id"]: m["name"] for m in ha("metadataprofile")}
    have = {x[ID[app]]: x for x in vp(ep)}
    added = synced = 0
    failed = []
    for item in ha(ep):
        cur = have.get(item[ID[app]])
        if cur:  # already here (e.g. from the folder backfill): match HA's flag
            if cur["monitored"] != item["monitored"]:
                cur["monitored"] = item["monitored"]
                if app == "sonarr":
                    hs = {s["seasonNumber"]: s["monitored"] for s in item["seasons"]}
                    for s in cur["seasons"]:
                        s["monitored"] = hs.get(s["seasonNumber"], s["monitored"])
                vp(f"{ep}/{cur['id']}", cur, "PUT"); synced += 1
            continue
        body = {k: v for k, v in item.items() if k not in ("id", "statistics", "movieFile", "tags", "images", "added")}
        body.update(path=nas(item["path"]), rootFolderPath=nas(item.get("rootFolderPath") or item["path"].rsplit("/", 1)[0]),
                    qualityProfileId=vp_qp.get(ha_qp.get(item.get("qualityProfileId")), default_qp), tags=[])
        if app == "radarr":
            body["addOptions"] = {"searchForMovie": False, "monitor": "movieOnly" if item["monitored"] else "none"}
        elif app == "sonarr":
            body["addOptions"] = {"searchForMissingEpisodes": False, "searchForCutoffUnmetEpisodes": False}
        else:
            body["metadataProfileId"] = vp_mp.get(ha_mp.get(item.get("metadataProfileId")), next(iter(vp_mp.values())))
            body["addOptions"] = {"monitor": "none", "searchForMissingAlbums": False}  # albums synced below
        try:
            vp(ep, body); added += 1
        except urllib.error.HTTPError as e:
            failed.append(f"{item.get('title') or item.get('artistName')}: {e.code} {e.read()[:150].decode(errors='ignore')}")
    print(f"{app}: added {added}, flags synced {synced}, failed {len(failed)}", flush=True)
    for f in failed:
        print("   !", f)

    if app == "sonarr" and episodes:  # episode-level monitored flags
        vp_series = {s["tvdbId"]: s["id"] for s in vp("series")}
        on, off = [], []
        for s in ha("series"):
            if s["tvdbId"] not in vp_series:
                continue
            ha_eps = {(e["seasonNumber"], e["episodeNumber"]): e["monitored"] for e in ha(f"episode?seriesId={s['id']}")}
            for e in vp(f"episode?seriesId={vp_series[s['tvdbId']]}"):
                want = ha_eps.get((e["seasonNumber"], e["episodeNumber"]))
                if want is not None and want != e["monitored"]:
                    (on if want else off).append(e["id"])
        for ids, flag in ((on, True), (off, False)):
            if ids:
                vp("episode/monitor", {"episodeIds": ids, "monitored": flag}, "PUT")
        print(f"sonarr: episodes monitored +{len(on)} / -{len(off)}")

    if app == "lidarr" and albums:  # album-level monitored flags, matched by MusicBrainz id
        ha_alb = {a["foreignAlbumId"]: a["monitored"] for a in ha("album")}
        on, off = [], []
        for a in vp("album"):
            want = ha_alb.get(a["foreignAlbumId"])
            if want is not None and want != a["monitored"]:
                (on if want else off).append(a["id"])
        for ids, flag in ((on, True), (off, False)):
            if ids:
                vp("album/monitor", {"albumIds": ids, "monitored": flag}, "PUT")
        print(f"lidarr: albums monitored +{len(on)} / -{len(off)} (HA has {len(ha_alb)} albums)")


args = [a for a in sys.argv[1:] if not a.startswith("--")]
for app in args or APPS:
    run(app, "--episodes" in sys.argv, "--albums" in sys.argv)
