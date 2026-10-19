"""Generate src/careerfit/ontology/skills_imported.yaml from open technology taxonomies.

    uv run python scripts/import_taxonomy.py --download --esco "scratch/ESCO dataset - v1.2.1 - classification - en - csv"

Offline, never in CI: the inputs are large downloads kept out of the repo (.cache/ and scratch/ are
gitignored). It writes two committed files next to skills.yaml:
- skills_imported.yaml: the generated skills. Don't edit it; put corrections in
  import_overrides.yaml and run this again.
- IMPORT_MANIFEST.yaml: input versions and hashes, how many names each rule kept or dropped, and
  lists to review (dropped everyday words, rejected ESCO labels, terms that contain a curated one).

Sources (see ontology/NOTICE.md for licences and the required statements):
- O*NET 31.0 "Software Skills": technology names used by occupations. Kept: any name used by a
  computer occupation (SOC 15-*), or flagged Hot Technology or In Demand anywhere.
- ESCO v1.2.1 digital skills collection: only "knowledge" concepts (tools and technologies, not
  "can do X" competences).

The rules, in the order they run:
1. Clean the name: drop a trailing " software"; an acronym that spells the words before it becomes
   the name ("Learning management system LMS" -> "lms", alias "learning management system"); a
   parenthetical acronym becomes an alias ("Adobe Experience Manager (AEM)"); an ESCO tag in
   parentheses is dropped ("Python (computer programming)"). Lowercase.
2. A vendor prefix ("Adobe Photoshop") adds the rest as an alias ("photoshop"), but only when the
   rest has a word that isn't an everyday word: "Microsoft Word" never yields the alias "word".
3. Drop names longer than 5 words or 40 characters, names with ",;" (lists), O*NET's own category
   labels ("Accounting software"), and names of 1 or 2 characters.
4. A one-word name that is an everyday word in the dictionary word list ("spark", "chef", "shiny")
   is dropped unless import_overrides.yaml keeps it: as a skill, it would match ordinary prose.
   Modern everyday words the 1934 word list lacks ("database", "workflow") count too.
   An ESCO name about knowledge of a topic ("concepts of telecommunications", "levels of software
   testing") is dropped too: a JD never names it as a tool.
5. ESCO alternative labels mix synonyms with related technologies ("computer programming" lists
   Lua, AWK and PowerShell; "computer vision" lists Keras), so none becomes an alias unless
   import_overrides.yaml allows it. An ESCO skill merges with an O*NET one only under the same name.
6. Anything already in skills.yaml (name or alias, any case) is not imported: a colliding name drops
   the skill, a colliding alias drops the alias. The hand-written list always wins.
"""

import argparse
import csv
import hashlib
import re
import sys
import urllib.request
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
ONTOLOGY_DIR = ROOT / "src" / "careerfit" / "ontology"
CACHE = ROOT / ".cache" / "taxonomy"
ONET_URL = "https://www.onetcenter.org/dl_files/database/db_31_0_csv/software_skills.csv"
ONET_VERSION = "31.0"
ESCO_VERSION = "v1.2.1"
WORDS = Path("/usr/share/dict/words")
VENDORS = ("adobe", "amazon web services", "amazon", "apache", "apple", "atlassian", "autodesk", "cisco", "ibm",
           "google", "microsoft", "oracle", "salesforce", "sap", "teradata", "vmware", "esri", "symantec", "emc")
MAX_WORDS, MAX_CHARS, MIN_CHARS = 5, 40, 3
_ACRONYM = re.compile(r"[A-Z][A-Z0-9]{1,7}")
_PAREN = re.compile(r"\s*\(([^()]*)\)\s*$")
# The macOS word list is Webster's 1934 edition: it has "team" but not "database". These modern
# everyday words count as everyday too, so "Database software" doesn't become the skill "database".
MODERN_EVERYDAY = frozenset("""
    antivirus app apps backup blog chatbot cybersecurity dashboard database desktop digitization ebook
    ecommerce email encryption firewall firmware freeware groupware internet intranet laptop malware
    middleware multimedia online podcast smartphone software spreadsheet spyware webinar webmail website
    wiki wifi workflow workstation
""".split()) | frozenset("""
    api crm cms dms edw erp gis hcm hris iam ide jdbc mdm odbc plm scm sdk sso tim
""".split())  # generic acronyms (and a first name): "sap erp" must not match every "ERP experience"
# ESCO names that describe knowledge about a topic, not a tool or technology a JD would name.
_ABSTRACT = re.compile(r"(concepts|principles|levels|types|methods|techniques|fundamentals|characteristics|"
                       r"features|functionalities|aspects|theory|theories) (of|for|in)\b|"
                       r"\b(functionalities|principles|characteristics)$")


