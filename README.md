# Image attribute pipeline

Read images, ask Gemini for descriptions and item attributes, upload the images
to Amazon S3, and save the results in SQLite, JSON, and text.

## Setup

Python 3.10 or newer is required. From the project folder:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Create `.env` in the project root using `.env.example` as a template. Configure
a Gemini API key, an available image-capable model, an existing S3 bucket,
the bucket's region, and AWS upload credentials. Temporary credentials also
require `AWS_SESSION_TOKEN`. You can use a configured AWS profile instead.

## Run

```powershell
.\.venv\Scripts\python.exe src/main.py
```

With the virtual environment already active, the command is simply:

```powershell
python src/main.py
```

The program prints progress for each image and saves the actual results to
`outputs/cloud/`. Images without identifiable attributes use `null`; no
placeholder descriptions or fixed demo fixtures are used.

View the saved database:

```powershell
python src/main.py --view
```

Use another input folder or output location:

```powershell
python src/main.py --input-dir C:\path\to\images --output-dir outputs\custom
```

## Results

- `results.db`: filename, S3 URI, description, item type, color, brand,
  distinctive features, run mode, and model.
- `results.json`: successful records from the current run.
- `results.txt`: readable descriptions and attributes from the current run.
- `run_report.json`: success/failure counts and per-image errors.

Supported inputs are PNG, JPEG, and WebP. The contents determine the MIME type,
including JPEG data stored in files named `.png`. Folders are scanned without
recursing into subfolders.

The application validates Gemini's JSON with Pydantic, updates records by
filename, and continues after an individual image fails. A batch with failures
exits with code 1; configuration errors exit with code 2. JSON validity does not
guarantee the model's descriptions are factually correct.

SQLite migration preserves untouched old records. Processing the same filename
updates that record and its S3 object, so use separate outputs/object naming
when working with distinct datasets that reuse filenames. Text and JSON exports
are replaced on each run; the database retains older unprocessed records.

## Before comparison

The unchanged teammate code remains in the sibling
`Senior-Design-Mini-Project-baseline` folder. From its `cloud-results` directory:

```powershell
& C:\Users\abhig\Senior-Design-Mini-Project\.venv\Scripts\python.exe ..\src\main.py
Get-Content results.txt
```

The baseline produces sentence descriptions. The final application adds
structured attributes, validation, correct MIME handling, stable exports, and
visible progress/error reporting.

The assignment write-up is `Abhigyan Assignment 5 responses.txt`.
