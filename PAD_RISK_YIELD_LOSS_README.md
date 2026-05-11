# Pad Risk 主线下的四种 Yield Loss 计算梳理

这份文档把当前 D2W modeling 流程里的 pad-level risk map 计算串起来，重点回答一个问题：从输入的 pad 布局出发，四种失效机制如何被转换成每个 pad 的 yield loss，最后又如何汇总成 risk map。

对应主入口是 `D2W/pad_risk_map_calculator.py`，核心计算在 `D2W/assembly_yield_calculator.py` 的 `Pad_Yield_Map_Generator()` 中完成。

## 1. 总体主线

pad risk 的计算不是直接从 die yield 开始，而是先把每个 interface 展开成 pad 网格，然后对每个有效 pad 分别计算四类失效概率。

整体流程如下：

```text
.bmap + criticality.txt + config.yaml
        |
        v
convert_3dblox_to_pad_bitmap()
        |
        v
CRITICAL / REDUNDANT / DUMMY pad bitmap
        |
        v
Pad_Yield_Map_Generator()
        |
        +--> overlay pad yield      Y_ovl(i)
        +--> particle pad yield     Y_df(i)
        +--> mechanical pad yield   Y_ce(i)
        +--> ESD pad yield          Y_esd(i)
        |
        v
Y_bond(i) = Y_ovl(i) * Y_df(i) * Y_ce(i) * Y_esd(i)
        |
        v
risk_map_generator()
        |
        v
<x> <y> <P_esd_fail> <P_overlay_fail> <P_particle_fail> <P_mechanical_fail>
```

其中对任意 pad `i`：

```text
P_mechanism_fail(i) = 1 - Y_mechanism(i)
```

最终 `.map` 文件的四个 loss 列分别是：

```text
P_esd_fail(i)        = 1 - Y_esd(i)
P_overlay_fail(i)    = 1 - Y_ovl(i)
P_particle_fail(i)   = 1 - Y_df(i)
P_mechanical_fail(i) = 1 - Y_ce(i)
```

当前代码还会生成一张 overall risk PNG，对应：

```text
P_bond_fail(i) = 1 - Y_bond(i)
```

## 2. Pad 集合与坐标

`pad_risk_map_calculator.py` 先读取设计目录下的 `.bmap` 和对应 criticality 文件，调用：

```text
convert_3dblox_to_pad_bitmap(...)
```

生成 `pad_bitmap_collection`。后续四种 loss 都只在有效 pad 上计算。有效 pad mask 是：

```text
valid_pad_mask =
    CRITICAL_PAD_BITMAP
    OR REDUNDANT_PAD_BITMAP
    OR DUMMY_PAD_BITMAP
```

每个 pad 的中心坐标来自 `interface.pad_coords`，形状可以理解为：

```text
pad_coords[i] = (x_i, y_i)
```

因此 pad risk map 的基本粒度是物理 pad，而不是 net。criticality 和 redundancy 会影响哪些 pad 被视为关键/冗余，以及后续 simulation 里如何容忍多个 pad failure；但在 analytical pad risk map 文件中，输出仍然是逐 pad 的失效概率。

## 3. Overlay Yield Loss

对应代码：

```text
D2W/overlay_yield_calculator.py
pad_overlay_yield_map_generator()
```

### 3.1 先算最大允许 misalignment

overlay failure 有两个约束：

1. top pad 和 bottom pad 的接触面积不能低于 `CONTACT_AREA_CONSTRAINT`。
2. pad 与相邻 pad 的 critical distance 不能低于 `CRITICAL_DIST_CONSTRAINT`。

代码先计算两个约束各自允许的最大偏移，然后取更严格者：

```text
M_allow = min(M_ca, M_cd)
```

`M_ca` 来自两个圆形 pad 的重叠面积方程。设 top/bottom pad 半径分别为 `r_t`、`r_b`，中心偏移为 `m`，重叠面积：

```text
A_overlap(m)
  = r_t^2 * arccos((r_t^2 + m^2 - r_b^2) / (2 * r_t * m))
  + r_b^2 * arccos((r_b^2 + m^2 - r_t^2) / (2 * r_b * m))
  - m * r_t * sin(theta_t)
```

求解：

```text
A_overlap(M_ca) = CONTACT_AREA_CONSTRAINT * pi * r_t^2
```

`M_cd` 来自 pitch、pad 尺寸与 critical distance 约束。代码中：

```text
P = min(PITCH_r, PITCH_c)
```

checkerboard 时会使用更保守的邻近距离：

```text
P = min(sqrt(PITCH_r^2 + PITCH_c^2), 2 * PITCH_r, 2 * PITCH_c)
```

然后：

```text
M_cd
  = (1 - CRITICAL_DIST_CONSTRAINT) * P
    - 0.5 * (2 * r_t)
    + (CRITICAL_DIST_CONSTRAINT - 0.5) * (2 * r_b)
```

### 3.2 每个 pad 的系统性偏移

对 pad `i`，坐标为 `(x_i, y_i)`。系统性误差由平移、旋转、倍率变化组成：

```text
dx_i = T_x - theta * y_i + M * x_i
dy_i = T_y + theta * x_i + M * y_i
s_i  = sqrt(dx_i^2 + dy_i^2)
```

其中 `T_x`、`T_y`、`theta`、`M` 都从 config 里的正态分布参数采样。

### 3.3 pad overlay yield

随机 overlay error 记为：

```text
R ~ Normal(mu_r, sigma_r)
```

对一次系统误差采样，pad 成功条件是总偏移落在允许窗口内：

```text
-M_allow <= s_i + R <= M_allow
```

因此该采样下的成功概率为：

```text
P_success(i | sample)
  = Phi(( M_allow - s_i - mu_r) / sigma_r)
    - Phi((-M_allow - s_i - mu_r) / sigma_r)
```

对 `num_samples` 个系统误差样本取平均：

```text
Y_ovl(i) = mean_sample(P_success(i | sample))
```

overlay yield loss：

```text
P_overlay_fail(i) = 1 - Y_ovl(i)
```

## 4. Particle / Defect Yield Loss

对应代码：

```text
D2W/defect_yield_calculator.py
pad_defect_yield_map_generator()
```

这里的主线是：particle defect 造成 void，void 是否 fatal 取决于 pad 到 first contact 位置的距离，以及 void tail 的空间扩展。

