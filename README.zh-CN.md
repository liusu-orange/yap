# YAP+

YAP+ 是一个基于 Python 的先进封装良率建模与仿真工具，支持对任意 I/O pad 布局进行良率分析。当前模型主要面向 wafer-to-wafer（W2W）和 die-to-wafer（D2W）混合键合。

项目也提供了 [YAP GUI](http://nanocad.ee.ucla.edu:8081/yap_gui/) 和 [用户指南视频](https://youtu.be/8hiKIQ6C7ng)。

## 本地运行状态

我在当前工作区验证过：

- Python 版本：`Python 3.12.6`
- `requirements.txt` 里的依赖可以安装成功。
- 运行入口可启动，但当前拷贝缺少必要的 `.bmap` 输入文件。例如 HBM_A 的最小命令会停在：

```text
FileNotFoundError: Bump map not found at input/HBM_A/Center_IO\HBM_footprint_A.bmap
```

原因是仓库的 `.gitignore` 明确忽略了 `*.bmap`、`*.3dbv`、`*.3dbx`、`*.3dbf` 等大输入文件。要完整跑通，需要从论文源码包、作者发布包或原始数据交付中补齐这些输入。

当前这份工作区可见的 D2W 设计族是：

- `HBM_A`
- `HBM_B`

英文 README 中还提到 `design_1_p5` 和 `design_2_p10`，但当前目录下没有对应的 `D2W/configs/design_1_p5`、`D2W/configs/design_2_p10`、`D2W/input/design_1_p5`、`D2W/input/design_2_p10`。

## 文件结构

```text
.
├── D2W/                  # D2W 混合键合代码
│   ├── configs/          # Golden 配置与各设计配置
│   │   ├── GOLDEN.yaml
│   │   ├── HBM_A/
│   │   ├── HBM_B/
│   │   └── old_configs/
│   ├── input/            # 各设计输入、bump map 与 criticality 文件
│   │   ├── HBM_A/
│   │   │   ├── Original/
│   │   │   ├── Center_IO/
│   │   │   ├── Edge_IO/
│   │   │   └── Random_IO/
│   │   ├── HBM_B/
│   │   └── old_bmap/
│   ├── output/           # 输出目录；部分旧输出随当前拷贝保留
│   ├── utils/            # bump map / criticality 处理辅助脚本
│   ├── pad_risk_map_calculator.py
│   └── simulator_main.py
├── LICENSE
├── README.md
├── README.zh-CN.md
├── requirements.txt      # Python 依赖
└── yap-doc.md
```

## 安装

1. 进入项目目录：

```powershell
cd E:\YAP-yap-IO_assign\YAP-yap-IO_assign
```

2. 可选：创建并激活虚拟环境。

```powershell
python -m venv yap_env
.\yap_env\Scripts\Activate.ps1
```

如果使用 conda：

```bash
conda create -n yap_env python=3.12
conda activate yap_env
```

3. 安装依赖：

```powershell
python -m pip install -r requirements.txt
```

依赖包括 `matplotlib`、`numpy`、`omegaconf`、`opencv-python`、`scipy`、`sympy`、`scikit-learn`。

## 怎么跑起来

所有主要运行命令都在 `D2W` 目录下执行：

```powershell
cd E:\YAP-yap-IO_assign\YAP-yap-IO_assign\D2W
```

### 1. 准备输入文件

每个设计变体目录需要至少包含：

- `<INTERFACE>.bmap`
- `<INTERFACE>_criticality.txt`
- 可选：`<INTERFACE>_criticality_esd_strict.txt`

以 `HBM_A/Center_IO` 为例，配置文件里 `INTERFACE` 是 `HBM_footprint_A`，因此需要：

```text
D2W/input/HBM_A/Center_IO/HBM_footprint_A.bmap
D2W/input/HBM_A/Center_IO/HBM_footprint_A_criticality.txt
D2W/input/HBM_A/Center_IO/HBM_footprint_A_criticality_esd_strict.txt
```

当前工作区已经有 criticality 文件，但缺 `.bmap`。补齐后即可运行下面的命令。

### 2. 生成 criticality 文件

如果已经有 `.bmap`，可以从 bump map 自动生成 criticality 文件：

```powershell
python utils/generate_criticality.py --force
```

也可以对指定文件生成默认与 strict ESD 两套 profile：

```powershell
python utils/generate_criticality.py --file input/HBM_A/Center_IO/HBM_footprint_A.bmap --profiles both --force
```

支持的 profile：

- `default`：冗余复制 net 可容忍 `R-1` 次 ESD 失败和 `R-1` 次机械失败。
- `esd_strict`：冗余复制 net 可容忍 `0` 次 ESD 失败和 `R-1` 次机械失败。

### 3. 计算 pad 级风险图

HBM_A 的单个变体示例：

```powershell
python pad_risk_map_calculator.py
  --config configs/HBM_A/HBM_A.yaml
  --mode d2w_modeling
  --ds_name HBM_A/Center_IO
  --ds_dir input/HBM_A/Center_IO
  --verbose
```

使用 pessimistic 配置：

```powershell
python pad_risk_map_calculator.py `
  --config configs/HBM_A/HBM_A_overlay_pessimistic.yaml `
  --mode d2w_modeling `
  --ds_name HBM_A/Center_IO `
  --ds_dir input/HBM_A/Center_IO `
  --verbose
```

使用 strict ESD criticality：

```powershell
python pad_risk_map_calculator.py `
  --config configs/HBM_A/HBM_A.yaml `
  --mode d2w_modeling `
  --ds_name HBM_A/Center_IO `
  --ds_dir input/HBM_A/Center_IO `
  --criticality-profile esd_strict `
  --verbose
```

### 4. 运行 D2W 良率仿真

HBM_A 的单个变体示例：

```powershell
python simulator_main.py 
  --config configs/HBM_A/HBM_A.yaml 
  --mode d2w_simulation 
  --ds_name HBM_A/Original 
  --ds_dir input/HBM_A/Original 
  --criticality-profile default 
  --verbose
```

保存失败热力图与 NPZ 输出：

```powershell
python simulator_main.py 
  --config configs/HBM_A/HBM_A.yaml 
  --mode d2w_simulation 
  --ds_name HBM_A/Center_IO 
  --ds_dir input/HBM_A/Center_IO 
  --criticality-profile default 
  --save-failure-maps 
  --verbose
```

### 5. 批量脚本

仓库提供了 Bash 脚本批量跑多个设计或多个变体。Windows PowerShell 不能直接执行 `.sh`，需要 Git Bash、WSL 或其他 Bash 环境。

生成多个设计的 pad risk map：

```bash
cd D2W
./run_design_pad_risk_maps.sh HBM_A HBM_B
```

运行多个设计的仿真：

```bash
cd D2W
./run_design_simulations.sh HBM_A HBM_B
```

并行生成 risk map：

```bash
cd D2W
./run_all_pad_risk_maps_parallel.sh --jobs 16 HBM_A HBM_B
./run_all_pad_risk_maps_parallel.sh --jobs 16 --skip-existing HBM_A HBM_B
```

并行运行仿真实验：

```bash
cd D2W
./run_design_1_p5_design_2_p10_hbm_parallel.sh --jobs 16
./run_design_1_p5_design_2_p10_hbm_parallel.sh --jobs 16 --skip-existing
./run_design_1_p5_design_2_p10_hbm_parallel.sh --dry-run --jobs 4
```

注意：最后这个并行脚本默认会包含 `design_1_p5`、`design_2_p10`、`HBM_A`、`HBM_B`。当前工作区没有 `design_1_p5/design_2_p10`，所以如果没有补齐这两个设计的数据，建议先只跑 HBM 相关脚本或单条 Python 命令。

## 代码入口怎么读

### `D2W/pad_risk_map_calculator.py`

用于分析建模，输出每个 pad 的失效风险图。核心流程：

1. 读取命令行参数。
2. 读取 YAML 配置。
3. 根据 `ds_dir` 找 `.bmap` 和 criticality 文件。
4. 把 3dblox/bump map 转成内部 pad bitmap。
5. 调用 `Pad_Yield_Map_Generator` 计算 ESD、overlay、particle、mechanical 等机制的 pad 风险。
6. 写出 `.map` 文本和 PNG 风险图。

### `D2W/simulator_main.py`

用于 Monte Carlo 风格的装配良率仿真。核心流程：

1. 读取配置和设计输入。
2. 生成或复用 pad bitmap。
3. 调用 `Assembly_Yield_Simulator` 对多个 die stack 做仿真。
4. 输出整体 assembly yield、各 interface yield、summary 文本，必要时输出 failure map。

### `D2W/utils/generate_criticality.py`

从 `.bmap` 生成 net criticality 文件。它支持两种 profile：

- `default`
- `esd_strict`

### `D2W/utils/package_hbm_designs.py`

把 HBM_A / HBM_B 打包成轻量 single-interface 设计变体。它会生成：

- `Original`
- `Center_IO`
- `Edge_IO`
- `Random_IO`

但它要求源文件存在，例如：

```text
D2W/input/HBM_A/HBM_footprint_A.bmap
D2W/input/HBM_B/HBM_footprint_B.bmap
```

当前工作区缺这些源 `.bmap`，所以该脚本也不能完整执行。

## 文件格式

### 1. Bump Map（`.bmap`）

格式：

```text
<instance> <bump_type> <x> <y> <port> <net>
```

示例：

```text
Bump_0 uBUMP 115 1610 txdatasb txdatasb
```

### 2. Risk Map（`.map`）

格式：

```text
<x> <y> <esd_failure_probability> <overlay_failure_probability> <particle_failure_probability> <mechanical_failure_probability>
```

示例：

```text
115 1610 0.15 0.05 0.03 0.20
```

概率值是 0 到 1 之间的浮点数。

说明：

- ESD criticality 会乘以 `esd_failure_probability`。
- Mechanical criticality 会乘以 `overlay_failure_probability`、`particle_failure_probability` 和 `mechanical_failure_probability`。
- 优化目标会同时考虑四类失效机制。

### 3. Criticality（`.txt`）

当前格式：

```text
<net1> [net2] [net3] ... <group_size> <tolerated_esd_failures> <tolerated_mechanical_failures>
```

字段含义：

- `group_size`：冗余组中 pad/bump 的总数。
- `tolerated_esd_failures`：该组失效前可容忍的 ESD 失败数量。
- `tolerated_mechanical_failures`：该组失效前可容忍的机械失败数量。

支持两类文件名：

- `*_criticality.txt`
  - 默认 profile。
  - 冗余复制 signal net 可容忍 `R-1` 次 ESD 失败和 `R-1` 次机械失败。
- `*_criticality_esd_strict.txt`
  - strict ESD profile。
  - 冗余复制 signal net 可容忍 `0` 次 ESD 失败和 `R-1` 次机械失败。
  - PG 和 dummy net 相对默认文件保持不变。

读取文件时会计算 criticality：

```text
esd_criticality = (group_size - tolerated_esd_failures) / group_size
mechanical_criticality = (group_size - tolerated_mechanical_failures) / group_size
```

示例：

```text
vccfwdio 5 4 4
```

表示单个 net 有 5 个 pad，可容忍 4 次 ESD 失败和 4 次机械失败，因此 ESD criticality 和 mechanical criticality 都是 0.2。

```text
rxckRD rxckn rxckp rxtrk 4 1 1
```

表示一个 4 pad 冗余组，可容忍 1 次 ESD 失败和 1 次机械失败，因此两个 criticality 都是 0.75。

旧格式仍兼容但已不推荐：

```text
<net> <esd_criticality> <mechanical_criticality>
```

示例：

```text
txdatasb 0.8 0.7
```

### 4. 3dbv 文件（`.3dbv`）

3dblox 格式输入文件，包含 die 尺寸和 `.3dbf` 文件路径等信息。

### 5. 3dbf 文件（`.3dbf`）

3dblox 格式输入文件，包含 bump pitch、bump size 等信息。

## 输出

### 1. `<interface>_risk__<config_stem>__<criticality_profile>.map`

文本格式的 interface 风险图。每一行对应一个 pad，包含 pad 的 x/y 坐标，以及不同失效机制下的失效概率。

后缀 `__<config_stem>__<criticality_profile>` 用于区分 baseline 和各种 pessimistic case。

### 1a. `<interface>_<mechanism>_risk_map__<config_stem>__<criticality_profile>.png`

`pad_risk_map_calculator.py` 默认会写出各失效机制的 pad risk map PNG。

`--plot` 只控制建模期间额外弹出的交互式图。

### 2. `assembly_yield_summary__<config_stem>__<criticality_profile>.txt`

仿真摘要文本，包含：

- 仿真设置
- 运行时间
- 总体 assembly yield
- 各 interface yield

### 3. `assembly_yield_per_interface__<config_stem>__<criticality_profile>.txt`

各 interface 的仿真 assembly yield。每行包含 interface 名称和对应 yield。

### 4. `assembly_fail_map_per_interface_dict__<config_stem>__<criticality_profile>.npz`

每个 pad 在所有仿真样本中的平均失败次数，按 interface 和失效机制保存。

只有同时启用 `--verbose` 和 `--save-failure-maps` 时才会写出。

### 5. `assembly_fail_vec_per_interface_dict__<config_stem>__<criticality_profile>.npz`

各 die sample 在不同失效机制下的失败向量。verbose 模式下会写出，即使没有启用 failure-map PNG/NPZ 保存。

示例：仿真 die A、B、C、D、E，其中 A、B、D 通过，C、E 失败，则该机制的失败向量是：

```text
0, 0, 1, 0, 1
```

### 6. `simulation_failure_map_<mechanism>__<config_stem>__<criticality_profile>.png`

各 interface 的仿真失败热力图，机制包括：

- `overlay`
- `particle`
- `mechanical`
- `ESD`
- `overall`

这些 PNG 只有在 `simulator_main.py` 启用 `--save-failure-maps` 时才会写出。

## Generator 工具

项目提供了几个用于快速生成测试起始文件的辅助脚本：

- `assign_bump_names.py`：给原始 bump map 分配 net name 和 port name。
- `generate_criticality.py`：从 bump map 生成 criticality 文件。

## 论文链接

待补充。
