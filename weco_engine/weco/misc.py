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

from itertools import product


def number_of_correlations(*sizes):
    """
    compute the number of possible correlations

    :param sizes: wells size

    Warning: Brut force, can use a lot of time and memory

    example:
        number_of_correlations(10,13,20)
    """
    sizes = tuple(reversed(sorted(sizes)))
    if len(sizes) < 2:
        return 0
    if sizes[-1] <= 0:
        return 0
    if sizes[1] == 1:
        return 1
    sizes = list(filter(lambda x: x > 1, sizes))
    nbr_dim = len(sizes)
    nbr_cor = 0
    delta_idx = tuple(product((0, -1), repeat=nbr_dim))[1:]

    sizes_product = tuple(tuple(range(1, n + 1)) for n in sizes)

    buffer: dict = dict()

    def get_buffer(_idx):
        _idx = tuple(sorted(_idx))
        if _idx[0] == 0:
            return 0
        if _idx[-2] == 1:
            return 1
        return buffer[_idx]

    for idx in product(*sizes_product):
        idx = tuple(sorted(idx))
        if idx[-2] == 1 or idx in buffer:
            continue
        nbr_cor = sum(
            get_buffer(list(
                a + b for a, b in zip(idx, i_delta_idx)
            ))
            for i_delta_idx in delta_idx
        )
        buffer[idx] = nbr_cor
    return nbr_cor


def print_number_of_correlations(*sizes):
    """
    print the number of possible correlations

    :param sizes: wells size
    """
    res = number_of_correlations(*sizes)
    print(list(sizes), ':', res)
    if res > 1000000:
        str_res = str(res)
        print(f'{str_res[0]}.{str_res[1:3]}e{len(str_res) - 1}')


def memory_limit(limit: float) -> bool:
    """
    Set memory limit (Linux only)

    Uses resource.prlimit

    :param limit: Memory limit in Go (2³30 bytes)
    :return: False if function fails
    """
    try:
        from resource import prlimit, RLIMIT_AS
        _, hard = prlimit(0, RLIMIT_AS)
        prlimit(0, RLIMIT_AS, (int(limit * (1 << 30)), hard))
    except Exception as err:
        print("*ERR* Memory Limit Fail:", err)
        return False
    return True


if __name__ == '__main__':
    print_number_of_correlations(20, 20, 20, 20, 20)
    # print_number_of_correlations(300, 333, 230)
