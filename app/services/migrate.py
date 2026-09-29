"""Additive schema top-up for databases created before a column existed.

``Base.metadata.create_all`` creates missing *tables* but never missing
*columns*, so adding ``courses.track_id`` to a running install would otherwise
mean dropping the database. This module adds any column listed below that is
not already there, and does nothing on a fresh database where ``create_all``
has already produced the full schema.

Deliberately limited to nullable columns with no default. Anything needing a
backfill, a type change or a constraint is a real migration and wants Alembic --
see the limitations in the README. The point here is that the one thing this
app actually does between versions (hang a new optional relationship off an
existing table) should not cost anyone their data.
"""

from sqlalchemy import inspect, text

# table -> column -> the type as the database should see it.
ADDITIONS: dict[str, dict[str, str]] = {
    "courses": {"track_id": "INTEGER"},
    "lectures": {"chapter_id": "INTEGER"},
    "notes": {"chapter_id": "INTEGER"},
    "tests": {"chapter_id": "INTEGER"},
    # Carries a DEFAULT so existing rows land on "free", not NULL -- adding
    # billing must never paywall a track that was open yesterday.
    "tracks": {"requires_subscription": "BOOLEAN DEFAULT 0"},
}


def ensure_schema(engine) -> list[str]:
    """Add any missing optional column. Returns what it changed, for logging."""
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    applied: list[str] = []

    with engine.begin() as connection:
        for table, columns in ADDITIONS.items():
            if table not in existing_tables:
                continue  # create_all will build it complete
            present = {col["name"] for col in inspector.get_columns(table)}
            for column, sql_type in columns.items():
                if column in present:
                    continue
                connection.execute(
                    text(f"ALTER TABLE {table} ADD COLUMN {column} {sql_type}")
                )
                applied.append(f"{table}.{column}")

    return applied
