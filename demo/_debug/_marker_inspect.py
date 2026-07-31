import zipfile, re, h5py
z = zipfile.ZipFile("drogon.epc"); h5 = h5py.File("drogon.h5","r")
names=[n for n in z.namelist() if n.endswith('.xml') and not n.startswith('_rels') and n!='[Content_Types].xml']
def by_uuid(u):
    f=next((n for n in names if u in n),None); return z.read(f).decode() if f else None
def tag1(x,t):
    m=re.search(r'<[^>]*\b'+t+r'>(.*?)</[^>]*\b'+t+r'>',x,re.S); return m.group(1).strip() if m else None
frames=sorted(n for n in names if 'WellboreMarkerFrameRepresentation' in n)
seen={}
for n in frames:
    xml=z.read(n).decode()
    fu=re.search(r'uuid="([0-9a-f-]+)"',xml).group(1)
    w=re.search(r'RepresentedInterpretation>.*?<eml:Title>(.*?)<',xml,re.S); w=w.group(1) if w else '?'
    tr=re.search(r'<resqml2?:Trajectory>.*?<eml:UUID>([0-9a-f-]+)',xml,re.S); tu=tr.group(1) if tr else None
    mdp=re.search(r'PathInHdfFile>(.*?)<',xml).group(1); md=h5[mdp][()]
    ms=re.findall(r'<resqml2?:WellboreMarker .*?</resqml2?:WellboreMarker>',xml,re.S)
    print(f"\n=== {w}  frame={fu}  traj={tu}  nodes={len(md)}")
    for i,m in enumerate(ms):
        t=tag1(m,'Title'); k=tag1(m,'GeologicBoundaryKind')
        hi=re.search(r'Interpretation>.*?<eml:UUID>([0-9a-f-]+)',m,re.S)
        print(f"   [{i}] md={md[i]:>10.3f}  {(t or '?'):14s} {(k or '?'):9s} interp={hi.group(1) if hi else '-'}")
    if tu and tu not in seen:
        tx=by_uuid(tu)
        if tx:
            mdd=re.search(r'MdDatum>.*?<eml:UUID>([0-9a-f-]+)',tx,re.S); du=mdd.group(1) if mdd else None
            print(f"   TRAJ {tu}: StartMd={tag1(tx,'StartMd')} FinishMd={tag1(tx,'FinishMd')} MdDatum={du}")
            if du:
                dx=by_uuid(du)
                if dx:
                    print(f"        MdDatum MdReference={tag1(dx,'MdReference')} coords={re.findall(r'Coordinate(.)>(.*?)<',dx)}")
            seen[tu]=True
