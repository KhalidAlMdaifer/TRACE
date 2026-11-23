"""Reference only: how the mockups' dot-matrix map rows were generated.

Each row of dots is drawn as one horizontal SVG line whose stroke-width equals the dot size
and whose stroke-dasharray is "size gap", so a row is a single path segment. This script
finds, for each row, the runs of dots that fall inside the emirate polygons and prints the
path data.

The polygons below are rough hand-drawn placeholders in the mockups' 1000 x 760 drawing
space. They are NOT real boundaries. In the app, draw dots on a canvas from the region
pack's real polygons (docs/04-data.md, docs/08-design.md).

    python design/dot_map_prototype.py
"""
P = {
 'AD': [(33,390),(64,430),(218,402),(373,420),(455,410),(541,346),(592,296),(637,266),(701,310),(755,320),(792,316),(806,306),(801,370),(801,440),(755,520),(728,620),(692,700),(655,714),(215,652)],
 'DXB': [(637,266),(659,244),(710,186),(721,178),(746,200),(768,230),(783,264),(797,296),(806,306),(792,316),(755,320),(701,310)],
 'HAT': [(828,262),(846,270),(837,290),(806,306)],
 'SHJ': [(721,178),(732,162),(745,166),(764,158),(801,160),(828,180),(837,220),(828,262),(806,306),(797,296),(783,264),(768,230),(746,200)],
 'AJM': [(732,162),(741,154),(752,157),(745,166)],
 'UAQ': [(741,154),(750,140),(786,114),(810,140),(801,160),(764,158),(752,157)],
 'RAK': [(786,114),(826,82),(850,26),(865,50),(870,110),(855,140),(837,164),(828,180),(801,160),(810,140)],
 'FUJ': [(870,110),(886,116),(903,172),(903,216),(905,246),(874,256),(846,270),(828,262),(837,220),(828,180),(837,164),(855,140)],
}
def inside(pt, poly):
    x,y = pt; c = False; n = len(poly)
    for i in range(n):
        x1,y1 = poly[i]; x2,y2 = poly[(i+1)%n]
        if (y1>y) != (y2>y):
            xi = x1 + (y-y1)*(x2-x1)/(y2-y1)
            if x < xi: c = not c
    return c
def which(pt):
    for k,poly in P.items():
        if inside(pt, poly): return k
    return None
def fmt(v):
    s = ('%.1f' % v).rstrip('0').rstrip('.')
    return s
def runs(dots, pitch, size):
    # dots: list of (xleft, ycenter) ; group consecutive in a row
    out = []
    rows = {}
    for x,y in dots: rows.setdefault(y, []).append(x)
    for y in sorted(rows):
        xs = sorted(rows[y]); start = xs[0]; prev = xs[0]
        for x in xs[1:]:
            if abs(x - prev - pitch) > 1e-6:
                out.append('M%s %sH%s' % (fmt(start), fmt(y), fmt(prev+size))); start = x
            prev = x
        out.append('M%s %sH%s' % (fmt(start), fmt(y), fmt(prev+size)))
    return ''.join(out)
def singles(dots, size):
    return ''.join('M%s %sh%s' % (fmt(x), fmt(y), fmt(size)) for x,y in sorted(dots, key=lambda d:(d[1],d[0])))

# Overview: pitch 14, size 5
pitch, size = 14, 5
allD = []; byE = {}
for k in range(0, 55):
    y = 14*k + 7
    for j in range(0, 72):
        xl = 14*j + 4.5
        e = which((xl+2.5, y))
        if e:
            allD.append((xl,y)); byE.setdefault(e, []).append((xl,y))
def lvl(x,y):
    h = (int(x*2)*73856093 ^ int(y)*19349663) % 100
    return 2 if h < 7 else (1 if h < 27 else 0)
l1 = [d for d in allD if lvl(*d)==1]; l2 = [d for d in allD if lvl(*d)==2]
print('OV_COUNT', len(allD), {k:len(v) for k,v in byE.items()}, len(l1), len(l2))
print('OV_BASE', runs(allD, pitch, size))
print('OV_L1', singles(l1, size))
print('OV_L2', singles(l2, size))
print('OV_DXB', runs(byE['DXB']+byE.get('HAT',[]), pitch, size))

# Zoom: pitch 6, size 2.2, window
pitch, size = 6, 2.2
dx = []; oth = []
for k in range(17, 67):
    y = 6*k + 3
    for j in range(92, 148):
        xl = 6*j + 1.9
        e = which((xl+1.1, y))
        if e in ('DXB','HAT'): dx.append((xl,y))
        elif e: oth.append((xl,y))
print('ZM_COUNT', len(dx), len(oth))
print('ZM_DXB', runs(dx, pitch, size))
print('ZM_OTH', runs(oth, pitch, size))
