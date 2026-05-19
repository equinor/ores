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

from .data import WellList
from typing import Sequence, Tuple, List, Optional

Coords = Sequence[Tuple[float, float]]


def _dist2(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    xd = a[0] - b[0]
    yd = a[1] - b[1]
    return xd * xd + yd * yd


def compute_nearest_ordering(coords: Coords, first: int = 0) -> List[int]:
    """
    order the items from the seed(first)
    at each steep add the nearest item from all already added items

    :param coords: x,y coordinates
    :param first: first item
    :return: sorted items
    """

    def calc_dist(i1, i2):
        x1, y1 = coords[i1]
        x2, y2 = coords[i2]
        d1 = x1 - x2
        d2 = y1 - y2
        return d1 * d1 + d2 * d2

    assert 0 <= first < len(coords)
    result = [first]

    todo = list(
        (calc_dist(first, num), num)
        for num in range(len(coords))
        if num != first
    )
    while todo:
        todo.sort()
        new_item = todo[0][1]
        result.append(new_item)
        new_todo = list(
            (min(dist, calc_dist(new_item, num)), num)
            for dist, num in todo[1:]
        )
        todo = new_todo
    return result


def test_compute_nearest_ordering():
    data = ((1., 0.), (3., 0.), (0., 1.), (1., 1.), (0., 4.))
    nearest = compute_nearest_ordering(data)
    print(nearest)
    data2 = list(data[i] for i in nearest)
    print(compute_triangle(data2))


def nearest_reorder(wells: WellList, first=0):
    coords = tuple((well.x, well.y) for well in wells.wells)
    order = compute_nearest_ordering(coords, first=first)
    wells.wells = list(wells.wells[i] for i in order)


def compute_triangle(coords: Coords) -> tuple:
    def calc_dist(i1, i2):
        return _dist2(coords[i1], coords[i2])

    def get_triangle(n: int):
        if n < 2:
            return ()
        if n == 2:
            return 0, 1
        dist = list((calc_dist(n, i), i) for i in range(n))
        dist.sort()
        return dist[0][1], dist[1][1]

    return tuple(map(get_triangle, range(len(coords))))


def triangle_data(wells: WellList, data_name: str):
    coords = tuple((well.x, well.y) for well in wells.wells)
    data = compute_triangle(coords)
    for well, data in zip(wells.wells, data):
        well.add_data(data_name, data)


def triangle_test(coords: Sequence[Tuple[float, float]],
                  first: int = 0,
                  names: Optional[Sequence[str]] = None,
                  limit: int = 0):
    if not limit:
        limit = len(coords)
    if not names:
        names = list(chr(65 + i) for i in range(len(coords)))
    print(coords)
    print(names)
    ordering = compute_nearest_ordering(coords, first=first)
    coords = list(coords[i] for i in ordering)
    names = list(names[i] for i in ordering)
    print(names, coords)
    triangles = compute_triangle(coords)
    for name, tri in list(zip(names, triangles))[2:]:
        print("  ", name, names[tri[0]], names[tri[1]])

    import matplotlib.pyplot as plt
    x = list(i[0] for i in coords)
    y = list(i[1] for i in coords)
    plt.scatter(x, y)
    for n, name in enumerate(names):
        plt.annotate(f"{name}[{n + 1}]", coords[n])

    for n in range(2, limit):
        a, b = triangles[n]
        plt.plot(
            (x[n], x[a], x[b], x[n]),
            (y[n], y[a], y[b], y[n]),
        )
    plt.show()


def compute_delaunay(coords: Coords, first: int = 0) -> Tuple[List[int], List[tuple]]:
    """
    Computes the triangulation from a list of points and defines an ordering from this triangulation.
    The ordering iterates through the Delaunay triangulation from the 'first' point to iteratively
    add connected triangles by increasing distance with the current front.

    :param coords: The input points
    :param first: Index of the first point in the ordering.
    :return: The list of points ordered by increasing "Delaunay distance", and For each ordered point,
        the two points forming the triangle(s) added with this point
    """
    from scipy.spatial import Delaunay

    def tri_dist(tricoord):
        """
        Computes the distance between a triangle and some input point (coords[first])

        :param tricoord: two triplets of triangle vertices
        :return: the distance
        """
        xd = coords[first][0] - sum(coords[i][0] for i in tricoord) / 3.
        yd = coords[first][1] - sum(coords[i][1] for i in tricoord) / 3.
        return xd * xd + yd * yd

    def get_new():
        """
        Finds a triangle which has a common edge and find its additional vertex
        :return:
        """
        for _tri in triangles:
            # noinspection PyShadowingNames
            a, b, c = _tri[1]
            if a in order and b in order:
                return c
            if c in order and b in order:
                return a
            if a in order and c in order:
                return b
        raise Exception("Bad triangles")

    # Sort triangles by increasing distances to 'first'
    # noinspection PyTypeChecker
    triangles = Delaunay(coords).simplices
    triangles = list((tri_dist(i), tuple(i)) for i in triangles)
    triangles.sort()

    ta, tb = set(triangles[0][1]) - {first}
    if _dist2(coords[tb], coords[first]) < _dist2(coords[ta], coords[first]):
        ta, tb = tb, ta
    order = [first, ta, tb]  # first triangle with vertices ordered by proximity to first vertex.
    tri_prop = [(), (), (order.index(first), order.index(ta))]  # = [(), '), (0,1)]
    del triangles[0]
    while triangles:
        new_point = get_new()
        order.append(new_point)
        new_tri_prop = ()
        new_triangles = list()
        for tri in triangles:
            a, b, c = tri[1]
            if a in order and b in order and c in order:
                new_tri_prop += tuple(
                    map(order.index, (set(tri[1]) - {new_point})))
            else:
                new_triangles.append(tri)
        triangles = new_triangles
        tri_prop.append(new_tri_prop)
    return order, tri_prop


def triangle_test2(coords: Sequence[Tuple[float, float]],
                   first: int = 0,
                   names: Optional[Sequence[str]] = None,
                   limit: int = 0):
    """
    Computes the Delaunay ordering and outputs the result

    :param coords: The list of coordinates
    :param first: The starting point
    :param names: the names of the points (optional)
    :param limit: Allows to compute only on the N first points (ignored if 0)
    """
    if not limit:
        limit = len(coords)
    if not names:
        names = list(chr(65 + i) for i in range(len(coords)))

    ordering, tri_prop = compute_delaunay(coords, first)
    coords = list(coords[i] for i in ordering)
    names = list(names[i] for i in ordering)

    for n in range(len(coords)):
        print('*', names[n], coords[n], ' '.join(
            f'[{names[tri_prop[n][i]]}, {names[tri_prop[n][i + 1]]}]'
            for i in range(0, len(tri_prop[n]), 2)
        ))

    import matplotlib.pyplot as plt
    x = list(i[0] for i in coords)
    y = list(i[1] for i in coords)
    #
    plt.scatter(x, y)
    for n, name in enumerate(names):
        plt.annotate(f"{name}[{n + 1}]", coords[n])

    tri = list()
    for n, tp in enumerate(tri_prop[:limit]):

        for j in range(0, len(tp), 2):
            tri.append((n, tp[j], tp[j + 1]))

    plt.triplot(x, y, tri)
    plt.show()


def delaunay_reorder(wells: WellList, first=0, data_name=None):
    coords = tuple((well.x, well.y) for well in wells.wells)
    order, tri_data = compute_delaunay(coords, first=first)
    wells.wells = list(wells.wells[i] for i in order)
    if data_name:
        for well, data in zip(wells.wells, tri_data):
            well.add_data(data_name, data)


def main():
    from argparse import ArgumentParser

    parser = ArgumentParser()
    sub_parser = parser.add_subparsers(
        title="ordering function", metavar="FUNC", required=True)

    # ============= nearest ==================
    def do_nearest():
        nearest_reorder(wells, first=args.first)
        if args.triangle:
            triangle_data(wells, args.triangle)

    sub_cmd = sub_parser.add_parser('nearest', help='nearest point ordering')
    sub_cmd.set_defaults(func=do_nearest)
    sub_cmd.add_argument('--first', '-f', type=int,
                         help='first well (default=0)', default=0)
    sub_cmd.add_argument('--triangle', '-t',
                         help='triangle data name')

    # ============= triangles ==================
    def do_triangles():
        delaunay_reorder(wells, first=args.first, data_name=args.triangle)

    sub_cmd = sub_parser.add_parser('triangles', help='Delaunay')
    sub_cmd.set_defaults(func=do_triangles)
    sub_cmd.add_argument('--first', '-f', type=int,
                         help='first well (default=0)', default=0)
    sub_cmd.add_argument('--triangle', '-t',
                         help='triangles data name')

    # ============= triangle_test ==================
    def do_triangle_test():
        triangle_test(list((i.x, i.y) for i in wells.wells),
                      names=list(i.name for i in wells.wells),
                      first=args.first, limit=args.limit)

    sub_cmd = sub_parser.add_parser('triangle_test',
                                    help='Computes the ordering by increasing distance and triangulates')
    sub_cmd.set_defaults(func=do_triangle_test)
    sub_cmd.add_argument('--first', '-f', type=int,
                         help='first well (default=0)', default=0)
    sub_cmd.add_argument('--limit', '-l', type=int,
                         help='number of points to draw', default=0)

    # ============= triangle_test ==================
    def do_triangle_test2():
        triangle_test2(list((i.x, i.y) for i in wells.wells),
                       names=list(i.name for i in wells.wells),
                       first=args.first, limit=args.limit)

    sub_cmd = sub_parser.add_parser('triangle_test2', help='Delaunay Ordering (recommended to avoid crossings)')
    sub_cmd.set_defaults(func=do_triangle_test2)
    sub_cmd.add_argument('--first', '-f', type=int,
                         help='first well (default=0)', default=0)
    sub_cmd.add_argument('--limit', '-l', type=int,
                         help='number of points to draw', default=0)

    parser.add_argument("input", help="input wells file")
    parser.add_argument("--output", "-o", help="output wells file")

    args = parser.parse_args()

    try:
        wells = WellList(args.input)
    except Exception as err:
        print(f"Can't load wells file {args.input} : {err}")
        return

    args.func()

    if args.output:
        wells.write(args.output)


if __name__ == '__main__':
    # test_compute_nearest_ordering()
    main()
