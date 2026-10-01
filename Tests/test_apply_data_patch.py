"""The update workflow's open-pr job applies a patch from the low-trust build job with this script."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from rtp_model import REPO_ROOT

SCRIPT = REPO_ROOT / ".github" / "scripts" / "apply_data_patch.py"

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


def git(repo: Path, *args: str, stdin: bytes | None = None) -> str:
    return subprocess.run(["git", "-c", "commit.gpgsign=false", "-c", "user.email=t@t", "-c", "user.name=t",
                           *args], cwd=repo, check=True, capture_output=True, input=stdin).stdout.decode()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    (repo / "CSV").mkdir(parents=True)
    (repo / ".github").mkdir()
    (repo / "CSV" / "rtp.csv").write_text("year,class,index,label\n")
    (repo / ".github" / "wf.yml").write_text("name: wf\n")
    (repo / "README.md").write_text("readme\n")
    (repo / ".gitignore").write_text(".venv/\n")
    git(repo, "init", "-q")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "base")
    return repo


def apply(repo: Path, patch: str) -> subprocess.CompletedProcess[str]:
    path = repo.parent / "changes.patch"
    path.write_text(patch)
    env = {**os.environ, "LC_ALL": "C.UTF-8", "LANG": "C.UTF-8"}
    return subprocess.run([sys.executable, str(SCRIPT), str(path)], cwd=repo, capture_output=True, text=True,
                          env=env)


def new_file(path: str, content: str = "x", mode: str = "100644") -> str:
    return (f"diff --git a/{path} b/{path}\nnew file mode {mode}\n--- /dev/null\n+++ b/{path}\n"
            f"@@ -0,0 +1 @@\n+{content}\n")


@pytest.fixture
def data_repo(repo: Path) -> Path:
    (repo / "JSON").mkdir()
    (repo / "JSON" / "2025.json").write_text("{}\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "data")
    return repo


def test_accepts_data_changes_and_leaves_them_unstaged(repo):
    patch = new_file("JSON/2027.json", "{}") + (
        "diff --git a/CSV/rtp.csv b/CSV/rtp.csv\n--- a/CSV/rtp.csv\n+++ b/CSV/rtp.csv\n"
        "@@ -1 +1,2 @@\n year,class,index,label\n+2027,SS,0.840,SS\n")
    result = apply(repo, patch)
    assert result.returncode == 0, result.stdout + result.stderr
    assert git(repo, "diff", "--cached", "--name-only") == ""
    assert sorted(git(repo, "status", "--porcelain", "--untracked-files=all").splitlines()) == [
        " M CSV/rtp.csv", "?? JSON/2027.json"]


@pytest.mark.parametrize(("patch", "message"), [
    (new_file(".github/workflows/evil CSV/x.yml"), "unexpected paths"),
    (new_file("JSON/x", "../../etc/passwd", mode="00120000"), "non-regular file modes"),
    (new_file(".venv/evil.pth", "import os"), "unexpected paths"),
    ("diff --git a/README.md b/README.md\ndeleted file mode 100644\n--- a/README.md\n+++ /dev/null\n"
     "@@ -1 +0,0 @@\n-readme\n", "unexpected paths"),
    (new_file("JSON/x", "../../etc/passwd", mode="0120000"), "non-regular file modes"),
    (new_file("JSON/x", "../../etc/passwd", mode="120000"), "non-regular file modes"),
    (new_file("CSV/run.sh", "echo", mode="100755"), "non-regular file modes"),
    (new_file("CSV/.gitattributes", "* -diff"), "unexpected paths"),
    (new_file("JSON/nested/x.json"), "unexpected paths"),
    ("diff --git a/.github/wf.yml b/JSON/wf.yml\nsimilarity index 100%\n"
     "rename from .github/wf.yml\nrename to JSON/wf.yml\n", "b'.github/wf.yml'"),
])
def test_rejects_non_data_changes(repo, patch, message):
    result = apply(repo, patch)
    assert result.returncode == 1
    assert message in result.stdout


def stage_raw_entry(repo: Path, mode: str, path: bytes) -> None:
    """Put an index entry whose name the local filesystem may not allow (e.g. invalid UTF-8)."""
    blob = git(repo, "hash-object", "-w", "--stdin", stdin=b"../../etc/passwd").strip()
    record = mode.encode() + b" " + blob.encode() + b"\t" + path + b"\0"
    git(repo, "update-index", "--add", "-z", "--index-info", stdin=record)


@pytest.mark.parametrize(("mode", "path", "message"), [
    ("120000", b"JSON/\xff", "non-regular file modes"),
    ("100644", b".github/workflows/\xff.yml", "unexpected paths"),
])
def test_rejects_invalid_utf8_entries(repo, mode, path, message):
    stage_raw_entry(repo, mode, path)
    result = apply(repo, new_file("JSON/2027.json", "{}"))
    assert result.returncode == 1
    assert message in result.stdout
    assert "\\xff" in result.stdout


def test_rejected_names_cannot_inject_workflow_commands(repo):
    stage_raw_entry(repo, "100644", b"JSON/a\n::stop-commands::token")
    result = apply(repo, new_file("JSON/2027.json", "{}"))
    assert result.returncode == 1
    assert not any(line.startswith("::stop-commands::") for line in result.stdout.splitlines())


def test_git_failure_aborts(repo):
    result = apply(repo, "not a patch\n")
    assert result.returncode != 0
    assert git(repo, "status", "--porcelain") == ""


def test_symlink_patch_never_creates_a_symlink(repo):
    result = apply(repo, new_file("JSON/x", "../../etc/passwd", mode="120000"))
    assert result.returncode == 1
    assert not (repo / "JSON" / "x").is_symlink()


@pytest.mark.parametrize(("patch", "message"), [
    ("diff --git a/JSON/2025.json b/JSON/2025.json\nold mode 100644\nnew mode 100755\n", "non-regular file modes"),
    ("diff --git a/JSON/2025.json b/JSON/2025.json\n--- a/JSON/2025.json\n+++ b/JSON/2025.json\n"
     "@@ -1 +1 @@\n-{}\n+{\"x\": 1}\n"
     "diff --git a/JSON/2025.json b/JSON/2025.json\nold mode 100644\nnew mode 100755\n", "non-regular file modes"),
    ("diff --git a/JSON/sub b/JSON/sub\nnew file mode 160000\nindex 0000000..1234567\n--- /dev/null\n+++ b/JSON/sub\n"
     "@@ -0,0 +1 @@\n+Subproject commit 1234567890123456789012345678901234567890\n", "non-regular file modes"),
    ("diff --git a/JSON/2025.json b/JSON/2025.json\ndeleted file mode 100644\n--- a/JSON/2025.json\n+++ /dev/null\n"
     "@@ -1 +0,0 @@\n-{}\n" + new_file("JSON", "/etc", mode="120000"), "non-regular file modes"),
])
def test_rejects_mode_and_type_changes_to_existing_data(data_repo, patch, message):
    result = apply(data_repo, patch)
    assert result.returncode == 1
    assert message in result.stdout


def test_copy_from_git_internals_is_refused(data_repo):
    patch = "diff --git a/.git/config b/JSON/c\nsimilarity index 100%\ncopy from .git/config\ncopy to JSON/c\n"
    result = apply(data_repo, patch)
    assert result.returncode != 0
    assert not (data_repo / "JSON" / "c").exists()


def test_accepts_data_deletion(data_repo):
    patch = ("diff --git a/JSON/2025.json b/JSON/2025.json\ndeleted file mode 100644\n--- a/JSON/2025.json\n"
             "+++ /dev/null\n@@ -1 +0,0 @@\n-{}\n")
    result = apply(data_repo, patch)
    assert result.returncode == 0, result.stdout + result.stderr
    assert git(data_repo, "status", "--porcelain") == " D JSON/2025.json\n"


def test_requires_patch_argument(repo):
    result = subprocess.run([sys.executable, str(SCRIPT)], cwd=repo, capture_output=True, text=True)
    assert result.returncode == 1
    assert "usage: apply_data_patch.py PATCH" in result.stderr
