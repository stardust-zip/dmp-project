import argparse
import math
import os

import pandas as pd
from sqlalchemy.orm import Session
from src import models, schemas
from src.database import SessionLocal, init_db
from src.schemas import IngestionStatus

DATA_DIR = "/app/data/raw/data"


def get_or_create(db: Session, model, **kwargs):
    instance = db.query(model).filter_by(**kwargs).first()
    if not instance:
        instance = model(**kwargs)
        db.add(instance)
    return instance


def seed_lookups(db: Session):
    print("Seeding Lookup Tables...")

    device_types = [
        {
            "id": "virtual_meter",
            "description": "Virtual meter aggregated from kaggle data. This is not a real device in the sense that we have information about them, for every metric that we don't have the real device's info, its id will be virual_meter.",
        }
    ]
    for dt in device_types:
        get_or_create(db, models.DeviceType, **dt)

    metric_units = {
        "electricity": "kWh",
        "solar": "kWh",
        "steam": "kg",
        "hotwater": "m3",
        "chilledwater": "m3",
        "gas": "m3",
        "water": "m3",
        "irrigation": "m3",
    }
    for m, unit in metric_units.items():
        metric = db.query(models.MetricType).filter_by(id=m).first()
        if metric:
            metric.unit = unit
            metric.description = metric.description or f"{m} consumption"
        else:
            db.add(
                models.MetricType(
                    id=m,
                    unit=unit,
                    description=f"{m} consumption",
                )
            )

    db.commit()


def seed_metadata(db: Session):
    print("Seeding Locations and Devices from metadata.csv...")
    meta_path = os.path.join(DATA_DIR, "metadata", "metadata.csv")
    if not os.path.exists(meta_path):
        print(f"Metadata file not found at {meta_path}")
        return

    df_meta = pd.read_csv(meta_path)

    # Seed Location Types
    loc_types = df_meta["primaryspaceusage"].unique()

    for lt in loc_types:
        lt_str = "Unknown" if pd.isna(lt) else str(lt)
        get_or_create(db, models.LocationType, id=lt_str)
    if "site_id" in df_meta.columns:
        get_or_create(db, models.LocationType, id="site")

    db.commit()

    if "site_id" in df_meta.columns:
        for site_id in sorted(df_meta["site_id"].dropna().astype(str).unique()):
            get_or_create(
                db,
                models.Location,
                id=site_id,
                location_type_id="site",
                name=f"Site {site_id}",
            )
        db.commit()

    # Seed Locations
    for _, row in df_meta.iterrows():
        b_id = str(row["building_id"])
        site_id = None
        if "site_id" in df_meta.columns:
            raw_site_id = row.get("site_id")
            if not pd.isna(raw_site_id):
                site_id = str(raw_site_id)

        metadata_dict = {}

        sqm_val = row.get("sqm")
        if isinstance(sqm_val, (int, float)) and not math.isnan(float(sqm_val)):
            metadata_dict["sqm"] = float(sqm_val)

        tz_val = row.get("timezone")
        if isinstance(tz_val, str) and tz_val.strip().lower() != "nan":
            metadata_dict["timezone"] = str(tz_val)

        yb_val = row.get("yearbuilt")
        if isinstance(yb_val, (int, float)) and not math.isnan(float(yb_val)):
            metadata_dict["yearbuilt"] = float(yb_val)

        # Safely handle primaryspaceusage for the type checker
        psu_val = row.get("primaryspaceusage")
        if isinstance(psu_val, str) and psu_val.strip().lower() != "nan":
            loc_type_id = str(psu_val)
        else:
            loc_type_id = "Unknown"

        # Validate via Pydantic schema with explicit type casting
        loc_payload = schemas.LocationCreate(
            id=b_id,
            location_type_id=loc_type_id,
            name=f"Building {b_id}",
            metadata=metadata_dict,
        )
        get_or_create(
            db,
            models.Location,
            id=loc_payload.id,
            parent_id=site_id,
            location_type_id=loc_payload.location_type_id,
            name=loc_payload.name,
            metadata_=loc_payload.metadata,
        )
    db.commit()


