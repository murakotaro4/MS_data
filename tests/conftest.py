import sys
from pathlib import Path
from typing import Any

import pytest

# Ensure project root is on sys.path for `import ms_data.*`
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ms_data.gh import auto_review_merge  # noqa: E402

GITHUB_ACTIONS_BOT = "github-actions[bot]"


class FakeGitHubClient:
    """auto_review_merge.GitHubClient の代替。

    responses はエンドポイントの部分一致キー -> ペイロード。
    `/issues/comments/{id}` と `/issues/comments/{id}/reactions` のように
    キーが包含関係になるため、長いキーから順に照合する。
    POST されたコメントは記録し、以降の issue_comment() 照会にも応答する。
    """

    def __init__(self, repo: str = "owner/repo"):
        self.repo = repo
        self.responses: dict[str, Any] = {}
        self.posted_comments: list[tuple[str, str]] = []
        self._comments_by_id: dict[str, dict[str, Any]] = {}
        self._next_comment_id = 1000

    def api_json(
        self,
        endpoint: str,
        *,
        method: str = "GET",
        fields: dict[str, str] | None = None,
        headers: list[str] | None = None,
        paginate: bool = False,
    ) -> Any:
        if method == "POST":
            comment = {
                "id": self._next_comment_id,
                "created_at": "2026-05-31T10:00:00Z",
                "user": {"login": GITHUB_ACTIONS_BOT},
                "body": (fields or {}).get("body", ""),
            }
            self._next_comment_id += 1
            self._comments_by_id[str(comment["id"])] = comment
            self.posted_comments.append((endpoint, comment["body"]))
            return comment

        for comment_id, comment in self._comments_by_id.items():
            if endpoint.endswith(f"/issues/comments/{comment_id}"):
                return comment
        for key in sorted(self.responses, key=len, reverse=True):
            if key in endpoint:
                return self.responses[key]
        return []

    def issue_comments(self, pr_number: str) -> list[dict[str, Any]]:
        return self.api_json(
            f"repos/{self.repo}/issues/{pr_number}/comments", paginate=True
        )

    def post_issue_comment(self, pr_number: str, body: str) -> dict[str, Any]:
        return self.api_json(
            f"repos/{self.repo}/issues/{pr_number}/comments",
            method="POST",
            fields={"body": body},
        )

    def issue_comment(self, comment_id: str) -> dict[str, Any]:
        return self.api_json(f"repos/{self.repo}/issues/comments/{comment_id}")


class FakeTime:
    """sleep() が時刻を進める time モジュール代替。実時間を消費しない。"""

    def __init__(self):
        self.now = 0.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


@pytest.fixture
def fake_gh(monkeypatch) -> FakeGitHubClient:
    client = FakeGitHubClient()
    monkeypatch.setattr(auto_review_merge, "GitHubClient", lambda repo: client)
    return client


@pytest.fixture
def fake_time(monkeypatch) -> FakeTime:
    fake = FakeTime()
    monkeypatch.setattr(auto_review_merge, "time", fake)
    return fake


@pytest.fixture
def load_fixture():
    """tests/fixtures 配下の UTF-8 テキストを読み込む。"""

    def _load_fixture(name: str) -> str:
        return (Path(__file__).with_name("fixtures") / name).read_text(
            encoding="utf-8"
        )

    return _load_fixture


@pytest.fixture
def read_github_output():
    """GITHUB_OUTPUT 形式（key=value 行、append モード）を dict に読む。"""

    def _read(path: Path) -> dict[str, str]:
        result: dict[str, str] = {}
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            key, _, value = line.partition("=")
            result[key] = value
        return result

    return _read
