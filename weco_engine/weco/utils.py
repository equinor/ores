#!/usr/bin/python3

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

"""
WeCo utility classes
"""


class MeanAccumulator:
    """
    Compute the mean
    """

    def __init__(self, *v):
        self._nbr = 0
        self._sum = 0.
        if v:
            self.add(*v)

    def mean(self):
        """
        compute the mean of added values
        """
        return 0. if self._nbr == 0 else self._sum / float(self._nbr)

    def add(self, *v):
        """
        add some values
        """
        if not v:
            return
        self._nbr += len(v)
        self._sum += sum(v)


class MinMax:
    """
    Compute the min and max of values
    """
    _min = None
    _max = None

    def __call__(self, value):
        """
        Add value
        """
        if self._min is None:
            self._max = self._min = value
        elif value > self._max:
            self._max = value
        elif value < self._min:
            self._min = value

    def min(self):
        """
        :return: min
        """
        return self._min

    def max(self):
        """
        :return: max
        """
        return self._max

    def range(self):
        """
        :return: min,max
        """
        return self._min, self._max
