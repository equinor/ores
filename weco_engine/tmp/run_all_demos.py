"""Run all WeCo demos headless — proper plots with correlations, regions, logs."""
import os, sys, signal, traceback, re
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
from matplotlib.lines import Line2D
import numpy as np

sys.path.insert(0, '/home/maap/weco')

from weco.workflow import CorrelationWorkflow
from weco.data import WellList, Well

# Extract DEMOS from studio.py without importing Qt
_studio_src = open('/home/maap/weco/weco/studio.py').read()
_match = re.search(r'^DEMOS\s*=\s*\[', _studio_src, re.MULTILINE)
if _match:
    # Find the opening bracket
    _bracket_pos = _studio_src.index('[', _match.start())
    _depth = 0
    _end = _bracket_pos
    for _i in range(_bracket_pos, len(_studio_src)):
        _ch = _studio_src[_i]
        if _ch == '[': _depth += 1
        elif _ch == ']': _depth -= 1
        if _depth == 0:
            _end = _i + 1
            break
    _block = "DEMOS = " + _studio_src[_bracket_pos:_end]
    _ns = {}
    exec(compile(_block, '<demos>', 'exec'), _ns)
    DEMOS = _ns['DEMOS']
else:
    DEMOS = []

OUT_DIR = '/home/maap/weco/tmp/demo_plots'
os.makedirs(OUT_DIR, exist_ok=True)
TIMEOUT_SEC = 300

# Colour palette for facies/regions
REGION_COLORS = [
    '#ffffff', '#f4d03f', '#e67e22', '#2ecc71', '#1abc9c',
    '#3498db', '#9b59b6', '#e74c3c', '#95a5a6', '#34495e',
    '#f39c12', '#27ae60', '#2980b9', '#8e44ad', '#c0392b',
    '#16a085', '#d35400', '#7f8c8d', '#2c3e50', '#1a5276',
]
WELL_COLORS = [
    '#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd',
    '#8c564b', '#e377c2', '#7f7f7f', '#bcbd22', '#17becf',
    '#aec7e8', '#ffbb78', '#98df8a', '#ff9896', '#c5b0d5',
]


def get_depth(well):
    for dn in ("Depth", "DEPTH", "MD", "TVD"):
        if dn in well.data and well.data[dn]:
            return np.array(well.data[dn], dtype=float)
    return np.arange(well.size, dtype=float)