### 4.1 first contact 距离

对 pad `i` 计算其到 first contact 的距离 `L_i`：

```text
center:
L_i = sqrt(x_i^2 + y_i^2)

vertical-edge:
L_i = abs(DIE_W / 2 + x_i)

horizontal-edge:
L_i = abs(DIE_L / 2 + y_i)

corner:
L_i = sqrt((DIE_W / 2 + x_i)^2 + (DIE_L / 2 + y_i)^2)
```

### 4.2 fatal defect 平均数

代码使用闭式 critical-area 近似。定义：

```text
term_i = k_r * L_i + k_r0
```

对均匀 particle density `D0`，每个 pad 的 fatal main void 平均数为：

```text
lambda_df(i)
  = pi * D0 * [
      r_t^2
      + ((z - 1) / (z - 2)) * term_i^2 * t_0
      + (4 * (z - 1) / (2z - 3)) * term_i * r_t * t_0
    ]
```

其中：

- `r_t` 是 top pad 半径 `PAD_TOP_R_um`。
- `D0` 是 particle density。
- `t_0`、`z` 描述 particle thickness distribution。
- `k_r`、`k_r0` 控制 void tail 随 first-contact 距离增长的尺度。

如果配置里启用了 edge-enhanced particle density，也就是 `D1 > D0` 且 `EDGE_REGION_WIDTH_um > 0`，则先按 pad 到最近 die edge 的距离计算局部 density：

```text
w_i = clip(1 - dist_to_nearest_edge_i / EDGE_REGION_WIDTH_um, 0, 1)
D_i = D0 + (D1 - D0) * w_i
```

然后把上式里的 `D0` 替换成 `D_i`：

```text
lambda_df(i) = D_i * A_critical(i)
```

### 4.3 Poisson yield

fatal defect 数按 Poisson 模型处理，所以 pad defect yield 为：

```text
Y_df(i) = exp(-lambda_df(i))
```

particle / defect yield loss：

```text
P_particle_fail(i) = 1 - Y_df(i)
```

## 5. Mechanical / Cu Expansion Yield Loss

对应代码：

```text
D2W/Cu_expansion_yield_calculator.py
pad_Cu_expansion_yield_map_generator()

D2W/debond.py
debond_dishing_intervals_from_coords()
```

这里代码中的 yield key 是 `Y_ce`，输出列名在 risk map 中叫 mechanical failure probability。可以理解为 Cu dishing / expansion / debond 相关的机械窗口。

### 5.1 每个 pad 的允许 dishing 区间

`debond_dishing_intervals_from_coords(cfg, valid_die_pad_coords)` 的核心目标是为每个 pad `i` 找到一组由 debond / peeling 约束决定的 dishing 边界：

```text
[D_low(i), D_high(i)] = sort([D_Cu(i), D_SiO2(i)])
```

这里的整体逻辑按三步理解最清楚：

```text
1. 先算 pad 位置相关的 global peeling stress p(i)
2. 再算 Cu / SiO2 材料本身的 critical peeling stress
3. 用 sigma_crit - p(i) 得到有效阈值，分别反解 D_Cu(i) 和 D_SiO2(i)
```

#### 5.1.1 Global Peeling Stress `p(i)`

先用一句话解释：`global peeling stress p(i)` 是整片上/下键合结构因为“整体翘曲不匹配”而施加到第 `i` 个 pad 位置上的外部剥离应力。

这不是单个 pad 自己产生的局部应力，而是一个宏观效应。可以按下面的图像理解：

```text
bottom stack（下层堆叠）弯成一种形状
top stack（上层堆叠）    弯成另一种形状

两者键合在一起后，界面被迫同时满足两边的弯曲形状。
如果两边弯曲不一致，界面就会被拉开或剥离。
这个“想把界面拉开”的应力，就是 global peeling stress（全局剥离应力）。
```

这里常见缩写和英文术语如下：

```text
CTE:
  coefficient of thermal expansion，热膨胀系数

warpage:
  翘曲，指 wafer / die stack 整体弯起来的程度

sag:
  挠度/翘曲位移，表示中心或边缘相对参考平面的位移量

peeling stress:
  剥离应力，方向上倾向于把 bonding interface 拉开

bonding interface:
  键合界面，也就是 top 和 bottom 两边贴合的界面

effective layer:
  等效层，把复杂材料混合区域简化成一个均匀材料层

Young's modulus:
  杨氏模量，表示材料抵抗拉伸/压缩变形的刚度

Poisson ratio:
  泊松比，表示材料受拉/压时横向变形与纵向变形的关系
```

“两层 warpage”更准确地说是“双层结构翘曲”。它不是说 wafer 真的只有两层，也不是说存在两个 warpage；它的意思是：为了计算整体翘曲，代码把一个 wafer 简化成两张粘在一起的等效材料板：

```text
chip effective layer（芯片等效层）
+ substrate effective layer（衬底等效层）
= one simplified wafer stack（一个简化 wafer 堆叠）
```

为什么这样会翘曲？可以想象一把双层尺子：上层材料和下层材料受热后想伸长的比例不同，但它们粘在一起，不能各自自由伸长。最后整体只能通过“弯曲”来协调这个差异。这个弯曲量就是这里说的 warpage（翘曲）。

在代码里，`warpage_D_two_layer_exact()` 做的就是这件事：

```text
输入：
  chip 等效层的厚度 / 模量 / CTE
  substrate 等效层的厚度 / 模量 / CTE
  温度变化 DeltaT
  有效尺寸 L

输出：
  这个双层结构因为热失配产生的翘曲量 D_warpage
```

然后 bottom stack 和 top stack 分别算出自己的翘曲：

```text
D_A = bottom stack 的热失配翘曲
D_B = top stack 的热失配翘曲
```

再和初始翘曲合并：

```text
s_total_A = S_INIT_A_M - D_A
s_total_B = S_INIT_B_M - D_B
```

这里：

```text
S_INIT_A_M:
  bottom stack 的初始翘曲，单位 m

S_INIT_B_M:
  top stack 的初始翘曲，单位 m

s_total_A / s_total_B:
  bottom / top 最终进入剥离应力模型的总翘曲量
```

