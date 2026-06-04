from sqlalchemy import inspect, text

from app.extensions import db


class SchemaService:
    """Small compatibility repairs for local MVP databases.

    This does not replace Flask-Migrate. It only applies known safe, nullable
    column additions that appeared during rapid MVP iteration.
    """

    @staticmethod
    def ensure_compatible_schema() -> list[str]:
        repaired: list[str] = []
        inspector = inspect(db.engine)
        if not inspector.has_table("templates"):
            return repaired

        template_columns = {column["name"] for column in inspector.get_columns("templates")}
        if "series" not in template_columns:
            db.session.execute(text(SchemaService._add_template_series_sql()))
            db.session.commit()
            repaired.append("templates.series")

        if inspector.has_table("workflow_nodes"):
            workflow_columns = {
                column["name"] for column in inspector.get_columns("workflow_nodes")
            }
            if "config" not in workflow_columns:
                db.session.execute(text(SchemaService._add_json_column_sql("workflow_nodes", "config")))
                db.session.commit()
                repaired.append("workflow_nodes.config")

        if inspector.has_table("models"):
            model_columns = {column["name"] for column in inspector.get_columns("models")}
            for column_name in ("parameter_schema", "default_params"):
                if column_name not in model_columns:
                    db.session.execute(text(SchemaService._add_json_column_sql("models", column_name)))
                    db.session.commit()
                    repaired.append(f"models.{column_name}")

        if inspector.has_table("jobs"):
            migrated = SchemaService._ensure_jobs_schema(inspector)
            repaired.extend(migrated)

        if inspector.has_table("prompt_versions"):
            migrated = SchemaService._ensure_prompt_versions_schema(inspector)
            repaired.extend(migrated)

        if inspector.has_table("job_prompt_refs"):
            migrated = SchemaService._ensure_job_prompt_refs_schema(inspector)
            repaired.extend(migrated)

        # Ensure default Series exists and seed templates without series
        if inspector.has_table("series"):
            migrated = SchemaService._ensure_default_series()
            repaired.extend(migrated)

        return repaired

    @staticmethod
    def _ensure_jobs_schema(inspector) -> list[str]:
        repaired: list[str] = []
        columns = {c["name"] for c in inspector.get_columns("jobs")}
        if "job_name" not in columns:
            db.session.execute(text(SchemaService._add_varchar_column_sql("jobs", "job_name", 255)))
            db.session.commit()
            repaired.append("jobs.job_name")
        return repaired

    @staticmethod
    def _ensure_default_series() -> list[str]:
        """Ensure default Series exists; assign orphaned templates to it."""
        repaired: list[str] = []
        from app.models.series import Series

        default = Series.query.filter_by(series_id="default").first()
        if not default:
            default = Series(
                series_id="default",
                name="Default Series",
                description="Default series for uncategorized templates",
                is_default=True,
            )
            db.session.add(default)
            db.session.commit()
            repaired.append("series.default_created")

        # Assign templates with no series to "default"
        try:
            result = db.session.execute(
                text("UPDATE templates SET series = 'default' WHERE series IS NULL OR series = ''")
            )
            if result.rowcount:
                db.session.commit()
                repaired.append(f"templates.series_backfill({result.rowcount})")
        except Exception:
            db.session.rollback()

        return repaired

    @staticmethod
    def _ensure_prompt_versions_schema(inspector) -> list[str]:
        """Migrate prompt_versions to Job-scoped prompt assets."""
        repaired: list[str] = []
        columns = {c["name"] for c in inspector.get_columns("prompt_versions")}
        unique_names = SchemaService._unique_constraint_names(inspector, "prompt_versions")
        has_old_unique = (
            "uq_prompt_template_type_version" in unique_names
            or SchemaService._has_unique_columns(
                inspector, "prompt_versions", ["template_id", "prompt_type", "version"]
            )
        )
        has_new_unique = (
            "uq_prompt_job_type_key_version" in unique_names
            or SchemaService._has_unique_columns(
                inspector,
                "prompt_versions",
                ["job_id", "prompt_type", "prompt_key", "version"],
            )
        )

        if "prompt_key" in columns and "job_id" in columns and has_new_unique and not has_old_unique:
            return repaired

        dialect = db.engine.dialect.name
        if dialect == "sqlite":
            if "prompt_key" in columns and "job_id" in columns and has_new_unique and not has_old_unique:
                return repaired
            db.session.execute(text("DROP TABLE IF EXISTS _prompt_versions_new"))
            db.session.execute(text("""
                CREATE TABLE _prompt_versions_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    prompt_id VARCHAR(80) UNIQUE NOT NULL,
                    template_id INTEGER NOT NULL REFERENCES templates(id),
                    job_id INTEGER REFERENCES jobs(id),
                    prompt_type VARCHAR(120) NOT NULL,
                    prompt_key VARCHAR(120) NOT NULL DEFAULT 'default',
                    version VARCHAR(40) NOT NULL,
                    title VARCHAR(255) NOT NULL,
                    content TEXT NOT NULL,
                    content_format VARCHAR(40) NOT NULL DEFAULT 'markdown',
                    is_active BOOLEAN NOT NULL DEFAULT 1,
                    source VARCHAR(80) NOT NULL DEFAULT 'manual',
                    parent_version VARCHAR(40),
                    note TEXT,
                    created_by VARCHAR(120),
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME,
                    CONSTRAINT uq_prompt_job_type_key_version
                        UNIQUE (job_id, prompt_type, prompt_key, version)
                )
            """))
            copy_sql = f"""
                INSERT INTO _prompt_versions_new
                    (id, prompt_id, template_id, job_id, prompt_type, prompt_key,
                     version, title, content, content_format, is_active, source,
                     parent_version, note, created_by, created_at, updated_at)
                SELECT
                    {SchemaService._column_or_default(columns, "id", "NULL")},
                    {SchemaService._column_or_default(columns, "prompt_id", "NULL")},
                    {SchemaService._column_or_default(columns, "template_id", "NULL")},
                    {SchemaService._column_or_default(columns, "job_id", "NULL")},
                    {SchemaService._column_or_default(columns, "prompt_type", "NULL")},
                    {SchemaService._column_or_default(columns, "prompt_key", "'default'")},
                    {SchemaService._column_or_default(columns, "version", "NULL")},
                    {SchemaService._column_or_default(columns, "title", "''")},
                    {SchemaService._column_or_default(columns, "content", "''")},
                    {SchemaService._column_or_default(columns, "content_format", "'markdown'")},
                    {SchemaService._column_or_default(columns, "is_active", "1")},
                    {SchemaService._column_or_default(columns, "source", "'manual'")},
                    {SchemaService._column_or_default(columns, "parent_version", "NULL")},
                    {SchemaService._column_or_default(columns, "note", "NULL")},
                    {SchemaService._column_or_default(columns, "created_by", "NULL")},
                    {SchemaService._column_or_default(columns, "created_at", "CURRENT_TIMESTAMP")},
                    {SchemaService._column_or_default(columns, "updated_at", "created_at")}
                FROM prompt_versions
            """
            db.session.execute(text(copy_sql))
            db.session.execute(text("DROP TABLE prompt_versions"))
            db.session.execute(text("ALTER TABLE _prompt_versions_new RENAME TO prompt_versions"))
            db.session.commit()
            repaired.append("prompt_versions.job_scoped_unique")
        else:
            if "job_id" not in columns:
                db.session.execute(text(
                    "ALTER TABLE prompt_versions ADD COLUMN job_id INTEGER REFERENCES jobs(id)"
                ))
                db.session.commit()
                repaired.append("prompt_versions.job_id")
            if "prompt_key" not in columns:
                db.session.execute(text(
                    "ALTER TABLE prompt_versions ADD COLUMN prompt_key VARCHAR(120) NOT NULL DEFAULT 'default'"
                ))
                db.session.commit()
                repaired.append("prompt_versions.prompt_key")
            if "updated_at" not in columns:
                db.session.execute(text(
                    "ALTER TABLE prompt_versions ADD COLUMN updated_at DATETIME"
                ))
                db.session.commit()
                repaired.append("prompt_versions.updated_at")
            unique_names = SchemaService._unique_constraint_names(inspector, "prompt_versions")
            if "uq_prompt_template_type_version" in unique_names:
                SchemaService._drop_unique_constraint("prompt_versions", "uq_prompt_template_type_version")
                repaired.append("prompt_versions.drop_uq_prompt_template_type_version")
            unique_names = SchemaService._unique_constraint_names(inspect(db.engine), "prompt_versions")
            if "uq_prompt_job_type_key_version" not in unique_names:
                db.session.execute(text(
                    "ALTER TABLE prompt_versions "
                    "ADD CONSTRAINT uq_prompt_job_type_key_version "
                    "UNIQUE (job_id, prompt_type, prompt_key, version)"
                ))
                db.session.commit()
                repaired.append("prompt_versions.uq_prompt_job_type_key_version")

        return repaired

    @staticmethod
    def _ensure_job_prompt_refs_schema(inspector) -> list[str]:
        """Migrate job_prompt_refs snapshots to include prompt_key in uniqueness."""
        repaired: list[str] = []
        columns = {c["name"] for c in inspector.get_columns("job_prompt_refs")}
        unique_names = SchemaService._unique_constraint_names(inspector, "job_prompt_refs")
        has_old_unique = (
            "uq_job_prompt_type_version" in unique_names
            or SchemaService._has_unique_columns(
                inspector, "job_prompt_refs", ["job_id", "prompt_type", "version"]
            )
        )
        has_new_unique = (
            "uq_job_prompt_type_key_version" in unique_names
            or SchemaService._has_unique_columns(
                inspector,
                "job_prompt_refs",
                ["job_id", "prompt_type", "prompt_key", "version"],
            )
        )

        if "prompt_key" in columns and has_new_unique and not has_old_unique:
            return repaired

        dialect = db.engine.dialect.name
        if dialect == "sqlite":
            db.session.execute(text("DROP TABLE IF EXISTS _job_prompt_refs_new"))
            db.session.execute(text("""
                CREATE TABLE _job_prompt_refs_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ref_id VARCHAR(80) UNIQUE NOT NULL,
                    job_id INTEGER NOT NULL REFERENCES jobs(id),
                    prompt_version_id INTEGER NOT NULL REFERENCES prompt_versions(id),
                    prompt_type VARCHAR(120) NOT NULL,
                    prompt_key VARCHAR(120) NOT NULL DEFAULT 'default',
                    version VARCHAR(40) NOT NULL,
                    title VARCHAR(255),
                    content_snapshot TEXT NOT NULL,
                    created_at DATETIME NOT NULL,
                    CONSTRAINT uq_job_prompt_type_key_version
                        UNIQUE (job_id, prompt_type, prompt_key, version)
                )
            """))
            copy_sql = f"""
                INSERT INTO _job_prompt_refs_new
                    (id, ref_id, job_id, prompt_version_id, prompt_type, prompt_key,
                     version, title, content_snapshot, created_at)
                SELECT
                    {SchemaService._column_or_default(columns, "id", "NULL")},
                    {SchemaService._column_or_default(columns, "ref_id", "NULL")},
                    {SchemaService._column_or_default(columns, "job_id", "NULL")},
                    {SchemaService._column_or_default(columns, "prompt_version_id", "NULL")},
                    {SchemaService._column_or_default(columns, "prompt_type", "NULL")},
                    {SchemaService._job_prompt_ref_key_expr(columns)},
                    {SchemaService._column_or_default(columns, "version", "NULL")},
                    {SchemaService._column_or_default(columns, "title", "NULL")},
                    {SchemaService._column_or_default(columns, "content_snapshot", "''")},
                    {SchemaService._column_or_default(columns, "created_at", "CURRENT_TIMESTAMP")}
                FROM job_prompt_refs
            """
            db.session.execute(text(copy_sql))
            db.session.execute(text("DROP TABLE job_prompt_refs"))
            db.session.execute(text("ALTER TABLE _job_prompt_refs_new RENAME TO job_prompt_refs"))
            db.session.commit()
            repaired.append("job_prompt_refs.prompt_key_unique")
        else:
            if "prompt_key" not in columns:
                db.session.execute(text(
                    "ALTER TABLE job_prompt_refs ADD COLUMN prompt_key VARCHAR(120) NOT NULL DEFAULT 'default'"
                ))
                if dialect == "mysql":
                    db.session.execute(text(
                        "UPDATE job_prompt_refs refs "
                        "JOIN prompt_versions prompts ON prompts.id = refs.prompt_version_id "
                        "SET refs.prompt_key = prompts.prompt_key "
                        "WHERE refs.prompt_key = 'default' AND prompts.prompt_key IS NOT NULL"
                    ))
                else:
                    db.session.execute(text(
                        "UPDATE job_prompt_refs "
                        "SET prompt_key = ("
                        "SELECT prompt_versions.prompt_key "
                        "FROM prompt_versions "
                        "WHERE prompt_versions.id = job_prompt_refs.prompt_version_id"
                        ") "
                        "WHERE prompt_key = 'default'"
                    ))
                db.session.commit()
                repaired.append("job_prompt_refs.prompt_key")
            unique_names = SchemaService._unique_constraint_names(inspector, "job_prompt_refs")
            if "uq_job_prompt_type_version" in unique_names:
                SchemaService._drop_unique_constraint("job_prompt_refs", "uq_job_prompt_type_version")
                repaired.append("job_prompt_refs.drop_uq_job_prompt_type_version")
            unique_names = SchemaService._unique_constraint_names(inspect(db.engine), "job_prompt_refs")
            if "uq_job_prompt_type_key_version" not in unique_names:
                db.session.execute(text(
                    "ALTER TABLE job_prompt_refs "
                    "ADD CONSTRAINT uq_job_prompt_type_key_version "
                    "UNIQUE (job_id, prompt_type, prompt_key, version)"
                ))
                db.session.commit()
                repaired.append("job_prompt_refs.uq_job_prompt_type_key_version")

        return repaired

    @staticmethod
    def _unique_constraint_names(inspector, table_name: str) -> set[str]:
        names = {
            constraint.get("name")
            for constraint in inspector.get_unique_constraints(table_name)
            if constraint.get("name")
        }
        for index in inspector.get_indexes(table_name):
            if index.get("unique") and index.get("name"):
                names.add(index["name"])
        return names

    @staticmethod
    def _has_unique_columns(inspector, table_name: str, columns: list[str]) -> bool:
        expected = tuple(columns)
        for constraint in inspector.get_unique_constraints(table_name):
            if tuple(constraint.get("column_names") or []) == expected:
                return True
        for index in inspector.get_indexes(table_name):
            if index.get("unique") and tuple(index.get("column_names") or []) == expected:
                return True
        return False

    @staticmethod
    def _drop_unique_constraint(table_name: str, constraint_name: str) -> None:
        dialect = db.engine.dialect.name
        if dialect == "mysql":
            db.session.execute(text(f"ALTER TABLE {table_name} DROP INDEX {constraint_name}"))
        else:
            db.session.execute(text(f"ALTER TABLE {table_name} DROP CONSTRAINT {constraint_name}"))
        db.session.commit()

    @staticmethod
    def _column_or_default(columns: set[str], column_name: str, default_sql: str) -> str:
        return column_name if column_name in columns else default_sql

    @staticmethod
    def _job_prompt_ref_key_expr(columns: set[str]) -> str:
        if "prompt_key" in columns:
            return "prompt_key"
        return (
            "COALESCE((SELECT prompt_key FROM prompt_versions "
            "WHERE prompt_versions.id = job_prompt_refs.prompt_version_id), 'default')"
        )

    @staticmethod
    def _add_template_series_sql() -> str:
        dialect = db.engine.dialect.name
        if dialect == "mysql":
            return "ALTER TABLE templates ADD COLUMN series VARCHAR(128) NULL AFTER name"
        if dialect == "sqlite":
            return "ALTER TABLE templates ADD COLUMN series VARCHAR(128)"
        return "ALTER TABLE templates ADD COLUMN series VARCHAR(128)"

    @staticmethod
    def _add_json_column_sql(table_name: str, column_name: str) -> str:
        dialect = db.engine.dialect.name
        if dialect == "mysql":
            return f"ALTER TABLE {table_name} ADD COLUMN {column_name} JSON NULL"
        if dialect == "sqlite":
            return f"ALTER TABLE {table_name} ADD COLUMN {column_name} JSON DEFAULT '{{}}'"
        return f"ALTER TABLE {table_name} ADD COLUMN {column_name} JSON"

    @staticmethod
    def _add_varchar_column_sql(table_name: str, column_name: str, length: int) -> str:
        return f"ALTER TABLE {table_name} ADD COLUMN {column_name} VARCHAR({length})"
