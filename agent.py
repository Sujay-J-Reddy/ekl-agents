"""
agent.py — EKL Agent
Reads a repo, maps requirements to files via Gemini, writes EKL changes, commits.
No crewai. No LiteLLM. Just google-generativeai + subprocess.
"""

import csv
import os
import subprocess
import time

from google import genai
from google.genai import types

DEFAULT_MODEL = "gemini-2.5-flash"


class EKLAgent:
    def __init__(
        self,
        repo_path: str,
        csv_path: str,
        commit_message: str,
        dry_run: bool = False,
    ):
        self.repo_path = repo_path
        self.csv_path = csv_path
        self.commit_message = commit_message
        self.dry_run = dry_run

        api_key = os.environ.get("GEMINI_API_KEY", "")
        if not api_key:
            raise EnvironmentError("GEMINI_API_KEY is not set.")
        model = os.environ.get("GEMINI_MODEL", DEFAULT_MODEL)
        self._client = genai.Client(api_key=api_key)
        self._model = model
        print(f"[LLM] model={model} | Google AI Studio")

    # ── Gemini ────────────────────────────────────────────────────────────────

    def _llm(self, prompt: str) -> str:
        for attempt in range(1, 4):
            try:
                return self._client.models.generate_content(
                    model=self._model,
                    contents=prompt
                ).text
            except Exception as exc:
                if "429" in str(exc) or "RESOURCE_EXHAUSTED" in str(exc):
                    wait = 60 * attempt
                    print(f"[WARN] Rate limit (attempt {attempt}/3). Waiting {wait}s...")
                    time.sleep(wait)
                else:
                    raise
        raise RuntimeError("Rate limit persisted after 3 retries.")

    # ── Repo ──────────────────────────────────────────────────────────────────

    def _read_repo_structure(self) -> str:
        ekl_exts = {".ekl", ".csc", ".rul", ".mfr", ".calc"}
        lines = [f"Repository root: {self.repo_path}", ""]
        all_ekl = []
        for root, dirs, files in os.walk(self.repo_path):
            dirs[:] = [d for d in sorted(dirs) if not d.startswith(".")]
            rel_root = os.path.relpath(root, self.repo_path)
            depth = 0 if rel_root == "." else rel_root.count(os.sep) + 1
            indent = "  " * depth
            if rel_root != ".":
                lines.append(f"{indent}{os.path.basename(root)}/")
            for f in sorted(files):
                ext = os.path.splitext(f)[1].lower()
                tag = " [EKL]" if ext in ekl_exts else ""
                lines.append(f"{'  ' * (depth + 1)}{f}{tag}")
                if ext in ekl_exts:
                    all_ekl.append(os.path.relpath(os.path.join(root, f), self.repo_path))
        lines += ["", f"EKL files ({len(all_ekl)}):"] + [f"  {f}" for f in all_ekl]
        return "\n".join(lines)

    def _read_file(self, relative_path: str) -> str:
        full = os.path.join(self.repo_path, relative_path)
        if not os.path.isfile(full):
            return ""
        with open(full, encoding="utf-8", errors="replace") as fh:
            return fh.read()

    def _write_file(self, relative_path: str, content: str):
        full = os.path.join(self.repo_path, relative_path)
        os.makedirs(os.path.dirname(full) or self.repo_path, exist_ok=True)
        with open(full, "w", encoding="utf-8") as fh:
            fh.write(content)
        print(f"  [WRITE] {relative_path} ({len(content)} chars)")

    # ── CSV ───────────────────────────────────────────────────────────────────

    def _load_requirements(self) -> list:
        with open(self.csv_path, newline="", encoding="utf-8-sig") as fh:
            rows = list(csv.DictReader(fh))
        if not rows:
            raise ValueError(f"CSV is empty: {self.csv_path}")
        normalised = [{k.strip().lower(): v.strip() for k, v in r.items()} for r in rows]
        print(f"[CSV] Columns: {list(normalised[0].keys())}")
        return normalised

    # ── Planning ──────────────────────────────────────────────────────────────

    def _plan_changes(self, requirements: list, repo_structure: str) -> list:
        """Ask Gemini which files to change for each requirement."""
        reqs_text = "\n".join(
            f"{r.get('id', '?')}: {r.get('description', '')} | "
            f"Acceptance: {r.get('acceptance criteria', '')} | "
            f"Priority: {r.get('priority', '')}"
            for r in requirements
        )

        prompt = f"""You are an expert EKL developer working on a 3DEXPERIENCE / CATIA repository.

REPOSITORY STRUCTURE:
{repo_structure}

REQUIREMENTS:
{reqs_text}

TASK:
For each requirement, decide which file(s) to modify or create.

Rules:
- Only reference files that exist in the repository structure, unless a CREATE is genuinely needed.
- A single requirement may affect multiple files — list each as a separate line.
- If a requirement has no EKL impact, skip it.

Respond in this EXACT format — one line per file change, nothing else:
REQ_ID|ACTION|relative/file/path

Where ACTION is MODIFY or CREATE. Example:
REQ-001|MODIFY|PLMAttributesPropagation_VPMReference.ekl
REQ-002|CREATE|rules/NewRule.ekl
"""
        print("[PLAN] Asking Gemini to map requirements to files...")
        response = self._llm(prompt).strip()
        print(f"[PLAN] Plan:\n{response}\n")

        plan = []
        for line in response.splitlines():
            line = line.strip()
            if not line or "|" not in line:
                continue
            parts = [p.strip() for p in line.split("|")]
            if len(parts) < 3:
                continue
            req_id, action, filepath = parts[0], parts[1].upper(), parts[2]
            req_row = next((r for r in requirements if r.get("id", "") == req_id), None)
            if req_row is None:
                print(f"  [WARN] No requirement found for id '{req_id}' — skipping.")
                continue
            plan.append({**req_row, "id": req_id, "action": action, "file": filepath})

        if not plan:
            raise ValueError(f"Gemini returned no valid plan.\nRaw:\n{response}")
        print(f"[PLAN] {len(plan)} change(s) planned.")
        return plan

    # ── EKL generation ────────────────────────────────────────────────────────

    def _generate_ekl(self, req: dict, existing: str, repo_structure: str) -> str:
        action = req.get("action", "MODIFY").upper()
        prompt = f"""You are an expert EKL (3DEXPERIENCE EKL / Essbase Kernel Language) developer.

TASK: {action} the file '{req["file"]}' to satisfy this requirement:
{req.get("description", "")}

Acceptance criteria: {req.get("acceptance criteria", "N/A")}

REPOSITORY STRUCTURE (for context):
{repo_structure}

EXISTING FILE CONTENT:
{existing if existing.strip() else "(empty — new file)"}

INSTRUCTIONS:
- Return ONLY the complete new file content — no markdown, no explanation, no code fences.
- For MODIFY: preserve all existing content; only add or change what the requirement asks.
- For CREATE: write a complete valid EKL file from scratch.
- Use correct EKL syntax for 3DEXPERIENCE.
- Start your response with the very first character of the file.
"""
        raw = self._llm(prompt).strip()
        # Strip accidental markdown fences
        for fence in ["```ekl", "```EKL", "```"]:
            if raw.startswith(fence):
                raw = raw[len(fence):]
                if raw.endswith("```"):
                    raw = raw[:-3]
                raw = raw.strip()
                break
        return raw

    # ── Git ───────────────────────────────────────────────────────────────────

    def _git_commit(self, changelog: str = "") -> str:
        import shutil
        git_exe = shutil.which("git")
        if git_exe is None:
            for candidate in [
                r"C:\Program Files\Git\bin\git.exe",
                r"C:\Program Files (x86)\Git\bin\git.exe",
                r"C:\Users\sujay.a.jayarama\AppData\Local\Programs\Git\cmd\git.exe",
                r"C:\Users\sujay.a.jayarama\AppData\Local\Programs\Git\bin\git.exe",
            ]:
                if os.path.isfile(candidate):
                    git_exe = candidate
                    break
        if git_exe is None:
            return "[GIT ERROR] git not found. Add Git to PATH and restart."

        def git(*args):
            r = subprocess.run(
                [git_exe, *args], cwd=self.repo_path, capture_output=True, text=True
            )
            return r.returncode, r.stdout.strip(), r.stderr.strip()

        if self.dry_run:
            _, status, _ = git("status", "--short")
            _, diff, _ = git("diff", "--stat", "HEAD")
            return f"[DRY RUN] Would commit:\n{status}\n{diff}"

        _, status, _ = git("status", "--short")
        if not status:
            return "[GIT] Nothing to commit — working tree is clean."

        rc, _, err = git("add", "-A")
        if rc != 0:
            return f"[GIT ERROR] git add -A failed:\n{err}"

        message = self.commit_message
        if changelog.strip():
            message = f"{message}\n\n{changelog.strip()[:2000]}"

        rc, out, err = git("commit", "-m", message)
        if rc != 0:
            return f"[GIT ERROR] git commit failed:\n{err}\n{out}"

        _, sha, _ = git("rev-parse", "--short", "HEAD")
        _, diff, _ = git("diff", "--stat", "HEAD~1", "HEAD")
        return (
            f"[GIT] Commit successful!\n"
            f"Hash : {sha}\n"
            f"Msg  : {self.commit_message}\n"
            f"Diff :\n{diff}"
        )

    # ── Run ───────────────────────────────────────────────────────────────────

    def run(self) -> str:
        print("\n[STEP 1] Reading repository structure...")
        repo_structure = self._read_repo_structure()
        print(repo_structure)

        print("\n[STEP 2] Loading requirements CSV...")
        requirements = self._load_requirements()
        for r in requirements:
            print(f"  {r.get('id', '?')} | {r.get('description', '')[:70]}")

        print("\n[STEP 3] Planning file changes...")
        plan = self._plan_changes(requirements, repo_structure)
        for p in plan:
            print(f"  {p.get('id', '?')} | {p.get('action', '?')} | {p.get('file', '?')}")

        changelog_lines = []

        print("\n[STEP 4] Generating and writing EKL changes...")
        for req in plan:
            req_id  = req.get("id", "?")
            action  = req.get("action", "MODIFY").upper()
            relpath = req.get("file", "").strip()

            print(f"\n  [{req_id}] {action} → {relpath}")

            if action == "DELETE":
                full = os.path.join(self.repo_path, relpath)
                if os.path.isfile(full):
                    if not self.dry_run:
                        os.remove(full)
                    print(f"  [DELETE] {relpath}")
                else:
                    print(f"  [SKIP] Not found: {relpath}")
                changelog_lines.append(f"{req_id}: DELETE {relpath}")
                continue

            existing = self._read_file(relpath) if action == "MODIFY" else ""
            print(f"  Calling Gemini...")
            new_content = self._generate_ekl(req, existing, repo_structure)

            if self.dry_run:
                print(f"  [DRY RUN] Would write {len(new_content)} chars to {relpath}")
                print(new_content[:300])
            else:
                self._write_file(relpath, new_content)

            changelog_lines.append(
                f"{req_id}: {action} {relpath}\n"
                f"  Desc: {req.get('description', '')}\n"
                f"  Written: {len(new_content)} chars"
            )

        changelog = "\n\n".join(changelog_lines)

        print("\n[STEP 5] Committing to git...")
        commit_result = self._git_commit(changelog)
        print(commit_result)

        return f"=== CHANGE LOG ===\n{changelog}\n\n=== GIT ===\n{commit_result}"