最后 Suhir peeling model（Suhir 剥离应力模型）把 `s_total_A` 和 `s_total_B` 的差异转换成位置相关的 `p(i)`。直觉上，两边翘曲差越大，界面越容易被拉开；pad 越靠近边缘，通常越容易感受到较大的剥离应力。

这里的 global peeling stress 指的是：整片 bottom/top bonded stack 因为材料热膨胀系数不同、厚度不同、初始翘曲不同，在键合/退火过程中产生整体弯曲。整体弯曲会在 bonding interface 上引入一个位置相关的剥离应力 `p(i)`。

它和后面的 `sigma_SiO2(D)`、`sigma_Cu(D)` 不同：

```text
global peeling stress p(i):
  来自整片 die/wafer stack 的宏观 warpage mismatch
  是 pad 位置 i 相关的外加载荷

local peeling stress sigma_material(D):
  来自单个 pad 附近 Cu/SiO2 因 dishing、热膨胀、接触面积产生的局部应力
  是 dishing D 的函数
```

所以在代码里，global stress 的作用是先消耗掉一部分材料可承受的 peeling budget：

```text
sigma_eff_material(i) = sigma_crit_material - p(i)
```

再用剩下的 `sigma_eff` 去反解 pad 允许的 dishing 边界。

如果 `include_global_peeling_stress=True`，代码会先根据 config 构造 bottom/top 等效 wafer stack，计算 pre/post-bond warpage，然后用 Suhir peeling kernel 得到边缘附近的 global peeling stress。

##### 5.1.1.1 什么是“三材料混合层等效成一层”

config 里 bottom/top wafer 的 chip layer 和 substrate layer 不是只包含单一材料，而是用 Cu、SiO2、Si 的体积分数描述一个等效混合层。例如：

```text
B_Chip_Cu_V
B_Chip_Sio2_V
B_Chip_Si_V
B_Chip_T
```

表示 bottom wafer 的 chip layer 中 Cu / SiO2 / Si 的体积分数，以及这一层的厚度。

“三材料混合层等效成一层”的意思是：不逐个建模 Cu、SiO2、Si 的细节图形，而是把这一层看成一个均匀的 effective layer。它有等效的 thermal expansion coefficient、Young's modulus、Poisson ratio 和 thickness。

先把 bottom/top wafer 的三材料混合层等效成一层：

```text
alpha_eq = (alpha_1 V_1 + alpha_2 V_2 + alpha_3 V_3) / (V_1 + V_2 + V_3)
E_eq     = (E_1 V_1     + E_2 V_2     + E_3 V_3)     / (V_1 + V_2 + V_3)
nu_eq    = (nu_1 V_1    + nu_2 V_2    + nu_3 V_3)    / (V_1 + V_2 + V_3)
```

这里：

```text
V_1, V_2, V_3:
  三种材料的体积分数，例如 Cu / SiO2 / Si volume fraction

alpha_1, alpha_2, alpha_3:
  三种材料的 CTE, coefficient of thermal expansion（热膨胀系数）

E_1, E_2, E_3:
  三种材料的 Young's modulus

nu_1, nu_2, nu_3:
  三种材料的 Poisson ratio

t_m:
  该 effective layer 的厚度，单位 m
```

在代码里，bottom 和 top 各有两类 layer：

```text
Chip layer:
  B_Chip_* 或 T_Chip_*

Substrate layer:
  B_Sub_* 或 T_Sub_*
```

所以 `process_wafer()` 做的是：

```text
bottom wafer:
  B_Chip 三材料混合 -> bottom chip effective layer
  B_Sub  三材料混合 -> bottom substrate effective layer

top wafer:
  T_Chip 三材料混合 -> top chip effective layer
  T_Sub  三材料混合 -> top substrate effective layer
```

##### 5.1.1.2 什么是“单个 wafer 的两层 warpage”

每个 wafer 被简化成两层结构：

```text
chip effective layer + substrate effective layer
```

这两层的 CTE、模量、厚度不同。温度从 `T_R` 变化到 `T_anl` 时，两层想膨胀的程度不同，于是单个 wafer 会产生弯曲/翘曲，代码用 `warpage_D_two_layer_exact()` 计算这个 warpage。

单个 wafer 的两层 warpage 公式是：

```text
ratio = t_c / t_s

D_warpage
  = [3 L^2 / (4(t_c + t_s))]
    * (1 + ratio)^2
    * (alpha_s - alpha_c)
    * DeltaT
    / denominator
```

其中：

```text
denominator
  = 3(1 + t_c / t_s)^2
    + (1 + t_c E_c / (t_s E_s))
      * ((t_c^2 / t_s^2) + (t_s E_s / (t_c E_c)))
```

这里的参数含义：

```text
D_warpage:
  单个 wafer 因两层热失配产生的翘曲量，单位 m

L:
  wafer / die-region 的有效半径或特征长度，代码里来自 WAFER_A.L_m / WAFER_B.L_m

t_c:
  chip effective layer thickness

t_s:
  substrate effective layer thickness

E_c:
  chip effective layer Young's modulus

E_s:
  substrate effective layer Young's modulus

alpha_c:
  chip effective layer CTE

alpha_s:
  substrate effective layer CTE

DeltaT:
  T_anl - T_R
```

直觉上，如果 chip layer 和 substrate layer 的热膨胀差越大、温差越大、厚度/模量越不匹配，`D_warpage` 就越明显。

然后得到 bottom/top 的总 sag：

```text
s_total_A = S_INIT_A_M - D_A
s_total_B = S_INIT_B_M - D_B
```

这里：

```text
S_INIT_A_M:
  bottom wafer 的 pre-anneal / initial warpage，单位 m

S_INIT_B_M:
  top wafer 的 pre-anneal / initial warpage，单位 m

D_A:
  bottom wafer 因温度变化和两层失配计算出的 warpage

D_B:
  top wafer 因温度变化和两层失配计算出的 warpage

s_total_A, s_total_B:
  进入 bonded-stack peeling 计算的 bottom/top 总 sag
```

##### 5.1.1.3 Suhir peeling kernel 如何把 warpage mismatch 变成 `p(i)`

有了 bottom/top 的总 sag 后，代码用 Suhir peeling model 把两片结构的弯曲差转换成 interface peeling stress。

Suhir kernel 中：

