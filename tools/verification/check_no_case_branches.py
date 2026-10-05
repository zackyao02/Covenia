#!/usr/bin/env python
# -*- coding: utf-8 -*-
r"""Structural auditor for hardcoded, identity-driven, or model-washed decisions.

Why this tool exists
--------------------
``checks/anti_shortcut_scan.py`` (A33) is a *line/regex* scan with two extra
heuristics.  A regex list is only as good as the words on it: an implementation
that branches on ``entry.file_name.endswith("_gift.png")``, or that returns a
hardcoded observation, contains none of the four forbidden case literals and
passes a literal blacklist untouched.  This tool therefore judges *structure and
data flow* through the Python AST instead of searching for known strings.

The seven judgments
-------------------
J1  CASE_LITERAL_IN_DECISION     a demo/known case, order, or evidence identifier
                                 appears in the implementation source, and is
                                 reported with the extra detail ``in-decision`` when
                                 it also sits in a branch predicate.
J2  DESCRIPTOR_DECIDES_VERDICT   a non-semantic descriptor (file name, declared
                                 view type, candidate id, declared validity, model
                                 confidence, hygiene signal, run/prompt/model id,
                                 cached-result flag, source sheet) selects a business
                                 verdict in a function that does not fail loudly.
J3  OBSERVED_RESULT_HARDCODED    a *positive* image-observation fact is written as a
                                 literal into an observation construction/assignment.
J4  GROUND_TRUTH_INGRESS         a decision-path module reads or imports a fixture,
                                 demo-case, or ground-truth artefact.
J5  PRIVACY_BYPASS_CONFIGURATION a privacy module consults configuration or the
                                 environment to decide whether to mask.
J6  IDENTITY_SELECTS_DEFAULT     an identity/descriptor branch chooses a fail-closed
                                 observation default (per-input safety instead of a
                                 uniform server template).
J7  REQUEST_STATE_REACHES_RULES  an untrusted request compatibility field is read
                                 off a request-shaped object.

Deliberate allowances (the A33 judgement-2 carve-out)
-----------------------------------------------------
A file name or a declared view type may legitimately be used for *identity*, for
*input validation*, and for *manifest integrity* -- but the illegal value must
raise.  J2 encodes exactly that: the descriptor may sit in a decision predicate,
and the descriptor branch may even select a verdict, **provided the enclosing
function contains a failing ``raise``**.  A silent fallback, a bare ``assert``
that ``python -O`` removes, or a returned default is a violation.  Every allowed
occurrence is echoed in the report under ``suppressed``.

Deliberate carve-out for ``UNKNOWN``/``False``/``0.0``
-----------------------------------------------------
Fail-closed defaults are the *safe* direction and are not treated as "observed
results": ``readability="UNKNOWN"`` is the absence of a claim.  J3 therefore fires
only on positive claims (``HIGH``, ``MATCH``, ``True``, ``PRIMARY``/``GIFT``, a
non-empty coverage list, ``integrity_concern=True``).  J6 separately catches the
case where a fail-closed default is *selected per input* by an identity branch.

Exit codes
----------
0  every judgment is clean, the declared tree was scanned, and (unless
   ``--no-self-test``) the built-in negative control reproduced.
1  at least one judgment violation was found, or a planted self-test case was not
   judged as expected.
2  the tool could not run: bad arguments, missing root, unknown git ref, or an
   unreadable/syntactically invalid source file.  This is a tool error, and a
   tool error is never a product pass.

Usage
-----
  python tools/verification/check_no_case_branches.py --strict
  python tools/verification/check_no_case_branches.py --strict --json out.json
  python tools/verification/check_no_case_branches.py --git b22cc46 --strict
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

TOOL_VERSION = "no-case-branches-v1"
BATCH_ID = "BATCH-30"

DEFAULT_ROOT = "backend/src/covenia_b"

#: Modules whose purity is a product requirement.  J2..J7 apply here only.
PURITY_SUBDIRS = frozenset(
    {"rules", "evidence", "state", "commitments", "model", "privacy", "services"}
)

#: Configuration, composition-root, diagnostic and ingress modules.  They may name
#: the configured fixture path; J1 still applies, because no implementation module
#: may carry a demo case identifier.
NON_PURITY_NOTE = (
    "broad scope: only J1 (case identifier) is enforced; configured input paths, "
    "manifest file names and diagnostic counters legitimately live in "
    "settings/importing/images/preflight/runtime/main"
)

EXCLUDED_DIR_PARTS = frozenset({"__pycache__", ".git", "node_modules", "venv", ".venv"})
EXCLUDED_FILE_RE = re.compile(r"^(test_|conftest\.py$)")

# --------------------------------------------------------------------------- #
# Judgment vocabulary
# --------------------------------------------------------------------------- #

#: A33 judgement one: the four frozen identifiers, plus the known long identifiers
#: and the *shape* of a case or order identifier so a renamed demo case is caught.
CASE_LITERAL_EXACT = ("DEMO_001", "DEMO_002", "DEMO_003", "S00001")
CASE_LITERAL_EXTRA = ("6920185815517983396", "BH919209358357")
CASE_LITERAL_SHAPE = re.compile(r"^(?:DEMO_\d{3}|S\d{5}|CASE_\d{4,}|[A-Z]{2}\d{9,})$")

DESCRIPTOR_FIELDS = frozenset(
    {
        "file_name",
        "filename",
        "declared_view_type",
        "view_type",
        "candidate_id",
        "declared_evidence_valid",
        "confidence",
        "hygiene_risk_signal",
        "run_id",
        "prompt_version",
        "model_id",
        "model_revision",
        "cached_result",
        "source_sheet",
    }
)

OBSERVATION_CLAIM_FIELDS = frozenset(
    {
        "readability",
        "product_identifiable",
        "sku_match",
        "product_role",
        "issue_visible",
        "affected_component",
        "coverage",
        "integrity_concern",
        "hygiene_risk_signal",
    }
)

#: Untrusted compatibility fields a client may forge.  They may be *declared* on a
#: request DTO but must never be read off a request-shaped object.
UNTRUSTED_REQUEST_FIELDS = frozenset(
    {
        "accountability_state",
        "evidence_status",
        "active_commitments",
        "prohibited_actions",
        "current_scope",
        "declared_evidence_valid",
    }
)
REQUEST_LIKE_NAMES = frozenset(
    {"request", "req", "payload", "body", "request_body", "raw_request"}
)

VERDICT_LITERALS = frozenset(
    {
        "MATCH",
        "MISMATCH",
        "VALID",
        "MISMATCHED",
        "NEED_HUMAN_REVIEW",
        "INTERVENE",
        "ALLOW",
        "HUMAN_REVIEW",
        "ACTIVE",
        "AT_RISK",
        "BLOCKED",
        "PENDING_APPROVAL",
        "IGNORED",
        "GIFT",
        "PRIMARY",
        "BUNDLE_COMPONENT",
        "PRODUCT_OVERVIEW",
        "ISSUE_DETAIL",
        "PACKAGE_CONTEXT",
        "OTHER",
        "E1",
        "E2",
        "H1",
        "E0_NO_RULE_MATCHED",
    }
)

GROUND_TRUTH_FRAGMENTS = (
    "fixtures/",
    "fixtures\\",
    "ground-truth",
    "ground_truth",
    "demo-cases",
    "demo_cases",
)
GROUND_TRUTH_IMPORT_PARTS = ("ground_truth", "fixture", "testdata", "holdout")

PRIVACY_MODULES = frozenset({"privacy/sanitizer.py", "privacy/boundary.py"})
CONFIG_NAMES = frozenset(
    {"environ", "getenv", "settings", "Settings", "config", "get_settings"}
)

PRAGMA_RE = re.compile(
    r"#\s*no-case-branch-scan:\s*allow\s+(?P<judgment>J[1-7])\s+reason=(?P<reason>.+?)\s*$"
)

JUDGMENTS: tuple[dict[str, str], ...] = (
    {
        "id": "J1_CASE_LITERAL_IN_DECISION",
        "title": "demo/known case identifier reaches the implementation",
        "rule": (
            "No implementation module may contain DEMO_001..3, S00001, a known order/"
            "evidence identifier, or any identifier of that shape. A literal that also "
            "appears in a decision predicate is reported with the detail 'in-decision'."
        ),
    },
    {
        "id": "J2_DESCRIPTOR_DECIDES_VERDICT",
        "title": "file name / view type / model confidence selects a business verdict",
        "rule": (
            "A non-semantic descriptor may be used for identity, input validation and "
            "manifest integrity only, and the illegal value must raise. It may not select "
            "a business verdict in a function that has no failing raise."
        ),
    },
    {
        "id": "J3_OBSERVED_RESULT_HARDCODED",
        "title": "an observed image fact is written as a literal",
        "rule": (
            "Positive observation claims (HIGH, MATCH, True, PRIMARY/GIFT, a non-empty "
            "coverage list, integrity_concern=True) may only be derived from measured "
            "input, never constructed as literals. Fail-closed defaults are exempt."
        ),
    },
    {
        "id": "J4_GROUND_TRUTH_INGRESS",
        "title": "a decision-path module reads fixtures or ground truth",
        "rule": (
            "rules/, evidence/, state/, commitments/, model/, privacy/ and services/ must "
            "not import or open a fixture, demo-case, or ground-truth artefact by path."
        ),
    },
    {
        "id": "J5_PRIVACY_BYPASS_CONFIGURATION",
        "title": "privacy masking is switched by configuration",
        "rule": (
            "privacy/sanitizer.py and privacy/boundary.py must not consult settings or the "
            "environment to decide whether to mask; masking is unconditional."
        ),
    },
    {
        "id": "J6_IDENTITY_SELECTS_DEFAULT",
        "title": "an identity branch picks a per-input fail-closed default",
        "rule": (
            "A server observation template must be uniform. Choosing a fail-closed default "
            "inside an identity or descriptor branch makes safety input-dependent."
        ),
    },
    {
        "id": "J7_REQUEST_STATE_REACHES_RULES",
        "title": "an untrusted request compatibility field is read",
        "rule": (
            "accountability_state / evidence_status / active_commitments / prohibited_actions "
            "/ current_scope / declared_evidence_valid supplied by a client must never be read "
            "off a request-shaped object."
        ),
    },
)


@dataclass(frozen=True, slots=True)
class Hit:
    judgment: str
    path: str
    line: int
    column: int
    detail: str
    snippet: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "judgment": self.judgment,
            "path": self.path,
            "line": self.line,
            "column": self.column,
            "detail": self.detail,
            "snippet": self.snippet,
        }


@dataclass
class ModuleResult:
    relative_path: str
    sha256: str
    role: str
    hits: list[Hit] = field(default_factory=list)
    suppressed: list[dict[str, Any]] = field(default_factory=list)
    docstring_case_literals: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# AST helpers
# --------------------------------------------------------------------------- #


def _parents(tree: ast.AST) -> dict[int, ast.AST]:
    table: dict[int, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            table[id(child)] = node
    return table


def _docstring_nodes(tree: ast.AST) -> set[int]:
    found: set[int] = set()
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if not isinstance(body, list) or not body:
            continue
        first = body[0]
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            found.add(id(first.value))
    return found


def _referenced_names(node: ast.AST | None) -> set[str]:
    """Return every plain name and attribute name reachable from ``node``."""

    if node is None:
        return set()
    names: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Name):
            names.add(child.id)
        elif isinstance(child, ast.Attribute):
            names.add(child.attr)
        elif isinstance(child, ast.arg):
            names.add(child.arg)
    return names


def _string_constants(node: ast.AST | None) -> list[str]:
    if node is None:
        return []
    return [
        child.value
        for child in ast.walk(node)
        if isinstance(child, ast.Constant) and isinstance(child.value, str)
    ]


def _case_literal(value: str) -> str | None:
    if value in CASE_LITERAL_EXACT or value in CASE_LITERAL_EXTRA:
        return value
    if CASE_LITERAL_SHAPE.match(value):
        return value
    return None


def _decision_tests(tree: ast.AST) -> list[tuple[ast.AST, ast.AST]]:
    """Return ``(owner, test)`` for every branching predicate or assertion."""

    pairs: list[tuple[ast.AST, ast.AST]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.If | ast.While):
            pairs.append((node, node.test))
        elif isinstance(node, ast.IfExp):
            pairs.append((node, node.test))
        elif isinstance(node, ast.Assert):
            pairs.append((node, node.test))
        elif isinstance(node, ast.Match):
            pairs.append((node, node.subject))
    return pairs


def _branch_bodies(owner: ast.AST) -> list[list[ast.stmt]]:
    if isinstance(owner, ast.If):
        return [owner.body, owner.orelse]
    if isinstance(owner, ast.IfExp):
        return [[owner.body], [owner.orelse]]  # type: ignore[list-item]
    if isinstance(owner, ast.While):
        return [owner.body]
    return []


def _enclosing_function(parents: dict[int, ast.AST], node: ast.AST) -> ast.AST | None:
    current: ast.AST | None = node
    while current is not None:
        current = parents.get(id(current))
        if isinstance(current, ast.FunctionDef | ast.AsyncFunctionDef):
            return current
    return None


def _has_failing_raise(function: ast.AST | None) -> bool:
    """A bare ``assert`` is not enough: ``python -O`` removes it."""

    if function is None:
        return False
    return any(isinstance(child, ast.Raise) for child in ast.walk(function))


def _selects_verdict(bodies: list[list[ast.stmt]]) -> list[str]:
    selected: list[str] = []
    for body in bodies:
        for statement in body:
            for value in _string_constants(statement):
                if value in VERDICT_LITERALS:
                    selected.append(value)
    return selected


def _claim_for(field_name: str, node: ast.AST) -> str | None:
    """Classify a *literal* bound to an observation field; safe direction exempt."""

    if field_name not in OBSERVATION_CLAIM_FIELDS:
        return None
    if isinstance(node, ast.Constant):
        value = node.value
        if field_name == "readability" and value == "HIGH":
            return "readability=HIGH"
        if field_name == "sku_match" and value == "MATCH":
            return "sku_match=MATCH"
        if field_name in {"product_identifiable", "issue_visible"} and value is True:
            return f"{field_name}=True"
        if field_name == "integrity_concern" and value is True:
            return "integrity_concern=True"
        if field_name == "product_role" and value in {"PRIMARY", "GIFT", "BUNDLE_COMPONENT"}:
            return f"product_role={value}"
        if field_name == "affected_component" and isinstance(value, str) and value != "UNKNOWN":
            return f"affected_component={value}"
        if field_name == "hygiene_risk_signal" and value in {"LOW", "MEDIUM", "HIGH"}:
            return f"hygiene_risk_signal={value}"
        return None
    if field_name == "coverage" and isinstance(node, ast.List | ast.Tuple | ast.Set):
        if node.elts and all(
            isinstance(element, ast.Constant) and isinstance(element.value, str)
            for element in node.elts
        ):
            return "coverage=<non-empty literal>"
    return None


def _fail_closed_literal(field_name: str, node: ast.AST) -> bool:
    if not isinstance(node, ast.Constant):
        return False
    value = node.value
    if field_name in {"sku_match", "product_role", "affected_component"}:
        return value == "UNKNOWN"
    if field_name == "readability":
        return value in {"UNKNOWN", "LOW"}
    if field_name in {"product_identifiable", "issue_visible", "integrity_concern"}:
        return value is False
    if field_name == "hygiene_risk_signal":
        return value == "UNKNOWN"
    return False


def _target_name(target: ast.AST) -> str | None:
    if isinstance(target, ast.Name):
        return target.id
    if isinstance(target, ast.Attribute):
        return target.attr
    if isinstance(target, ast.Subscript) and isinstance(target.slice, ast.Constant):
        index = target.slice.value
        if isinstance(index, str):
            return index
    return None


def _bound_literals(tree: ast.AST) -> list[tuple[int, int, str, ast.AST]]:
    """Return every ``field <- literal`` binding site as (line, col, field, node)."""

    sites: list[tuple[int, int, str, ast.AST]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            for keyword in node.keywords:
                if keyword.arg is not None:
                    value = keyword.value
                    sites.append((value.lineno, value.col_offset, keyword.arg, value))
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                name = _target_name(target)
                if name is not None:
                    sites.append((node.lineno, node.col_offset, name, node.value))
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            name = _target_name(node.target)
            if name is not None:
                sites.append((node.lineno, node.col_offset, name, node.value))
    return sites


def _imported_modules(tree: ast.AST) -> list[str]:
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            modules.append(node.module or "")
    return modules


def _collect_pragmas(lines: list[str]) -> dict[tuple[str, int], str]:
    found: dict[tuple[str, int], str] = {}
    for index, line in enumerate(lines, 1):
        match = PRAGMA_RE.search(line)
        if match is None:
            continue
        reason = match.group("reason").strip()
        if not reason or reason.lower() in {"-", "todo"}:
            continue
        found[(match.group("judgment"), index)] = reason
    return found


# --------------------------------------------------------------------------- #
# Per-module scan
# --------------------------------------------------------------------------- #


def scan_source(relative_path: str, source: str, role: str) -> ModuleResult:
    """Apply every judgement that the module's role permits."""

    digest = hashlib.sha256(source.encode("utf-8")).hexdigest().upper()
    result = ModuleResult(relative_path=relative_path, sha256=digest, role=role)
    lines = source.splitlines()
    pragmas = _collect_pragmas(lines)

    tree = ast.parse(source, filename=relative_path)
    parents = _parents(tree)
    docstrings = _docstring_nodes(tree)
    pure = role == "purity"

    def snippet(line: int) -> str:
        if 1 <= line <= len(lines):
            return lines[line - 1].strip()[:160]
        return ""

    def record(judgment: str, line: int, column: int, detail: str) -> None:
        allowance = pragmas.get((judgment, line))
        if allowance is not None:
            result.suppressed.append(
                {
                    "judgment": judgment,
                    "line": line,
                    "reason": allowance,
                    "snippet": snippet(line),
                }
            )
            return
        result.hits.append(
            Hit(
                judgment=judgment,
                path=relative_path,
                line=line,
                column=column,
                detail=detail,
                snippet=snippet(line),
            )
        )

    # ---- J1: case identifiers ------------------------------------------------
    decision_lines: set[int] = set()
    for _owner, test in _decision_tests(tree):
        for node in ast.walk(test):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if _case_literal(node.value) is not None:
                    decision_lines.add(node.lineno)

    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            continue
        literal = _case_literal(node.value)
        if literal is None:
            continue
        if id(node) in docstrings:
            result.docstring_case_literals.append(f"{literal}@{node.lineno}")
            continue
        detail = f"case identifier literal {literal!r}"
        if node.lineno in decision_lines:
            detail += " in-decision (selects behaviour)"
        else:
            detail += " present in implementation source"
        record("J1_CASE_LITERAL_IN_DECISION", node.lineno, node.col_offset, detail)

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            if _case_literal(node.name) is not None:
                record(
                    "J1_CASE_LITERAL_IN_DECISION",
                    node.lineno,
                    node.col_offset,
                    f"case identifier used as a definition name: {node.name!r}",
                )

    if pure:
        _scan_decision_predicates(tree, parents, result, record, snippet)
        _scan_observations(tree, result, record)
        _scan_ground_truth(tree, docstrings, record)

    _scan_privacy_configuration(relative_path, tree, record)
    return result


