<<<<<<< HEAD
# Senior-Design-Mini-Project
=======
# VLM, S3, and SQLite Mini Project

This project demonstrates a simple image-processing pipeline using a **vision-language model (VLM)**:

1. Read PNG images from `assets/`.
2. Upload each image to an existing Amazon S3 bucket.
3. Send each image to Google Gemini for a one-sentence description.
4. Save the image filename, S3 URI, and description in SQLite and `results.txt`.

Gemini is the VLM because it receives both text and image data. This project uses Gemini as an existing model; it does not train a model from scratch.

## Project Structure

```text
assets/             PNG images processed by the program
src/main.py         Main pipeline
results.db          SQLite database created after a run
results.txt         Text file containing descriptions
requirements.txt    Python dependencies
```

## Requirements

- Python 3.10 or newer
- A Google Gemini API key
- An AWS account and an S3 bucket
- AWS credentials with permission to upload objects to that bucket

The S3 bucket must already exist. The program creates the `vlm-demo/` object prefix automatically when it uploads images, but it does not create the bucket.

## Installation

From the project directory, install the dependencies:

```powershell
python -m pip install -r requirements.txt
```

## Configuration

Create a file named `.env` in the project root. Use your own values:

```env
VLM_API_KEY=your-gemini-api-key
VLM_MODEL=gemini-2.0-flash

AWS_ACCESS_KEY_ID=your-aws-access-key
AWS_SECRET_ACCESS_KEY=your-aws-secret-key
S3_BUCKET=your-existing-bucket-name
```

The current code uses the `us-east-1` AWS region. If your bucket is in another region, update `region_name` in `src/main.py`.

Never commit `.env` or publish API keys and AWS secret keys. If a credential is exposed, revoke it and create a replacement.

## Run Without Cloud Services

Use demo mode to test the local pipeline without AWS or Gemini:

```powershell
python src/main.py --demo
```

This creates placeholder S3 URIs and placeholder VLM responses. It still writes the results to `results.db` and `results.txt`.

## Run With AWS and Gemini

After creating the S3 bucket and configuring `.env`, run:

```powershell
python src/main.py
```

Images are uploaded under keys like:

```text
vlm-demo/horse.png
```

The corresponding S3 URI is stored in the database, for example:

```text
s3://your-existing-bucket-name/vlm-demo/horse.png
```

## View Database Results

Open the database with SQLite:

```powershell
sqlite3 results.db
```

Then run:

```sql
.tables
SELECT * FROM image_results;
.quit
```

The `image_results` table contains:

- `filename`: the PNG filename
- `s3_uri`: the location of the uploaded image in S3
- `description`: Gemini's response

## Pipeline

```text
PNG image
   |
   +--> Amazon S3 upload
   |
   +--> Gemini VLM description
   |
   +--> SQLite and results.txt
```
>>>>>>> master