```text
D1 = E_A * h_A^3 / (12 * (1 - nu_A^2))
D2 = E_B * h_B^3 / (12 * (1 - nu_B^2))

K = 1 / [
      (1 - nu_A) * h_A / (3E_A)
      + (1 - nu_B) * h_B / (3E_B)
    ]

kappa_A = 2 * s_total_A / R^2
kappa_B = 2 * s_total_B / R^2

M = (D1 * D2) / (D1 + D2) * (kappa_A - kappa_B)
beta = (K * (D1 + D2) / (4 * D1 * D2)) ^ 0.25
p_max = K * M / (2 * beta * D1)
```

这里：

```text
D1, D2:
  bottom/top wafer effective bending stiffness

E_A, E_B:
  bottom/top wafer effective Young's modulus

h_A, h_B:
  bottom/top wafer effective thickness

nu_A, nu_B:
  bottom/top wafer effective Poisson ratio

K:
  interface / foundation effective stiffness

kappa_A, kappa_B:
  bottom/top 的曲率，约等于 2 * sag / R^2

M:
  由 bottom/top 曲率差引起的 bending moment

beta:
  peeling stress 的空间衰减参数

p_max:
  边缘附近的最大 peeling stress

R:
  stack 的有效半径，代码里是 min(WAFER_A.L_m, WAFER_B.L_m)
```

对 pad `i`，先算它到中心的半径：

```text
r_i = sqrt(x_i^2 + y_i^2)
s_i = R - r_i
```

global peeling stress：

```text
p(i)
  = p_max * exp(-beta * s_i)
    * (cos(beta * s_i) - sin(beta * s_i))
```

其中：

```text
r_i:
  pad i 到 stack 中心的径向距离

s_i = R - r_i:
  pad i 到外边缘的径向距离

p(i):
  pad i 位置处的 global peeling stress
```

这个形式表达了一个重要物理直觉：global peeling stress 通常在边缘附近更强，往中心会衰减并振荡。因此同样的 Cu/SiO2 局部结构，在 die/wafer 边缘附近允许的 dishing 窗口可能更窄。

单位转换成 MPa 后用于降低 Cu/SiO2 的临界阈值：

```text
sigma_eff_material(i) = sigma_crit_material - p(i)
```

如果 `include_global_peeling_stress=False`，则：

```text
p(i) = 0
```

#### 5.1.2 Critical Peeling Stress

global stress 算出来之后，下一步是计算材料本身能承受的 critical peeling stress。代码对 SiO2 和 Cu 分别算临界值。

通用形式是：

```text
sigma_crit
  = contact_factor
    * sqrt((Gc * E) / (aY2 * (1 - nu^2)))
```

其中：

```text
Gc  = adhesion energy
E   = Young's modulus
nu  = Poisson ratio
aY2 = CRIT_aY2_UM * 1e-6
```

SiO2 的 critical stress：

```text
sigma_crit_SiO2
  = Effective_Contact_Area
    * sqrt((GC_SIO2_JPM2 * E_OX) / (CRIT_aY2 * (1 - nu_OX^2)))
```

Cu 的 critical stress：

```text
sigma_crit_Cu
  = sqrt((GC_CU_JPM2 * E_Cu) / (CRIT_aY2 * (1 - nu_Cu^2)))
```

注意这里 Cu 使用的 `contact_factor = 1.0`，而 SiO2 使用 `Effective_Contact_Area`。

有了 global peeling stress 后，每个 pad 的有效阈值变为：

```text
sigma_eff_SiO2(i) = sigma_crit_SiO2 - p(i)
sigma_eff_Cu(i)   = sigma_crit_Cu   - p(i)
```

也就是说，越靠近高 global peeling stress 区域的 pad，留给局部 Cu/SiO2 dishing 的 stress budget 越小，因此允许 dishing 窗口会更紧。

#### 5.1.3 Local Pad-Scale Stress Model

这一小节要做的事情是：建立两个“局部应力函数”，描述当 pad 表面有某个 dishing `D` 时，局部会产生多大的 peeling stress。

```text
sigma_SiO2(D): 给定 dishing D 时，SiO2 侧的局部剥离应力
sigma_Cu(D):   给定 dishing D 时，Cu 侧的局部剥离应力
```

有了这两个函数后，下一节就可以用有效阈值 `sigma_eff_SiO2(i)` / `sigma_eff_Cu(i)` 反推出允许的 `D_SiO2(i)` / `D_Cu(i)`。

##### 5.1.3.1 先定义一个 pad 周期单元

模型先把每个 pad 周围的局部区域看成一个周期单元。设有效 pitch 为 `p`，Cu pad 直径为 `d`：

```text
A_cell = p^2
A_cu   = pi * d^2 / 4
A_ox   = A_cell - A_cu
```

参数解释：

```text
p:
  effective pitch，有效 pad 间距。这里用于近似单个 pad 对应的周期单元边长。

d:
  Cu pad 直径，代码里 d = 2 * PAD_TOP_R_um。

A_cell:
  一个 pad 对应的周期单元面积。

A_cu:
  Cu pad 的面积。

A_ox:
  oxide area，氧化物/SiO2 区域面积，也就是周期单元里非 Cu 的面积。
```

这一步的目的，是把局部结构简化成：

```text
一个 Cu 圆形 pad + 周围 SiO2 区域
```

后面的 SiO2 peeling stress 会用到 `A_cu / A_ox`，Cu peeling stress 会用到 `A_cell / A_cu`。

##### 5.1.3.2 计算 Cu / SiO2 的热失配应力

Cu 和 SiO2 的 CTE 不同。CTE 是 coefficient of thermal expansion（热膨胀系数）。升温时，Cu 和 SiO2 想膨胀的程度不同，于是产生 thermal mismatch stress（热失配应力）。

```text
DeltaT = T_anl - T_R
DeltaAlpha = (CU_ALPHA_PPM - OX_ALPHA_PPM) * 1e-6

sigma_t = (E_Cu / (1 - nu_Cu)) * DeltaAlpha * DeltaT
```

参数解释：

```text
T_anl:
  anneal temperature，退火温度。

T_R:
  reference temperature，参考温度/室温。

DeltaT:
  温度变化量。

CU_ALPHA_PPM:
  Cu 的热膨胀系数，单位 ppm/C。

OX_ALPHA_PPM:
  SiO2 的热膨胀系数，单位 ppm/C。

DeltaAlpha:
  Cu 与 SiO2 的热膨胀系数差。乘 1e-6 是把 ppm 转成普通比例。

E_Cu:
  Cu 的 Young's modulus（杨氏模量）。

nu_Cu:
  Cu 的 Poisson ratio（泊松比）。

sigma_t:
  thermal mismatch stress，热失配应力。
```

