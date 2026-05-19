#!/usr/bin/env python3

# Association Scientifique pour la Geologie et ses Applications (ASGA)
#
# Copyright (c) 2018 ASGA. All Rights Reserved.
#
# This program is a Trade Secret of the ASGA and it is not to be:
#  - reproduced, published, or disclosed to other,
#  - distributed or displayed,
#  - used for purposes or on Sites other than described in the GOCAD
#    Advancement Agreement, without the prior written authorization
#    of the ASGA.
#
# Licencee agrees to attach or embed this Notice on all copies of the program,
# including partial copies or modified versions thereof.

def check(no_gui=False, verbose=False, quiet=False):
    error = False

    def set_result(test, result, text=""):
        nonlocal error
        if not result:
            error = True
        if quiet:
            return
        if verbose and text and not result:
            print(test, ": FAIL (", text, ")")
        elif result:
            print(test, ": OK")
        else:
            print(test, ": FAIL")

    def test_import(module):
        try:
            __import__(module)
        except Exception as err:
            set_result("import " + module, False, repr(err))
        else:
            set_result("import " + module, True)

    test_import('weco.data')
    test_import('weco.ext')
    test_import('weco.las2welllist')
    test_import('weco.lasfile')
    test_import('weco.multiscale')
    test_import('weco.res2csv')
    test_import('weco.res2las')
    test_import('weco.testgen')
    test_import('weco.misc')
    test_import('weco.engine_data')
    test_import('weco.order')
    test_import('weco.resqml')
    test_import('weco.utils')
    test_import('weco.hints')
    test_import('weco.data_import')
    if not no_gui:
        test_import("PyQt6")
        test_import("weco.studio")
        test_import("weco.resview")

    return -1 if error else 0


def main():
    import sys
    import argparse
    parser = argparse.ArgumentParser(description='Check ')
    parser.add_argument("--no-gui", "-g", action="store_true",
                        help="No gui check")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Show error")
    parser.add_argument("--quiet", "-q", action="store_true",
                        help="No Output")

    args = parser.parse_args()

    sys.exit(check(**vars(args)))


if __name__ == '__main__':
    main()
