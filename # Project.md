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


## 6. Cretae a cli script called qrz.py

Create a CLI utility called qrz.py that uses the QRZ.com API to query for a single callsign. The input will be a text string that will passed to QRZ as a callsign. 

The output should be a table with the information returned by QRZ.




