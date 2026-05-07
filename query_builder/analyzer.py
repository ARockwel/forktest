# ─────────────────────────────────────────────────────────────────────────────
# QUERY BUILDER INTERNAL — DO NOT MODIFY
# SQL analysis utilities: parameter detection, temp table detection, and
# execution topology derivation (which queries run in parallel vs sequentially).
# ─────────────────────────────────────────────────────────────────────────────

from __future__ import annotations
import re
from collections import deque
from query_builder.model import QuerySpec, ScenarioSpec


# ── SQL pattern detection ─────────────────────────────────────────────────────

def detect_parameters(sql: str) -> list[str]:
    """
    Return unique @variable names found in sql, in order of first appearance.
    Skips @@system variables (@@SERVERNAME, @@ROWCOUNT, etc.).
    """
    seen = set()
    result = []
    for m in re.finditer(r'@(?!@)(\w+)', sql, re.IGNORECASE):
        name = m.group(1)
        if name not in seen:
            seen.add(name)
            result.append(name)
    return result


def detect_creates_temp(sql: str) -> list[str]:
    """
    Return unique #table names that this SQL creates, in order of appearance.
    Detects: SELECT ... INTO #name  and  CREATE TABLE #name
    """
    seen = set()
    result = []
    patterns = [
        r'\bINTO\s+(#\w+)',           # SELECT ... INTO #name
        r'\bCREATE\s+TABLE\s+(#\w+)', # CREATE TABLE #name
    ]
    for pattern in patterns:
        for m in re.finditer(pattern, sql, re.IGNORECASE):
            name = m.group(1).upper()
            if name not in seen:
                seen.add(name)
                result.append(m.group(1))
    return result


def detect_reads_temp(sql: str) -> list[str]:
    """
    Return unique #table names that this SQL reads from, in order of appearance.
    Detects: FROM #name  and  JOIN #name
    """
    seen = set()
    result = []
    for m in re.finditer(r'\b(?:FROM|JOIN)\s+(#\w+)', sql, re.IGNORECASE):
        name = m.group(1).upper()
        if name not in seen:
            seen.add(name)
            result.append(m.group(1))
    return result


def refresh_temp_table_detection(query: QuerySpec) -> None:
    """Update query.creates_temp_tables and query.reads_temp_tables from current SQL."""
    combined = query.combined_sql()
    query.creates_temp_tables = detect_creates_temp(combined)
    query.reads_temp_tables   = detect_reads_temp(combined)


def detect_dataframe_reads(sql: str, all_queries: list[QuerySpec]) -> list[str]:
    """
    Return the dataframe_key values from other queries that are referenced
    as table names in this SQL.  Used to auto-detect DataFrame dependencies.
    """
    found = []
    for q in all_queries:
        if q.creates_dataframe and q.dataframe_key:
            if re.search(r'\b' + re.escape(q.dataframe_key) + r'\b', sql, re.IGNORECASE):
                found.append(q.dataframe_key)
    return found


def refresh_dataframe_detection(query: QuerySpec, all_queries: list[QuerySpec]) -> None:
    """Update query.reads_dataframe_keys from current SQL and sibling query specs."""
    query.reads_dataframe_keys = detect_dataframe_reads(
        query.combined_sql(),
        [q for q in all_queries if q.id != query.id],
    )


def _split_select_list(clause: str) -> list[str]:
    """Split a SELECT column list by top-level commas (ignores commas inside parens)."""
    parts, depth, buf = [], 0, []
    for ch in clause:
        if ch == '(':
            depth += 1; buf.append(ch)
        elif ch == ')':
            depth -= 1; buf.append(ch)
        elif ch == ',' and depth == 0:
            parts.append(''.join(buf)); buf = []
        else:
            buf.append(ch)
    if buf:
        parts.append(''.join(buf))
    return parts


def detect_output_columns(sql: str) -> list[str]:
    """
    Return column names/aliases produced by the last SELECT that emits a result set.
    Skips SELECT ... INTO (those write to a temp table, not the result set).
    Returns [] if columns cannot be statically determined (e.g. SELECT *).
    """
    # Find the last SELECT...FROM span that has no INTO between SELECT and FROM
    matches = list(re.finditer(r'\bSELECT\b(.*?)\bFROM\b', sql, re.IGNORECASE | re.DOTALL))
    select_clause = None
    for m in reversed(matches):
        span = sql[m.start():m.end()]
        if not re.search(r'\bINTO\b', span, re.IGNORECASE):
            select_clause = m.group(1)
            break
    if select_clause is None:
        return []

    # Strip optional DISTINCT / TOP N modifiers
    select_clause = re.sub(r'^\s*DISTINCT\s+', '', select_clause, flags=re.IGNORECASE)
    select_clause = re.sub(
        r'^\s*TOP\s+\d+\s*(?:PERCENT\s+)?(?:WITH\s+TIES\s+)?',
        '', select_clause, flags=re.IGNORECASE,
    )

    if re.match(r'\s*\*\s*$', select_clause):
        return []

    columns = []
    for part in _split_select_list(select_clause):
        part = part.strip()
        # AS alias: ... AS [name] or ... AS name
        m_alias = re.search(r'\bAS\s+\[?(\w+)\]?\s*$', part, re.IGNORECASE)
        if m_alias:
            columns.append(m_alias.group(1))
            continue
        # Skip expressions (contains function calls, operators, spaces mid-token)
        if re.search(r'[()/*+\-]', part):
            continue
        # Simple: schema.table.col or table.col or col (with optional brackets)
        m_col = re.match(r'^(?:\[?\w+\]?\.)*\[?(\w+)\]?\s*$', part)
        if m_col:
            columns.append(m_col.group(1))

    return columns


