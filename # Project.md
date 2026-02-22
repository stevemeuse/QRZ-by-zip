# Project.md

Create a project that takes API data from QRZ.com. We will query QRZ.com for a given zip code, return a list of all registered ham radio operators in that zip code and list the number of profile views each operator has.

## 1. QRZ.com

QRZ.com is the source of the data. The QRZ XML API is queried with a callsign to retrieve operator profile data including view counts. The FCC amateur radio licensee database (EN.dat, sourced from the FCC bulk download at data.fcc.gov) is used to look up all callsigns registered to a given zip code.

- EN.dat is downloaded via HTTP range requests (avoiding the full 173 MB ZIP download)
- EN.dat is cached locally at `~/.cache/qrz/en_dat.gz` and refreshed every 7 days

## 2. Authentication

The credentials for the API call are stored in a file in the user's home directory called `.qrz` in JSON format:

```json
{ "login": "CALLSIGN", "api": "your_qrz_password" }
```

Accepted keys: `login`, `username`, or `email` for the login name; `api` for the password.

## 3. Output

The output is a CSV file named `ham_operators_<zipcode>.csv` with two columns:

- **Callsign** — the FCC/QRZ callsign
- **Profile Views** — number of QRZ profile views

### Output behavior:
- If the output file already exists, it is deleted before writing a new one
- Records are de-duplicated by callsign before writing
- Records are sorted by Profile Views, descending

## 4. Usage

```
python3 qrz_lookup.py <zipcode>
```

## 5. Bulk County Run — Plymouth County, MA

The script was run for all 36 zip codes in Plymouth County, Massachusetts. Output files were stored in the `Plymouth/` subdirectory.

### Plymouth County zip codes processed:
02043, 02045, 02047, 02050, 02061, 02066, 02301, 02302, 02324, 02325, 02330,
02332, 02333, 02338, 02339, 02341, 02346, 02347, 02350, 02351, 02359, 02360,
02364, 02366, 02367, 02370, 02379, 02382, 02532, 02538, 02558, 02571, 02576,
02738, 02739, 02770

- 35 CSV files produced (02325 had no registered operators)
- A combined county-wide file `Plymouth/ham_operators_plymouth_co.csv` was created by concatenating all zip-level files
- The combined file was de-duplicated and sorted by Profile Views, descending
- Final combined file: **1,484 unique operator records**
- All CSV files were archived into `Plymouth/ham_data_plymouth.zip` (26 KB)