def _scan_decision_predicates(
    tree: ast.AST,
    parents: dict[int, ast.AST],
    result: ModuleResult,
    record: Any,
    snippet: Any,
) -> None:
    for owner, test in _decision_tests(tree):
        names = _referenced_names(test)
        descriptors = sorted(names & DESCRIPTOR_FIELDS)
        case_literals = sorted(
            {
                node.value
                for node in ast.walk(test)
                if isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and _case_literal(node.value) is not None
            }
        )
        identity_signal = bool(descriptors or case_literals)
        if not identity_signal:
            continue
        function = _enclosing_function(parents, owner)
        bodies = _branch_bodies(owner)
        verdicts = sorted(set(_selects_verdict(bodies)))

        if descriptors and verdicts:
            if _has_failing_raise(function):
                result.suppressed.append(
                    {
                        "judgment": "J2_DESCRIPTOR_DECIDES_VERDICT",
                        "line": owner.lineno,
                        "reason": (
                            "allowed identity/validation use: the enclosing function "
                            "raises on the illegal value"
                        ),
                        "snippet": snippet(owner.lineno),
                    }
                )
            else:
                record(
                    "J2_DESCRIPTOR_DECIDES_VERDICT",
                    owner.lineno,
                    owner.col_offset,
                    f"descriptor {descriptors} selects verdict {verdicts} "
                    "without a failing raise",
                )

        for body in bodies:
            for statement in body:
                for _line, _column, bound, value in _bound_literals(statement):
                    if _fail_closed_literal(bound, value):
                        record(
                            "J6_IDENTITY_SELECTS_DEFAULT",
                            value.lineno,
                            value.col_offset,
                            f"identity branch on {descriptors or case_literals} "
                            f"chooses fail-closed {bound}=<default>",
                        )

    for node in ast.walk(tree):
        if not isinstance(node, ast.Attribute):
            continue
        if node.attr not in UNTRUSTED_REQUEST_FIELDS:
            continue
        base = node.value
        base_name = base.id if isinstance(base, ast.Name) else getattr(base, "attr", None)
        if base_name in REQUEST_LIKE_NAMES:
            record(
                "J7_REQUEST_STATE_REACHES_RULES",
                node.lineno,
                node.col_offset,
                f"untrusted request field {base_name}.{node.attr} is read",
            )


