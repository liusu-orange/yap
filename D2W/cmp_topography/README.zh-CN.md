# CMP Topography 建模说明

本文档解释当前 `cmp_topography` 原型的建模思路。英文 `README.md`
保留为运行命令说明。

## 1. 目标

当前目标是打通：

```text
GDSII Cu 版图
  -> 局部密度 local density
  -> 有效密度 effective density
  -> 接触压力 contact pressure
  -> Cu dishing
  -> 铜高度均值 mu_h
```

最终输出的 `mu_h_nm.npy` 可以作为后续接入 YAP `TOP_DISH_MEAN_nm /
BOT_DISH_MEAN_nm` 空间映射的基础。

## 2. 合成 GDS 版图

测试 GDS 为 `input/cmp_topography/synthetic_cmp.gds`，芯片尺寸为：

```text
2000 um x 1600 um
```

Cu 图形位于 GDS layer `10`。四个区域如下：

| 区域 | 位置 | Pad Size | Pitch | 理论面积密度 | Pad 数量 |
|---|---|---:|---:|---:|---:|
| small_dense | 左上 | 10 um x 10 um | 20 um x 20 um | 25% | 1419 |
| large_dense | 右上 | 40 um x 40 um | 80 um x 80 um | 25% | 88 |
| small_sparse | 左下 | 10 um x 10 um | 50 um x 50 um | 4% | 221 |
| large_sparse | 右下 | 40 um x 40 um | 200 um x 200 um | 4% | 20 |

`small_dense` 和 `large_dense` 的理论密度相同，都是：

```text
10*10 / (20*20) = 25%
40*40 / (80*80) = 25%
```

它们用于验证：有效密度只能描述长程面积密度，不能区分同密度下不同
Pad Size / Pitch 带来的 Dishing 差异。

## 3. 局部密度

首先将版图划分为固定 Tile。当前默认：

```text
tile_size = 20 um
```

每个 Tile 的局部 Cu 密度为：

```text
d_ij = Area(Cu intersect Tile_ij) / Area(Tile_ij)
```

代码使用 `gdstk` 读取 GDSII，多边形面积交集由 `shapely` 精确计算。

输出：

```text
local_density.npy
local_density.png
```

## 4. 有效密度

CMP 抛光垫不会只感受到一个 20 um Tile，而会感受到周围一定范围的图形。
因此定义有效密度：

```text
rho_eff(x,y) = (d(x,y) conv K(x,y)) / (1(x,y) conv K(x,y))
```

当前核函数为 Gaussian：

```text
K(dx,dy) = exp(-(dx^2 + dy^2) / (2L^2))
```

当前默认：

```text
interaction_length L = 150 um
```

分母 `1 conv K` 是边界归一化项，用来避免芯片边缘因为卷积窗口不完整而
出现虚假的低密度。

当前 synthetic case 结果：

```text
map_shape = 80 x 100
local_density_mean = 0.10525
effective_density_min = 0.01465
effective_density_max = 0.24279
effective_density_mean = 0.10979
```

四个区域中心的有效密度约为：

```text
small_dense  center rho_eff = 0.2425
large_dense  center rho_eff = 0.2413
small_sparse center rho_eff = 0.0394
large_sparse center rho_eff = 0.0408
```

这说明同样 25% 面积密度的 dense 区域，在有效密度图中基本相同。

## 5. 为什么需要载荷守恒归一化

从有效密度到压力的直觉是：低密度区域支撑少，局部压力更高；高密度区域
支撑多，局部压力更低。

若直接使用：

```text
P_raw = P0 * (rho_eff + epsilon)^(-alpha)
```

则不同版图会导致全芯片平均压力也发生变化。这相当于同一台 CMP 设备在
不同版图上施加了不同总载荷，物理含义不清。

更清晰的写法是先定义无量纲压力因子：

```text
F_raw(x,y) = (rho_eff(x,y) + epsilon)^(-alpha) * F_edge(r)
P_macro(x,y) = P0 * F_raw(x,y) / mean(F_raw)
```

