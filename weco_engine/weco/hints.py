# Association Scientifique pour la Geologie et ses Applications (ASGA)
#
# Copyright (c) 2024 ASGA. All Rights Reserved.
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

from pathlib import Path
from typing import Dict

hint_path = Path(__file__).resolve().parent
hint_data: Dict[str, Dict[str, str]] = dict()


def read_hint_file(group: str) -> Dict[str, str]:
    """
    read hint file,

    file name: "hints_{group}?.txt"
    format:
        * # ; comments
        * === hint_name : new hint


    :param group: group name
    :return: hints dictionary
    """
    path = hint_path / f'hints_{group}.txt'
    if not path.exists():
        return {}
    result = {}
    name: str = ""
    buf: list[str] = list()

    def end_block():
        if name:
            while len(buf) > 0 and buf[-1] == "":
                del buf[-1]
            if buf:
                result[name] = '\n'.join(buf)
        buf.clear()

    with path.open() as f:
        for line in f:
            if line.startswith("#"):
                continue
            if line.startswith("==="):
                end_block()
                name = line[3:].strip()
                continue
            buf.append(line.rstrip())
    end_block()
    return result


def get_hint(group: str, name: str, default: str = "") -> str:
    """
    get a hint from a hint file (hints_*.txt)

    get_hint("options","order") will get order section in hints_options.txt

    :param group: hint group name (file)
    :param name: hint name (hint name in file)
    :param default: if the hint is not found, return default
    """
    if group not in hint_data:
        hint_data[group] = read_hint_file(group)

    return hint_data[group].get(name, default)


__all__ = ["get_hint"]

if __name__ == '__main__':
    print(repr(get_hint("NONE", "NONE")))
    print(repr(get_hint("options", "NONE")))
    print(repr(get_hint("options", "order")))
