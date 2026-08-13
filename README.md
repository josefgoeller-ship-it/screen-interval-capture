# Screen Interval Capture

Small Windows 10/11 GUI that captures the full desktop on a fixed interval and saves PNG screenshots named by capture time.

## Setup

```bash
cd C:\MyProjects\screen-interval-capture
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## Run

```bash
python main.py
```

## Usage

1. Choose an output folder (or keep the default `captures` folder).
2. Set the interval in seconds.
3. Click **Start** to begin capturing; **Stop** to pause.

Filenames look like `2026-08-13_21-26-45.png`. Settings are saved in `config.json`.