def seed_telemetry(db: Session, limit: int | None = 1000):
    """
    Seeds timeseries telemetry data.
    limit: Max rows to read from CSV for testing purposes. Set to None for full load.
    """
    print("Seeding Telemetry Data (Meters)...")
    meters_dir = os.path.join(DATA_DIR, "meters", "cleaned")

    if not os.path.exists(meters_dir):
        print(f"Meters directory not found at {meters_dir}")
        return

    metrics = [
        "electricity",
        "chilledwater",
        "steam",
        "hotwater",
        "gas",
        "water",
        "solar",
        "irrigation",
    ]

    for metric in metrics:
        csv_path = os.path.join(meters_dir, f"{metric}_cleaned.csv")
        if not os.path.exists(csv_path):
            continue

        print(f"Processing {metric} data...")

        # Read limited rows to avoid memory/time exhaustion during initial dev
        df = pd.read_csv(csv_path, nrows=limit)

        # Melt dataframe to transform building columns into rows
        df_melted = df.melt(
            id_vars=["timestamp"], var_name="building_id", value_name="value"
        )
        df_melted = df_melted.dropna(subset=["value"])

        # Ensure timestamp is timezone-aware
        df_melted["timestamp"] = pd.to_datetime(df_melted["timestamp"], utc=True)

        db_records = []
        devices_created = set()

        for _, row in df_melted.iterrows():
            # Explicitly cast to string
            b_id = str(row["building_id"])
            device_id = f"meter_{metric}_{b_id}"

            # Ensure Device exists before inserting telemetry
            if device_id not in devices_created:
                dev_payload = schemas.DeviceCreate(
                    id=device_id,
                    location_id=b_id,
                    device_type_id="virtual_meter",
                    status="Active",
                )
                get_or_create(db, models.Device, **dev_payload.model_dump())
                db.commit()
                devices_created.add(device_id)

            # Validate Telemetry Data via Pydantic
            try:
                # Bypass Pyright's strictness by casting the Series value to a native string first
                raw_ts = str(row["timestamp"])
                py_timestamp = pd.to_datetime(raw_ts).to_pydatetime()

                # Cast value to string before float to ensure type safety for Pyright
                raw_val = str(row["value"])

                telemetry_payload = schemas.TelemetryDataPayload(
                    timestamp=py_timestamp,
                    device_id=device_id,
                    metric_type_id=metric,
                    value=float(raw_val),
                    ingestion_status=IngestionStatus.Success,
                )
                db_records.append(
                    models.TelemetryData(**telemetry_payload.model_dump())
                )
            except Exception as e:
                print(f"Validation failed for {device_id} at {row['timestamp']}: {e}")

            # Batch insert to avoid huge memory spikes
            if len(db_records) >= 5000:
                db.bulk_save_objects(db_records)
                db.commit()
                db_records.clear()

        # Insert remaining records
        if db_records:
            db.bulk_save_objects(db_records)
            db.commit()

    print("Telemetry seeding completed.")


def run_seeder(limit: int | None = 1000):
    init_db()
    db = SessionLocal()
    try:
        seed_lookups(db)
        seed_metadata(db)
        # Limiting to 1000 records per metric type for fast PoC testing
        # Change limit=None when you want the full Kaggle dataset imported
        seed_telemetry(db, limit=limit)
        print("Database successfully seeded!")
    except Exception as e:
        db.rollback()
        print(f"An error occurred during seeding: {e}")
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Seed the DMP database with Smart City data."
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=1000,
        help="Max rows to seed per metric for fast testing. Default: 1000.",
    )

    parser.add_argument(
        "--full",
        action="store_true",
        help="Seed the entire dataset. This overrides the --limit flag.",
    )

    args = parser.parse_args()

    final_limit = None if args.full else args.limit

    run_seeder(limit=final_limit)
