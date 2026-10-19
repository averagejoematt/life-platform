# COACH SESSION — moved

The coach-session prompt now has ONE source: `.claude/skills/coach-session/SKILL.md` (#5086).

This file was the second, hand-kept copy; it and the claude.ai synced copy had drifted apart
(the synced copy still described the retired v0.4 program and a role-play board). The text was
rewritten to the training charter and moved into the skill, where Claude Code can load it and
the claude.ai account copy is refreshed from it (`docs/coaching/SYNCED_SKILLS.md`). Drift
between the two is reported by `scripts/check_synced_skill_drift.py`.

Kept as a pointer so the links to it from older docs and skills still resolve. Edit the skill,
not this file.
