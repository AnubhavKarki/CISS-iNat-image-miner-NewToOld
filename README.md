# iNaturalist Image Downloader (Recent to Oldest)

Async Python tool to download species images and metadata from iNaturalist API with rate limiting and CSV logging.

## Features

- Async image downloads with `aiohttp` (20 concurrent connections)
- iNaturalist API rate limiting (9500 queries/day, 4GB/hour media)
- Species-specific folders with metadata CSV
- Resume capability via `species.csv` tracking
- Exception and incomplete species logging
- Configurable quality, size, and license filters

## Requirements

```bash
pip install aiohttp
```

Python 3.8+

## Quick Start

1. Create `species.csv` with columns: `name`, `missing_to_1000`, `max_inat_id`

```
name,missing_to_1000,max_inat_id
"Heliconius charithonia",150,1234567
"Monarch Butterfly",200,987654
```

2. Run downloader:

```bash
python downloader.py -q research -s medium -l any
```

## Usage

```bash
python downloader.py [-q QUALITY] [-s SIZE] [-l LICENSE]
```

**Arguments:**

| Flag | Description | Options | Default |
|------|-------------|---------|---------|
| `-q, --quality` | Observation quality grade | `research`, `any` | `research` |
| `-s, --size` | Image size | `small`, `medium`, `large`, `original` | `medium` |
| `-l, --license` | Photo license filter | `any`, `cc-by`, `cc-by-nc`, etc. | `any` |

## Output Structure

```
D:\inat_downloader\__results\
├── species_name\
│   ├── species_name_metadata.csv
│   └── species_name_observer_license_id_photo.jpeg
├── __results\
│   ├── incomplete_species_log.csv
│   └── exceptions_log.csv
```

**Metadata columns:** `species_name`, `observation_id`, `observation_license`, `observer_login`, `observation_quality`, `observation_date`, `observation_latitude`, `observation_longitude`

## Rate Limits

| Limit | Value | Reset |
|-------|-------|-------|
| API queries | 9500/day | 24h |
| Media download | 4GB/hour | 1h |
| Media download | 22GB/day | 24h |

Exceeds trigger warnings but continue execution.

## Resume Logic

- Tracks `max_inat_id` per species in `species.csv`
- Mines observations backward from last ID
- Stops at target count per species (`missing_to_1000`)
- Logs incomplete species for manual review

## File Naming

```
species-observer_license_id_photo.jpeg
```

Species prefix validation skips mismatches.

## Logging

- `incomplete_species_log.csv`: Species short of target
- `exceptions_log.csv`: Failed observations with error details

## Configuration

Hardcoded output: `D:\inat_downloader\__results`

Edit `log_dir` paths in `log_incomplete_species()` and `log_exception()` functions.

## API Endpoints

Uses `https://api.inaturalist.org/v1/observations` with filters:
- `taxon_name={species}`
- `quality_grade={quality}`
- `has[]=photos`
- `license={license}`
- `photo_license={license}`
- `id_below={start_id}` (backward pagination)
