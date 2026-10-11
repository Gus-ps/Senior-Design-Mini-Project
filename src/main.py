"""Small learning demo: S3 stores images, a VLM describes them, SQLite stores results."""

import argparse
import base64
import os
import sqlite3
from google import genai
from pathlib import Path
from dotenv import load_dotenv


load_dotenv()


def upload_image(image_path: Path, bucket: str, demo: bool) -> str:
    """Upload one image to S3 and return its S3 URI."""
    key = f"vlm-demo/{image_path.name}"
    if demo:
        return f"s3://{bucket}/{key}"

    import boto3 

    
    s3 = boto3.client("s3",
                      aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
                        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
                        region_name="us-east-1",)
    s3.upload_file(str(image_path), bucket, key)
    return f"s3://{bucket}/{key}"


def ask_vlm(image_path: Path, demo: bool) -> str:
    """Send an image to an OpenAI-compatible vision model."""
    if demo:
        return "Demo response: the VLM would describe the main subject here."

    api_key = os.environ["VLM_API_KEY"]
    model = os.getenv("VLM_MODEL", "gemini-3.6-flash")
    
    
    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(

        model=model,
        contents=[
            "What is in this image? Answer in one sentence.",
            genai.types.Part.from_bytes(
                data=image_path.read_bytes(),
                mime_type="image/png",
            ),
        ],
    )
    return response.text


def save_result(database: sqlite3.Connection, filename: str, s3_uri: str, description: str) -> None:
    
    database.execute(
        """
        CREATE TABLE IF NOT EXISTS image_results (
            filename TEXT PRIMARY KEY,
            s3_uri TEXT NOT NULL,
            description TEXT NOT NULL
        )
        """
    )

    database.execute(
        "INSERT OR REPLACE INTO image_results VALUES (?, ?, ?)",
        (filename, s3_uri, description),
    )
    database.commit()


def main() -> None:
    
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--demo", action="store_true", help="Run without AWS credentials")
    args = parser.parse_args()

    assets = Path(__file__).parent.parent / "assets"
    bucket = os.getenv("S3_BUCKET", "learning-vlm-bucket")
    images = sorted(assets.glob("*.png"))
    if not images:
        raise SystemExit(f"No PNG images found in {assets}")
    if not args.demo and not os.getenv("VLM_API_KEY"):
        raise SystemExit("Set VLM_API_KEY, or run `python src/main.py --demo` first.")

    with sqlite3.connect("results.db") as database:
        for image in images:
            s3_uri = upload_image(image, bucket, args.demo)
            description = ask_vlm(image, args.demo)
            save_result(database, image.name, s3_uri, description)
            with open("results.txt", "a") as f:
                f.write(f"{image.name}: {description}\n")


if __name__ == "__main__":
    main()