##### 5.1.3.3 把热应力分成弹性和塑性两部分

材料在低应力下主要是 elastic（弹性）响应；超过 yield stress（屈服应力）后，会进入 plastic（塑性）响应。代码把 `sigma_t` 拆成两部分：

```text
sigma_y = SIGMA_Y_MPA * 1e6

sigma_e_heat = min(sigma_t, sigma_y)
sigma_p_heat = max(sigma_t - sigma_y, 0)
```

参数解释：

```text
SIGMA_Y_MPA:
  Cu 的屈服应力，配置里单位是 MPa。

sigma_y:
  Cu 的屈服应力，转换成 Pa。

sigma_e_heat:
  heat stage（升温/退火阶段）中的弹性应力部分。

sigma_p_heat:
  heat stage 中超过屈服应力后的塑性应力部分。
```

直观理解：

```text
如果 sigma_t <= sigma_y:
  全部是弹性部分，sigma_p_heat = 0。

如果 sigma_t > sigma_y:
  sigma_y 以内算弹性，超过 sigma_y 的部分算塑性。
```

##### 5.1.3.4 heat stage 下 Cu 能靠近多少

接下来代码把弹性/塑性热应力转成一个等效位移量 `delta_heat`：

```text
delta_heat
  = (4 * nu_Cu / E_Cu)
    * (C_HEAT_E * sigma_e_heat + C_HEAT_P * sigma_p_heat)
```

参数解释：

```text
delta_heat:
  heat stage 下 Cu 热膨胀和弹塑性效应带来的等效接近/开口位移量。

C_HEAT_E:
  heat stage 中弹性应力对应的拟合系数。

C_HEAT_P:
  heat stage 中塑性应力对应的拟合系数。
```

这一步的物理含义是：升温后 Cu 会热膨胀，dishing 越小越容易接触，dishing 越大越难接触。`delta_heat` 可以理解为 heat stage 里 Cu 能用来“填补凹陷/形成接触”的位移尺度。

##### 5.1.3.5 给定 dishing D，计算 Cu 接触比例 phi(D)

`D` 是 dishing depth（碟形凹陷深度 / pad 表面凹陷量）。给定 `D` 后，代码估计 Cu 的有效接触比例 `phi(D)`：

```text
phi(D) = clip(((delta_heat - 2D) / (2D)) ^ EXP_PHI, 0, 1),  D > 0
phi(0) = 1
```

参数解释：

```text
phi(D):
  contact fraction，接触比例。值越接近 1，说明 Cu 有效接触越充分；值越接近 0，说明几乎没有有效接触。

2D:
  top/bottom 两侧 dishing 合起来的凹陷尺度。

EXP_PHI:
  接触比例模型的指数拟合参数。

clip(..., 0, 1):
  把计算结果限制在 0 到 1 之间。
```

如果：

```text
delta_heat - 2D <= 0
```

说明 heat stage 的等效位移不足以补偿 top/bottom 两侧 dishing，因此认为没有有效 contact（接触）：

```text
phi(D) = 0
```

##### 5.1.3.6 计算局部法向刚度 k_n

局部法向刚度描述界面对开口/闭合位移有多“硬”：

```text
k_n = 2 * E_Cu / (KN_DEN_M * (1 - nu_Cu))
```

参数解释：

```text
k_n:
  local normal stiffness，局部法向刚度。

KN_DEN_M:
  法向刚度模型里的等效长度尺度，配置里单位是 m。

E_Cu, nu_Cu:
  Cu 的杨氏模量和泊松比。
```

`k_n` 越大，表示同样的开口/闭合位移会产生更大的局部应力。

##### 5.1.3.7 SiO2 的 heat-dwell peeling stress

SiO2 的局部剥离应力在 heat-dwell（升温并保温阶段）计算。公式是：

```text
sigma_SiO2(D)
  = k_n * (delta_heat - 2D) * (phi(D) * A_cu) / A_ox
```

参数解释：

```text
sigma_SiO2(D):
  给定 dishing D 时，SiO2 侧的局部 peeling stress（剥离应力）。

delta_heat - 2D:
  heat stage 后还剩下的有效 opening/contact 驱动力。

phi(D) * A_cu:
  实际参与接触的 Cu 面积。

A_ox:
  SiO2 区域面积。Cu 接触力通过周围 oxide 区域传递时，会按 A_cu / A_ox 形成面积放大/分摊关系。
```

如果没有有效接触：

```text
delta_heat - 2D <= 0
```

或者接触比例为 0：

```text
phi(D) <= 0
```

则：

```text
sigma_SiO2(D) = 0
```

##### 5.1.3.8 cool-down 阶段的 Cu 有效屈服应力

Cu 的 peeling stress 在 cool-down（冷却阶段）计算。冷却时先考虑 Bauschinger effect（包辛格效应），它会降低反向加载时的有效屈服应力：

```text
sigma_y_cool = (1 - BAUSCHINGER) * sigma_y
```

参数解释：

```text
BAUSCHINGER:
  Bauschinger effect，包辛格效应系数。数值越大，冷却阶段有效屈服应力降得越多。

sigma_y_cool:
  cool-down 阶段使用的有效屈服应力。
```

然后用新的 `sigma_y_cool` 再拆一次弹性/塑性部分：

```text
sigma_e_cool = min(sigma_t, sigma_y_cool)
sigma_p_cool = max(sigma_t - sigma_y_cool, 0)
```

参数解释：

```text
sigma_e_cool:
  cool-down 阶段的弹性应力部分。

sigma_p_cool:
  cool-down 阶段的塑性应力部分。
```

##### 5.1.3.9 cool-down 位移量 delta_cool

cool-down 阶段也会得到一个等效位移量：

```text
delta_cool
  = (4 * nu_Cu / E_Cu)
    * (C_COOL_E * sigma_e_cool + C_COOL_P * sigma_p_cool)
```

参数解释：

