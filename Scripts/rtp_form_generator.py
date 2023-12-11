#!/usr/bin/env python3

import argparse
import json
import json2table
from datetime import datetime
from bs4 import BeautifulSoup


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-y", "--year", type=int, help="Year for PAX/RTP data")
    args = parser.parse_args()
    year = args.year

    build_direction = "LEFT_TO_RIGHT"
    table_attributes = {}

    if year is None:
        year = datetime.now().year

    with open("./rtp.json", "r") as json_file:
        pax_rtp_data = json.load(json_file)
        print(pax_rtp_data)
        #print(pax_rtp_data[str(year)]["STS"])

        # for each class, get current year's rtp and category
        # filter out classes without 2021 rtp
        # group together in the table

        table = json2table.convert(groupsdict,
                                   build_direction=build_direction,
                                   table_attributes=table_attributes)

        # print(BeautifulSoup(table, "html.parser").prettify())
        print(table)


if __name__ == '__main__':
    main()