# ── Execution topology ────────────────────────────────────────────────────────

class ExecutionGroup:
    """
    A set of queries that share a dependency chain (connected component).

    queries       — flat topological order (dependencies before dependents)
    levels        — level-parallel order: levels[0] can all run simultaneously,
                    levels[1] only after levels[0] complete, etc.
                    Queries in the same level have no deps on each other.
    shared_cursor — True when any query in the group creates a #temp table.
                    With the DataFrame injection approach, child queries at
                    level ≥1 receive the DataFrame and can use independent
                    cursors, so this flag is only used for backward compat.
    """
    def __init__(
        self,
        queries: list[QuerySpec],
        shared_cursor: bool,
        levels: list[list[QuerySpec]] | None = None,
    ):
        self.queries       = queries
        self.shared_cursor = shared_cursor
        self.levels        = levels if levels is not None else [[q] for q in queries]


def build_execution_topology(spec: ScenarioSpec) -> list[ExecutionGroup]:
    """
    Derive parallel execution groups from a ScenarioSpec.

    Algorithm:
      1. Build an undirected adjacency graph: two queries are adjacent if they
         share an extracted-value chain (takes/gives) OR a temp table dependency.
      2. Find connected components via BFS — each component becomes one thread.
      3. Within each component, topological sort (Kahn's algorithm) so that
         dependencies always execute before their dependents.
      4. Mark a component shared_cursor=True if any query in it touches a #table.

    Independent components run in parallel threads.
    Sequential ordering within a component ensures correct data flow.
    """
    queries    = spec.queries
    id_to_q    = {q.id: q for q in queries}
    n          = len(queries)
    idx        = {q.id: i for i, q in enumerate(queries)}

    # Build adjacency (undirected) and directed dep graph
    adj     = [set() for _ in range(n)]   # undirected, for component finding
    in_deg  = [0] * n                     # for Kahn's topological sort
    dep_adj = [[] for _ in range(n)]      # directed: dep_adj[i] = list of j that depend on i

    def _add_edge(a_id: str, b_id: str):
        """a must run before b."""
        if a_id not in idx or b_id not in idx:
            return
        a, b = idx[a_id], idx[b_id]
        if b not in adj[a]:
            adj[a].add(b)
            adj[b].add(a)
            dep_adj[a].append(b)
            in_deg[b] += 1

    # Extracted-value edges: source_query_id → this query
    for q in queries:
        for edge in q.takes:
            _add_edge(edge.source_query_id, q.id)

    # Temp table edges: query that creates #T → all queries that read #T
    # Build a map: #TABLE_UPPER → query_id of creator
    creator_map: dict[str, str] = {}
    for q in queries:
        for tbl in q.creates_temp_tables:
            creator_map[tbl.upper()] = q.id

    for q in queries:
        for tbl in q.reads_temp_tables:
            creator_id = creator_map.get(tbl.upper())
            if creator_id and creator_id != q.id:
                _add_edge(creator_id, q.id)

    # DataFrame edges: query that creates_dataframe with key K → queries that
    # reference K in their SQL (reads_dataframe_keys populated at QB save time)
    df_key_to_creator: dict[str, str] = {}  # key.upper() → query_id
    for q in queries:
        if q.creates_dataframe and q.dataframe_key:
            df_key_to_creator[q.dataframe_key.upper()] = q.id

    for q in queries:
        for key in q.reads_dataframe_keys:
            creator_id = df_key_to_creator.get(key.upper())
            if creator_id and creator_id != q.id:
                _add_edge(creator_id, q.id)

    # Find connected components via BFS
    visited    = [False] * n
    components = []
    for start in range(n):
        if visited[start]:
            continue
        component = []
        queue = deque([start])
        visited[start] = True
        while queue:
            node = queue.popleft()
            component.append(node)
            for neighbour in adj[node]:
                if not visited[neighbour]:
                    visited[neighbour] = True
                    queue.append(neighbour)
        components.append(component)

    # Level-by-level topological sort within each component (Kahn's BFS levels)
    groups = []
    for component in components:
        comp_set  = set(component)
        local_deg = {i: 0 for i in component}
        local_adj = {i: [] for i in component}

        for i in component:
            for j in dep_adj[i]:
                if j in comp_set:
                    local_adj[i].append(j)
                    local_deg[j] += 1

        # Process all zero-in-degree nodes as a batch to form levels
        ready        = [i for i in component if local_deg[i] == 0]
        levels_idx   = []   # list[list[int]] — each inner list = one parallel level
        sorted_ids   = []
        while ready:
            levels_idx.append(ready[:])
            sorted_ids.extend(ready)
            next_ready = []
            for node in ready:
                for j in local_adj[node]:
                    local_deg[j] -= 1
                    if local_deg[j] == 0:
                        next_ready.append(j)
            ready = next_ready

        # Fall back if cycle detected (shouldn't happen in valid specs)
        if len(sorted_ids) != len(component):
            sorted_ids = component
            levels_idx = [[i] for i in component]

        ordered_queries = [queries[i] for i in sorted_ids]
        levels          = [[queries[i] for i in lvl] for lvl in levels_idx]

        # shared_cursor if any query in this group touches a #temp table
        shared = any(
            q.creates_temp_tables or q.reads_temp_tables
            for q in ordered_queries
        )
        groups.append(ExecutionGroup(
            queries=ordered_queries,
            shared_cursor=shared,
            levels=levels,
        ))

    return groups
