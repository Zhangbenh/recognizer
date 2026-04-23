# Plant Recognizer

便携式植物识别与区域采样系统，基于单线程事件驱动状态机，默认中文显示，支持云端优先识别与本地回退。

## 1. 功能概览

- 普通模式：`HOME -> PREVIEW -> CAPTURED -> INFERENCING -> DISPLAY -> PREVIEW`，在 `INFERENCING` 内执行云端优先识别与本地回退
- 采样模式：`HOME -> MAP_SELECT -> REGION_SELECT -> PREVIEW -> CAPTURED -> INFERENCING -> DISPLAY -> RECORDING -> PREVIEW`
- 地图统计：`MAP_SELECT -> MAP_STATS -> MAP_SELECT`
- 错误处理：启动期致命错误进入 `ERROR`，运行期非致命错误提示后回安全状态
- 数据持久化：本地 JSON（`data/sampling_records.json`，按 region 分区存储，可做地图级聚合）
- 屏幕后端：地图页和区域页可升级为图片化选择页，文本后端继续保留用于测试与回归

## 2. 目录结构

```text
app/        应用主代码
config/     配置文件（labels/model_manifest/sampling/system/cloud/mapping）
models/     模型文件
data/       运行时数据（sampling_records.json）
assets/     字体与地图/区域图片资源
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
- 验收脚本扩展参数 `--scenario`: `all` / `cloud_success` / `cloud_fallback` / `local_only`

说明：

- v1.1 口径下默认识别策略为云端优先；云端不可用或请求失败时应自动回退本地模型
- 云端凭据与映射配置见 `config/cloud_config.json` 与 `config/baidu_plant_mapping.json`
- Phase 4 / Phase 5 验收推荐使用 `--scenario all` 输出分链路 `scenario_results`
- `--scenario` 仅用于确定性链路验收与排障，不替代真实百度云连通性手测

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
.venv\Scripts\python.exe scripts/phase4_real_runtime_acceptance.py --runtime mock --input keyboard --scenario all --samples 20 --warmup 3 --sleep-s 0.01 --output reports/phase4_real_runtime_report.mock.json
```

树莓派实机请改为 `--runtime real`。

补充说明：

- 报告顶层 `pass` 会汇总三条链路，分链路详情在 `scenario_results`
- 如需单独排查链路，可改为 `--scenario cloud_success`、`--scenario cloud_fallback` 或 `--scenario local_only`

### 5.3 Phase 5（采样流程）

```powershell
.venv\Scripts\python.exe scripts/phase5_sampling_mode_acceptance.py --runtime mock --input keyboard --scenario all --cycles 10 --output reports/phase5_sampling_mode_report.mock.json
```

补充说明：

- 自动化报告聚焦状态流、录制计数和统计页数据；screen 后端图片页与真实云端连通性仍需手测补充
- 建议在交付前再运行一次 `bash scripts/run_real_pi.sh` 或等价 real 模式命令做屏幕联调

### 5.4 Phase 6 一键检查

```powershell
powershell -ExecutionPolicy Bypass -File scripts/phase6_release_check.ps1
```

### 5.5 Phase 7 实机签收

```bash
bash scripts/phase7_real_signoff_pi.sh
```

补充说明：

- 执行前请先阅读 `docs/phase7_实机签收清单.txt`
- 确定性三链路签收通过后，仍应补一轮真实网络 + screen 后端手测

## 6. Phase 6 交付文件

- 部署指南：`docs/部署指南.txt`
- 升级说明：`docs/v1.1_升级说明.txt`
- 已知问题：`docs/已知问题清单.txt`
- 实机签收清单：`docs/phase7_实机签收清单.txt`
- 运行脚本：`scripts/run_mock.ps1`、`scripts/run_real_pi.sh`
- 收口检查：`scripts/phase6_release_check.ps1`

## 7. 参考文档

- `docs/架构设计_v2.1.txt`
- `docs/状态机设计_v2.0.txt`
- `docs/代码结构设计文档_v1.3.1.txt`
- `docs/用户故事及验收标准_v3.txt`
- `docs/v1.1_补丁开发文档.txt`
- `docs/v1.1_升级说明.txt`
