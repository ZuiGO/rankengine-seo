"""Git-based static site connector - modifies local HTML/TSX files and commits changes."""

import os
import re
import subprocess
from pathlib import Path
from typing import Any

from backend.services.connectors.base import BaseConnector
from backend.services.snapshot_service import capture_snapshot

REPO_ROOT = Path(__file__).parent.parent.parent.parent
SANDBOX_PATH = REPO_ROOT / "sandbox" / "static-replica"

class GitStaticConnector(BaseConnector):
    """Connector that writes directly to Next.js source files in the sandbox."""

    async def apply_field(self, suggestion: dict[str, Any]) -> tuple[bool, str, str, str, str]:
        """
        Applies a suggestion, commits, deploys to Vercel, and snapshots.
        Returns: (success, message, commit_hash, diff, preview_url)
        """
        try:
            field_type = suggestion.get("field_type")
            value = suggestion.get("suggested_value")
            suggestion_id = suggestion.get("id") or suggestion.get("suggestion_id")
            
            if not field_type or not value:
                return False, "Missing field_type or suggested_value", "", "", ""
                
            success, msg, modified_file = self._modify_source_file(field_type, value)
            if not success:
                return False, msg, "", "", ""
                
            # Git commit
            commit_hash, diff, git_err = self._commit_changes(f"Apply suggestion {suggestion_id}")
            if git_err:
                # Discard changes if commit failed (e.g., nothing to commit)
                subprocess.run(["git", "restore", "."], cwd=str(SANDBOX_PATH), capture_output=True)
                return False, f"Git commit failed: {git_err}", "", "", ""
                
            # Vercel Deploy
            deploy_success, preview_url = self._trigger_vercel_deploy()
            if not deploy_success:
                return False, f"Vercel deploy failed: {preview_url}", commit_hash, diff, ""
                
            # Snapshot
            job_id = suggestion.get("job_id")
            await capture_snapshot(preview_url, job_id, tag=f"apply_{suggestion_id}")
            
            return True, "Successfully applied and deployed", commit_hash, diff, preview_url
        except Exception as e:
            return False, str(e), "", "", ""

    async def read_field(self, page_url: str, field_type: str, selector: str) -> str:
        return ""

    async def rollback_field(self, suggestion: dict[str, Any], commit_hash: str) -> tuple[bool, str, str, str]:
        """
        Reverts a specific commit.
        Returns: (success, message, revert_commit_hash, preview_url)
        """
        try:
            suggestion_id = suggestion.get("id") or suggestion.get("suggestion_id")
            
            # Revert the commit
            result = subprocess.run(
                ["git", "revert", "--no-edit", commit_hash],
                cwd=str(SANDBOX_PATH),
                capture_output=True,
                text=True
            )
            if result.returncode != 0:
                # Maybe it was already reverted or conflicting
                return False, f"Git revert failed: {result.stderr}", "", ""
                
            rev_result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=str(SANDBOX_PATH),
                capture_output=True,
                text=True
            )
            new_commit = rev_result.stdout.strip()
            
            # Vercel Deploy
            deploy_success, preview_url = self._trigger_vercel_deploy()
            if not deploy_success:
                return False, f"Vercel deploy failed: {preview_url}", new_commit, ""
                
            # Snapshot
            job_id = suggestion.get("job_id")
            await capture_snapshot(preview_url, job_id, tag=f"revert_{suggestion_id}")
            
            return True, "Successfully reverted and deployed", new_commit, preview_url
        except Exception as e:
            return False, str(e), "", ""

    def _modify_source_file(self, field_type: str, new_value: str) -> tuple[bool, str, str]:
        page_file = SANDBOX_PATH / "src" / "app" / "products" / "railways" / "page.tsx"
        footer_file = SANDBOX_PATH / "src" / "components" / "Footer.tsx"
        hero_file = SANDBOX_PATH / "src" / "components" / "Hero.tsx"
        
        if field_type == "title":
            return self._regex_replace(
                page_file, 
                r"(title:\s*')[^']+(')", 
                f"\\g<1>{new_value}\\g<2>"
            )
        elif field_type == "meta_description":
            return self._regex_replace(
                page_file, 
                r"(description:\s*')[^']+(')", 
                f"\\g<1>{new_value}\\g<2>"
            )
        elif field_type == "alt_text":
            return self._regex_replace(
                hero_file,
                r'(<img[^>]+className="w-full h-64 object-cover hero-image rounded-lg"[^>]*)>',
                f'\\1 alt="{new_value}" />'
            )
        elif field_type == "footer_copyright":
            # Search for anything matching &copy; ... Fluid Controls Limited
            return self._regex_replace(
                footer_file,
                r"&copy;\s*\d{4}\s*Fluid Controls Limited[^\.]*\.",
                new_value
            )
        else:
            return False, f"Unsupported field_type: {field_type}", ""

    def _regex_replace(self, file_path: Path, pattern: str, replacement: str) -> tuple[bool, str, str]:
        if not file_path.exists():
            return False, f"File not found: {file_path}", ""
            
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
            
        new_content, count = re.subn(pattern, replacement, content)
        if count == 0:
            return False, f"Could not find matching pattern to replace in {file_path.name}", ""
            
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(new_content)
            
        return True, "", str(file_path)

    def _commit_changes(self, message: str) -> tuple[str, str, str]:
        # Check if there are changes
        status_res = subprocess.run(["git", "status", "--porcelain"], cwd=str(SANDBOX_PATH), capture_output=True, text=True)
        if not status_res.stdout.strip():
            return "", "", "No changes to commit"
            
        # Get diff
        subprocess.run(["git", "add", "."], cwd=str(SANDBOX_PATH), capture_output=True)
        diff_res = subprocess.run(["git", "diff", "--staged"], cwd=str(SANDBOX_PATH), capture_output=True, text=True)
        diff = diff_res.stdout
        
        # Commit
        commit_res = subprocess.run(["git", "commit", "-m", message], cwd=str(SANDBOX_PATH), capture_output=True, text=True)
        if commit_res.returncode != 0:
            return "", "", commit_res.stderr
            
        # Get hash
        rev_res = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(SANDBOX_PATH), capture_output=True, text=True)
        return rev_res.stdout.strip(), diff, ""

    def _trigger_vercel_deploy(self) -> tuple[bool, str]:
        res = subprocess.run(
            ["npx", "vercel", "--yes"],
            cwd=str(SANDBOX_PATH),
            capture_output=True,
            text=True
        )
        
        # The preview URL is usually printed to stdout or stderr depending on the CLI version
        output = res.stdout + res.stderr
        
        # Search for https://static-replica-[a-zA-Z0-9]+-jayesh15\.vercel\.app or similar
        match = re.search(r"(https://static-replica[^\s]+\.vercel\.app)", output)
        if match:
            return True, match.group(1)
        
        return False, output

