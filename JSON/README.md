# JSON

*The files included within this directory contain RTP/PAX data in JSON format.*

These files are generated from `CSV/` by `Scripts/rtp_files_generator.py`. Do not edit them by hand.

* `<year>.json`: indices for one year, `{"<year>": {"<class>": <index>}}`. [Schema](../Schema/rtp-year.schema.json)
* `latest.json`: the newest published year, same shape.

All years and class metadata are in [`../rtp.json`](../rtp.json) ([schema](../Schema/rtp.schema.json)).
