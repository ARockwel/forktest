# ─────────────────────────────────────────────────────────────────────────────
# QUERY BUILDER INTERNAL — DO NOT MODIFY
# Data model for in-progress scenario specifications.
# Serialises to/from JSON for draft persistence in query_builder/specs/.
# ─────────────────────────────────────────────────────────────────────────────

from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class ParameterSpec:
    """A user-supplied input parameter bound to an @variable in the SQL."""
    name: str           # @variable name as detected in SQL (without the @)
    label: str = ""     # display label shown in the scenario UI
    default: str = ""   # pre-filled default value

    def to_dict(self) -> dict:
        return {"name": self.name, "label": self.label, "default": self.default}

    @staticmethod
    def from_dict(d: dict) -> ParameterSpec:
        return ParameterSpec(
            name=d.get("name", ""),
            label=d.get("label", ""),
            default=d.get("default", ""),
        )


@dataclass
class SqlBlock:
    """One SQL statement (or batch) within a query. Executed in order on the same cursor."""
    label: str  # descriptive name shown in the builder UI, e.g. "Build Temp Table"
    sql: str

    def to_dict(self) -> dict:
        return {"label": self.label, "sql": self.sql}

    @staticmethod
    def from_dict(d: dict) -> SqlBlock:
        return SqlBlock(label=d.get("label", ""), sql=d.get("sql", ""))


@dataclass
class DependencyEdge:
    """
    Declares that this query takes an extracted value from an upstream query.

    The upstream query stores a value in result.extracted[extracted_key].
    This query receives it as the @variable named target_param.
    """
    source_query_id: str   # id of the upstream QuerySpec that produces the value
    extracted_key: str     # key in result.extracted on the upstream query
    target_param: str      # @variable in this query's SQL that receives the value
    gate: bool = False     # if True, skip this query (and all subsequent) when source returns error

    def to_dict(self) -> dict:
        return {
            "source_query_id": self.source_query_id,
            "extracted_key": self.extracted_key,
            "target_param": self.target_param,
            "gate": self.gate,
        }

    @staticmethod
    def from_dict(d: dict) -> DependencyEdge:
        return DependencyEdge(
            source_query_id=d.get("source_query_id", ""),
            extracted_key=d.get("extracted_key", ""),
            target_param=d.get("target_param", ""),
            gate=d.get("gate", False),
        )


@dataclass
class QuerySpec:
    """Full specification for a single generated query module."""
    id: str                                         # unique slug within the scenario
    title: str
    description: str
    sql_blocks: list[SqlBlock] = field(default_factory=list)
    parameters: list[ParameterSpec] = field(default_factory=list)
    gives: list[str] = field(default_factory=list)  # extracted keys this query puts in result.extracted
    takes: list[DependencyEdge] = field(default_factory=list)

    # Explicit DataFrame path — user checks "Create DataFrame" in the QB
    creates_dataframe: bool = False  # store this query's result as a named DataFrame
    dataframe_key: str = ""          # name children use in their SQL (e.g. "IssueData")
    reads_dataframe_keys: list[str] = field(default_factory=list)  # auto-detected on save

    # Auto-detected from SQL — not user-editable, refreshed on save
    creates_temp_tables: list[str] = field(default_factory=list)
    reads_temp_tables: list[str] = field(default_factory=list)

    def combined_sql(self) -> str:
        """All SQL blocks joined — used for analysis."""
        return "\n".join(b.sql for b in self.sql_blocks)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "sql_blocks": [b.to_dict() for b in self.sql_blocks],
            "parameters": [p.to_dict() for p in self.parameters],
            "gives": list(self.gives),
            "takes": [t.to_dict() for t in self.takes],
            "creates_dataframe": self.creates_dataframe,
            "dataframe_key": self.dataframe_key,
            "reads_dataframe_keys": list(self.reads_dataframe_keys),
            "creates_temp_tables": list(self.creates_temp_tables),
            "reads_temp_tables": list(self.reads_temp_tables),
        }

    @staticmethod
    def from_dict(d: dict) -> QuerySpec:
        return QuerySpec(
            id=d.get("id", ""),
            title=d.get("title", ""),
            description=d.get("description", ""),
            sql_blocks=[SqlBlock.from_dict(b) for b in d.get("sql_blocks", [])],
            parameters=[ParameterSpec.from_dict(p) for p in d.get("parameters", [])],
            gives=d.get("gives", []),
            takes=[DependencyEdge.from_dict(t) for t in d.get("takes", [])],
            creates_dataframe=d.get("creates_dataframe", False),
            dataframe_key=d.get("dataframe_key", ""),
            reads_dataframe_keys=d.get("reads_dataframe_keys", []),
            creates_temp_tables=d.get("creates_temp_tables", []),
            reads_temp_tables=d.get("reads_temp_tables", []),
        )


@dataclass
class ScenarioSpec:
    """Full specification for a generated scenario module and its query modules."""
    title: str
    icon: str
    environments: list[str]     # e.g. ["PROD", "QA"]
    business_units: list[str]   # e.g. ["Beef/Pork"] — loaded from business_units.json
    queries: list[QuerySpec]
    file_prefix: str            # generated files: query_<prefix>_<qid>.py, scenario_<prefix>.py

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "icon": self.icon,
            "environments": list(self.environments),
            "business_units": list(self.business_units),
            "queries": [q.to_dict() for q in self.queries],
            "file_prefix": self.file_prefix,
        }

    @staticmethod
    def from_dict(d: dict) -> ScenarioSpec:
        return ScenarioSpec(
            title=d.get("title", ""),
            icon=d.get("icon", "◈"),
            environments=d.get("environments", []),
            business_units=d.get("business_units", []),
            queries=[QuerySpec.from_dict(q) for q in d.get("queries", [])],
            file_prefix=d.get("file_prefix", ""),
        )
