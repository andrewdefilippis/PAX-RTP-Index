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

    with open("./JSON/{}.json".format(year), "r") as json_file:
        pax_rtp_data = json.load(json_file)
        print(pax_rtp_data)
        print(pax_rtp_data[str(year)]["STS"])

        group1 = ["STS", "STX", "STR", "STU", "STH"]
        group2 = ["XS-A", "XS-B", "EV"]
        group1dict = {}
        group2dict = {}
        groups = []
        groupsdict = {}
        for group in group1:
            group1dict[group] = pax_rtp_data[str(year)][group]
        for group in group2:
            group2dict[group] = pax_rtp_data[str(year)][group]
        groups.append(group1dict)
        groups.append(group2dict)
        groupsdict['group'] = groups
        print(groups)

        table = json2table.convert(groupsdict,
                                   build_direction=build_direction,
                                   table_attributes=table_attributes)

        # print(BeautifulSoup(table, "html.parser").prettify())
        print(table)


if __name__ == '__main__':
    main()

# Categories:
# Street ([A-Z]S|HCS) - Heritage Classic
# Street Touring (ST[A-Z])
# Street Prepared ([A-Z]SP)
# Street Modified ([A-Z]?SM[A-Z]?)
# Prepared ([A-Z]P|HCR) - Heritage Classic
# Modified ([A-Z]M)
# FSAE (FSAE)
# Classic American Muscle (CAM-[A-Z])
# Solo Spec Coupe (SSC)
# Street-R (SSR) - Part of Street Prepared but separate
# Kart Modified (KM|J[A-Z]) - Formula Junior
# Xtreme Street (XS-[A-Z]|EV)
