"""Check the PB workflow shipped in each independently installed provider prompt."""
from pathlib import Path
import unittest


PROVIDERS = Path(__file__).resolve().parents[1] / "multiprovider"
CONTRACTS = {
    "claude": "claude/01-jira-three-parallel-STRICT-ROUTING.md",
    "cursor": "cursor/01-scheduled-implement.md",
    "opencode": "opencode/.opencode/agents/factory-orchestrator.md",
    "openai": "openai/orchestrator.md",
}


class ProductBoardContracts(unittest.TestCase):
    def test_each_provider_matches_published_routing_and_handoff(self):
        routing = (PROVIDERS / "jira/ROUTING.md").read_text()
        for engine, path in CONTRACTS.items():
            with self.subTest(engine=engine):
                prompt = (PROVIDERS / path).read_text()
                profile = prompt.split("**Product Board (project PB, board 6).**", 1)[1]
                query = (f'project = PB AND sprint in openSprints() AND status = 10015 '
                         f'AND labels = "agent-ready" AND labels = "engine-{engine}" ORDER BY Rank ASC')
                self.assertIn(query, routing)
                self.assertIn(query, profile)
                for requirement in ("active sprint belonging to board 6", "exactly one supported engine",
                                    "immediately before claim", "`En curso` (10016)", "`CODE REVIEW` (10048)",
                                    "independent PASS and passing checks"):
                    self.assertIn(requirement, profile)
