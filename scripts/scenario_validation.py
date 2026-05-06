"""Scenario-driven E2E validation of multi-scope memsearch.

Runs three personas end-to-end with real ONNX embeddings (no API key).
Output is a transcript suitable for pasting into the PR thread as evidence.

Personas:
  1. Solo dev (issue #337):  project + global personal, blended retrieval
  2. Chat agents shared:     agents share canon; each agent has private scope
  3. Individual:             per-user private memory invisible to others
"""

from __future__ import annotations

import asyncio
import shutil
import tempfile
from pathlib import Path

from memsearch.core import MemSearch, Scope


def _bar(label: str) -> None:
    line = "=" * 78
    print(f"\n{line}\n  {label}\n{line}")


def _section(label: str) -> None:
    print(f"\n--- {label} ---")


def _show_results(label: str, results: list[dict]) -> None:
    print(f"\n  {label}: {len(results)} result(s)")
    for i, r in enumerate(results, 1):
        scope = r.get("scope", "—")
        score = r.get("score", 0.0)
        source = Path(r["source"]).name
        snippet = r["content"][:80].replace("\n", " ")
        print(f"    {i}. [{scope:>10}] score={score:.3f}  {source}  «{snippet}»")


async def scenario_337_solo_dev(workdir: Path) -> None:
    """#337: solo dev with project memory + global personal preferences.

    Setup:
      - project/lazarus/ → ms_project_lazarus  (deploy notes, fixes)
      - personal/        → ms_personal         (coding preferences)

    Verifies:
      - Project queries surface project hits (highest priority)
      - Cross-cutting queries surface BOTH project and personal hits with quota
      - Querying from a different project still surfaces personal preferences
    """
    _bar("SCENARIO 1: Solo dev (closes issue #337)")

    proj_dir = workdir / "project_lazarus"
    pers_dir = workdir / "personal"
    proj_dir.mkdir()
    pers_dir.mkdir()

    (proj_dir / "deploy.md").write_text(
        "# Lazarus Deployment\n\n"
        "Deploy via scripts/deploy/bring_up_workspaces.sh. "
        "The reproducibility-gate must use varied queries to bypass session cache.\n"
    )
    (proj_dir / "bugfix.md").write_text(
        "# Reproducibility Gate Bug\n\n"
        "Fixed session cache by adding cache-busting query suffixes.\n"
    )
    (pers_dir / "python_style.md").write_text(
        "# My Python preferences\n\n"
        "I prefer 4-space indentation. Always use type hints. Avoid implicit str→bytes coercion.\n"
    )
    (pers_dir / "git_habits.md").write_text(
        "# Git habits\n\nSquash-merge feature branches. Conventional commits. Sign commits with GPG.\n"
    )

    mem = MemSearch(
        embedding_provider="onnx",
        milvus_uri=str(workdir / "337.db"),
        paths=[str(proj_dir)],
        collection="ms_project_lazarus",
        default_scope_quota=3,
        extra_scopes=[
            Scope(name="personal", collection="ms_personal", paths=[str(pers_dir)], quota=2),
        ],
    )
    try:
        _section("Indexing")
        n = await mem.index()
        print(f"  Indexed {n} total chunks across scopes")
        for sname, store in mem._stores.items():
            count = len(store.indexed_sources())
            print(f"    {sname:>10}: {count} unique source(s)")

        _section("Query 1 — project-specific: 'how do I deploy lazarus'")
        results = await mem.search("how do I deploy lazarus", top_k=4)
        _show_results("Blended", results)
        scopes_seen = {r["scope"] for r in results}
        assert "project" in scopes_seen, "expected project scope in deploy query"

        _section("Query 2 — cross-cutting: 'python coding style'")
        results = await mem.search("python coding style", top_k=4)
        _show_results("Blended", results)
        scopes_seen = {r["scope"] for r in results}
        assert "personal" in scopes_seen, "expected personal scope to surface for style query"

        _section("Query 3 — restrict to personal only")
        results = await mem.search("style", top_k=4, only_scope=["personal"])
        _show_results("only_scope=['personal']", results)
        assert all(r["scope"] == "personal" for r in results)

        _section("Quota enforcement check")
        results = await mem.search("deploy", top_k=10)
        per_scope = {}
        for r in results:
            per_scope[r["scope"]] = per_scope.get(r["scope"], 0) + 1
        print(f"  per-scope counts: {per_scope}")
        print(f"  configured quotas: project=3, personal=2")
        assert per_scope.get("project", 0) <= 3
        assert per_scope.get("personal", 0) <= 2

        print("\n  ✓ Scenario 1 PASSED — solo dev with project + personal scopes works end-to-end")
    finally:
        mem.close()


