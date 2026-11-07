import argparse

from compare_pipeline.db import get_pipeline_session
from compare_pipeline.jobs import request_job
from compare_pipeline.worker import Worker


def main():
    parser = argparse.ArgumentParser(
        description="Otamiser Competitor Intelligence Pipeline"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Worker subcommand
    subparsers.add_parser("worker", help="Run the background job worker")

    # Run subcommand
    run_parser = subparsers.add_parser("run", help="Trigger a pipeline job")
    run_subparsers = run_parser.add_subparsers(dest="job_type", required=True)

    # run seed-catalog
    run_subparsers.add_parser(
        "seed-catalog", help="Seed catalog from otamiser.com/compare"
    )

    # run discover
    run_subparsers.add_parser("discover", help="Run AI competitor discovery")

    # run research --competitor-id
    res_parser = run_subparsers.add_parser(
        "research", help="Run evidence research on a competitor"
    )
    res_parser.add_argument("--competitor-id", required=True, help="Competitor UUID")

    # run generate --competitor-id
    gen_parser = run_subparsers.add_parser("generate", help="Generate comparison draft")
    gen_parser.add_argument("--competitor-id", required=True, help="Competitor UUID")

    # run gate --article-id
    gate_parser = run_subparsers.add_parser(
        "gate", help="Run automated 10-check gate on draft"
    )
    gate_parser.add_argument("--article-id", required=True, help="Article UUID")

    # run push-webflow --article-id
    wf_parser = run_subparsers.add_parser(
        "push-webflow", help="Push approved draft to Webflow test site"
    )
    wf_parser.add_argument("--article-id", required=True, help="Article UUID")

    # export-schema
    subparsers.add_parser(
        "export-schema",
        help="Export Pydantic Article schema to schemas/article.schema.json",
    )

    # validate
    val_parser = subparsers.add_parser(
        "validate", help="Run validation benchmarks (V1-V12)"
    )
    val_parser.add_argument("goal", help="Goal identifier (e.g. V1, V3, or 'all')")

    # report
    subparsers.add_parser("report", help="Generate validation report")

    args = parser.parse_args()

    if args.command == "worker":
        worker = Worker()
        worker.start()
    elif args.command == "run":
        with get_pipeline_session() as session:
            payload = {}
            if args.job_type in ("research", "generate"):
                payload["competitor_id"] = args.competitor_id
            elif args.job_type in ("gate", "push_webflow", "push-webflow"):
                payload["article_id"] = args.article_id

            job_id = request_job(
                session=session,
                kind=args.job_type.replace("-", "_"),
                payload=payload,
                requested_by="cli",
            )
            print(f"Queued job {job_id} of kind '{args.job_type}'")
    elif args.command == "export-schema":
        from compare_pipeline.export_schema import export_schema

        export_schema()
    elif args.command == "validate":
        from compare_pipeline.validation import run_validations

        res = run_validations()
        print(f"Validation metrics computed: {res}")
    elif args.command == "report":
        from compare_pipeline.validation import generate_validation_report

        generate_validation_report()


if __name__ == "__main__":
    main()