@dataclass
class Candidate:
    name: str
    aliases: set[str] = field(default_factory=set)
    sources: set[str] = field(default_factory=set)


@dataclass
class Report:
    counts: Counter = field(default_factory=Counter)
    review: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))

    def drop(self, rule: str, term: str) -> None:
        self.counts[rule] += 1
        self.review[rule].add(term)


def common_words(path: Path) -> set[str]:
    """Everyday words: the lowercase entries of the word list (proper nouns there are capitalised)."""
    return {w for w in path.read_text(encoding="utf-8").split() if w.islower()}


def everyday(token: str, words: set[str]) -> bool:
    """A word of ordinary English, inflected forms included: the word list holds base forms only, so
    "teams" is checked as "team" (an alias "teams" would match "engineering teams" in every JD)."""
    forms = {token}
    if token.endswith("ies"):
        forms.add(token[:-3] + "y")
    if token.endswith("es"):
        forms.add(token[:-2])
    if token.endswith("s"):
        forms.add(token[:-1])
    if token.endswith("ed"):
        forms |= {token[:-2], token[:-1]}
    if token.endswith("ing"):
        forms |= {token[:-3], token[:-3] + "e"}
    return any(form in words or form in MODERN_EVERYDAY for form in forms)


def _norm(text: str) -> str:
    return " ".join(text.split()).lower()


def clean_onet(example: str) -> tuple[str, set[str]]:
    """O*NET's workplace example as (name, aliases), before the drop rules."""
    aliases: set[str] = set()
    text = _strip_software(" ".join(example.split()))  # before and after: "... (EMR) software"
    paren = _PAREN.search(text)
    if paren:  # "Adobe Experience Manager (AEM)": the acronym is an alias
        inner = paren.group(1).strip()
        text = text[:paren.start()].strip()
        if _ACRONYM.fullmatch(inner):
            aliases.add(inner.lower())
    words = _strip_software(text).split()
    for i, word in enumerate(words):
        # An acronym spelled out by the words right before it stands for them: keep the acronym, which is
        # what job descriptions write. At the end, the spelled-out phrase is the skill too, so an alias.
        n = len(word)
        if i >= n and _ACRONYM.fullmatch(word) and "".join(w[0] for w in words[i - n:i]).upper() == word:
            if i == len(words) - 1:  # the whole phrase, qualifiers included: "oracle java enterprise edition"
                aliases.add(_norm(" ".join(words[:i])))
            words = words[:i - n] + words[i:]
            break
    return _norm(" ".join(words)), aliases


def _strip_software(text: str) -> str:
    return text[: -len(" software")].strip() if text.lower().endswith(" software") else text


def clean_esco(label: str) -> str:
    return _norm(_PAREN.sub("", label))


def vendor_alias(name: str, words: set[str]) -> str | None:
    for vendor in VENDORS:
        if name.startswith(vendor + " "):
            rest = name[len(vendor) + 1:]
            if any(not everyday(token, words) for token in rest.split()) and len(rest) >= MIN_CHARS:
                return rest
            return None
    return None


def keepable(term: str) -> bool:
    return (term.isascii() and MIN_CHARS <= len(term) <= MAX_CHARS and len(term.split()) <= MAX_WORDS
            and not any(c in term for c in ",;"))


