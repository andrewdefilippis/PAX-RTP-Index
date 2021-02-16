#!/usr/bin/env python3

import argparse
import json
from datetime import datetime
from re import match

import yaml
from jsonmerge import Merger


class CONST(object):
    __slots__ = ()
    # Solo Class Categories:
    STREET = {"Street": "^[A-Z]S$"}
    STREET_TOURING = {"Street Touring": "^ST[A-Z]$"}
    STREET_PREPARED = {"Street Prepared": "^[A-Z]SP$"}
    STREET_MODIFIED = {"Street Modified": "^[A-Z]?SM[A-Z]?$"}
    STREET_R = {"Street-R": "^SSR$"}
    XTREME_STREET = {"Xtreme Street": "^XS-[A-Z]$"}
    PREPARED = {"Prepared": "^[A-Z]P$"}
    MODIFIED = {"Modified": "^[A-Z]M$"}
    CLASSIC_AMERICAN_MUSCLE = {"Classic American Muscle": "^CAM-[A-Z]$"}
    SOLO_SPEC_COUPE = {"Solo Spec Coupe": "^SSC$"}
    FSAE = {"Formula SAE": "^FSAE$"}
    FORMULA_JUNIOR = {"Formula Junior": "^J[A-Z]$"}
    HERITAGE_CLASSIC = {"Heritage Classic": "^HC[A-Z]$"}
    ELECTRIC_VEHICLE = {"Electric Vehicle": "^EV$"}


C = CONST()


def solo_class_categories():
    return [C.STREET,
            C.STREET_TOURING,
            C.STREET_PREPARED,
            C.STREET_MODIFIED,
            C.STREET_R,
            C.XTREME_STREET,
            C.PREPARED,
            C.MODIFIED,
            C.CLASSIC_AMERICAN_MUSCLE,
            C.SOLO_SPEC_COUPE,
            C.FSAE,
            C.FORMULA_JUNIOR,
            C.HERITAGE_CLASSIC,
            C.ELECTRIC_VEHICLE]


def what_category_is_this(solo_class):
    # Return "category name"
    for solo_category in solo_class_categories():
        for name, regex in solo_category.items():
            if match(regex, solo_class):
                return name
    return str()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-y", "--year", type=int, help="Year for PAX/RTP data")
    args = parser.parse_args()
    year = args.year

    if year is None:
        year = datetime.now().year

    # load non-categorized json file
    with open("./JSON/{}.json".format(year), "r") as json_file:
        pax_rtp_data = json.load(json_file)
        print(pax_rtp_data)
        classes_dict = {"SoloClasses": {}}

        # Match each class in the json against each class category
        for solo_class in pax_rtp_data[str(year)]:
            solo_category = what_category_is_this(solo_class)

            # dump class into multi-dimensional dict
            classes_dict["SoloClasses"][solo_class] = {"RTP": [{year: pax_rtp_data[str(year)][solo_class]}],
                                                       "SoloCategory": solo_category}

    # dump dict to categorized json file
    formatted_json = json.dumps(classes_dict, indent=2, sort_keys=True)
    try:
        with open("./rtp.json", "r") as json_file:
            merge_schema = {
                "properties": {
                    "SoloClasses": {
                        "mergeStrategy": "objectMerge",
                        "patternProperties": {
                            "^.*$": {
                                "mergeStrategy": "objectMerge",
                                "patternProperties": {
                                    "^.*$": {
                                        "mergeStrategy": "append"
                                    },
                                    "^SoloCategory$": {
                                        "mergeStrategy": "overwrite"
                                    }
                                }
                            }
                        }
                    }
                }
            }
            merger = Merger(merge_schema)
            merged_file = merger.merge(json.load(json_file), classes_dict)
    except FileNotFoundError as e:
        with open("./rtp.json", "w") as json_file:
            pass
    except json.decoder.JSONDecodeError as e:
        pass
    with open("./rtp.json", "w") as json_file:
        try:
            json_output = json.dumps(merged_file, indent=2, sort_keys=True)
            json_file.write(json_output)
        except UnboundLocalError as e:
            json_file.write(formatted_json)
    with open("./rtp.yaml", "w") as yaml_file:
        try:
            yaml_file.write("---\n")
            yaml_file.write(yaml.dump(json.loads(json_output)))
        except UnboundLocalError as e:
            yaml_file.write(yaml.dump(json.loads(formatted_json)))

    print(formatted_json)
    print("\n---\n" + yaml.dump(json.loads(formatted_json)))


if __name__ == '__main__':
    main()
