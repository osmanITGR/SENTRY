#!/usr/bin/env python3
"""Compare the running code's dependencies and runtimes with what is current
RIGHT NOW, using live sources (package registries, advisory databases,
official release feeds) - never a model's memory.

Usage:
  python3 freshness_report.py [REPO] [--json] [--min-age-days 7] [--no-runtimes]
                              [--only npm,pypi,go,crates,pub,nuget,maven]
                              [--cache-ttl SEC] [--summary]

Reports, in priority order:
  SECURITY    the version in use has known vulnerabilities
  DEPRECATED  the package/version is deprecated, yanked or discontinued
  RUNTIME     language/toolchain version behind the current release line
  MAJOR       a newer major version exists (breaking changes likely)
  MINOR/PATCH newer compatible versions exist
  WAIT        newer version is younger than --min-age-days (supply-chain cooldown)
  UNKNOWN     a live source could not be reached (never guessed)

Exit 1 when SECURITY or DEPRECATED items exist, else 0. Standard library only.
Tests can point PRECISION_KIT_HTTP_FIXTURE at a JSON map of url -> response.
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import datetime as dt
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path

try:
    import tomllib
except ImportError:  # Python < 3.11
    tomllib = None

TIMEOUT = 12
UA = "precision-kit-freshness/1.0"
SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "dist", "build", "target", "vendor",
             ".dart_tool", ".gradle", "__pycache__", "out", "bin", "obj", ".next"}
NOW = dt.datetime.now(dt.timezone.utc)


# ---------------------------------------------------------------- http layer
_FIXTURE = None


def http(url: str, data: dict | None = None, accept: str = "application/json"):
    """GET/POST returning parsed JSON or text. Raises OSError when unreachable."""
    global _FIXTURE
    fixture_path = os.environ.get("PRECISION_KIT_HTTP_FIXTURE")
    if fixture_path:
        if _FIXTURE is None:
            _FIXTURE = json.loads(Path(fixture_path).read_text())
        key = ("POST " if data is not None else "") + url
        if key not in _FIXTURE:
            raise OSError(f"unreachable (fixture has no {key})")
        return _FIXTURE[key]
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body, headers={
        "User-Agent": UA, "Accept": accept,
        **({"Content-Type": "application/json"} if body else {})})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise LookupError(f"not found: {url}") from e
        raise OSError(f"HTTP {e.code} from {urllib.parse.urlparse(url).netloc}") from e
    except (urllib.error.URLError, TimeoutError) as e:
        raise OSError(f"unreachable: {urllib.parse.urlparse(url).netloc}") from e
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


# ---------------------------------------------------------------- versions
def vtuple(v: str) -> tuple:
    nums = re.findall(r"\d+", re.split(r"[-+]", v.lstrip("vV=^~<>! "), maxsplit=1)[0])
    return tuple(int(n) for n in nums[:4]) or (0,)


def is_prerelease(v: str) -> bool:
    return bool(re.search(r"(?i)[-.]?(alpha|beta|rc|pre|dev|snapshot|canary|next|nightly|preview)"
                          r"|\d[ab]\d", v.lstrip("v")))


def classify(current: str, latest: str) -> str:
    c, l = vtuple(current), vtuple(latest)
    c, l = c + (0,) * (3 - len(c)), l + (0,) * (3 - len(l))
    if c >= l:
        return "current" if c == l else "ahead"
    if l[0] != c[0]:
        return "major"
    if c[0] == 0 and l[1] != c[1]:
        return "major"  # 0.x minor bumps are breaking by semver convention
    return "minor" if l[1] != c[1] else "patch"


def age_days(iso: str | None) -> int | None:
    if not iso:
        return None
    try:
        t = dt.datetime.fromisoformat(iso.replace("Z", "+00:00"))
        if t.tzinfo is None:
            t = t.replace(tzinfo=dt.timezone.utc)
        return (NOW - t).days
    except ValueError:
        return None


def max_stable(versions) -> str | None:
    stable = [v for v in versions if not is_prerelease(v)]
    return max(stable, key=vtuple) if stable else None


# ---------------------------------------------------------------- data model
@dataclass
class Dep:
    ecosystem: str
    name: str
    current: str
    manifest: str
    exact: bool = True          # False when only a range/minimum was declared
    latest: str | None = None
    released: str | None = None
    deprecated: str | None = None
    vulns: list = field(default_factory=list)
    kind: str = "unknown"
    error: str | None = None


# ---------------------------------------------------------------- manifests
def read(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def load_toml(p: Path) -> dict:
    if tomllib is None or not p.exists():
        return {}
    try:
        return tomllib.loads(read(p))
    except Exception:
        return {}


def spec_version(spec: str) -> str | None:
    m = re.search(r"\d+(?:\.\d+){0,3}(?:[-.][0-9A-Za-z.]+)?", spec or "")
    return m.group(0) if m else None


def walk(repo: Path, names: set[str]):
    for dirpath, dirnames, filenames in os.walk(repo):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
        if len(Path(dirpath).relative_to(repo).parts) > 4:
            dirnames[:] = []
        for f in filenames:
            if f in names or any(f.endswith(n) for n in names if n.startswith(".")):
                yield Path(dirpath) / f


def npm_deps(repo: Path) -> list[Dep]:
    out = []
    for pj in walk(repo, {"package.json"}):
        try:
            pkg = json.loads(read(pj) or "{}")
        except json.JSONDecodeError:
            continue
        lock = {}
        lj = pj.parent / "package-lock.json"
        if lj.exists():
            try:
                lock = json.loads(read(lj)).get("packages", {})
            except json.JSONDecodeError:
                pass
        rel = str(pj.relative_to(repo))
        for section in ("dependencies", "devDependencies", "optionalDependencies"):
            for name, spec in (pkg.get(section) or {}).items():
                if not isinstance(spec, str) or re.match(r"(workspace|file|link|git|github|http|npm):|[*x]$|latest$", spec):
                    continue
                locked = (lock.get(f"node_modules/{name}") or {}).get("version")
                cur = locked or spec_version(spec)
                if cur:
                    out.append(Dep("npm", name, cur, rel,
                                   exact=bool(locked) or bool(re.fullmatch(r"=?\d+(\.\d+){2}", spec))))
    return out


def norm_py(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def pypi_deps(repo: Path) -> list[Dep]:
    out, seen = [], set()
    for root in {p.parent for p in walk(repo, {"pyproject.toml", "requirements.txt", "setup.cfg"})}:
        locked = {}
        for lockname in ("uv.lock", "poetry.lock", "pdm.lock"):
            for pkg in load_toml(root / lockname).get("package", []):
                if "name" in pkg and "version" in pkg:
                    locked[norm_py(pkg["name"])] = pkg["version"]
        declared: dict[str, tuple[str, str]] = {}
        py = load_toml(root / "pyproject.toml")
        reqs = list(py.get("project", {}).get("dependencies", []))
        for group in (py.get("project", {}).get("optional-dependencies") or {}).values():
            reqs += group
        for group in (py.get("dependency-groups") or {}).values():
            reqs += [g for g in group if isinstance(g, str)]
        for r in reqs:
            m = re.match(r"\s*([A-Za-z0-9][\w.-]*)\s*(?:\[[^\]]*\])?\s*([^;]*)", r)
            if m:
                declared[norm_py(m.group(1))] = (m.group(2).strip(), "pyproject.toml")
        for name, spec in (py.get("tool", {}).get("poetry", {}).get("dependencies") or {}).items():
            if name.lower() != "python":
                s = spec if isinstance(spec, str) else (spec or {}).get("version", "")
                declared[norm_py(name)] = (s, "pyproject.toml")
        for req in sorted(root.glob("requirements*.txt")):
            for line in read(req).splitlines():
                m = re.match(r"\s*([A-Za-z0-9][\w.-]*)\s*(?:\[[^\]]*\])?\s*((?:==|>=|~=|<=|>|<|!=)[^#;\s]+(?:\s*,\s*[^#;\s]+)*)?", line)
                if m and not line.strip().startswith(("#", "-")):
                    declared[norm_py(m.group(1))] = (m.group(2) or "", req.name)
        for name, (spec, mf) in declared.items():
            cur = locked.get(name)
            exact = bool(cur) or spec.startswith("==")
            cur = cur or spec_version(spec)
            key = (name, cur)
            if cur and key not in seen:
                seen.add(key)
                out.append(Dep("pypi", name, cur, str((root / mf).relative_to(repo)), exact=exact))
    return out


def go_deps(repo: Path) -> list[Dep]:
    out = []
    for gm in walk(repo, {"go.mod"}):
        text = read(gm)
        for block in re.findall(r"require\s*\((.*?)\)", text, re.S) + re.findall(r"^require\s+(\S+\s+\S+.*)$", text, re.M):
            for line in block.splitlines():
                m = re.match(r"\s*(\S+)\s+(v\S+)(.*)$", line)
                if m and "// indirect" not in m.group(3):
                    out.append(Dep("go", m.group(1), m.group(2), str(gm.relative_to(repo))))
    return out


def crates_deps(repo: Path) -> list[Dep]:
    out = []
    for ct in walk(repo, {"Cargo.toml"}):
        data = load_toml(ct)
        locked = {p["name"]: p["version"] for p in load_toml(ct.parent / "Cargo.lock").get("package", [])
                  if "name" in p and "version" in p}
        for section in ("dependencies", "dev-dependencies", "build-dependencies"):
            for name, spec in (data.get(section) or {}).items():
                s = spec if isinstance(spec, str) else (spec or {}).get("version")
                if not s or (isinstance(spec, dict) and ("path" in spec or "git" in spec)):
                    continue
                real = (spec.get("package") if isinstance(spec, dict) else None) or name
                cur = locked.get(real) or spec_version(s)
                if cur:
                    out.append(Dep("crates", real, cur, str(ct.relative_to(repo)), exact=real in locked))
    return out


def pub_deps(repo: Path) -> list[Dep]:
    out = []
    for ps in walk(repo, {"pubspec.yaml"}):
        locked = {}
        for m in re.finditer(r"^  ([\w-]+):\n(?:    .*\n)*?    version: \"?([^\"\n]+)\"?", read(ps.parent / "pubspec.lock"), re.M):
            locked[m.group(1)] = m.group(2)
        section = None
        for line in read(ps).splitlines():
            if re.match(r"^(dependencies|dev_dependencies):\s*$", line):
                section = line
                continue
            if line and not line.startswith(" "):
                section = None
            m = re.match(r"^  ([\w-]+):\s*(.*)$", line)
            if section and m and m.group(1) not in ("flutter", "flutter_test", "flutter_localizations"):
                spec = m.group(2).strip().strip("'\"")
                cur = locked.get(m.group(1)) or spec_version(spec)
                if cur and "sdk" not in spec:
                    out.append(Dep("pub", m.group(1), cur, str(ps.relative_to(repo)),
                                   exact=m.group(1) in locked))
    return out


def nuget_deps(repo: Path) -> list[Dep]:
    out = []
    for f in walk(repo, {".csproj", ".fsproj", "Directory.Packages.props"}):
        for m in re.finditer(r"<Package(?:Reference|Version)\s+Include=\"([^\"]+)\"\s+Version=\"([^\"]+)\"", read(f)):
            if spec_version(m.group(2)):
                out.append(Dep("nuget", m.group(1), spec_version(m.group(2)), str(f.relative_to(repo))))
    return out


def maven_deps(repo: Path) -> list[Dep]:
    out = []
    for pom in walk(repo, {"pom.xml"}):
        text = read(pom)
        props = dict(re.findall(r"<([\w.-]+)>([^<${}]+)</\1>", (re.search(r"<properties>(.*?)</properties>", text, re.S) or [None, ""])[1]))
        for dep in re.findall(r"<dependency>(.*?)</dependency>", text, re.S):
            g, a, v = (re.search(rf"<{t}>([^<]+)</{t}>", dep) for t in ("groupId", "artifactId", "version"))
            if g and a and v:
                ver = v.group(1).strip()
                ver = props.get(ver[2:-1], "") if ver.startswith("${") else ver
                if spec_version(ver):
                    out.append(Dep("maven", f"{g.group(1)}:{a.group(1)}", ver, str(pom.relative_to(repo))))
    for cat in walk(repo, {"libs.versions.toml"}):
        data = load_toml(cat)
        versions = data.get("versions", {})
        for lib in (data.get("libraries") or {}).values():
            if isinstance(lib, str):
                parts = lib.split(":")
                if len(parts) == 3:
                    out.append(Dep("maven", f"{parts[0]}:{parts[1]}", parts[2], str(cat.relative_to(repo))))
                continue
            module = lib.get("module") or (f"{lib['group']}:{lib['name']}" if "group" in lib and "name" in lib else None)
            ver = lib.get("version")
            if isinstance(ver, dict):
                ver = versions.get(ver.get("ref", ""), "") if "ref" in ver else ver.get("strictly") or ver.get("require")
            ver = ver or (versions.get(lib.get("version.ref", ""), "") if "version.ref" in lib else None)
            if isinstance(ver, dict):
                ver = ver.get("strictly") or ver.get("require")
            if module and ver and spec_version(str(ver)):
                out.append(Dep("maven", module, str(ver), str(cat.relative_to(repo))))
    for gb in walk(repo, {"build.gradle", "build.gradle.kts"}):
        for m in re.finditer(r"[\"']([\w.-]+):([\w.-]+):(\d[\w.-]*)[\"']", read(gb)):
            out.append(Dep("maven", f"{m.group(1)}:{m.group(2)}", m.group(3), str(gb.relative_to(repo))))
    return out


COLLECTORS = {"npm": npm_deps, "pypi": pypi_deps, "go": go_deps, "crates": crates_deps,
              "pub": pub_deps, "nuget": nuget_deps, "maven": maven_deps}


# ---------------------------------------------------------------- live lookups
def lookup(d: Dep) -> None:
    q = urllib.parse.quote
    try:
        if d.ecosystem == "npm":
            meta = http(f"https://registry.npmjs.org/{q(d.name, safe='@')}",
                        accept="application/vnd.npm.install-v1+json")
            d.latest = meta["dist-tags"]["latest"]
            d.deprecated = ((meta.get("versions") or {}).get(d.current) or {}).get("deprecated") \
                or ((meta.get("versions") or {}).get(d.latest) or {}).get("deprecated")
            try:
                found = http(f"https://registry.npmjs.org/-/v1/search?text={q(d.name)}&size=5")
                d.released = next((o["package"].get("date") for o in found.get("objects", [])
                                   if o["package"]["name"] == d.name and o["package"]["version"] == d.latest), None)
            except (OSError, LookupError, KeyError, TypeError):
                pass
        elif d.ecosystem == "pypi":
            meta = http(f"https://pypi.org/pypi/{q(d.name)}/json")
            releases = {v: files for v, files in meta["releases"].items() if files}
            d.latest = max_stable(releases) or meta["info"]["version"]
            files = releases.get(d.latest) or []
            d.released = min((f["upload_time_iso_8601"] for f in files), default=None)
            cur_files = releases.get(d.current) or []
            if cur_files and all(f.get("yanked") for f in cur_files):
                d.deprecated = "version yanked: " + (cur_files[0].get("yanked_reason") or "no reason given")
            if (meta["info"].get("classifiers") or []) and any("Inactive" in c for c in meta["info"]["classifiers"]):
                d.deprecated = d.deprecated or "project marked Development Status :: Inactive"
        elif d.ecosystem == "go":
            meta = http(f"https://proxy.golang.org/{q(d.name.lower(), safe='/')}/@latest")
            d.latest, d.released = meta["Version"], meta.get("Time")
            if not is_prerelease(d.current) and is_prerelease(d.latest):
                d.latest = d.current
        elif d.ecosystem == "crates":
            meta = http(f"https://crates.io/api/v1/crates/{q(d.name)}")
            d.latest = meta["crate"].get("max_stable_version") or meta["crate"]["max_version"]
            for v in meta.get("versions", []):
                if v["num"] == d.latest:
                    d.released = v.get("created_at")
                if v["num"] == d.current and v.get("yanked"):
                    d.deprecated = "version yanked"
        elif d.ecosystem == "pub":
            meta = http(f"https://pub.dev/api/packages/{q(d.name)}")
            d.latest, d.released = meta["latest"]["version"], meta["latest"].get("published")
            if meta.get("isDiscontinued"):
                d.deprecated = "package discontinued" + (f", replaced by {meta['replacedBy']}" if meta.get("replacedBy") else "")
        elif d.ecosystem == "nuget":
            meta = http(f"https://api.nuget.org/v3-flatcontainer/{d.name.lower()}/index.json")
            d.latest = max_stable(meta["versions"])
        elif d.ecosystem == "maven":
            g, a = d.name.split(":", 1)
            path = f"{g.replace('.', '/')}/{a}/maven-metadata.xml"
            base = "https://dl.google.com/android/maven2/" if g.startswith(("androidx.", "com.android.", "com.google.android.")) \
                else "https://repo1.maven.org/maven2/"
            xml = http(base + path, accept="application/xml")
            versions = re.findall(r"<version>([^<]+)</version>", xml if isinstance(xml, str) else "")
            d.latest = max_stable(versions)
            m = re.search(r"<lastUpdated>(\d{8})", xml if isinstance(xml, str) else "")
            if m and d.latest == (re.search(r"<release>([^<]+)</release>", xml) or [None, None])[1]:
                d.released = f"{m.group(1)[:4]}-{m.group(1)[4:6]}-{m.group(1)[6:]}T00:00:00Z"
        d.kind = classify(d.current, d.latest) if d.latest else "unknown"
    except LookupError:
        d.error = "not found in public registry (private/renamed package?)"
    except (OSError, KeyError, TypeError, ValueError) as e:
        d.error = str(e) or type(e).__name__


OSV_ECOSYSTEM = {"npm": "npm", "pypi": "PyPI", "go": "Go", "crates": "crates.io", "pub": "Pub",
                 "nuget": "NuGet", "maven": "Maven"}


def vulnerabilities(deps: list[Dep]) -> dict[str, str]:
    """Fill Dep.vulns. Returns {ecosystem: source used or 'unavailable: reason'}."""
    status: dict[str, str] = {}
    exact = deps  # ranges are checked at their declared minimum and labelled approximate
    try:  # OSV covers every ecosystem in one call
        for i in range(0, len(exact), 500):
            chunk = exact[i:i + 500]
            res = http("https://api.osv.dev/v1/querybatch", data={"queries": [
                {"package": {"name": d.name, "ecosystem": OSV_ECOSYSTEM[d.ecosystem]}, "version": d.current}
                for d in chunk]})
            for d, r in zip(chunk, res.get("results", [])):
                d.vulns = [v["id"] for v in (r.get("vulns") or [])]
        return {e: "osv.dev" for e in {d.ecosystem for d in deps}}
    except (OSError, LookupError, KeyError, TypeError) as e:
        osv_error = str(e)
    npm = [d for d in exact if d.ecosystem == "npm"]
    if npm:
        try:
            res = http("https://registry.npmjs.org/-/npm/v1/security/advisories/bulk",
                       data={d.name: [d.current] for d in npm})
            for d in npm:
                d.vulns = [f"{a.get('severity', '?')}: {a.get('title', '')} ({a.get('url', '')})"
                           for a in (res.get(d.name) or [])]
            status["npm"] = "npm advisories (osv.dev unreachable)"
        except (OSError, LookupError, TypeError) as e:
            status["npm"] = f"unavailable: {e}"
    py = [d for d in exact if d.ecosystem == "pypi"]
    if py:
        def one(d: Dep):
            try:
                meta = http(f"https://pypi.org/pypi/{urllib.parse.quote(d.name)}/{urllib.parse.quote(d.current)}/json")
                d.vulns = [f"{v.get('id')} (fixed in {', '.join(v.get('fixed_in') or ['?'])})"
                           for v in (meta.get("vulnerabilities") or [])]
            except (OSError, LookupError, TypeError):
                pass
        with cf.ThreadPoolExecutor(8) as pool:
            list(pool.map(one, py))
        status["pypi"] = "PyPI advisories (osv.dev unreachable)"
    for e in {d.ecosystem for d in deps} - set(status):
        status[e] = f"unavailable ({osv_error}); run the ecosystem's audit tool"
    return status


# ---------------------------------------------------------------- runtimes
def runtimes(repo: Path) -> list[dict]:
    out = []
    for root in sorted({repo} | {p.parent for p in walk(repo, {"go.mod", "pubspec.yaml", ".nvmrc", ".node-version",
                                                             "rust-toolchain.toml", "rust-toolchain",
                                                             ".python-version", "package.json"})}):
        for item in runtimes_in(root):
            rel = str(root.relative_to(repo))
            item["declared_in"] = item["declared_in"] if rel == "." else f"{rel}/{item['declared_in']}"
            if (item["runtime"], item["current"]) not in {(o["runtime"], o["current"]) for o in out}:
                out.append(item)
    return out


def runtimes_in(repo: Path) -> list[dict]:
    out = []

    def add(name, current, source, fetch):
        if not current:
            return
        item = {"runtime": name, "current": current, "declared_in": source}
        try:
            item["latest"] = fetch()
            item["kind"] = classify(current, item["latest"]) if item["latest"] else "unknown"
        except (OSError, LookupError, KeyError, TypeError, ValueError) as e:
            item["error"], item["kind"] = str(e), "unknown"
        out.append(item)

    nvmrc = next((repo / f for f in (".nvmrc", ".node-version") if (repo / f).exists()), None)
    node_cur = spec_version(read(nvmrc)) if nvmrc else None
    if not node_cur and (repo / "package.json").exists():
        try:
            node_cur = spec_version((json.loads(read(repo / "package.json")).get("engines") or {}).get("node", ""))
        except json.JSONDecodeError:
            pass
    add("node", node_cur, nvmrc.name if nvmrc else "package.json engines",
        lambda: next(r["version"].lstrip("v") for r in http("https://nodejs.org/dist/index.json") if r.get("lts")))
    gomod = re.search(r"^go\s+(\S+)", read(repo / "go.mod"), re.M)
    add("go", gomod.group(1) if gomod else None, "go.mod",
        lambda: max_stable([m for m in re.findall(r"go(\d+\.\d+(?:\.\d+)?)\.linux-amd64",
                                                  http("https://proxy.golang.org/golang.org/toolchain/@v/list"))]))
    rt = read(repo / "rust-toolchain.toml") + read(repo / "rust-toolchain")
    rust_cur = spec_version((re.search(r"channel\s*=\s*\"([^\"]+)\"", rt) or [None, rt.strip()])[1] or "")
    add("rust", rust_cur, "rust-toolchain",
        lambda: re.search(r"\[pkg\.rust\]\s*\nversion\s*=\s*\"(\d+\.\d+\.\d+)",
                          http("https://static.rust-lang.org/dist/channel-rust-stable.toml", accept="text/plain")).group(1))
    fl = re.search(r"^\s+flutter:\s*['\"]?[>=^ ]*(\d+\.\d+\.\d+)", read(repo / "pubspec.yaml"), re.M)

    def flutter_latest():
        data = http("https://storage.googleapis.com/flutter_infra_release/releases/releases_linux.json")
        h = data["current_release"]["stable"]
        return next(r["version"] for r in data["releases"] if r["hash"] == h)
    add("flutter", fl.group(1) if fl else None, "pubspec.yaml environment", flutter_latest)
    pyv = read(repo / ".python-version").strip() or (load_toml(repo / "pyproject.toml").get("project", {}).get("requires-python") or "")
    add("python", spec_version(pyv), ".python-version / requires-python",
        lambda: max_stable([r["cycle"] + ".0" for r in http("https://endoflife.date/api/python.json")
                            if r.get("eol") and age_days(str(r["eol"]) + "T00:00:00Z") is not None
                            and age_days(str(r["eol"]) + "T00:00:00Z") < 0]))
    return out


# ---------------------------------------------------------------- report
def build(repo: Path, only: set[str] | None, with_runtimes: bool) -> dict:
    deps: list[Dep] = []
    for eco, fn in COLLECTORS.items():
        if not only or eco in only:
            deps += fn(repo)
    uniq: dict[tuple, Dep] = {}
    for d in deps:
        uniq.setdefault((d.ecosystem, d.name, d.current), d)
    deps = list(uniq.values())
    with cf.ThreadPoolExecutor(12) as pool:
        list(pool.map(lookup, deps))
    vuln_sources = vulnerabilities(deps) if deps else {}
    return {"repo": str(repo), "generated": NOW.isoformat(timespec="seconds"),
            "deps": [asdict(d) for d in deps], "vuln_sources": vuln_sources,
            "runtimes": runtimes(repo) if with_runtimes else []}


def render(report: dict, min_age: int, summary: bool) -> tuple[str, int]:
    deps = [Dep(**d) for d in report["deps"]]
    sec = [d for d in deps if d.vulns]
    dep_ = [d for d in deps if d.deprecated and not d.vulns]
    rts = [r for r in report["runtimes"] if r.get("kind") in ("major", "minor")]
    fresh = lambda d: (a := age_days(d.released)) is not None and a < min_age
    wait = [d for d in deps if d.kind in ("major", "minor", "patch") and fresh(d) and not d.vulns]
    flagged = sec + dep_ + wait
    major = [d for d in deps if d.kind == "major" and d not in flagged]
    minor = [d for d in deps if d.kind in ("minor", "patch") and d not in flagged]
    unknown = [d for d in deps if d.error]
    unknown_rt = [r for r in report["runtimes"] if r.get("error")]
    approx = sum(1 for d in deps if not d.exact)

    if summary:
        parts = [f"{len(sec)} security", f"{sum(1 for d in deps if d.deprecated)} deprecated", f"{len(rts)} runtime",
                 f"{len(major)} major", f"{len(minor)} minor/patch"]
        line = f"[precision-kit freshness {report['generated'][:10]}] " + ", ".join(parts)
        if unknown:
            line += f", {len(unknown)} unchecked"
        if sec or dep_:
            line += " -> run the live-modernize skill (security/deprecation first)."
        return line, (1 if sec or dep_ else 0)

    L = [f"Live freshness report for {report['repo']} at {report['generated']} (sources queried now)",
         f"{len(deps)} direct dependencies"
         + (f" ({approx} from declared ranges, no lockfile: versions approximate)" if approx else "")]
    for eco, src in sorted(report["vuln_sources"].items()):
        L.append(f"  advisories[{eco}]: {src}")

    def row(d: Dep, extra: str = "") -> str:
        a = age_days(d.released)
        return (f"  {d.ecosystem:<6} {d.name} {d.current} -> {d.latest or '?'}"
                + (f" (released {a}d ago)" if a is not None else "") + f"  [{d.manifest}]" + extra)

    def section(title: str, items: list, fmt) -> None:
        if items:
            L.append(f"\n## {title} ({len(items)})")
            L.extend(fmt(i) for i in items)

    section("SECURITY - known vulnerabilities in the version in use", sec,
            lambda d: row(d, "" if d.exact else "  (declared minimum; installed version may differ)")
            + (f"\n      - DEPRECATED: {d.deprecated}" if d.deprecated else "") + "\n" + "\n".join(f"      - {v}" for v in d.vulns[:8]))
    section("DEPRECATED / YANKED / DISCONTINUED", dep_, lambda d: row(d, f"\n      - {d.deprecated}"))
    section("RUNTIME behind current release", rts,
            lambda r: f"  {r['runtime']} {r['current']} -> {r['latest']} ({r['kind']})  [{r['declared_in']}]")
    section("MAJOR updates (read migration guide first)", sorted(major, key=lambda d: d.name), row)
    section("MINOR / PATCH updates", sorted(minor, key=lambda d: d.name), row)
    section(f"WAIT - newest release younger than {min_age} days (cooldown)", wait, row)
    section("UNKNOWN - live source unreachable, NOT checked", unknown + unknown_rt,
            lambda x: (f"  {x.ecosystem:<6} {x.name} {x.current}: {x.error}" if isinstance(x, Dep)
                       else f"  runtime {x['runtime']} {x['current']}: {x['error']}"))
    current = sum(1 for d in deps if d.kind in ("current", "ahead"))
    L.append(f"\nUp to date: {current}/{len(deps)} dependencies.")
    return "\n".join(L), (1 if sec or dep_ else 0)


def cache_file(repo: Path, cache_dir: Path) -> Path:
    h = hashlib.sha256(str(repo).encode())
    for f in sorted(walk(repo, {"package.json", "package-lock.json", "pyproject.toml", "requirements.txt",
                                "uv.lock", "poetry.lock", "go.mod", "Cargo.toml", "Cargo.lock", "pubspec.yaml",
                                "pubspec.lock", ".csproj", "pom.xml", "libs.versions.toml", "build.gradle",
                                "build.gradle.kts", ".nvmrc", ".python-version"})):
        h.update(str(f).encode() + read(f).encode())
    return cache_dir / f"freshness-{h.hexdigest()[:16]}.json"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("repo", nargs="?", default=".")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--summary", action="store_true", help="one line, for hooks")
    ap.add_argument("--min-age-days", type=int, default=7)
    ap.add_argument("--no-runtimes", action="store_true")
    ap.add_argument("--only", help="comma list of ecosystems: " + ",".join(COLLECTORS))
    ap.add_argument("--cache-ttl", type=int, default=0, help="reuse a report younger than SEC seconds")
    ap.add_argument("--cache-only", action="store_true", help="print cached report or nothing; never fetch")
    ap.add_argument("--cache-dir", type=Path, default=Path(os.environ.get(
        "CLAUDE_PLUGIN_DATA") or Path.home() / ".cache" / "precision-kit"))
    args = ap.parse_args()
    repo = Path(args.repo).resolve()
    only = set(args.only.split(",")) if args.only else None

    cf_path = cache_file(repo, args.cache_dir)
    report = None
    if (args.cache_ttl or args.cache_only) and cf_path.exists() and \
            (args.cache_only or time.time() - cf_path.stat().st_mtime < args.cache_ttl):
        report = json.loads(read(cf_path))
    if report is None:
        if args.cache_only:
            return 0
        report = build(repo, only, not args.no_runtimes)
        try:
            args.cache_dir.mkdir(parents=True, exist_ok=True)
            cf_path.write_text(json.dumps(report))
        except OSError:
            pass
    if args.json:
        print(json.dumps(report, indent=2))
        return 1 if any(d["vulns"] or d["deprecated"] for d in report["deps"]) else 0
    text, code = render(report, args.min_age_days, args.summary)
    if text:
        print(text)
    return code


if __name__ == "__main__":
    sys.exit(main())