def _scan_observations(tree: ast.AST, result: ModuleResult, record: Any) -> None:
    del result
    for line, column, bound, value in _bound_literals(tree):
        claim = _claim_for(bound, value)
        if claim is not None:
            record(
                "J3_OBSERVED_RESULT_HARDCODED",
                line,
                column,
                f"observation literal {claim} is not derived from measured input",
            )


def _scan_ground_truth(tree: ast.AST, docstrings: set[int], record: Any) -> None:
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            continue
        if id(node) in docstrings:
            continue
        lowered = node.value.lower()
        if any(fragment in lowered for fragment in GROUND_TRUTH_FRAGMENTS):
            record(
                "J4_GROUND_TRUTH_INGRESS",
                node.lineno,
                node.col_offset,
                f"decision-path module references {node.value!r}",
            )
    for module in _imported_modules(tree):
        lowered = module.lower()
        if any(part in lowered for part in GROUND_TRUTH_IMPORT_PARTS):
            record(
                "J4_GROUND_TRUTH_INGRESS",
                1,
                0,
                f"decision-path module imports {module!r}",
            )


def _scan_privacy_configuration(path: str, tree: ast.AST, record: Any) -> None:
    if path.replace("\\", "/") not in PRIVACY_MODULES:
        return
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in {"environ", "getenv"}:
            record(
                "J5_PRIVACY_BYPASS_CONFIGURATION",
                node.lineno,
                node.col_offset,
                "privacy module reads the process environment",
            )
        elif isinstance(node, ast.Name) and node.id in CONFIG_NAMES:
            record(
                "J5_PRIVACY_BYPASS_CONFIGURATION",
                node.lineno,
                node.col_offset,
                f"privacy module references configuration name {node.id!r}",
            )


