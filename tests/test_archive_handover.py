"""tests/test_archive_handover.py — #1650: the handover archive tool + the in-tree ratchet.

Two subjects, both belonging to the same contract:

  A. `scripts/archive_handover.py` — /wrap step (a). It must append the outgoing handover
     to the `session-archive` branch WITHOUT checking that branch out or touching the
     working tree (parallel worktrees are the norm here; a checkout would be the
     documented worktree-pollution incident class), and it must refuse rather than
     clobber.

  B. The in-tree ratchet — `handovers/` on `main` carries exactly the live pointer
     (`HANDOVER_LATEST.md`) plus its README, and `.gitignore` keeps it that way. This is
     the half that stops the 489-file regrowth #1650 just paid down.

Everything here is offline: the git tests build a throwaway repo in tmp_path, so no
network, no origin, no shared state.
"""

import importlib.util
import os
import subprocess

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
_SCRIPT = os.path.join(_REPO, "scripts", "archive_handover.py")


def _load_module():
    spec = importlib.util.spec_from_file_location("archive_handover", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ah = _load_module()


def _git(repo, *args):
    return subprocess.run(["git", *args], cwd=str(repo), capture_output=True, text=True, check=True).stdout.strip()


@pytest.fixture
def fake_repo(tmp_path, monkeypatch):
    """A throwaway git repo with a seeded `session-archive` branch and a live handover."""
    repo = tmp_path / "repo"
    (repo / "handovers").mkdir(parents=True)
    _git(repo.parent, "init", "-q", "-b", "main", str(repo))
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "handovers" / "HANDOVER_LATEST.md").write_text("# HANDOVER — the thing — 2026-07-26\n\nbody\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "seed")
    _git(repo, "branch", "session-archive")
    monkeypatch.setattr(ah, "ROOT", repo)
    return repo


# --- A1. Filename derivation ------------------------------------------------------------
def test_derive_name_uses_the_handover_date_and_an_explicit_slug():
    text = "# HANDOVER — cycle-11 reset day — 2026-07-26\n"
    assert ah.derive_name(text, "cycle-11-reset", None) == "HANDOVER_2026-07-26_cycle-11-reset.md"


def test_derive_name_falls_back_to_the_h1_title_when_no_slug_is_given():
    name = ah.derive_name("# HANDOVER — 2026-07-26 — Glass Engine\n", None, None)
    assert name.startswith("HANDOVER_2026-07-26_")
    assert ah.NAME_RE.match(name)


def test_derive_name_sanitises_path_separators_out_of_the_slug():
    """A slug can never escape handovers/ — the filename is the only thing we control."""
    name = ah.derive_name("# t\n", "../../etc/passwd", "2026-07-26")
    assert "/" not in name and ".." not in name
    assert ah.NAME_RE.match(name)


def test_derive_name_requires_a_date_it_can_find():
    with pytest.raises(ValueError):
        ah.derive_name("# no date here\n", "slug", None)


def test_name_regex_rejects_an_undated_filename():
    assert ah.NAME_RE.match("HANDOVER_2026-07-26_x.md")
    assert not ah.NAME_RE.match("HANDOVER_LATEST.md")
    assert not ah.NAME_RE.match("HANDOVER_2026-07-26_x.txt")


# --- A2. The archive commit -------------------------------------------------------------
def test_archive_appends_to_the_branch_without_touching_the_working_tree(fake_repo):
    before_head = _git(fake_repo, "rev-parse", "HEAD")
    rc = ah.main(["--slug", "the-thing", "--no-push", "--no-fetch"])
    assert rc == 0
    # the file landed on session-archive...
    listing = _git(fake_repo, "ls-tree", "-r", "--name-only", "session-archive")
    assert "handovers/HANDOVER_2026-07-26_the-thing.md" in listing.splitlines()
    # ...and nothing about the checkout moved: HEAD, the branch it points at, the tree.
    assert _git(fake_repo, "rev-parse", "HEAD") == before_head
    assert _git(fake_repo, "rev-parse", "--abbrev-ref", "HEAD") == "main"
    assert _git(fake_repo, "status", "--porcelain") == ""


def test_archived_content_is_byte_identical_to_the_source(fake_repo):
    src = (fake_repo / "handovers" / "HANDOVER_LATEST.md").read_text(encoding="utf-8")
    assert ah.main(["--slug", "the-thing", "--no-push", "--no-fetch"]) == 0
    stored = _git(fake_repo, "show", "session-archive:handovers/HANDOVER_2026-07-26_the-thing.md")
    assert stored == src.rstrip("\n")


def test_archive_is_idempotent_for_identical_content(fake_repo):
    assert ah.main(["--slug", "the-thing", "--no-push", "--no-fetch"]) == 0
    first = _git(fake_repo, "rev-parse", "session-archive")
    assert ah.main(["--slug", "the-thing", "--no-push", "--no-fetch"]) == 0
    assert _git(fake_repo, "rev-parse", "session-archive") == first, "a re-run must not add an empty duplicate commit"


def test_archive_refuses_to_clobber_a_differing_entry(fake_repo, capsys):
    assert ah.main(["--slug", "the-thing", "--no-push", "--no-fetch"]) == 0
    before = _git(fake_repo, "rev-parse", "session-archive")
    (fake_repo / "handovers" / "HANDOVER_LATEST.md").write_text("# HANDOVER — other — 2026-07-26\n", encoding="utf-8")
    assert ah.main(["--slug", "the-thing", "--no-push", "--no-fetch"]) == 1
    assert _git(fake_repo, "rev-parse", "session-archive") == before, "a refusal must write nothing"
    assert "--force" in capsys.readouterr().err


def test_force_overwrites_the_entry(fake_repo):
    assert ah.main(["--slug", "the-thing", "--no-push", "--no-fetch"]) == 0
    (fake_repo / "handovers" / "HANDOVER_LATEST.md").write_text("# HANDOVER — other — 2026-07-26\n", encoding="utf-8")
    assert ah.main(["--slug", "the-thing", "--no-push", "--no-fetch", "--force"]) == 0
    assert "other" in _git(fake_repo, "show", "session-archive:handovers/HANDOVER_2026-07-26_the-thing.md")


def test_prior_archive_entries_survive_a_new_one(fake_repo):
    assert ah.main(["--slug", "first", "--no-push", "--no-fetch"]) == 0
    (fake_repo / "handovers" / "HANDOVER_LATEST.md").write_text("# HANDOVER — second — 2026-07-27\n", encoding="utf-8")
    assert ah.main(["--slug", "second", "--no-push", "--no-fetch"]) == 0
    names = _git(fake_repo, "ls-tree", "-r", "--name-only", "session-archive").splitlines()
    assert "handovers/HANDOVER_2026-07-26_first.md" in names
    assert "handovers/HANDOVER_2026-07-27_second.md" in names


def test_dry_run_writes_nothing(fake_repo):
    before = _git(fake_repo, "rev-parse", "session-archive")
    assert ah.main(["--slug", "the-thing", "--dry-run", "--no-fetch"]) == 0
    assert _git(fake_repo, "rev-parse", "session-archive") == before


def test_missing_archive_branch_is_a_loud_refusal_not_a_silent_create(fake_repo, capsys):
    _git(fake_repo, "branch", "-D", "session-archive")
    assert ah.main(["--slug", "the-thing", "--no-push", "--no-fetch"]) == 1
    assert "not found" in capsys.readouterr().err


def test_allow_create_seeds_the_branch(fake_repo):
    _git(fake_repo, "branch", "-D", "session-archive")
    assert ah.main(["--slug", "the-thing", "--no-push", "--no-fetch", "--allow-create"]) == 0
    names = _git(fake_repo, "ls-tree", "-r", "--name-only", "session-archive").splitlines()
    assert names == ["handovers/HANDOVER_2026-07-26_the-thing.md"]


def test_empty_handover_is_refused(fake_repo, capsys):
    (fake_repo / "handovers" / "HANDOVER_LATEST.md").write_text("   \n", encoding="utf-8")
    assert ah.main(["--slug", "the-thing", "--no-push", "--no-fetch"]) == 1
    assert "empty" in capsys.readouterr().err


# --- B. The in-tree ratchet -------------------------------------------------------------
def _tracked_handovers():
    out = subprocess.run(
        ["git", "ls-files", "--", "handovers/"],
        cwd=_REPO,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return sorted(p for p in out.splitlines() if p)


def test_only_the_live_pointer_and_its_readme_are_tracked_in_main():
    """#1650: dated handovers belong on session-archive, never back on main."""
    assert _tracked_handovers() == ["handovers/HANDOVER_LATEST.md", "handovers/README.md"], (
        "handovers/ on main holds ONLY the live pointer + its README. A dated handover here "
        "means a wrap wrote to main instead of the session-archive branch — see "
        "scripts/archive_handover.py and .claude/commands/wrap.md step (a)."
    )


def test_gitignore_pins_the_ratchet():
    """Belt and braces: even an accidental `git add handovers/` cannot re-grow the dir."""
    lines = [ln.strip() for ln in open(os.path.join(_REPO, ".gitignore"), encoding="utf-8")]
    for rule in ("handovers/*", "!handovers/HANDOVER_LATEST.md", "!handovers/README.md"):
        assert rule in lines, f"missing .gitignore rule: {rule}"


def test_the_live_pointer_still_exists():
    """Every consumer (wrap, /uplevel, generate_review_bundle, check_residual_queue) reads it."""
    assert os.path.isfile(os.path.join(_REPO, "handovers", "HANDOVER_LATEST.md"))