注意：这里的 `F_raw` 不包含 `P0`。如果把 `P_raw` 定义成已经包含 `P0` 的
压力值，那么归一化公式就不应再额外乘一次 `P0`。当前代码采用的是
`F_raw` 版本，避免重复乘 `P0`。

这样做的含义是：

1. 保留密度导致的相对压力差异。
2. 保证全芯片平均压力仍为设备设定的 `P0`。
3. 防止压力因为版图整体稀疏或密集而整体漂移。

当前默认参数：

```text
P0 = 30 kPa
epsilon = 0.05
alpha = 0.8
```

这些参数存放在：

```text
cmp_topography/configs/synthetic_cmp_pressure.yaml
```

运行时使用：

```cmd
python cmp_topography\contact_pressure_model.py ^
  --config cmp_topography\configs\synthetic_cmp_pressure.yaml ^
  --density-dir output\cmp_topography\synthetic_cmp ^
  --gds input\cmp_topography\synthetic_cmp.gds ^
  --output-dir output\cmp_topography\synthetic_cmp_pressure ^
  --layer 10
```

命令行传入同名参数时会覆盖 YAML，例如：

```cmd
python cmp_topography\contact_pressure_model.py ^
  --config cmp_topography\configs\synthetic_cmp_pressure.yaml ^
  --density-dir output\cmp_topography\synthetic_cmp ^
  --gds input\cmp_topography\synthetic_cmp.gds ^
  --output-dir output\cmp_topography\synthetic_cmp_pressure_alpha1 ^
  --layer 10 ^
  --density-alpha 1.0
```

## 6. 边缘效应

预留径向边缘效应：

```text
F_edge(r) = 1 + beta * r_norm^n
```

其中：

```text
r_norm = distance_to_center / die_half_diagonal
```

当前默认关闭：

```text
beta = 0
n = 4
```

## 7. Pad Size 修正

有效密度不能区分 `10 um / 20 um pitch` 与 `40 um / 80 um pitch` 这类
相同面积密度但不同几何尺度的版图。因此新增 Pad Size 压力增强项：

```text
F_pad = 1 + C_W * (W / W0)^a
```

其中：

```text
W  = Tile 内 Cu polygon 的面积加权等效方形尺寸
W0 = reference_pad_size_um
```

当前默认：

```text
W0 = 10 um
C_W = 0.2
a = 1.0
```

Cu 上的局部压力为：

```text
P_Cu = P_macro * F_pad
```

没有 Cu 的 Tile 不定义 `P_Cu` 与 `mu_h`，图中会被屏蔽。

## 8. Preston 方程与 mu_h

使用 compact Preston 方程：

```text
MRR_Cu   = K_Cu   * P_Cu    * V
MRR_diel = K_diel * P_macro * V
```

Dishing 表示 Cu 相对局部介质多磨掉的高度：

```text
D_dishing = T * max(MRR_Cu - MRR_diel, 0)
```

YAP 中 Cu recess 的均值使用负号表示：

```text
mu_h = -D_dishing
```

当前默认参数：

```text
K_Cu = 1.0 nm/min/kPa
K_diel = 0.5 nm/min/kPa
T = 0.0877 min
V = 1.0
```

这些参数只是用于跑通流程的 compact-model 默认值，不代表最终校准后的 CMP
工艺参数。

## 9. 当前输出

`contact_pressure_model.py` 输出：

```text
pad_size_um.npy / .png
pressure_factor.npy
pressure_macro_kpa.npy / .png
pad_size_factor.npy
pressure_cu_kpa.npy / .png
mrr_cu_nm_per_min.npy
mrr_diel_nm_per_min.npy
dishing_nm.npy / .png
mu_h_nm.npy / .png
contact_pressure_summary.json
```

后续真正接入 YAP 的核心文件是：

```text
mu_h_nm.npy
```