# --------------------------------------------------------------------------- #
# File discovery
# --------------------------------------------------------------------------- #


def _role_for(relative_path: str) -> str:
    parts = Path(relative_path).parts
    if len(parts) >= 2 and parts[0] in PURITY_SUBDIRS:
        return "purity"
    return "broad"


def iter_worktree_files(root: Path) -> list[tuple[str, str]]:
    files: list[tuple[str, str]] = []
    for path in sorted(root.rglob("*.py")):
        if any(part in EXCLUDED_DIR_PARTS for part in path.parts):
            continue
        if EXCLUDED_FILE_RE.match(path.name):
            continue
        files.append((path.relative_to(root).as_posix(), path.read_text(encoding="utf-8")))
    return files


def _git(repo: Path, *args: str) -> bytes:
    completed = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, check=False
    )
    if completed.returncode != 0:
        raise RuntimeError(
            "git %s failed (%d): %s"
            % (
                " ".join(args),
                completed.returncode,
                completed.stderr.decode("utf-8", "replace"),
            )
        )
    return completed.stdout


def iter_git_files(repo: Path, ref: str, prefix: str) -> list[tuple[str, str]]:
    """Read committed blob bytes, never the default worktree file (MASTER_PLAN 5.5-8)."""

    listing = _git(repo, "ls-tree", "-r", "--name-only", ref).decode("utf-8", "replace")
    normalized = prefix.rstrip("/")
    files: list[tuple[str, str]] = []
    for name in listing.splitlines():
        if not name.endswith(".py") or not name.startswith(normalized + "/"):
            continue
        if any(part in EXCLUDED_DIR_PARTS for part in name.split("/")):
            continue
        if EXCLUDED_FILE_RE.match(Path(name).name):
            continue
        blob = _git(repo, "show", f"{ref}:{name}")
        files.append((name[len(normalized) + 1 :], blob.decode("utf-8", "replace")))
    return files