```text
delta_cool:
  cool-down 阶段由弹塑性应力贡献得到的等效位移量。

C_COOL_E:
  cool-down 阶段弹性应力对应的拟合系数。

C_COOL_P:
  cool-down 阶段塑性应力对应的拟合系数。
```

##### 5.1.3.10 Cu 的 cool-down peeling stress

最后计算 Cu 侧的局部剥离应力：

```text
area_factor = (A_cell / A_cu) ^ EXP_AREA
phi_factor  = (1 / phi(D)) ^ EXP_INVPHI

sigma_Cu(D)
  = k_n * (delta_cool - delta_heat + 2D)
    * phi_factor
    * area_factor
```

参数解释：

```text
sigma_Cu(D):
  给定 dishing D 时，Cu 侧的局部 peeling stress（剥离应力）。

delta_cool - delta_heat + 2D:
  cool-down 相对 heat stage 后的有效开口/剥离驱动力。

area_factor:
  面积修正因子。A_cell / A_cu 越大，说明 Cu 占周期单元面积越小，应力集中效应越强。

EXP_AREA:
  面积修正的指数拟合参数。

phi_factor:
  接触比例修正因子。phi(D) 越小，说明接触越少，局部 Cu peeling stress 会被放大。

EXP_INVPHI:
  接触比例修正的指数拟合参数。
```

如果没有有效接触：

```text
phi(D) <= 0
```

或者 cool-down 的有效剥离驱动力不为正：

```text
delta_cool - delta_heat + 2D <= 0
```

则：

```text
sigma_Cu(D) = 0
```

##### 5.1.3.11 这一节的输出是什么

到这里，本节最终得到两个函数：

```text
sigma_SiO2(D)
sigma_Cu(D)
```

它们的作用是：

```text
给定一个候选 dishing D
  -> 算出 SiO2 局部剥离应力
  -> 算出 Cu 局部剥离应力
```

下一节会把这两个函数反过来用：

```text
给定允许的应力阈值 sigma_eff
  -> 反解出允许的 dishing D
```

#### 5.1.4 反解 Dishing 边界

这一节里的几个词也先解释一下：

```text
inverse / 反解:
  已知允许的 stress 阈值，反过来求对应的 dishing D。

stress-vs-dishing function:
  应力-凹陷关系函数，即给定 D，算 sigma(D)。

fsolve:
  数值求根函数，可以逐个方程求解 D；当前代码为了速度没有逐 pad 使用它。

LUT:
  lookup table，查找表。代码先预先计算一组 D 和 sigma(D) 的对应关系，
  后续通过插值快速反解 D。

D_contact_max:
  Cu 仍能形成有效接触的最大 dishing 搜索上界。
```

现在每个 pad 都有两个有效阈值：

```text
sigma_eff_SiO2(i)
sigma_eff_Cu(i)
```

也有两个局部 stress-vs-dishing 函数：

```text
sigma_SiO2(D)
sigma_Cu(D)
```

所以 dishing 边界由下面两个方程反解得到：

```text
sigma_SiO2(D_SiO2(i)) = sigma_eff_SiO2(i)
sigma_Cu(D_Cu(i))     = sigma_eff_Cu(i)
```

代码不是逐 pad 调 `fsolve`，而是建立 LUT 后插值反解。

SiO2 的 LUT 搜索窗口：

```text
D_SiO2 in [-10, 10] nm
```

如果目标值不在窗口对应的 stress 范围内，则：

```text
D_SiO2(i) = -10 nm
```

Cu 的 LUT 搜索窗口：

```text
D_Cu in [0, D_contact_max]
D_contact_max = 0.5 * delta_heat
```

如果目标值不在窗口对应的 stress 范围内，则：

```text
D_Cu(i) = D_contact_max
```

#### 5.1.5 最终总结

综合上面两条反解路径：

```text
D_SiO2(i) = inverse_sigma_SiO2(sigma_crit_SiO2 - p(i))
D_Cu(i)   = inverse_sigma_Cu(sigma_crit_Cu - p(i))
```

然后：

```text
[D_low(i), D_high(i)] = sort([D_Cu(i), D_SiO2(i)])
```

这就是 mechanical / Cu expansion yield 里每个 pad 使用的允许 dishing 区间。

一句话说：global peeling stress `p(i)` 先消耗掉一部分材料可承受的 peeling budget，剩下的 `sigma_eff` 再通过 Cu/SiO2 的局部 stress model 反推出该 pad 允许的 dishing 下界和上界。

### 5.2 转成总 Cu height 的上下界

代码把 dishing bound 转成 top+bottom Cu height 的限制：

```text
U_i = -2 * D_low(i)
L_i = -2 * D_high(i)
U_i = min(U_i, 0)
```

其中 `U_i` 是 upper limit，`L_i` 是 lower limit。`U_i` 被 clip 到不大于 0，保证上界不会变成正的 protrusion 窗口。

### 5.3 top + bottom dishing 分布

top pad 和 bottom pad 的 dishing height 都按正态分布处理：

```text
H_top ~ Normal(mu_top, sigma_top)
H_bot ~ Normal(mu_bot, sigma_bot)
```

两者相加：

```text
H = H_top + H_bot
H ~ Normal(mu_top + mu_bot, sqrt(sigma_top^2 + sigma_bot^2))
```

### 5.4 mechanical yield

pad 成功条件是总 height 落在允许区间：

```text
L_i <= H <= U_i
```

所以：

```text
Y_ce(i)
  = Phi((U_i - (mu_top + mu_bot)) / sqrt(sigma_top^2 + sigma_bot^2))
    - Phi((L_i - (mu_top + mu_bot)) / sqrt(sigma_top^2 + sigma_bot^2))
```

mechanical yield loss：

```text
P_mechanical_fail(i) = 1 - Y_ce(i)
```

## 6. ESD Yield Loss

对应代码：

```text
D2W/esd_yield_calculator.py
pad_esd_yield_map_generator()
```

ESD（electrostatic discharge，静电放电）的 pad risk 不是简单地假设“每个 pad 独立失效”。当前代码的思路是：

```text
1. 抽象一个 charging voltage V（带电电压）
2. 由 V 算出可能发生放电的 arcing distance（放电距离）
3. 由 V 算出这次放电若发生时的 die-level failure probability（die 级失效概率）
4. 在给定 tilt（倾斜）和 dishing（凹陷）随机性的情况下，计算哪个 pad 最可能 first-touch（最先接触/最先放电）
5. pad i 的 ESD risk = 它成为 first-touch pad 的概率 * 该电压下 ESD 失效概率，再对 V 和 tilt 做积分平均
```

