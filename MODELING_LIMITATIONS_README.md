# 建模局限性说明

本文档总结当前良率预测与仿真方法中的几个主要局限。当前 D2W 流程更适合作为一种基于失效机制的良率比较和敏感性分析框架，用于比较不同布局、工艺窗口和 pessimistic case 是有价值的。但在解释绝对良率预测结果时，需要注意以下建模假设。

## 1. 失效机制之间采用独立相乘假设

在 `D2W/assembly_yield_calculator.py` 中，pad 级 bonding yield 当前按如下方式计算：

```python
Y_bond = Y_ovl * Y_df * Y_ce * Y_esd
```

这等价于假设 overlay、particle/void defect、Cu expansion 或 mechanical failure、ESD failure 之间统计独立。但在真实 hybrid bonding 工艺中，多个失效机制往往会被同一组物理变量共同影响，因此并不完全独立。

例如：

- dishing、warpage 和 tilt 会同时影响 Cu gap closure、first-contact location、ESD risk 和局部 peeling stress。
- particle-induced void 会改变局部接触状态，也可能改变局部机械应力。
- wafer、die 或 tool 的系统性 signature 可能让多个失效机制在同一空间区域同时变差。

因此，独立相乘假设可能会让 analytical pad risk map 看起来比较稳定，但低估耦合失效、tail risk 以及极端工艺窗口下的良率风险。

## 2. Overlay 随机误差被简化为一维径向扰动

在 `D2W/overlay_yield_simulator.py` 中，系统性 overlay displacement 首先按如下方式计算：

```python
dx = Tx - theta * y + M * x
dy = Ty + theta * x + M * y
```

这部分用于描述确定性的 translation、rotation 和 magnification。当前仿真器随后先把这个二维向量转成一个标量距离，再叠加一维随机项：

```python
pad_misalignment = sqrt(dx**2 + dy**2) + random_normal
```

这是一种简化的径向噪声模型。更符合物理直觉的做法是把随机 overlay 也看成二维向量误差，先分别加到 `dx` 和 `dy` 上，再计算最终距离：

```python
dx_total = dx + eps_x
dy_total = dy + eps_y
pad_misalignment = sqrt(dx_total**2 + dy_total**2)
```

当前的一维标量扰动可能产生非物理的负 misalignment，也可能以不符合真实二维 placement error 的方式人为减小径向距离。

## 3. Cu Gap 和 Mechanical Variation 被建模为独立同分布 Pad 样本

在 `D2W/Cu_gap_simulator.py` 中，top 和 bottom dishing 当前是对每个 pad 独立地从 normal distribution 中采样：

```python
top_dish = normal(TOP_DISH_MEAN_nm, TOP_DISH_STD_nm, num_pads)
bot_dish = normal(BOT_DISH_MEAN_nm, BOT_DISH_STD_nm, num_pads)
```

这是一个有用的一阶近似，但真实 CMP 和 Cu recess 行为通常具有明显的空间结构，例如：

- pattern-density effect
- local neighborhood correlation
- die-scale gradient
- wafer-level signature
- tool signature
- lot-to-lot offset

这些空间结构会导致 mechanical failure 成片或成簇出现，而不是像独立随机噪声一样零散分布。仓库中已经包含 spatial-correlation 相关工具，但主仿真流程目前还没有把 Cu dishing 生成为一个具有空间相关性的 surface 或 random field。

因此，当前模型可能能较好估计平均 single-pad mechanical risk，但可能低估 clustered mechanical failure 以及 die-to-die、wafer-to-wafer 的良率方差。

## 4. 圆形 Pad 重叠面积是理想化几何判据

当前 overlay contact-area limit 基于两个理想圆形 pad 的重叠面积计算。模型会计算 top pad 和 bottom pad 两个圆之间的 lens-shaped overlap area，并将其与 top pad 面积的一定比例进行比较。

这是一个简洁、可解析的 pad-to-pad contact 近似，但它简化了多个真实物理细节：

- 实际 pad 形状可能不是完美圆形。
- CMP 后的表面并非理想平面。
- oxide deformation 和 surface roughness 会影响真实接触状态。
- electrical pass 和 mechanical pass 不一定只由二维投影重叠面积决定。
- contact resistance 和局部 stress 可能需要更详细的模型或工艺数据校准。

因此，当前圆形重叠面积判据更适合作为 compact design-rule-level approximation。若要进行更严格的绝对良率预测，需要使用 process data 对该判据进行校准，或进一步引入更详细的 contact、resistance、stress 模型。
