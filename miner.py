import argparse
import csv
import os
import datetime
import asyncio
import aiohttp
from aiohttp import ClientSession, ClientTimeout, TCPConnector

# iNaturalist query limits, minus a safety margin
MAX_QUERIES_PER_DAY = 9500
MAX_MEDIA_PER_HOUR = 4
MAX_MEDIA_PER_DAY = 22

# User query tracking
my_daily_queries = {"value": 0, "reset_time": datetime.datetime.now() + datetime.timedelta(hours=24)}
my_hourly_media = {"value": 0, "reset_time": datetime.datetime.now() + datetime.timedelta(hours=1)}
my_daily_media = {"value": 0, "reset_time": datetime.datetime.now() + datetime.timedelta(hours=24)}

# Run information
current_images_number = 0
current_dataset_size = 0

# Logging
def log_incomplete_species(species_name, images_downloaded, missing_images):
    log_dir = r"D:\inat_downloader\__results"
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, "incomplete_species_log.csv")
    file_exists = os.path.exists(log_path)
    with open(log_path, 'a', newline='', encoding='utf-8') as log_file:
        writer = csv.writer(log_file)
        if not file_exists:
            writer.writerow(['species_name', 'images_downloaded', 'missing_images'])
        writer.writerow([species_name, images_downloaded, missing_images])

def log_exception(species_name, obs_id, exception_msg):
    log_dir = r"D:\inat_downloader\__results"
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, "exceptions_log.csv")
    file_exists = os.path.exists(log_path)
    with open(log_path, 'a', newline='', encoding='utf-8') as log_file:
        writer = csv.writer(log_file)
        if not file_exists:
            writer.writerow(['species_name', 'observation_id', 'exception'])
        writer.writerow([species_name, obs_id, exception_msg])

# Rate Evaluation
def evaluate_query_rate():
    if my_daily_queries["value"] > MAX_QUERIES_PER_DAY:
        print(f"WARNING: Daily query limit reached ({my_daily_queries['value']}) — continuing anyway.")
        my_daily_queries["value"] = 0
        my_daily_queries["reset_time"] = datetime.datetime.now() + datetime.timedelta(hours=24)

def evaluate_media_rate():
    if my_hourly_media["value"] > MAX_MEDIA_PER_HOUR:
        print(f"WARNING: Hourly media limit reached ({my_hourly_media['value']:.2f} GB) — continuing anyway.")
        my_hourly_media["value"] = 0
        my_hourly_media["reset_time"] = datetime.datetime.now() + datetime.timedelta(hours=1)

    if my_daily_media["value"] > MAX_MEDIA_PER_DAY:
        print(f"WARNING: Daily media limit reached ({my_daily_media['value']:.2f} GB) — continuing anyway.")
        my_daily_media["value"] = 0
        my_daily_media["reset_time"] = datetime.datetime.now() + datetime.timedelta(hours=24)

# Image Download
async def download_image(session: ClientSession, image_url, file_path):
    global current_images_number, current_dataset_size
    try:
        async with session.get(image_url) as resp:
            if resp.status == 200:
                content = await resp.read()
                os.makedirs(os.path.dirname(file_path), exist_ok=True)
                with open(file_path, "wb") as f:
                    f.write(content)
                current_images_number += 1
                current_dataset_size += len(content) / 1e6
                print(f"INFO: {current_images_number} images downloaded ({round(current_dataset_size, 2)} MB)")
                my_hourly_media["value"] += len(content) / 1e9
                my_daily_media["value"] += len(content) / 1e9
                evaluate_media_rate()
            else:
                print(f"WARNING: Couldn't download image at {image_url} (status {resp.status})")
    except Exception as e:
        print(f"ERROR downloading {image_url}: {e}")

