#!/usr/bin/env python3
"""Gluetun info and settings for the Librarry VPN tab. Prints one JSON line.
  vpnctl.py status | servers | set <country> [city] | reconnect | ips"""
import json, os, re, subprocess, sys, urllib.request

DIR = os.path.dirname(os.path.abspath(__file__))
VPN_ENV = os.path.join(DIR, "vpn.env")
SERVERS = os.path.expanduser("~/.local/share/library-stack/gluetun/servers/protonvpn.json")
API = "http://127.0.0.1:8000/v1/"


def api(path, body=None):
    req = urllib.request.Request(API + path, method="PUT" if body else "GET",
                                 data=json.dumps(body).encode() if body else None,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read() or "null")
    except Exception as e:
        return {"error": str(e)}


def read_env():
    env = {}
    if os.path.exists(VPN_ENV):
        for line in open(VPN_ENV):
            if "=" in line and not line.startswith("#"):
                k, v = line.rstrip("\n").split("=", 1)
                env[k] = v
    return env


def podman(*args):
    return subprocess.run(["podman", *args], capture_output=True, text=True).stdout


def status():
    env = read_env()
    ip = api("publicip/ip")
    pf = api("portforward")
    vpn = api("vpn/status")
    log = podman("logs", "gluetun")
    server = next((m[1] for l in reversed(log.splitlines())
                   if (m := re.search(r"\[([\w.-]+\.protonvpn\.net)\]", l))), "")
    return {
        "vpn": vpn.get("status", vpn.get("error")),
        "ip": ip.get("public_ip"), "country": ip.get("country"), "region": ip.get("region"), "city": ip.get("city"),
        "server": server, "forwarded_port": pf.get("port"),
        "choice": {"country": env.get("SERVER_COUNTRIES", ""), "city": env.get("SERVER_CITIES", "")},
        "provider": "protonvpn (OpenVPN, port-forwarding servers only)",
    }


def servers():
    out = {}
    for s in json.load(open(SERVERS))["servers"]:
        if s.get("vpn") == "openvpn" and s.get("port_forward"):
            out.setdefault(s["country"], set()).add(s.get("city", ""))
    return {c: sorted(x for x in cities if x) for c, cities in sorted(out.items())}


def set_server(country, city=""):
    lines = [f"SERVER_COUNTRIES={country}"] + ([f"SERVER_CITIES={city}"] if city else [])
    open(VPN_ENV, "w").write("\n".join(lines) + "\n")
    # env_file changes need a recreate; the VPN-sharing apps are recreated with it
    subprocess.run([os.path.join(DIR, "stackctl.sh"), "recreate-vpn"], check=True,
                   stdout=subprocess.DEVNULL)
    return {"ok": True, "country": country, "city": city}


def whoami(cmd):
    """ipinfo as seen by cmd; returns ip / place / isp, or the failure."""
    try:
        out = subprocess.run(cmd + ["curl", "-s", "-m", "8", "https://ipinfo.io/json"],
                             capture_output=True, text=True, timeout=15).stdout
        d = json.loads(out)
        return {"ip": d.get("ip"), "city": d.get("city"), "country": d.get("country"),
                "isp": re.sub(r"^AS\d+\s+", "", d.get("org", ""))}
    except Exception as e:
        return {"error": str(e) or "unreachable"}


def ips():
    # checked for real: once from inside gluetun's network (via transmission), once from voidpad itself
    return {"vpn": whoami(["podman", "exec", "transmission"]), "local": whoami([])}


def reconnect():
    # stop/start the tunnel in place: gluetun picks another matching server
    api("vpn/status", {"status": "stopped"})
    api("vpn/status", {"status": "running"})
    return {"ok": True}


cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
res = {"status": status, "servers": servers, "reconnect": reconnect, "ips": ips,
       "set": lambda: set_server(*sys.argv[2:4])}[cmd]()
print(json.dumps(res))
