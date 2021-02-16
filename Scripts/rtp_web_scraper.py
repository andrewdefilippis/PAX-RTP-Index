#!/usr/bin/env python3

import argparse
import json
import yaml
from datetime import datetime
from re import match
from urllib.request import urlopen

from bs4 import BeautifulSoup


def html_parser(data, year):
    text = ""

    soup = BeautifulSoup(data, "html.parser")
    h1_tags = soup.find_all("h1")
    table = soup.find("table")

    # Confirm that the page being viewed is the same year being requested
    for header in h1_tags:
        h_text = header.get_text()
        if match('^[0-9]{4}.*RTP Index', h_text):
            h_year = h_text.split(' ')[0]

            if year is not None and not match("^{}".format(year), h_text):
                raise ValueError("The year \"{}\" in the header on the PAX page, does not match the requested year: {}".format(h_year, year))
            elif year is None:
                year = h_year
                json_output = {year: {}}
            else:
                json_output = {year: {}}

    # Loop through the rows and columns for the PAX/RTP data
    for row in table.find_all("tr"):
        for td in row.find_all("td"):
            try:
                if match('^\s*[A-Za-z]', td.get_text()):
                    text = td.get_text().strip().strip("*").split(' ')[0]
                    json_output[year][text] = None
                elif match('^\s*[0-9]', td.get_text()):
                    json_output[year][text] = float(td.get_text().strip())
            except Exception as e:
                continue

    return json_output


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-y", "--year", type=int, help="Year for PAX/RTP data")
    args = parser.parse_args()
    year = args.year
    now_year = datetime.now().year

    earliest_rtp_year = 1995
    base_page = "https://www.solotime.info/pax/"
    rtp_html = "rtp{}.html"

    # From the /rtp2021.html document as of 2021-02-15:
    #
    # Please update your links and bookmarks to http://solotime.info/pax/
    # This corrected link will then be correct every year and always have the newest numbers!
    if year is None or year == now_year:
        year = now_year
        url = base_page
    elif year == now_year + 1:
        # Allow specification of the next year for when RTP data is released before January 1st of said year.
        # The year will be validated against the year specified in the header on the PAX html page.
        url = base_page
    elif year >= earliest_rtp_year and year <= now_year - 1:
        url = base_page + rtp_html.format(year)
    else:
        raise ValueError("Value supplied for year must be from {} to {}.".format(earliest_rtp_year, now_year))

    data = urlopen(url).read()
    json_output = html_parser(data, year)

    formatted_json = json.dumps(json_output, indent=2, sort_keys=True)
    with open("./JSON/{}.json".format(year), "w") as json_file:
        json_file.write(formatted_json)
    with open("./YAML/{}.yaml".format(year), "w") as yaml_file:
        yaml_file.write("---\n")
        yaml_file.write(yaml.dump(json_output))

    print(formatted_json)
    print("\n---\n" + yaml.dump(json_output))


if __name__ == '__main__':
    main()
