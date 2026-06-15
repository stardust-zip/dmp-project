"""
One-off script: backfill primaryspaceusage into Location.metadata_ and fix
anomaly_detected_event.primary_space_usage rows stored as 'NaN'.
"""
import math
import os

import pandas as pd
from sqlalchemy import text

DATA_DIR = "/app/data/raw/data"


def run():
    from src.database import SessionLocal, init_db

    init_db()
    db = SessionLocal()

    try:
        meta_path = os.path.join(DATA_DIR, "metadata", "metadata.csv")
        df = pd.read_csv(meta_path)

        # --- Step 1: update Location.metadata_ ---
        updated_locations = 0
        for _, row in df.iterrows():
            b_id = str(row["building_id"])
            psu_val = row.get("primaryspaceusage")
            if not isinstance(psu_val, str) or psu_val.strip().lower() in ("nan", ""):
                continue

            db.execute(
                text("""
                    UPDATE location
                    SET metadata = COALESCE(metadata, '{}'::jsonb) || jsonb_build_object('primaryspaceusage', :psu)
                    WHERE id = :bid
                """),
                {"psu": psu_val.strip(), "bid": b_id},
            )
            updated_locations += 1

        db.commit()
        print(f"Updated {updated_locations} Location records with primaryspaceusage.")

        # --- Step 2: fix anomaly_detected_event rows stored as 'NaN' or NULL ---
        result = db.execute(
            text("""
                UPDATE anomaly_detected_event e
                SET primary_space_usage = l.metadata->>'primaryspaceusage'
                FROM location l
                WHERE e.building_id = l.id
                  AND (e.primary_space_usage = 'NaN' OR e.primary_space_usage IS NULL)
                  AND l.metadata->>'primaryspaceusage' IS NOT NULL
            """)
        )
        db.commit()
        print(f"Fixed {result.rowcount} anomaly_detected_event rows.")

        # --- Verify ---
        row = db.execute(
            text("""
                SELECT
                  COUNT(*) AS total,
                  COUNT(CASE WHEN primary_space_usage IS NOT NULL
                              AND primary_space_usage != 'NaN' THEN 1 END) AS good,
                  COUNT(DISTINCT primary_space_usage) AS distinct_vals
                FROM anomaly_detected_event
            """)
        ).fetchone()
        print(f"Verification — total: {row[0]}, good psu: {row[1]}, distinct values: {row[2]}")

    except Exception as exc:
        db.rollback()
        raise exc
    finally:
        db.close()


if __name__ == "__main__":
    run()
