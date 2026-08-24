"""Verify the three-outcome band rule: setpoint band, tighter-of band, or no band."""

from src import schema
from src.config import KILN, MILL, load_config
from src.digital_twin.layout import panel_tags
from src.process_models.plant import PlantTwin
from src.simulation.scheduler import SETPOINTS

twin = PlantTwin()
snap = twin.current_state_snapshot()

constraints: dict[str, tuple[float, float]] = {}
nominal: dict[str, float] = {}
for line in snap.get("units", {}).values():
    for comp in line.get("units", {}).values():
        for tag, band in (comp.get("constraints") or {}).items():
            constraints[str(tag)] = (float(band[0]), float(band[1]))
        for key in ("inputs", "outputs"):
            for tag, value in (comp.get(key) or {}).items():
                if isinstance(value, (int, float)):
                    nominal.setdefault(str(tag), float(value))

references = {"kiln": twin.kiln.reference, "mill": twin.cement_mill.reference}
ranges = {"kiln": load_config(KILN)["operating_ranges"], "mill": load_config(MILL)["operating_ranges"]}
setpoints: dict[str, tuple[tuple[float, float], str]] = {}
for spec in SETPOINTS:
    block = ranges[spec.dataset]
    if spec.variable in block:
        setpoints[spec.tag] = (tuple(float(v) for v in block[spec.variable]), "absolute")
    elif spec.ratio_key and spec.ratio_key in block:
        ratio = block[spec.ratio_key]
        ref = float(getattr(references[spec.dataset], spec.reference_attr))
        setpoints[spec.tag] = ((float(ratio[0]) * ref, float(ratio[1]) * ref), "ratio")

tags = []
for dataset in ("kiln", "mill"):
    for tag in panel_tags(dataset):
        if tag not in tags:
            tags.append(tag)

no_band, from_setpoint, tightened, unchanged, no_nominal = [], [], [], [], []
for tag in tags:
    spec = schema.get_tag(tag) if schema.has_tag(tag) else None
    sch = (spec.range_min, spec.range_max) if spec else (None, None)
    con = constraints.get(tag)
    nom = nominal.get(tag)
    if tag in setpoints:
        from_setpoint.append((tag, setpoints[tag]))
        continue
    if con and sch[0] is not None:
        cand = (max(con[0], sch[0]), min(con[1], sch[1]))
        if cand != con:
            tightened.append((tag, con, cand))
    elif con:
        cand = con
    else:
        cand = sch
    if cand[0] is None:
        no_band.append((tag, "no documented range"))
    elif nom is None:
        no_nominal.append((tag, cand))
    elif not (cand[0] <= nom <= cand[1]):
        no_band.append((tag, f"nominal {nom:.4g} outside {cand}"))
    else:
        unchanged.append(tag)

print(f"FROM SETPOINT RANGE ({len(from_setpoint)}):")
for tag, (band, basis) in from_setpoint:
    print(f"   {tag:38s} ({band[0]:.4g}, {band[1]:.4g})  [{basis}]")
print(f"\nTIGHTENED constraint -> intersection ({len(tightened)}):")
for tag, con, cand in tightened:
    print(f"   {tag:38s} {con} -> {cand}")
print(f"\nNO BAND / status not judged ({len(no_band)}):")
for tag, why in no_band:
    print(f"   {tag:38s} {why}")
print(f"\nNO NOMINAL VALUE, band kept ({len(no_nominal)}):")
for tag, cand in no_nominal:
    print(f"   {tag:38s} {cand}")
print(f"\nUNCHANGED ({len(unchanged)}): {len(unchanged)} tags")