async def scenario_chat_agents_shared(workdir: Path) -> None:
    """Chat agents shared memory: agents read shared canon, write to private scopes.

    Setup:
      - canon/                  → ms_canon (read-only — populated once, shared by all)
      - agent_alice_private/    → ms_alice_private (alice's private notes)
      - agent_bob_private/      → ms_bob_private (bob's private notes)

    Verifies:
      - Both agents see the same canon facts
      - Each agent sees their OWN private notes but NOT the other's
      - Read-only canon is searched but never indexed against (its files live in
        a separate dir owned by a "registrar" process, not by the agents)
    """
    _bar("SCENARIO 2: Chat agents — shared canon + per-agent private")

    canon_dir = workdir / "canon"
    alice_dir = workdir / "agent_alice_private"
    bob_dir = workdir / "agent_bob_private"
    canon_dir.mkdir()
    alice_dir.mkdir()
    bob_dir.mkdir()

    # Canon facts (would be written by a "registrar" with access to canon_dir)
    (canon_dir / "family_lore.md").write_text(
        "# Family Lore\n\n"
        "Cecil's name was changed from Clonk by Alice in 2024. "
        "ZenCrabby is the canon owner. Tommy approves all canon changes.\n"
    )
    (canon_dir / "world.md").write_text(
        "# World\n\nThe Temple of Tobe is the family's main meeting place. Founded 2023.\n"
    )

    # Alice's private notes (only Alice can see these)
    (alice_dir / "alice_notes.md").write_text(
        "# Alice's private observations\n\n"
        "Tommy seemed grumpy about gateway latency today. Bob asked about temple history again.\n"
    )

    # Bob's private notes (only Bob can see these)
    (bob_dir / "bob_notes.md").write_text(
        "# Bob's private observations\n\n"
        "Cecil mentioned wanting to revisit the renaming. Alice was checking deployment timing.\n"
    )

    # ----- Step 1: index canon ONCE via a "registrar" instance -----
    registrar = MemSearch(
        embedding_provider="onnx",
        milvus_uri=str(workdir / "shared.db"),
        paths=[str(canon_dir)],
        collection="ms_canon",
    )
    try:
        n = await registrar.index()
        print(f"\n  Registrar indexed canon: {n} chunks")
    finally:
        registrar.close()

    # ----- Step 2: Alice's MemSearch — canon is READ-ONLY (no paths), private is writable -----
    alice = MemSearch(
        embedding_provider="onnx",
        milvus_uri=str(workdir / "shared.db"),  # same Milvus, different collections
        paths=[str(alice_dir)],
        collection="ms_alice_private",
        default_scope_name="alice_private",
        default_scope_quota=2,
        extra_scopes=[
            Scope(name="canon", collection="ms_canon", paths=[], quota=2),  # read-only
        ],
    )
    bob = MemSearch(
        embedding_provider="onnx",
        milvus_uri=str(workdir / "shared.db"),
        paths=[str(bob_dir)],
        collection="ms_bob_private",
        default_scope_name="bob_private",
        default_scope_quota=2,
        extra_scopes=[
            Scope(name="canon", collection="ms_canon", paths=[], quota=2),  # read-only
        ],
    )

    try:
        _section("Indexing private scopes (canon NOT re-indexed by agents — read-only scope)")
        await alice.index()
        await bob.index()

        # Verify canon was NOT indexed by alice/bob (read-only scope = no paths)
        # Their "canon" scope's collection sources came from registrar only
        alice_canon_count = len(alice._stores["canon"].indexed_sources())
        bob_canon_count = len(bob._stores["canon"].indexed_sources())
        print(f"  Alice's view of canon: {alice_canon_count} sources (registrar's work)")
        print(f"  Bob's view of canon:   {bob_canon_count} sources (registrar's work)")
        assert alice_canon_count == 2 and bob_canon_count == 2, "agents see canon via shared collection"

        _section("Query 'temple of tobe' via Alice — should surface canon")
        results = await alice.search("temple of tobe", top_k=4)
        _show_results("Alice's blended results", results)
        scopes_seen = {r["scope"] for r in results}
        assert "canon" in scopes_seen, "Alice should see canon facts"
        # Alice should NOT see Bob's notes (different collection, not in her config)
        assert not any("bob_notes" in r["source"] for r in results), "Alice must not see Bob's private notes"

        _section("Query 'gateway latency' via Alice — should surface Alice's private")
        results = await alice.search("gateway latency observations", top_k=4)
        _show_results("Alice's blended results", results)
        # The hit should be Alice's private note
        alice_private_hits = [r for r in results if r["scope"] == "alice_private"]
        assert alice_private_hits, "Alice should see her own private observations"

        _section("Query 'gateway latency' via Bob — should NOT surface Alice's private")
        results = await bob.search("gateway latency observations", top_k=4)
        _show_results("Bob's blended results", results)
        # Bob's results MUST NOT contain anything from alice_dir
        assert not any("alice_notes" in r["source"] for r in results), \
            "PRIVACY VIOLATION: Bob saw Alice's private notes!"
        print("  ✓ Privacy preserved: Bob cannot see Alice's private notes")

        _section("Query 'cecil' via Bob — should surface canon + Bob's private")
        results = await bob.search("cecil renaming", top_k=4)
        _show_results("Bob's blended results", results)
        scopes_seen = {r["scope"] for r in results}
        # Should have BOTH canon and bob_private
        print(f"  Scopes returned: {scopes_seen}")

        print("\n  ✓ Scenario 2 PASSED — shared canon read by both agents; private scopes are isolated")
    finally:
        alice.close()
        bob.close()