最后得到：

```text
Y_esd(i) = 1 - R_esd(i)
```

其中 `R_esd(i)` 是 pad `i` 的 ESD failure probability（ESD 失效概率）。

### 6.1 输入：有效 pad 坐标和基础参数

ESD 计算只在有效 pad 上做。输入坐标为：

```text
pad_coords_um[i] = (x_i, y_i)
```

参数解释：

```text
x_i, y_i:
  pad i 的中心坐标，单位 um。

pad_size_um:
  pad 尺寸，当前调用中使用 2 * PAD_TOP_R_um。

pad_pitch_um:
  pad pitch，pad 间距，用于画图和部分几何尺度。

top_die_w_um, top_die_h_um:
  top die 的宽和高，单位 um，用于计算 die 面积。
```

### 6.2 电压积分：charging voltage `V`

ESD 风险和带电电压有关。代码假设 charging voltage（带电电压）`V` 在：

```text
[V_MIN_V, V_MAX_V]
```

这个区间内取值，并用 Gauss-Legendre quadrature（高斯-勒让德积分）做数值积分。

参数解释：

```text
V_MIN_V:
  电压积分下界，单位 V。

V_MAX_V:
  电压积分上界，单位 V。

ESD_ANALYTICAL_VOLTAGE_Q:
  电压方向的积分点数量。点数越多，积分更细，但计算更慢。
```

对每个电压积分点 `V`，代码都会计算两件事：

```text
d_arc(V): 这个电压下可能跨越的最大放电距离
p_fail(V): 这个电压下单次 ESD 事件导致 die 失效的概率
```

### 6.3 电压到放电距离 `d_arc(V)`

`d_arc(V)` 是 arcing distance（放电距离）：给定电压 `V`，空气间隙最大能隔多远仍可能发生放电。

代码使用 modified Paschen curve（修正 Paschen 曲线）：

```text
V = 97 d,                         d < 3.5 um
V = 337,                          3.5 um < d < 7 um
V = 170 + 2.48 d + 58 sqrt(d),    d > 7 um
```

参数解释：

```text
V:
  charging voltage，带电电压，单位 V。

d:
  air-gap distance，空气间隙距离，单位 um。

d_arc(V):
  给定 V 后反解出来的最大放电距离，单位 um。
```

实际计算时，代码是给定 `V`，反过来求 `d_arc(V)`：

```text
d_arc(V) = inverse_Paschen(V)
```

直觉上：

```text
V 越大，可跨越的空气间隙越大，越远的 pad 也可能发生放电。
```

### 6.4 电压到 die-level ESD failure probability

接下来，代码估计电压 `V` 对应的 peak current（峰值电流）。先算 die 面积：

```text
A_die_mm2 = (top_die_w_um * 1e-3) * (top_die_h_um * 1e-3)
```

参数解释：

```text
top_die_w_um, top_die_h_um:
  top die 的宽和高，单位 um。

1e-3:
  把 um 转成 mm。

A_die_mm2:
  die 面积，单位 mm^2。
```

然后用经验公式计算峰值电流：

```text
I_peak(V) = 0.0045 * A_die_mm2^0.35 * sqrt(V)
```

参数解释：

```text
I_peak(V):
  peak current，峰值电流，单位 A。

0.0045 和 0.35:
  经验拟合系数，用来描述 die 面积和电压对 ESD 峰值电流的影响。
```

再用 Weibull CDF（Weibull cumulative distribution function，Weibull 累积分布函数）得到单次事件失效概率：

```text
p_fail(V) =
  0,                                  I_peak(V) < CUTOFF_MIN_A
  1 - exp(-(I_peak(V) / lambda)^k),   otherwise
```

参数解释：

```text
p_fail(V):
  single-event failure probability，单次 ESD 事件造成 die 失效的概率。

CUTOFF_MIN_A:
  最小电流门槛。如果 I_peak 低于这个值，认为不会触发 ESD 失效。

k:
  Weibull shape parameter，形状参数，代码里是 WEIBULL_K。

lambda:
  Weibull scale parameter，尺度参数，代码里是 WEIBULL_LAMBDA。
```

直觉上：

```text
I_peak 越大，p_fail(V) 越大。
```

### 6.5 tilt 随机性：die 不是完全平行靠近

ESD first-touch 还取决于两片 die/wafer 靠近时的倾斜。代码把 x/y 两个方向的 tilt（倾斜角）建模为正态分布：

```text
theta_x ~ Normal(TILT_X_MEAN_DEG, TILT_X_STD_DEG)
theta_y ~ Normal(TILT_Y_MEAN_DEG, TILT_Y_STD_DEG)
```

参数解释：

```text
theta_x:
  x 方向 tilt，单位 degree（度）。

theta_y:
  y 方向 tilt，单位 degree（度）。

TILT_X_MEAN_DEG, TILT_Y_MEAN_DEG:
  tilt 均值。

TILT_X_STD_DEG, TILT_Y_STD_DEG:
  tilt 标准差。
```

代码用 Gauss-Hermite quadrature（高斯-赫米特积分）对 tilt 分布做积分。

参数解释：

```text
ESD_ANALYTICAL_OUTER_QX:
  theta_x 方向的积分点数量。

ESD_ANALYTICAL_OUTER_QY:
  theta_y 方向的积分点数量。
```

### 6.6 固定 tilt 下，每个 pad 的 deterministic contact limit

在某一组固定的 `theta_x`、`theta_y` 下，代码先计算每个 pad 的 deterministic contact limit（确定性接触界限）：

```text
C_i = z_top + a * x_i + b * y_i - corner_drop
```

参数解释：

```text
C_i:
  pad i 的确定性接触界限。可以理解为不考虑随机 dishing 时，pad i 还有多少几何 gap margin。

z_top:
  top die 的初始 z 方向偏移，当前默认是 0。

a, b:
  由 theta_x / theta_y 转换来的倾斜平面系数。它们描述 x/y 位置变化会如何改变局部 gap。

x_i, y_i:
  pad i 的中心坐标。

corner_drop:
  pad 不是一个点，而是有尺寸。倾斜时最低角会比中心更早接触，corner_drop 用来扣掉这个角点效应。
```

