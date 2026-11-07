import urllib.parse

import psycopg

from compare_pipeline.config import settings


def parse_role_credentials(url: str):
    parsed = urllib.parse.urlparse(url)
    return parsed.username, parsed.password, parsed.path.lstrip("/")


def bootstrap_roles():
    """Connects as superuser and provisions migrator, pipeline_rw, and web_app roles."""
    admin_user, admin_pass, db_name = parse_role_credentials(settings.DATABASE_URL)
    migrator_user, migrator_pass, _ = parse_role_credentials(
        settings.DATABASE_URL_MIGRATOR
    )
    pipeline_user, pipeline_pass, _ = parse_role_credentials(
        settings.DATABASE_URL_PIPELINE
    )
    web_user, web_pass, _ = parse_role_credentials(settings.DATABASE_URL_WEB)

    print(f"Connecting to database '{db_name}' as superuser '{admin_user}'...")
    conn = psycopg.connect(settings.DATABASE_URL, autocommit=True)
    with conn.cursor() as cur:
        roles = [
            (migrator_user, migrator_pass),
            (pipeline_user, pipeline_pass),
            (web_user, web_pass),
        ]
        for role_name, role_pass in roles:
            cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role_name,))
            if not cur.fetchone():
                print(f"Creating role '{role_name}'...")
                query = psycopg.sql.SQL("CREATE ROLE {} WITH LOGIN PASSWORD {}").format(
                    psycopg.sql.Identifier(role_name),
                    psycopg.sql.Literal(role_pass),
                )
                cur.execute(query)
            else:
                print(f"Updating password for role '{role_name}'...")
                query = psycopg.sql.SQL("ALTER ROLE {} WITH LOGIN PASSWORD {}").format(
                    psycopg.sql.Identifier(role_name),
                    psycopg.sql.Literal(role_pass),
                )
                cur.execute(query)

            grant_query = psycopg.sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                psycopg.sql.Identifier(db_name),
                psycopg.sql.Identifier(role_name),
            )
            cur.execute(grant_query)

        # Create schema 'app' owned by migrator
        cur.execute("CREATE SCHEMA IF NOT EXISTS app;")
        cur.execute(
            psycopg.sql.SQL("ALTER SCHEMA app OWNER TO {}").format(
                psycopg.sql.Identifier(migrator_user)
            )
        )
        cur.execute(
            psycopg.sql.SQL("GRANT USAGE, CREATE ON SCHEMA app TO {}").format(
                psycopg.sql.Identifier(migrator_user)
            )
        )

    conn.close()
    print("Database roles and schema 'app' successfully bootstrapped.")


if __name__ == "__main__":
    bootstrap_roles()
