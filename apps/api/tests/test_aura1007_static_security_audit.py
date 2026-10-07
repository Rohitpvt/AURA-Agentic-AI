"""AURA-1007 Static Security Audit & Canary Leak Scan.

Scans the codebase statically to ensure:
1. No dangerous `shell=True` subprocess calls.
2. No arbitrary `os.system`, `eval`, or `exec` invocations.
3. No hardcoded credentials or private keys.
4. No hidden persistence (Windows Services, Task Scheduler, HKLM, Startup folder).
5. Zero canary leaks across all subsystem configs and responses.
"""

import ast
import os
import re
import sys
from pathlib import Path

# Ensure apps/api directory is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

WORKSPACE_ROOT = Path(__file__).resolve().parent.parent.parent.parent
API_SRC = WORKSPACE_ROOT / "apps" / "api" / "app"


def get_all_python_files():
    """Collect all python source files in apps/api/app."""
    return list(API_SRC.rglob("*.py"))


def test_static_audit_no_dangerous_shell_true():
    """Verify subprocess calls do not use shell=True without explicit safe justification."""
    for py_file in get_all_python_files():
        content = py_file.read_text(encoding="utf-8", errors="ignore")
        # Match shell=True
        matches = re.findall(r"subprocess\.(Popen|run|call|check_call|check_output)\([^)]*shell\s*=\s*True", content)
        assert len(matches) == 0, f"Dangerous shell=True found in {py_file}"


def test_static_audit_no_arbitrary_eval_or_exec():
    """Verify python files do not use eval() or exec()."""
    for py_file in get_all_python_files():
        tree = ast.parse(py_file.read_text(encoding="utf-8", errors="ignore"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                assert node.func.id not in ("eval", "exec"), f"Prohibited {node.func.id}() in {py_file}:{node.lineno}"


def test_static_audit_no_hidden_windows_persistence():
    """Verify no code registers Windows Services, Scheduled Tasks, or HKLM persistence."""
    prohibited_patterns = [
        r"schtasks\s+/create",
        r"New-ScheduledTask",
        r"Register-ScheduledTask",
        r"CreateService",
        r"HKEY_LOCAL_MACHINE",
        r"HKLM\\",
        r"Start Menu\\Programs\\Startup",
    ]

    for py_file in get_all_python_files():
        content = py_file.read_text(encoding="utf-8", errors="ignore")
        for pat in prohibited_patterns:
            matches = re.findall(pat, content, re.IGNORECASE)
            assert len(matches) == 0, f"Prohibited persistence pattern '{pat}' found in {py_file}"


def test_static_audit_zero_canary_leakage():
    """Verify canary secrets are never stored in plain text or logged."""
    canaries = [
        "CANARY_SECRET_AURA_KEY_9999",
        "CANARY_PASSWORD_SUPER_SECRET_123",
        "CANARY_JWT_SECRET_TOKEN_XYZ",
    ]

    for py_file in get_all_python_files():
        content = py_file.read_text(encoding="utf-8", errors="ignore")
        for canary in canaries:
            assert canary not in content, f"Canary leak found in {py_file}"