更直观地说：

```text
如果 die 有 tilt，那么不同位置的 pad 到对面表面的距离不同。
某些边缘或角落 pad 会更早接近对面，成为 first-touch pad 的概率更高。
```

### 6.7 top/bottom dishing 的随机 gap

除了 tilt，pad 本身的 top/bottom dishing 也会改变局部 gap。代码把 top pad 和 bottom pad 的 dishing 合并成一个随机变量：

```text
H_i ~ Normal(mu_h, sigma_h)

mu_h    = (TOP_DISH_MEAN_nm + BOT_DISH_MEAN_nm) * 1e-3
sigma_h = sqrt(TOP_DISH_STD_nm^2 + BOT_DISH_STD_nm^2) * 1e-3
```

参数解释：

```text
H_i:
  pad i 的 top+bottom 合并 dishing 随机量，单位 um。

TOP_DISH_MEAN_nm, BOT_DISH_MEAN_nm:
  top/bottom pad dishing 均值，单位 nm。

TOP_DISH_STD_nm, BOT_DISH_STD_nm:
  top/bottom pad dishing 标准差，单位 nm。

1e-3:
  把 nm 转成 um。

mu_h:
  top+bottom 合并后的均值。

sigma_h:
  top+bottom 合并后的标准差。两个独立正态分布相加，所以方差相加。
```

### 6.8 first-touch probability：哪个 pad 最先放电

在固定 `V`、`theta_x`、`theta_y` 下，代码要计算：

```text
P_first(i | theta_x, theta_y, V)
```

含义是：

```text
在当前电压和倾斜条件下，pad i 成为 first-touch / first-discharge pad 的概率。
```

first-touch 的判断和两个量有关：

```text
C_i:
  tilt 决定的确定性 contact limit。

H_i:
  dishing 带来的随机 gap 变化。
```

同时，电压 `V` 给出 arcing distance：

```text
d_arc(V)
```

如果某个 pad 的实际 gap 已经小到 `d_arc(V)` 可以跨越，那么它就可能先发生 discharge（放电）。代码用 `_fixed_tilt_probability_map_with_arcing()` 做一维 gap 积分，得到所有候选 pad 的 first-touch 概率。

为了加速，代码会先选 candidate pads（候选 pad）：

```text
只评估 deterministic contact limit C_i 接近最小值的一批 pad
```

参数解释：

```text
ESD_ANALYTICAL_CANDIDATE_SIGMA_WINDOW:
  用 sigma_h 的倍数定义候选窗口。越大，候选 pad 越多，越准确但越慢。

ESD_ANALYTICAL_CANDIDATE_MIN_PADS:
  候选 pad 的最小数量，避免候选集合太小。

ESD_ANALYTICAL_CANDIDATE_DISABLE_FRACTION:
  如果候选 pad 占总 pad 比例太高，就关闭 pruning，直接评估全体 pad。

ESD_ANALYTICAL_INNER_Q:
  gap 积分的积分点数量。
```

最后会归一化：

```text
sum_i P_first(i | theta_x, theta_y, V) = 1
```

也就是在某一次固定条件下，总会有某个 pad 承担 first-touch / discharge risk。

### 6.9 ESD pad risk 和 yield

对一个固定电压和固定 tilt 条件，pad `i` 的风险贡献是：

```text
p_fail(V) * P_first(i | theta_x, theta_y, V)
```

参数解释：

```text
p_fail(V):
  如果发生 ESD event，该电压下 die 失效的概率。

P_first(i | theta_x, theta_y, V):
  pad i 在当前几何状态下成为 first-touch / discharge pad 的概率。
```

然后代码对 voltage（电压）和 tilt（倾斜）做期望积分：

```text
R_esd(i)
  = E_V,theta [
      p_fail(V) * P_first(i | theta_x, theta_y, V)
    ]
```

参数解释：

```text
R_esd(i):
  pad i 的 ESD failure probability，ESD 失效概率。

E_V,theta:
  对 charging voltage V 和 tilt theta_x/theta_y 做期望，也就是积分平均。
```

最终：

```text
Y_esd(i) = 1 - R_esd(i)
P_esd_fail(i) = 1 - Y_esd(i) = R_esd(i)
```

也就是说，ESD yield loss 本身就是 `R_esd(i)`。

## 7. 四种 loss 的合并关系

四种机制在当前 pad-level analytical map 中按独立项相乘：

```text
Y_bond(i)
  = Y_ovl(i)
    * Y_df(i)
    * Y_ce(i)
    * Y_esd(i)
```

所以 overall pad bonding loss 是：

```text
P_bond_fail(i)
  = 1 - Y_bond(i)
  = 1 - Y_ovl(i) * Y_df(i) * Y_ce(i) * Y_esd(i)
```

注意：`.map` 文本文件默认不直接写 `P_bond_fail`，而是写四个分机制 loss；overall risk 主要通过 PNG 输出。

## 8. 输出文件如何读

`risk_map_generator()` 输出文本 risk map：

```text
<x> <y> <esd_failure_probability> <overlay_failure_probability> <particle_failure_probability> <mechanical_failure_probability>
```

每一行对应一个 pad：

```text
x_i y_i P_esd_fail(i) P_overlay_fail(i) P_particle_fail(i) P_mechanical_fail(i)
```

同时会输出五类 PNG：

```text
<interface>_esd_risk_map...
<interface>_overlay_risk_map...
<interface>_particle_risk_map...
<interface>_mechanical_risk_map...
<interface>_overall_risk_map...
```

## 9. 一句话总结

pad risk 主线可以压缩成下面这条公式链：

```text
layout/config
  -> pad bitmap + pad coords
  -> Y_ovl(i), Y_df(i), Y_ce(i), Y_esd(i)
  -> loss_k(i) = 1 - Y_k(i)
  -> Y_bond(i) = product_k Y_k(i)
  -> overall_loss(i) = 1 - Y_bond(i)
```

其中四种 yield loss 的物理含义分别是：

```text
overlay:    pad 对准后是否仍满足接触面积和 critical distance
particle:   该 pad 是否被 fatal void / particle critical area 击中
mechanical: Cu dishing / expansion / debond 窗口是否满足
ESD:        该 pad 是否成为 first-touch discharge pad 且触发 ESD failure
```
