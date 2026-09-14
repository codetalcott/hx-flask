"""
Generate hx_vocab.py from the htmx 4 source tree.

A hand-listed vocabulary is where a linter's false errors come from: the first
draft of this project flagged ``revealed`` and ``hx-on::after:swap``, both valid
htmx 4. So every list below is read from htmx's own files, and this script
fails loudly when a file it relies on has moved.

    HTMX_SRC=~/path/to/htmx-4.0.0 python tools/gen_vocab.py
"""

from __future__ import annotations

import os
import pathlib
import re
import sys

SRC = pathlib.Path(os.environ.get("HTMX_SRC", "~/projects/convergence/examples/material/htmx-4.0.0")).expanduser()
OUT = pathlib.Path(__file__).resolve().parent.parent / "hx_vocab.py"

ATTR_NAME = re.compile(r"`(hx-[a-z-]+(?::[a-z-]+)*)`")
TABLE_ROW = re.compile(r"^\|\s*`([^`]+)`\s*\|\s*(.*?)\s*\|")


def must(path: pathlib.Path) -> str:
    if not path.exists():
        sys.exit(f"gen_vocab: {path} is missing; point HTMX_SRC at an htmx 4 checkout")
    return path.read_text()


def core_attributes() -> list[str]:
    names = []
    for f in sorted((SRC / "docs/reference/01-attributes").glob("*.md")):
        if f.name == "index.md":
            continue
        names.append(re.sub(r"^\d+-", "", f.stem))
    return names


def extension_attributes(core: set[str]) -> dict[str, list[str]]:
    result = {}
    for f in sorted((SRC / "docs/extensions").glob("*.md")):
        ext = re.sub(r"^\d+-", "", f.stem)
        found = set(ATTR_NAME.findall(f.read_text()))
        # the extension's own attributes: not core, and not another extension's
        own = sorted(n for n in found if n.split(":")[0] not in core and n != "hx-ext")
        # keep only names that belong to this extension by prefix, plus a few documented aliases
        base = ext.replace("htmx-2-compat", "")
        own = [n for n in own if not base or n.startswith(f"hx-{base.split('-', 1)[-1]}") or n.startswith(ext) or n.split(":")[0] == ext]
        if own:
            result[ext] = own
    return result


def extension_names() -> dict[str, str]:
    """Every name an extension answers to -> its file name. htmx registers some under the file name
    (hx-live) and some under a short name (sse, ws, upsert), and ``htmx.config.extensions`` wants the
    registered one; both mean the same extension."""
    names = {}
    for f in sorted((SRC / "src/ext").glob("*.js")):
        m = re.search(r"""registerExtension\(\s*['"]([\w-]+)['"]""", f.read_text())
        if not m:
            sys.exit(f"gen_vocab: {f.name} registers no extension")
        names.setdefault(f.stem, f.stem)
        names.setdefault(m.group(1), f.stem)
    for short, stem in (("sse", "hx-sse"), ("ws", "hx-ws")):
        if names.get(short) != stem:
            sys.exit(f"gen_vocab: {stem}.js no longer registers as {short}")
    return dict(sorted(names.items()))