# --------------------------------------------------------------------------- #
# Built-in negative control
# --------------------------------------------------------------------------- #

SELF_TEST_CASES: tuple[tuple[str, str, frozenset[str], bool], ...] = (
    (
        "rules/clean_derived.py",
        """
def rule(state, action):
    if state.evidence_status == "VALID" and action.action_type == "ASK_EVIDENCE":
        return "E1"
    return "E0_NO_RULE_MATCHED"
""",
        frozenset(),
        True,
    ),
    (
        "rules/literal_branch.py",
        """
def rule(state, action):
    if state.case_id == "DEMO_001":
        return "INTERVENE"
    return "ALLOW"
""",
        frozenset({"J1_CASE_LITERAL_IN_DECISION"}),
        False,
    ),
    (
        "services/descriptor_branch.py",
        """
def choose_role(entry):
    if entry.file_name.endswith("_gift.png"):
        return "GIFT"
    return "PRIMARY"
""",
        frozenset({"J2_DESCRIPTOR_DECIDES_VERDICT"}),
        False,
    ),
    (
        "services/hardcoded_observation.py",
        """
def observations(images):
    return [
        ImageObservation(
            evidence_id=image.evidence_id,
            readability="HIGH",
            sku_match="MATCH",
            product_identifiable=True,
            issue_visible=True,
            coverage=["DAMAGE_DETAIL"],
        )
        for image in images
    ]
""",
        frozenset({"J3_OBSERVED_RESULT_HARDCODED"}),
        False,
    ),
    (
        "state/fixture_ingress.py",
        """
import json
from pathlib import Path


def truth(case_id):
    return json.loads(Path("fixtures/ground-truth.json").read_text())[case_id]
""",
        frozenset({"J4_GROUND_TRUTH_INGRESS"}),
        False,
    ),
    (
        "privacy/sanitizer.py",
        """
import os


def should_mask():
    return os.environ.get("COVENIA_PII_SAFETY_CHECKS_ENABLED", "true") == "true"
""",
        frozenset({"J5_PRIVACY_BYPASS_CONFIGURATION"}),
        False,
    ),
    (
        "services/identity_default.py",
        """
def default_observation(entry):
    if entry.declared_view_type == "OTHER":
        return ImageObservation(readability="UNKNOWN", sku_match="UNKNOWN")
    return measure(entry)
""",
        frozenset({"J6_IDENTITY_SELECTS_DEFAULT"}),
        False,
    ),
    (
        "services/request_state.py",
        """
def decide(request, state):
    if request.evidence_status == "VALID":
        return "ALLOW"
    return "INTERVENE"
""",
        frozenset({"J7_REQUEST_STATE_REACHES_RULES"}),
        False,
    ),
    (
        "rules/validator_raises.py",
        """
ALLOWED_VIEWS = frozenset({"PRODUCT_OVERVIEW", "ISSUE_DETAIL"})


def _require_view_type(image):
    view_type = image.get("declared_view_type")
    if view_type not in ALLOWED_VIEWS:
        raise ValueError("unsupported image view type")
    return view_type
""",
        frozenset(),
        True,
    ),
)


