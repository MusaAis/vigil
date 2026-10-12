"""The Vercel front (deploy/vercel) only proxies to the backend; it holds no code and no secrets."""
import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_vercel_config_is_a_single_catch_all_proxy():
    cfg = json.load(open(os.path.join(ROOT, "deploy", "vercel", "vercel.json"), encoding="utf-8"))
    assert cfg["rewrites"] == [{"source": "/(.*)", "destination": cfg["rewrites"][0]["destination"]}]
    dest = cfg["rewrites"][0]["destination"]
    assert re.fullmatch(r"https://[a-z0-9.-]+/\$1", dest), dest
    assert set(cfg) <= {"$schema", "rewrites"}  # no env, no build commands, no functions


def test_vercel_folder_has_only_static_placeholders():
    files = sorted(os.path.relpath(os.path.join(d, f), os.path.join(ROOT, "deploy", "vercel"))
                   for d, _, fs in os.walk(os.path.join(ROOT, "deploy", "vercel")) for f in fs)
    assert files == ["public/robots.txt", "vercel.json"]