def build(onet_rows: list[dict], esco_rows: list[dict], curated: dict, words: set[str], overrides: dict,
          ) -> tuple[dict[str, Candidate], Report]:
    """The imported skills, keyed by name, plus what each rule did. Pure: no files, no network."""
    report = Report()
    keep_words = {_norm(w) for w in overrides.get("keep", [])}
    drop = {_norm(w) for w in overrides.get("drop", [])}
    rename = {_norm(k): _norm(v) for k, v in (overrides.get("rename") or {}).items()}
    alias_allow = {_norm(k): {_norm(a) for a in v} for k, v in (overrides.get("alias_allow") or {}).items()}
    taken = {_norm(t) for name, entry in curated.items() for t in (*entry.aliases, name)}
    categories = {_norm(r["Element Name"]) for r in onet_rows}

    by_example: dict[str, list[dict]] = defaultdict(list)
    for row in onet_rows:
        by_example[row["Workplace Example"]].append(row)
    report.counts["onet_distinct_examples"] = len(by_example)
    candidates: dict[str, Candidate] = {}
    for example, rows in sorted(by_example.items()):
        if not any(r["O*NET-SOC Code"].startswith("15-") or r["Hot Technology"] == "Y" or r["In Demand"] == "Y"
                   for r in rows):
            report.counts["onet_not_in_scope"] += 1
            continue
        name, aliases = clean_onet(example)
        if _norm(example) in categories or name in categories:
            report.drop("dropped_category_label", example)
            continue
        if alias := vendor_alias(name, words):
            aliases.add(alias)
        candidates.setdefault(name, Candidate(name)).aliases.update(aliases)
        candidates[name].sources.add("onet")

    for row in esco_rows:
        if row.get("skillType") != "knowledge":
            report.counts["esco_not_knowledge"] += 1
            continue
        name = clean_esco(row["preferredLabel"])
        if _ABSTRACT.search(name):
            report.drop("dropped_esco_abstract", name)
            continue
        labels = {clean_esco(a) for a in re.split(r"\n| \| ", row.get("altLabels") or "") if a.strip()}
        # ESCO's alternative labels mix synonyms with related technologies ("computer programming" lists
        # Lua, AWK and PowerShell), so none is an alias until a person allows it in import_overrides.yaml.
        accepted = labels & alias_allow.get(name, set())
        for rejected in sorted(labels - accepted):
            report.drop("esco_alias_not_reviewed", f"{name}: {rejected}")
        target = candidates.setdefault(name, Candidate(name))  # the same name as an O*NET skill: one skill
        target.sources.add("esco")
        target.aliases |= accepted

    candidates = merge_vendor_duplicates(candidates, report)
    result: dict[str, Candidate] = {}
    used: set[str] = set()
    for name in sorted(candidates):
        c = candidates[name]
        final = rename.get(name, name)
        if final in drop:
            report.drop("dropped_by_override", final)
            continue
        if not keepable(final):
            report.drop("dropped_shape", final)
            continue
        if len(final.split()) == 1 and everyday(final, words) and final not in keep_words:
            report.drop("dropped_everyday_word", final)
            continue
        if final in taken:
            report.drop("dropped_curated_collision", final)
            continue
        if final in result:  # a rename onto another skill's name; an alias clash is cleared below
            report.counts["merged_same_name"] += 1
            result[final].aliases |= c.aliases
            result[final].sources |= c.sources
            continue
        aliases = set()
        for alias in c.aliases | alias_allow.get(final, set()):
            if alias == final or not keepable(alias):
                continue
            if alias in taken:
                report.drop("alias_dropped_curated_collision", f"{final}: {alias}")
            elif alias in used or alias in candidates:
                report.drop("alias_dropped_imported_collision", f"{final}: {alias}")
            elif len(alias.split()) == 1 and everyday(alias, words):
                report.drop("alias_dropped_everyday_word", f"{final}: {alias}")
            else:
                aliases.add(alias)
        result[final] = Candidate(final, aliases, set(c.sources))
        used |= {final, *aliases}
    # The alias loop above can't see a later name, so drop any alias that became another skill's name.
    for c in result.values():
        clashes = {a for a in c.aliases if a in result and a != c.name}
        for alias in sorted(clashes):
            report.drop("alias_dropped_imported_collision", f"{c.name}: {alias}")
        c.aliases -= clashes
    for c in result.values():
        for term in (c.name, *c.aliases):
            inside = sorted(t for t in taken if re.search(rf"(?<!\w){re.escape(t)}(?!\w)", term) and t != term)
            if inside:
                report.review["contains_a_curated_term"].add(f"{term}: {', '.join(inside)}")
    report.counts["imported_skills"] = len(result)
    report.counts["imported_aliases"] = sum(len(c.aliases) for c in result.values())
    return result, report