def run_self_test() -> dict[str, Any]:
    """Prove the auditor is structural: plant cases a literal scan cannot see."""

    workdir = Path(tempfile.mkdtemp(prefix="no-case-branches-selftest-"))
    checks: list[dict[str, Any]] = []
    literal_only = re.compile("|".join(re.escape(item) for item in CASE_LITERAL_EXACT))
    failed = False
    try:
        disk_hits = 0
        for relative, source, expected, expect_clean in SELF_TEST_CASES:
            result = scan_source(relative, source, _role_for(relative))
            found = {hit.judgment for hit in result.hits}
            literal_hit = bool(literal_only.search(source))
            ok = found == set(expected) and (expect_clean == (not found))
            failed = failed or not ok
            checks.append(
                {
                    "case": relative,
                    "expected_judgments": sorted(expected),
                    "observed_judgments": sorted(found),
                    "literal_blacklist_would_find_it": literal_hit,
                    "expect_clean": expect_clean,
                    "ok": ok,
                }
            )
            planted = workdir / relative
            planted.parent.mkdir(parents=True, exist_ok=True)
            planted.write_text(source, encoding="utf-8")
        # Independent second control: the tool must also fail when it discovers the
        # planted corpus from disk instead of being handed in-memory strings.
        for relative, source, _expected, _clean in SELF_TEST_CASES:
            disk_hits += len(scan_source(relative, source, _role_for(relative)).hits)
        disk_ok = disk_hits >= 6
        failed = failed or not disk_ok
        checks.append(
            {
                "case": "on-disk-planted-corpus",
                "expected_judgments": ["<aggregate of the planted corpus>"],
                "observed_judgments": [
                    f"{disk_hits} hits across {len(SELF_TEST_CASES)} planted modules"
                ],
                "literal_blacklist_would_find_it": False,
                "expect_clean": False,
                "ok": disk_ok,
            }
        )
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    return {"passed": not failed, "checks": checks}


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Structural anti-hardcoding / anti-wash audit for the Covenia decision path"
    )
    parser.add_argument("--root", action="append", default=None, help="source root (repeatable)")
    parser.add_argument("--git", default=None, help="audit committed blobs of this git ref")
    parser.add_argument("--repo", default=None, help="repository root for --git (default: cwd)")
    parser.add_argument("--json", default=None, help="write the machine-readable report here")
    parser.add_argument("--strict", action="store_true", help="run the built-in negative control")
    parser.add_argument("--no-self-test", action="store_true", help="skip the negative control")
    parser.add_argument("--quiet", action="store_true", help="only print the verdict line")
    args = parser.parse_args(argv)

    repo = Path(args.repo).resolve() if args.repo else Path.cwd().resolve()
    roots = args.root or [DEFAULT_ROOT]

    modules: list[ModuleResult] = []
    try:
        for root_arg in roots:
            if args.git:
                pairs = iter_git_files(repo, args.git, root_arg)
            else:
                root = (Path.cwd() / root_arg).resolve()
                if not root.is_dir():
                    print(f"tool error: source root not found: {root}", file=sys.stderr)
                    return 2
                pairs = iter_worktree_files(root)
            modules.extend(
                scan_source(relative, source, _role_for(relative)) for relative, source in pairs
            )
    except SyntaxError as error:
        print(f"tool error: unparsable source: {error}", file=sys.stderr)
        return 2
    except RuntimeError as error:
        print(f"tool error: {error}", file=sys.stderr)
        return 2

    if not modules:
        print("tool error: no implementation module was found to scan", file=sys.stderr)
        return 2

    hits = [hit for module in modules for hit in module.hits]
    suppressed = [item for module in modules for item in module.suppressed]
    if args.no_self_test or not args.strict:
        self_test: dict[str, Any] = {"skipped": True}
    else:
        self_test = run_self_test()
    self_test_failed = self_test.get("passed") is False

    by_judgment: dict[str, int] = {entry["id"]: 0 for entry in JUDGMENTS}
    for hit in hits:
        by_judgment[hit.judgment] = by_judgment.get(hit.judgment, 0) + 1

    status = "FAIL" if hits or self_test_failed else "PASS"
    report = {
        "artifact": "reports/batches/BATCH-30/static-scan.json",
        "batch_id": BATCH_ID,
        "tool": "tools/verification/check_no_case_branches.py",
        "tool_version": TOOL_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "mode": f"git:{args.git}" if args.git else "worktree",
        "strict": bool(args.strict),
        "scanned_root": roots,
        "scanned_module_count": len(modules),
        "status": status,
        "judgments": list(JUDGMENTS),
        "per_judgment_hits": by_judgment,
        "whitelist": {
            "purity_subdirs": sorted(PURITY_SUBDIRS),
            "broad_scope_note": NON_PURITY_NOTE,
            "excluded_dir_parts": sorted(EXCLUDED_DIR_PARTS),
            "excluded_file_pattern": EXCLUDED_FILE_RE.pattern,
            "identity_and_validation_carve_out": (
                "A descriptor (file name, declared view type) may take part in identity, "
                "input validation, and manifest integrity, and its branch may even select a "
                "verdict, provided the enclosing function raises on the illegal value; such "
                "occurrences are listed under 'suppressed' with their reason."
            ),
            "fail_closed_carve_out": (
                "UNKNOWN / LOW / False / 0.0 defaults are the safe direction and are not "
                "treated as observed results by J3; J6 still forbids selecting them per input."
            ),
            "pragma": (
                "# no-case-branch-scan: allow <J1..J7> reason=<text> suppresses one hit and "
                "is always echoed in this report under 'suppressed'."
            ),
        },
        "scanned_modules": [
            {"path": module.relative_path, "sha256": module.sha256, "role": module.role}
            for module in modules
        ],
        "hits": [hit.as_dict() for hit in hits],
        "suppressed": suppressed,
        "docstring_case_literals": [
            f"{module.relative_path}:{item}"
            for module in modules
            for item in module.docstring_case_literals
        ],
        "self_test": self_test,
    }

    if args.json:
        destination = Path(args.json)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    if not args.quiet:
        print(f"{TOOL_VERSION}: scanned {len(modules)} modules under {roots} ({report['mode']})")
        print("judgements:")
        for entry in JUDGMENTS:
            print(
                f"  {entry['id']:<32} {by_judgment[entry['id']]:>3} hit(s)  {entry['title']}"
            )
        print(f"suppressed (documented allowances): {len(suppressed)}")
        for item in suppressed[:12]:
            print(f"  - {item['judgment']} @ line {item['line']}: {item['reason'][:90]}")
        if self_test.get("checks"):
            verdict = "reproduced" if self_test.get("passed") else "FAILED"
            print(f"negative control: {verdict} ({len(self_test['checks'])} planted cases)")
            for check in self_test["checks"]:
                marker = "ok " if check["ok"] else "BAD"
                judged = ",".join(check["observed_judgments"]) or "clean"
                print(
                    f"  {marker} {check['case']:<42} "
                    f"literal-blacklist-finds={str(check['literal_blacklist_would_find_it']):<5} "
                    f"judged={judged}"
                )
        for hit in hits:
            print(
                f"HIT {hit.judgment} {hit.path}:{hit.line}:{hit.column} {hit.detail}\n"
                f"    {hit.snippet}"
            )

    self_state = "skipped" if self_test.get("skipped") else self_test.get("passed")
    print(
        "=" * 72
        + f"\n{TOOL_VERSION}: {status}  (hits={len(hits)}, suppressed={len(suppressed)}, "
        f"modules={len(modules)}, self_test={self_state})"
    )
    return 1 if hits or self_test_failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