# Download Observations
async def download_observations(species_name, observations, image_size, session, target_images):
    global current_images_number
    species_folder = os.path.join(
        r"D:\inat_downloader\__results",
        species_name.replace(" ", "_")
    )
    os.makedirs(species_folder, exist_ok=True)
    metadata_file_path = os.path.join(species_folder, f"{species_name.replace(' ', '_')}_metadata.csv")
    metadata_file_exists = os.path.exists(metadata_file_path)

    with open(metadata_file_path, 'a', newline='', encoding='utf-8') as metadata_file:
        csv_writer = csv.writer(metadata_file)
        if not metadata_file_exists:
            csv_writer.writerow([
                'species_name', 'observation_id', 'observation_license', 'observer_login',
                'observation_quality', 'observation_date', 'observation_latitude', 'observation_longitude'
            ])

        species_hyphen = species_name.lower().replace(" ", "-")

        for obs in observations:
            if current_images_number >= target_images:
                break
            try:
                species = obs["taxon"]["name"]
                obs_id = obs["id"]
                obs_license = obs.get("license_code") or "none"
                observer_login = obs["user"]["login"]
                obs_quality = obs.get("quality_grade") or "none"
                obs_date = obs.get("observed_on") or "none"
                obs_lat = obs_lon = "none"
                if obs.get("geojson"):
                    obs_lat = obs["geojson"]["coordinates"][1] or "none"
                    obs_lon = obs["geojson"]["coordinates"][0] or "none"

                csv_writer.writerow([species, obs_id, obs_license, observer_login, obs_quality, obs_date, obs_lat, obs_lon])

                for photo_id, photo in enumerate(obs["photos"]):
                    if current_images_number >= target_images:
                        break

                    file_name = f"{species.replace(' ', '-')}_{observer_login}_{obs_license}_{obs_id}_{photo_id}.jpeg"
                    if not file_name.lower().startswith(species_hyphen):
                        print(f"SKIP: Image filename '{file_name}' does not match species '{species_name}'")
                        continue

                    file_path = os.path.join(species_folder, file_name)
                    await download_image(session, photo["url"].replace("/square", f"/{image_size}"), file_path)

            except Exception as e:
                log_exception(species_name, obs.get("id", "n/a"), str(e))
                print(f"WARNING: Skipping observation {obs.get('id', 'n/a')} due to exception: {e}")

# Fetch Observations
async def fetch_observations(session, species, quality, license_str, start_id, per_page, lat=None, lng=None, radius=None):
    url = (
        f"https://api.inaturalist.org/v1/observations?"
        f"taxon_name={species}&quality_grade={quality}&has[]=photos&license={license_str}"
        f"&photo_license={license_str}&page=1&per_page={per_page}&order_by=id&order=desc&id_below={start_id}"
    )

    async with session.get(url) as resp:
        my_daily_queries["value"] += 1
        evaluate_query_rate()
        data = await resp.json()
        return data.get("results", [])

# Main
async def main():
    parser = argparse.ArgumentParser(description="Download images from iNaturalist")
    parser.add_argument("-q", "--quality", default="research", choices=["research", "any"])
    parser.add_argument("-s", "--size", default="medium", choices=["small", "medium", "large", "original"])
    parser.add_argument("-l", "--license", default="any")
    args = parser.parse_args()

    print("\n-------------------------- SCRIPT STARTED --------------------------\n")

    my_species = []
    if os.path.exists("species.csv"):
        with open("species.csv", "r", encoding="utf-8") as species_file:
            species_reader = list(csv.DictReader(species_file))
            for row in species_reader:
                try:
                    missing = int(row.get("missing_to_1000", 0))
                except:
                    missing = 0
                if missing > 0 and row["name"] not in [s["name"] for s in my_species]:
                    start_id = int(row.get("max_inat_id", 0))  # start from last ID
                    my_species.append({
                        "name": row["name"],
                        "start_id": start_id,
                        "missing_to_1000": missing
                    })
    else:
        print("ERROR: species.csv file not found")
        return

    os.makedirs(r"D:\inat_downloader\__results", exist_ok=True)
    timeout = ClientTimeout(total=60)
    connector = TCPConnector(limit=20)

    async with ClientSession(timeout=timeout, connector=connector) as session:
        global current_images_number, current_dataset_size
        for species in my_species:
            current_images_number = 0
            current_dataset_size = 0
            id_below = species["start_id"]  # backward mining
            download_target = species["missing_to_1000"]

            while current_images_number < download_target:
                try:
                    obs_batch = await fetch_observations(
                        session, species["name"], args.quality, args.license, id_below,
                        min(200, download_target - current_images_number)
                    )
                    if not obs_batch:
                        print(f"INFO: No more observations returned for {species['name']}, stopping early.")
                        break

                    # Update id_below to continue backward sequential mining
                    id_below = min(obs["id"] for obs in obs_batch) - 1

                    await download_observations(species["name"], obs_batch, args.size, session, download_target)
                except Exception as e:
                    log_exception(species["name"], "n/a", str(e))
                    print(f"WARNING: Skipping batch for {species['name']} due to exception: {e}")

            missing_images = max(0, download_target - current_images_number)
            if missing_images > 0:
                log_incomplete_species(species["name"], current_images_number, missing_images)
                print(f"WARNING: {species['name']} - only {current_images_number} images downloaded, {missing_images} missing.")
            else:
                print(f"INFO: Images and metadata download for {species['name']} complete with full set.")

    print("\nSCRIPT TERMINATED SUCCESSFULLY\n")

if __name__ == "__main__":
    asyncio.run(main())