def merge_vendor_duplicates(candidates: dict[str, Candidate], report: Report) -> dict[str, Candidate]:
    """"apache hadoop" (O*NET) and "hadoop" (ESCO) are one tool: merge into the vendor-free name, with
    the vendor name as an alias. Only when one vendor alone maps to that name: "apple ios" and
    "cisco ios" are different products, so neither may claim "ios", and both keep their full names."""
    claims: dict[str, list[str]] = defaultdict(list)
    for name, c in candidates.items():
        for vendor in VENDORS:
            if name.startswith(vendor + " "):
                claims[name[len(vendor) + 1:]].append(name)
                break
    merged = dict(candidates)
    for plain, vendored in sorted(claims.items()):
        if len(vendored) > 1:
            for name in vendored:
                merged[name].aliases.discard(plain)
                report.drop("alias_dropped_two_vendors", f"{name}: {plain}")
            continue
        if plain not in merged or vendored[0] not in merged:
            continue
        source = merged.pop(vendored[0])
        target = merged[plain]
        target.aliases |= (source.aliases | {vendored[0]}) - {plain}
        target.sources |= source.sources
        report.counts["merged_vendor_duplicate"] += 1
    return merged


def render_skills(skills: dict[str, Candidate]) -> str:
    lines = [
        "# GENERATED by scripts/import_taxonomy.py: do not edit by hand. Put corrections in",
        "# import_overrides.yaml and regenerate. Technology skills from open taxonomies (O*NET®, ESCO);",
        "# see NOTICE.md for the sources, licences and changes. The hand-written skills.yaml always wins:",
        "# an entry here whose name or alias is already in skills.yaml is ignored when the list is loaded.",
        "",
    ]
    if not skills:
        lines.append("{}")
    for name in sorted(skills):
        c = skills[name]
        lines += [f"{_q(name)}:", f"  aliases: [{', '.join(_q(a) for a in sorted(c.aliases))}]",
                  "  ambiguous: false", f"  sources: [{', '.join(s for s in ('onet', 'esco') if s in c.sources)}]"]
    return "\n".join(lines) + "\n"


def _q(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--onet", type=Path, default=CACHE / "onet_31_0_software_skills.csv")
    parser.add_argument("--download", action="store_true", help="fetch the O*NET file if it isn't cached")
    parser.add_argument("--esco", type=Path, help="folder of the ESCO v1.2.1 English CSV classification")
    parser.add_argument("--words", type=Path, default=WORDS, help="dictionary word list (one word per line)")
    parser.add_argument("--out", type=Path, default=ONTOLOGY_DIR)
    args = parser.parse_args(argv)

    sys.path.insert(0, str(ROOT / "src"))
    from careerfit.analyze.ontology import load_ontology

    if not args.onet.exists():
        if not args.download:
            print(f"{args.onet} not found: run with --download", file=sys.stderr)
            return 2
        args.onet.parent.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(ONET_URL, args.onet)
    onet_rows = list(csv.DictReader(args.onet.open(encoding="utf-8")))
    esco_rows: list[dict] = []
    esco_files = {}
    if args.esco:
        digital = args.esco / "digitalSkillsCollection_en.csv"
        esco_rows = list(csv.DictReader(digital.open(encoding="utf-8")))
        esco_files[digital.name] = _sha256(digital)
    overrides = yaml.safe_load((args.out / "import_overrides.yaml").read_text(encoding="utf-8")) or {}
    curated = load_ontology(args.out / "skills.yaml")
    skills, report = build(onet_rows, esco_rows, curated, common_words(args.words), overrides)

    (args.out / "skills_imported.yaml").write_text(render_skills(skills), encoding="utf-8")
    manifest = {
        "generated": date.today().isoformat(),
        "sources": {
            "onet": {"version": ONET_VERSION, "url": ONET_URL, "file": args.onet.name, "sha256": _sha256(args.onet),
                     "rows": len(onet_rows)},
            "esco": {"version": ESCO_VERSION, "files": esco_files, "rows": len(esco_rows)} if args.esco else None,
            "words": {"path": str(args.words), "sha256": _sha256(args.words)},
        },
        "counts": dict(sorted(report.counts.items())),
        "review": {rule: sorted(terms) for rule, terms in sorted(report.review.items())},
    }
    header = "# GENERATED by scripts/import_taxonomy.py with skills_imported.yaml. The review lists are for\n" \
             "# deciding overrides: a dropped everyday word that is really a tool can be kept in import_overrides.yaml.\n"
    (args.out / "IMPORT_MANIFEST.yaml").write_text(header + yaml.safe_dump(manifest, sort_keys=False, width=110),
                                                   encoding="utf-8")
    print(f"{report.counts['imported_skills']} skills, {report.counts['imported_aliases']} aliases written",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