def plot_demo(wf, demo, out_path):
    """Full correlation plot: continuous logs + region strips + correlation lines."""
    wl = wf.well_list
    rf = wf.res_file
    opts = demo.get('opts', {})
    n_wells = wl.nbr_wells()
    n_res = rf.get_nbr_results() if rf else 0

    # Determine what to show
    var_data = opts.get('var_data', '')
    var_data2 = opts.get('var_data2', '')
    var_data3 = opts.get('var_data3', '')
    same_region = opts.get('same_region', '')
    no_crossing = opts.get('no_crossing', '')

    # Collect log names and region names
    data_names = set()
    region_names = set()
    for i in range(n_wells):
        w = wl.get_well(i)
        data_names.update(w.data.keys())
        region_names.update(w.region.keys())
    data_names -= {'Depth', 'DEPTH', 'MD', 'X', 'Y', 'Z',
                   '_marker_names', '_marker_ids'}
    data_names = {n for n in data_names if not n.startswith('_')}

    # Choose logs to plot (prioritize var_data options)
    show_logs = []
    for dn in [var_data, var_data2, var_data3]:
        if dn and dn in data_names:
            show_logs.append(dn)
    if not show_logs:
        for prio in ['GR', 'RT', 'DEN', 'SPT', 'SON', 'COND', 'MS', 'WC']:
            if prio in data_names:
                show_logs.append(prio)
                break

    # Choose regions to show
    show_regions = []
    for rn in [same_region, no_crossing]:
        if rn and rn in region_names:
            show_regions.append(rn)
    if not show_regions:
        for rn in sorted(region_names):
            if rn not in show_regions:
                show_regions.append(rn)
            if len(show_regions) >= 2:
                break

    n_log_tracks = max(1, len(show_logs))
    n_reg_tracks = len(show_regions)

    # Figure sizing
    well_width = 0.8 + n_reg_tracks * 0.25 + n_log_tracks * 0.6
    gap_width = 0.4
    fig_w = max(12, n_wells * well_width + (n_wells - 1) * gap_width + 2)
    fig_h = 8
    fig = plt.figure(figsize=(fig_w, fig_h))

    # GridSpec layout
    cols_per_well = n_reg_tracks + n_log_tracks
    total_cols = n_wells * cols_per_well + (n_wells - 1)  # gaps
    ratios = []
    for wi in range(n_wells):
        for _ in range(n_reg_tracks):
            ratios.append(0.25)
        for _ in range(n_log_tracks):
            ratios.append(1.0)
        if wi < n_wells - 1:
            ratios.append(0.6)  # gap

    gs = fig.add_gridspec(1, total_cols, width_ratios=ratios, wspace=0.02,
                          left=0.03, right=0.97, top=0.86, bottom=0.06)

    # Well order from result
    if rf and n_res > 0:
        order = list(rf.well_id)
    else:
        order = list(range(n_wells))

    # Global depth range
    well_depths = {}
    for idx in order:
        well_depths[idx] = get_depth(wl.get_well(idx))
    all_d = np.concatenate(list(well_depths.values()))
    d_min, d_max = float(np.min(all_d)), float(np.max(all_d))
    d_pad = max(1, (d_max - d_min) * 0.02)
    y_lim = (d_max + d_pad, d_min - d_pad)

    col = 0
    first_ax = None
    well_log_axes = []  # first log axis per well (for correlation lines)

    for wi_disp, wi_data in enumerate(order):
        w = wl.get_well(wi_data)
        depth = well_depths[wi_data]
        wcolor = WELL_COLORS[wi_disp % len(WELL_COLORS)]

        # Region strips
        for ri, rname in enumerate(show_regions):
            ax = fig.add_subplot(gs[0, col], sharey=first_ax if first_ax else None)
            col += 1
            ax.set_xlim(0, 1)
            ax.set_ylim(y_lim)
            ax.set_xticks([])
            if first_ax is None:
                first_ax = ax
                ax.set_ylabel("Depth", fontsize=9)
            else:
                ax.tick_params(left=False, labelleft=False)

            # Draw coloured intervals
            if rname in w.region:
                for rid, start, length in w.region[rname]:
                    if start < len(depth) and start + length <= len(depth):
                        d_top = depth[start]
                        d_bot = depth[min(start + length - 1, len(depth) - 1)]
                        c = REGION_COLORS[rid % len(REGION_COLORS)]
                        ax.axhspan(d_top, d_bot, color=c, alpha=0.7)

            # Region header
            if wi_disp == 0:
                ax.set_title(rname, fontsize=7, rotation=45, ha='left', pad=2)

        # Log tracks
        log_axes = []
        for li, lname in enumerate(show_logs):
            share = first_ax if first_ax else None
            ax = fig.add_subplot(gs[0, col], sharey=share)
            col += 1
            if first_ax is None:
                first_ax = ax
            ax.set_ylim(y_lim)
            ax.tick_params(left=False, labelleft=False, bottom=False, labelbottom=False)

            if lname in w.data:
                vals = np.array(w.data[lname], dtype=float)[:len(depth)]
                valid = ~np.isnan(vals)
                if valid.any():
                    ax.plot(vals[valid], depth[valid], color=wcolor, lw=0.8)
                    # Fill
                    vmin, vmax = np.nanmin(vals), np.nanmax(vals)
                    if vmax > vmin:
                        ax.fill_betweenx(depth[valid], vmin, vals[valid],
                                         alpha=0.15, color=wcolor)
                        ax.set_xlim(vmin - (vmax-vmin)*0.05, vmax + (vmax-vmin)*0.05)

            log_axes.append(ax)

        # Well name
        if log_axes:
            mid = log_axes[len(log_axes)//2]
            mid.set_title(w.name, fontsize=8, fontweight='bold', color=wcolor, pad=6)
            well_log_axes.append(mid)

        # Gap
        if wi_disp < n_wells - 1:
            ax_gap = fig.add_subplot(gs[0, col], sharey=first_ax)
            col += 1
            ax_gap.set_axis_off()

    # === Draw correlation lines ===
    if rf and n_res > 0 and len(well_log_axes) == n_wells:
        path = rf.get_result_full_path(0)  # best result
        # path is tuple of tuples: path[marker_idx][well_idx] = sample_index
        n_markers = len(path)

        # Subsample markers if too many (avoid visual clutter)
        marker_step = max(1, n_markers // 60)
        draw_markers = list(range(0, n_markers, marker_step))

        for mi in draw_markers:
            row = path[mi]  # tuple of sample indices per well (in well_id order)

            # Map well_id order to display order
            pts = []
            for wi_disp, wi_data in enumerate(order):
                # Find position in rf.well_id
                try:
                    rf_pos = list(rf.well_id).index(wi_data)
                except ValueError:
                    pts.append(None)
                    continue
                sample_idx = row[rf_pos]
                d = well_depths[wi_data]
                if 0 <= sample_idx < len(d):
                    pts.append((wi_disp, float(d[sample_idx])))
                else:
                    pts.append(None)

            # Draw line segments between consecutive valid points
            for i in range(len(pts) - 1):
                if pts[i] is not None and pts[i+1] is not None:
                        ax1 = well_log_axes[pts[i][0]]
                        ax2 = well_log_axes[pts[i+1][0]]
                        coord1 = ax1.transData.transform(
                            (ax1.get_xlim()[1], pts[i][1]))
                        coord2 = ax2.transData.transform(
                            (ax2.get_xlim()[0], pts[i+1][1]))
                        inv = fig.transFigure.inverted()
                        p1 = inv.transform(coord1)
                        p2 = inv.transform(coord2)
                        line = Line2D([p1[0], p2[0]], [p1[1], p2[1]],
                                      transform=fig.transFigure,
                                      color='#333333', alpha=0.4, lw=0.5,
                                      zorder=0)
                        fig.lines.append(line)

    # === Legend ===
    legend_items = []
    for rname in show_regions:
        ids_seen = set()
        code_table = {}
        for i in range(n_wells):
            w = wl.get_well(i)
            if rname in w.region:
                for rid, _, _ in w.region[rname]:
                    ids_seen.add(rid)
            ct = w.data.get(f'_code_table_{rname}', {})
            if ct and not code_table:
                code_table = ct

        for rid in sorted(ids_seen):
            label = code_table.get(rid, code_table.get(str(rid), f"{rname}={rid}"))
            c = REGION_COLORS[rid % len(REGION_COLORS)]
            legend_items.append(
                Rectangle((0,0), 1, 1, fc=c, alpha=0.7, label=str(label)))

    if legend_items:
        fig.legend(handles=legend_items, loc='lower right', fontsize=7,
                   ncol=min(6, len(legend_items)), framealpha=0.9)

    # === Title ===
    cost_str = ""
    if rf and n_res > 0:
        cost_str = f"  |  Best cost: {rf.get_result_cost(0):.4f}"
    fig.suptitle(
        f"{demo['title']}  [{demo['id']}]\n"
        f"{n_wells} wells | {n_res} correlations{cost_str}\n"
        f"logs: {', '.join(show_logs)}  |  regions: {', '.join(show_regions)}",
        fontsize=10, fontweight='bold', y=0.99
    )

    # Options info box
    txt_parts = []
    for k in ['cost_function', 'order', 'same_region', 'no_crossing',
              'var_data', 'var_data2', 'var_data3', 'var_weight', 'var_weight2']:
        if k in opts:
            txt_parts.append(f"{k}: {opts[k]}")
    if txt_parts:
        fig.text(0.01, 0.01, '\n'.join(txt_parts), fontsize=7, va='bottom',
                 family='monospace', bbox=dict(boxstyle='round', fc='wheat', alpha=0.6))

    fig.savefig(out_path, dpi=120, bbox_inches='tight')
    plt.close(fig)


# === Main ===
class DemoTimeout(Exception):
    pass

def _alarm(signum, frame):
    raise DemoTimeout()

results = []
print(f"Running {len(DEMOS)} demos -> {OUT_DIR}/\n")

for demo in DEMOS:
    demo_id = demo['id']
    title = demo['title']
    wells_path = os.path.join('/home/maap/weco/data', demo['wells'])
    opts = demo.get('opts', {})

    print(f"  [{demo_id:20s}] {title:35s}", end=" ", flush=True)

    if not os.path.exists(wells_path):
        print("FILE NOT FOUND")
        results.append((demo_id, "NOT_FOUND", 0))
        continue

    signal.signal(signal.SIGALRM, _alarm)
    signal.alarm(TIMEOUT_SEC)

    try:
        wf = CorrelationWorkflow()
        wf.import_wells(wells_path)
        for key, val in opts.items():
            wf.options[key.replace('_', '-')] = str(val)
        wf.run()

        n_wells = wf.well_list.nbr_wells()
        n_res = wf.res_file.get_nbr_results() if wf.res_file else 0
        signal.alarm(0)

        safe_id = demo_id.replace('/', '_').replace(' ', '_')
        png_path = os.path.join(OUT_DIR, f"{safe_id}.png")
        plot_demo(wf, demo, png_path)

        print(f"OK {n_wells:2d} wells, {n_res:3d} cor -> {safe_id}.png")
        results.append((demo_id, "OK", n_res))

    except DemoTimeout:
        signal.alarm(0)
        print("TIMEOUT")
        results.append((demo_id, "TIMEOUT", 0))
    except Exception as e:
        signal.alarm(0)
        print(f"ERROR: {e}")
        traceback.print_exc()
        results.append((demo_id, "ERROR", 0))

# Summary
print(f"\n{'='*60}")
print(f"RESULTS: {sum(1 for _,s,_ in results if s=='OK')}/{len(results)} OK, "
      f"{sum(1 for _,_,n in results if n>0)} with correlations")
print(f"{'='*60}")
for did, status, n_cor in results:
    icon = 'OK' if n_cor > 0 else ('TO' if status == 'TIMEOUT' else '!!')
    print(f"  [{icon:2s}] {did:20s} {status:8s} cor={n_cor}")
print(f"\nPNGs in: {OUT_DIR}/")
