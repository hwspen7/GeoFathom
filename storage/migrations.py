"""Numbered, transactional migrations after the legacy base-schema bootstrap."""
CURRENT=2

def migrate(connection):
    version=connection.execute("PRAGMA user_version").fetchone()[0]
    if version>CURRENT:
        raise RuntimeError("Database schema is newer than this GeoFathom build.")
    if version==CURRENT:
        return
    # The legacy base schema is initialized by database._connect first.
    if version!=1:
        raise RuntimeError("Unrecognized database migration starting version.")
    if connection.in_transaction:
        connection.commit()
    connection.execute("BEGIN IMMEDIATE")
    try:
        version=connection.execute("PRAGMA user_version").fetchone()[0]
        if version==1:
            from core.access import _schema
            _schema(connection)
            connection.execute("""CREATE TABLE IF NOT EXISTS gf_migrations(
                version INTEGER PRIMARY KEY,applied_at TEXT NOT NULL)""")
            connection.execute("""INSERT OR IGNORE INTO gf_migrations VALUES(
                2,strftime('%Y-%m-%dT%H:%M:%fZ','now'))""")
            connection.execute("PRAGMA user_version=2")
        elif version!=CURRENT:
            raise RuntimeError("Concurrent migration changed database version.")
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
