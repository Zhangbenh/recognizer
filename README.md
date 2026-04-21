# Plant Recognizer

便携式离线植物识别器，基于单线程事件驱动状态机，支持普通模式与采样模式。

## 1. 功能概览

- 普通模式：`HOME -> PREVIEW -> CAPTURED -> INFERENCING -> DISPLAY -> PREVIEW`
- 采样模式：`HOME -> MAP_SELECT -> REGION_SELECT -> PREVIEW -> CAPTURED -> INFERENCING -> DISPLAY -> RECORDING -> PREVIEW`
- 错误处理：启动期致命错误进入 `ERROR`，运行期非致命错误提示后回安全状态
- 数据持久化：本地 JSON（按 region 聚合统计）

## 2. 目录结构

```text
app/        应用主代码
config/     配置文件（labels/model_manifest/sampling/system）
models/     模型文件
data/       运行时数据（sampling_records.json）
docs/       设计文档与验收文档
scripts/    验收脚本与运行脚本
tests/      自动化测试
```

## 3. 快速启动

### 3.1 Windows 开发机（推荐 mock）

```powershell
.venv\Scripts\python.exe app\main.py --runtime mock --input keyboard --log-level INFO
```

### 3.2 树莓派实机（real）

```bash
SDL_VIDEODRIVER=kmsdrm python3 app/main.py --runtime real --input gpio --ui-backend screen --log-level INFO
```

或者：

```bash
bash scripts/run_real_pi.sh
```

### 3.3 常用参数

- `--runtime`: `real` / `mock`
- `--input`: `keyboard` / `gpio`
- `--ui-backend`: `text` / `screen` / `both`
- `--max-ticks`: 测试用最大 tick 数
- `--idle-sleep`: 空闲 sleep 秒数
- `--log-level`: `DEBUG/INFO/WARNING/ERROR`

### 3.4 树莓派屏幕渲染依赖

```bash
sudo apt update
sudo apt install -y python3-picamera2 python3-pygame
```

说明：

- 当前 HDMI 小屏验证推荐 `SDL_VIDEODRIVER=kmsdrm`
- 若无屏幕只保留日志输出，可使用 `--ui-backend text`

## 4. 输入映射

### keyboard（开发调试）

- `c`: BTN1_SHORT
- `C`: BTN1_LONG
- `v`: BTN2_SHORT
- `V`: BTN2_LONG

### gpio（树莓派）

- BTN1: GPIO17
- BTN2: GPIO18

## 5. 验收与回归

### 5.1 全量测试

```powershell
.venv\Scripts\python.exe -m pytest -q
```

### 5.2 Phase 4（性能门槛）

```powershell
.venv\Scripts\python.exe scripts/phase4_real_runtime_acceptance.py --runtime mock --input keyboard --samples 20 --warmup 3 --sleep-s 0.01 --output reports/phase4_real_runtime_report.mock.json
```

树莓派实机请改为 `--runtime real`。

### 5.3 Phase 5（采样流程）

```powershell
.venv\Scripts\python.exe scripts/phase5_sampling_mode_acceptance.py --runtime mock --input keyboard --cycles 10 --output reports/phase5_sampling_mode_report.mock.json
```

### 5.4 Phase 6 一键检查

```powershell
powershell -ExecutionPolicy Bypass -File scripts/phase6_release_check.ps1
```

## 6. Phase 6 交付文件

- 部署指南：`docs/部署指南.txt`
- 已知问题：`docs/已知问题清单.txt`
- 运行脚本：`scripts/run_mock.ps1`、`scripts/run_real_pi.sh`
- 收口检查：`scripts/phase6_release_check.ps1`

## 7. 参考文档

- `docs/架构设计_v2.1.txt`
- `docs/状态机设计_v2.0.txt`
- `docs/代码结构设计文档_v1.3.1.txt`
- `docs/用户故事及验收标准_v3.txt`
