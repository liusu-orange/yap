# CMP Topography Prototype

This module implements the first CMP topography stage:

```text
GDSII Cu polygons -> local density map -> effective density map
```

Generate the synthetic test layout from Windows CMD:

```cmd
python cmp_topography\generate_synthetic_gds.py ^
  --output input\cmp_topography\synthetic_cmp.gds
```

Extract density maps:

```cmd
python cmp_topography\effective_density.py ^
  --gds input\cmp_topography\synthetic_cmp.gds ^
  --output-dir output\cmp_topography\synthetic_cmp ^
  --layer 10 ^
  --tile-size-um 20 ^
  --interaction-length-um 150 ^
  --bounds-um 0 0 2000 1600 ^
  --debug-polygons 2 ^
  --debug-tiles 3
```

The Gaussian convolution is normalized near layout boundaries to avoid an
artificial low-density halo.

Compute compact contact-pressure and Cu-height maps:

```cmd
python cmp_topography\contact_pressure_model.py ^
  --config cmp_topography\configs\synthetic_cmp_pressure.yaml ^
  --density-dir output\cmp_topography\synthetic_cmp ^
  --gds input\cmp_topography\synthetic_cmp.gds ^
  --output-dir output\cmp_topography\synthetic_cmp_pressure ^
  --layer 10
```