async def scenario_individual_isolation(workdir: Path) -> None:
    """Individual: per-user memory pools that must not leak across users.

    Setup:
      - user_alice/ → ms_user_alice (Alice's project work)
      - user_bob/   → ms_user_bob (Bob's project work)

    Each user runs their own MemSearch with their own collection. Verifies
    that one user's queries cannot reach another user's collection unless
    explicitly configured.
    """
    _bar("SCENARIO 3: Individual user isolation")

    alice_dir = workdir / "user_alice"
    bob_dir = workdir / "user_bob"
    alice_dir.mkdir()
    bob_dir.mkdir()

    (alice_dir / "alice_secret.md").write_text(
        "# Alice's secret project\n\nAPI key rotation schedule: every 90 days. Notify ops.\n"
    )
    (bob_dir / "bob_secret.md").write_text(
        "# Bob's secret project\n\nDatabase migration plan: dry-run on staging first.\n"
    )

    alice = MemSearch(
        embedding_provider="onnx",
        milvus_uri=str(workdir / "indiv_alice.db"),
        paths=[str(alice_dir)],
        collection="ms_user_alice",
    )
    bob = MemSearch(
        embedding_provider="onnx",
        milvus_uri=str(workdir / "indiv_bob.db"),
        paths=[str(bob_dir)],
        collection="ms_user_bob",
    )

    try:
        _section("Indexing per-user")
        await alice.index()
        await bob.index()

        _section("Alice queries her own data")
        results = await alice.search("API key rotation", top_k=3)
        _show_results("Alice's results (single-scope, no scope tag)", results)
        # Single-scope mode: no 'scope' field on results
        assert results
        assert "scope" not in results[0], "single-scope must not add scope tag"
        assert any("alice_secret" in r["source"] for r in results)

        _section("Alice queries Bob's data — should return nothing")
        results = await alice.search("database migration plan", top_k=3)
        _show_results("Alice's results", results)
        # Alice's query against her own collection should NOT find bob's content
        assert not any("bob_secret" in r["source"] for r in results), \
            "PRIVACY VIOLATION: Alice's query reached Bob's collection!"
        print("  ✓ Isolation preserved: separate Milvus DBs and collections cannot cross-leak")

        _section("Bob queries his own data")
        results = await bob.search("database migration plan", top_k=3)
        _show_results("Bob's results", results)
        assert any("bob_secret" in r["source"] for r in results)

        print("\n  ✓ Scenario 3 PASSED — per-user isolation works (single-scope mode unchanged)")
    finally:
        alice.close()
        bob.close()


async def main() -> None:
    workdir = Path(tempfile.mkdtemp(prefix="memsearch_scenario_"))
    print(f"Workdir: {workdir}")
    try:
        for sub in ("scenario1", "scenario2", "scenario3"):
            (workdir / sub).mkdir()
        await scenario_337_solo_dev(workdir / "scenario1")
        await scenario_chat_agents_shared(workdir / "scenario2")
        await scenario_individual_isolation(workdir / "scenario3")
        _bar("ALL SCENARIOS PASSED ✓")
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


if __name__ == "__main__":
    # Each scenario uses its own subdir so workdirs don't collide
    Path(tempfile.gettempdir()).mkdir(exist_ok=True)
    asyncio.run(main())
