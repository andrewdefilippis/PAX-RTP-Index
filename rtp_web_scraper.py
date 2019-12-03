#!/usr/bin/env python3

import argparse
import json
from datetime import datetime
from re import match
from urllib.request import urlopen

from bs4 import BeautifulSoup


def html_parser(data, year):
    json_file = {year: {}}
    text = ""

    soup = BeautifulSoup(data, "html.parser")
    table = soup.find("table")

    for row in table.find_all("tr"):
        for td in row.find_all("td"):
            try:
                if match('^[A-Za-z]', td.get_text()):
                    text = td.get_text()
                    json_file[year][text] = None
                elif match('^[0-9]', td.get_text()):
                    json_file[year][text] = td.get_text()
            except Exception as e:
                continue
    return json_file


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-y", "--year", type=int, help="Year for PAX/RTP data")
    args = parser.parse_args()
    year = args.year
    earliest_rtp_year = 1995

    try:
        try:
            if year is None:
                year = datetime.now().year
                url = "http://solotime.info/pax/rtp{}.html".format(year)
            elif earliest_rtp_year <= year:
                url = "http://solotime.info/pax/rtp{}.html".format(year)
            else:
                raise
        except Exception as e:
            raise ValueError

        data = urlopen(url).read()
        json_file = html_parser(data, year)

    except ValueError as e:
        raise ValueError("Value supplied for year is invalid.")
    except Exception as e:
        raise Exception(e)

    print(json.dumps(json_file, indent=2, sort_keys=True))


if __name__ == '__main__':
    main()