def removed_attributes() -> dict[str, str]:
    """Rename tables in both skill files; a name that is core in htmx 4 is not removed."""
    core = set(core_attributes())
    ext_names = {a for attrs in extension_attributes(core).values() for a in attrs}
    removed = {}
    for doc in ("docs/skills/htmx-upgrade-from-htmx2.md", "docs/skills/htmx-guidance.md"):
        for line in must(SRC / doc).splitlines():
            m = TABLE_ROW.match(line)
            if not m:
                continue
            old, rest = m.group(1), m.group(2)
            name = old.split("=")[0].split(" ")[0].strip()
            if not re.fullmatch(r"hx-[a-z-]+", name) or name in core or name in ext_names:
                continue
            replacement = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", rest.split("|")[0]).strip().strip("`")
            removed.setdefault(name, replacement)
    for must_have in ("hx-ext", "hx-vars", "hx-disabled-elt", "hx-disinherit", "hx-request"):
        if must_have not in removed:
            sys.exit(f"gen_vocab: {must_have} not found in the rename tables")
    return removed


def swap_styles() -> tuple[list[str], dict[str, str], dict[str, str]]:
    """Headings under '## Swap Methods' in the hx-swap reference, checked against src/htmx.js."""
    js = must(SRC / "src/htmx.js")
    doc = must(SRC / "docs/reference/01-attributes/08-hx-swap.md")
    section = doc.split("## Swap Methods", 1)[1].split("\n## ", 1)[0]
    aliases = dict(re.findall(r"style === '(\w+)' \? '(\w+)'", js))
    ext_styles = {"upsert": "hx-upsert", "download": "hx-download"}
    styles = []
    for heading in re.findall(r"^### (.+)$", section, re.M):
        for name in re.findall(r"`([A-Za-z]+)`", heading):
            if name in aliases or name in ext_styles:
                continue
            if f"'{name}'" not in js:
                sys.exit(f"gen_vocab: swap style {name} is documented but absent from the source")
            styles.append(name)
    for style, ext in ext_styles.items():
        ext_doc = SRC / "docs/extensions"
        if not any(style in f.read_text() for f in ext_doc.glob(f"*{ext}.md")):
            sys.exit(f"gen_vocab: swap style {style} not documented by {ext}")
    return styles, aliases, ext_styles


def swap_modifiers() -> list[str]:
    doc = must(SRC / "docs/reference/01-attributes/08-hx-swap.md")
    js = must(SRC / "src/htmx.js")
    section = doc.split("## Modifiers", 1)[1].split("\n## ", 1)[0]
    documented = set(re.findall(r"^### `([a-zA-Z]+)`", section, re.M))
    in_source = set(re.findall(r"swapSpec\??\.([a-zA-Z]+)", js)) - {"style"}
    undocumented_but_real = in_source - documented  # showTarget, scrollTarget
    ghosts = documented - in_source
    if ghosts:
        sys.exit(f"gen_vocab: swap modifiers documented but absent from the source: {ghosts}")
    return sorted(documented | undocumented_but_real)


def trigger_modifiers() -> list[str]:
    guidance = must(SRC / "docs/skills/htmx-guidance.md")
    js = must(SRC / "src/htmx.js")
    names = []
    in_table = False
    for line in guidance.splitlines():
        m = TABLE_ROW.match(line)
        if m and m.group(1) == "once":
            in_table = True
        if in_table:
            if not m:
                break
            names.append(m.group(1).split(":")[0].split(" ")[0])
    for extra in ("consume", "root", "rootMargin", "threshold", "from", "target", "delay", "throttle"):
        if extra not in names:
            names.append(extra)
    for n in names:
        if not re.search(rf"spec\.{n}\b", js):
            sys.exit(f"gen_vocab: trigger modifier {n} is documented but not in the source")
    return sorted(set(names))


def htmx2_event_names() -> dict[str, str]:
    """The rename table in whats-new (new names are links), plus every camelCase
    name the htmx-2-compat extension re-fires, so nothing is missed."""
    text = must(SRC / "docs/whats-new-in-htmx-4.md")
    compat = must(SRC / "src/ext/htmx-2-compat.js")
    row = re.compile(r"^\|\s*`(htmx:[A-Za-z:]+)`\s*\|\s*(?:\[`([^`]+)`\]\([^)]*\)|`([^`]+)`|([^|]*?))\s*\|")
    renames = {}
    for line in text.splitlines():
        m = row.match(line)
        if m and re.search(r"[A-Z]", m.group(1)):
            new = (m.group(2) or m.group(3) or m.group(4) or "").strip()
            renames[m.group(1)] = new if new and new not in ("—", "-") else "(removed)"
    for name in re.findall(r'maybeRetriggerEvent\(elt, "(htmx:[A-Za-z]+)"', compat):
        renames.setdefault(name, "(see htmx-2-compat.js)")
    if len(renames) < 10:
        sys.exit("gen_vocab: the event rename table in whats-new-in-htmx-4.md was not found")
    return renames


def main() -> None:
    core = core_attributes()
    ext = extension_attributes(set(core))
    ext_names = extension_names()
    removed = removed_attributes()
    styles, aliases, ext_styles = swap_styles()
    smods = swap_modifiers()
    tmods = trigger_modifiers()
    events = htmx2_event_names()
    version = re.search(r'"version":\s*"([^"]+)"', must(SRC / "package.json")).group(1) if (SRC / "package.json").exists() else "4.0.0"

    def lit(v):
        return repr(v)

    body = f'''"""
htmx {version} vocabulary. GENERATED by tools/gen_vocab.py from the htmx source tree;
do not edit by hand. Regenerate against a new htmx release.
"""

VERSION = {lit(version)}

# docs/reference/01-attributes/*.md
CORE_ATTRIBUTES = {lit(core)}

# docs/extensions/*.md, the attributes each extension adds
EXTENSION_ATTRIBUTES = {lit(ext)}

# src/ext/*.js: every name an extension answers to (file name, or the name it registers) -> file name
EXTENSION_NAMES = {lit(ext_names)}

# Attribute families: any name starting with one of these is valid syntax.
FAMILIES = ("hx-on", "hx-status:", "hx-live", "hx-sse", "hx-ws", "hx-multipart")

# Attributes that may sit on an ancestor and reach descendants with :inherited.
INHERITABLE = ("hx-target", "hx-swap", "hx-confirm", "hx-boost", "hx-sync", "hx-indicator",
               "hx-include", "hx-push-url", "hx-replace-url", "hx-headers", "hx-vals",
               "hx-disable", "hx-select", "hx-select-oob", "hx-encoding", "hx-validate",
               "hx-config", "hx-preload", "hx-pending", "hx-prompt", "hx-targets")

REQUEST_ATTRIBUTES = ("hx-get", "hx-post", "hx-put", "hx-patch", "hx-delete", "hx-query", "hx-action")

# docs/skills/htmx-upgrade-from-htmx2.md: htmx 2 names and what replaced them
REMOVED_ATTRIBUTES = {lit(removed)}

# docs/skills/htmx-guidance.md swap table, plus the aliases in src/htmx.js
SWAP_STYLES = {lit(styles)}
SWAP_ALIASES = {lit(aliases)}
EXTENSION_SWAP_STYLES = {lit(ext_styles)}

# docs/reference/01-attributes/08-hx-swap.md, confirmed against src/htmx.js
SWAP_MODIFIERS = {lit(smods)}

# docs/skills/htmx-guidance.md trigger table, confirmed against src/htmx.js
TRIGGER_MODIFIERS = {lit(tmods)}
SPECIAL_TRIGGERS = ("load", "every", "intersect", "revealed")

# docs/whats-new-in-htmx-4.md: htmx 2 camelCase event names and their htmx 4 form
HTMX2_EVENT_NAMES = {lit(events)}
'''
    OUT.write_text(body)
    print(f"wrote {OUT}: {len(core)} core attrs, {sum(len(v) for v in ext.values())} extension attrs in {len(ext)} extensions, {len(ext_names)} extension names, "
          f"{len(removed)} removed, {len(styles)} swap styles, {len(smods)} swap modifiers, {len(tmods)} trigger modifiers, {len(events)} event renames")


if __name__ == "__main__":
    main()
