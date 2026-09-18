"""Command Line Interface for Transit Planner backend."""
import argparse
import sys
from pathlib import Path
import uvicorn

from .storage.database import get_db_path, create_connection, init_db
from .services.data_importer import seed_network_and_geometries, inspect_and_import_csvs, DATA_RAW_DIR

def main():
    parser = argparse.ArgumentParser(description="Transit Planner Backend CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # init
    init_parser = subparsers.add_parser("init", help="Initialize SQLite database and import source CSVs")
    init_parser.add_argument("--source-dir", type=str, default=str(DATA_RAW_DIR), help="Path to raw CSV directory")
    init_parser.add_argument("--mode", type=str, default="demo", choices=["demo", "live"], help="Database mode")
    init_parser.add_argument("--reset", action="store_true", help="Force reset existing tables")

    # reset
    reset_parser = subparsers.add_parser("reset", help="Reset demo database")
    reset_parser.add_argument("--mode", type=str, default="demo", choices=["demo", "live"], help="Database mode")

    # serve
    serve_parser = subparsers.add_parser("serve", help="Run FastAPI server")
    serve_parser.add_argument("--host", type=str, default="127.0.0.1", help="Host address")
    serve_parser.add_argument("--port", type=int, default=8000, help="Port number")
    serve_parser.add_argument("--mode", type=str, default="demo", choices=["demo", "live"], help="Database mode")

    args = parser.parse_args()

    if args.command in ("init", "reset"):
        db_path = get_db_path(args.mode)
        conn = create_connection(db_path)
        print(f"Connecting to database: {db_path}")

        force_reset = getattr(args, "reset", False) or (args.command == "reset")
        seed_network_and_geometries(conn, dataset_id=f"{args.mode}-seed-1", mode=args.mode, force_reset=force_reset)
        print("Seeded network nodes, lanes, calendar rules and geometries.")

        src_dir = Path(getattr(args, "source_dir", str(DATA_RAW_DIR)))
        if src_dir.exists():
            findings = inspect_and_import_csvs(conn, src_dir)
            print(f"Imported source CSVs from {src_dir}: {len(findings)} files processed.")
        else:
            print(f"Warning: source directory {src_dir} not found.")

        conn.close()
        print("Initialization complete.")

    elif args.command == "serve":
        import os
        os.environ["TRANSIT_MODE"] = args.mode
        print(f"Starting server on {args.host}:{args.port} (mode={args.mode})")
        uvicorn.run("backend.app.main:app", host=args.host, port=args.port, reload=False)

if __name__ == "__main__":
    main()
