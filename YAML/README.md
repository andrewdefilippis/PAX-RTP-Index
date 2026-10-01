# YAML

*The files included within this directory contain RTP/PAX data in YAML format.*

These files are generated from `CSV/` by `Scripts/rtp_files_generator.py`. Do not edit them by hand.

* `<year>.yaml`: indices for one year. The year key is a string (`'2026':`), matching the JSON files. [Schema](../Schema/rtp-year.schema.json)
* `latest.yaml`: the newest published year, same shape.

All years and class metadata are in [`../rtp.yaml`](../rtp.yaml).
