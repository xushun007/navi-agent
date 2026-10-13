from __future__ import annotations

import unittest

from navi_agent.runtime.tools.policy import BashCommandPolicy, SensitiveToolPolicy


class BashCommandPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = BashCommandPolicy(
            fallback=SensitiveToolPolicy(
                approval_required_tools={"write_file": "write requires approval"}
            )
        )

    def test_allows_known_read_only_commands_and_pipelines(self) -> None:
        commands = [
            "pwd",
            "ls -la",
            "find . -type f | wc -l",
            "find . -type f | sort",
            "find . -type f | sort -u | wc -l",
            "rg --files | wc -l",
            "cd src; find . -type f | wc -l",
            'find src tests scripts evals -name "*.py" 2>/dev/null | wc -l',
            (
                'ls -a; echo "---"; find . \\( -name .venv -o -name .git '
                '-o -name node_modules -o -name .mypy_cache -o -name __pycache__ \\) '
                '-prune -o -name "*.py" -print 2>/dev/null | wc -l'
            ),
            (
                'find . \\( -name .venv -o -name .git -o -name .uv-cache '
                '-o -name .worktrees -o -name node_modules -o -name __pycache__ '
                '-o -name site \\) -prune -o -name "*.py" -print 2>/dev/null '
                "| sed 's|^\\./||' | awk -F/ '{print $1}' | sort | uniq -c | sort -rn"
            ),
            "cat .e*",
            "cat file?.txt",
        ]

        for command in commands:
            with self.subTest(command=command):
                decision = self.policy.decide("bash", {"command": command}, None)
                self.assertTrue(decision.allows_execution)
                self.assertFalse(decision.requires_approval)

    def test_requires_approval_for_mutating_or_unknown_commands(self) -> None:
        commands = [
            "rm build.log",
            "python -c 'print(1)'",
            "git commit -m test",
            "echo value > output.txt",
            "echo $(whoami)",
            "cat $HOME/.config",
            "find . -exec cat {} ;",
            "sort -o files.txt",
            "sort --output=files.txt",
            "sort --compress-program=gzip",
            "sort --random-source=seed.txt",
            "cd",
            "cd -",
            "cd ~",
            "cd src*",
            "cd src | pwd",
            "cd src || pwd",
            "rg -nz needle .",
            "git status --short",
            "git log -1 --oneline",
            "git diff",
            "git show HEAD",
            "sed -i '' 's/old/new/' file.txt",
            "sed 's/x/y/w output.txt' input.txt",
            "awk 'BEGIN { system(\"rm file.txt\") }'",
            "awk '{ print $1 > \"output.txt\" }' input.txt",
            "find $HOME -type f",
            "find . -delete",
        ]

        for command in commands:
            with self.subTest(command=command):
                decision = self.policy.decide("bash", {"command": command}, None)
                self.assertFalse(decision.allows_execution)
                self.assertTrue(decision.requires_approval)

    def test_requires_approval_for_background_execution(self) -> None:
        decision = self.policy.decide(
            "bash",
            {"command": "sleep 1", "background": True},
            None,
        )

        self.assertTrue(decision.requires_approval)

    def test_denies_catastrophic_commands_without_approval(self) -> None:
        for command in ["sudo ls", "shutdown now", "rm -rf /", "rm --recursive --force ~"]:
            with self.subTest(command=command):
                decision = self.policy.decide("bash", {"command": command}, None)
                self.assertFalse(decision.allows_execution)
                self.assertFalse(decision.requires_approval)

    def test_delegates_non_bash_tools_to_fallback(self) -> None:
        decision = self.policy.decide("write_file", {"path": "a.txt"}, None)

        self.assertTrue(decision.requires_approval)
