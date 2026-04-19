"""
GPIO 按键输入原型 — 阶段二技术验证 #3
========================================
验证目标（来自开发计划 §3.3）：
  1. 两颗按键均稳定响应，无误触发
  2. 长按（≥ 1000ms）与短按（< 1000ms）可正确区分
  3. 软件去抖有效（50ms 消抖延迟）

硬件接线（来自参考硬件调试书）：
  按键1（确认/拍照）: GPIO17 (BCM) → Pin 11 — 按键 — GND
  按键2（返回/长按）: GPIO18 (BCM) → Pin 12 — 按键 — GND  ← 暂定，确认后修改
  逻辑：内部上拉（PUD_UP），未按下 = 高电平，按下 = 低电平

关键注意事项（来自硬件调试书）：
  - BCM 编号 17 对应物理 Pin 11，不要混用 BOARD 编号
  - 接线必须是 GPIO → 按键 → GND，不要接 3.3V
  - 建议加软件防抖，避免重复触发

运行方式（树莓派终端）：
  python3 button_proto.py

  运行后按按键，终端输出事件。
  按 Ctrl+C 退出并显示统计报告。

依赖安装：
  sudo apt install -y python3-rpi.gpio
"""

import sys
import time

# ── 常量配置（修改此处即可适配不同接线）───────────────────────────────────────
BTN1_PIN        = 17       # GPIO17 — 确认键 / 拍照键
BTN2_PIN        = 18       # GPIO18 — 返回键（暂定，确认实物后修改）

LONG_PRESS_MS   = 1000     # 长按阈值（毫秒）
DEBOUNCE_MS     = 50       # 去抖延迟（毫秒）
POLL_INTERVAL   = 0.01     # 轮询间隔（秒），10ms

# ── 按键状态机 ────────────────────────────────────────────────────────────────
class ButtonState:
    """单颗按键的状态跟踪器（轮询模式）。"""

    def __init__(self, pin: int, name: str):
        self.pin        = pin
        self.name       = name
        self._pressed   = False     # 当前是否处于按下状态
        self._press_ts  = 0.0       # 按下时刻（monotonic）

    def update(self, gpio_module) -> str | None:
        """
        轮询当前电平，返回事件字符串或 None。
        返回值: "SHORT_PRESS" | "LONG_PRESS" | None
        """
        # GPIO.LOW（0）= 按键按下（接 GND）
        level = gpio_module.input(self.pin)

        if not self._pressed and level == gpio_module.LOW:
            # 检测到下降沿：等待去抖延迟后再确认
            time.sleep(DEBOUNCE_MS / 1000.0)
            if gpio_module.input(self.pin) == gpio_module.LOW:
                # 去抖后仍然是低电平，确认为有效按下
                self._pressed  = True
                self._press_ts = time.monotonic()

        elif self._pressed and level == gpio_module.HIGH:
            # 检测到上升沿：按键松开
            duration_ms = (time.monotonic() - self._press_ts) * 1000
            self._pressed = False

            if duration_ms >= LONG_PRESS_MS:
                return "LONG_PRESS"
            else:
                return "SHORT_PRESS"

        return None


# ── 统计器 ────────────────────────────────────────────────────────────────────
class Stats:
    def __init__(self):
        self.events = {
            "BTN1_SHORT": 0,
            "BTN1_LONG":  0,
            "BTN2_SHORT": 0,
            "BTN2_LONG":  0,
        }

    def record(self, btn_name: str, event: str):
        key = f"{btn_name}_{event.replace('_PRESS', '')}"
        if key in self.events:
            self.events[key] += 1

    def total(self):
        return sum(self.events.values())

    def report(self):
        print("\n" + "=" * 50)
        print("【按键输入原型 — 验证报告】")
        print(f"  BTN1（GPIO{BTN1_PIN}）短按次数: {self.events['BTN1_SHORT']}")
        print(f"  BTN1（GPIO{BTN1_PIN}）长按次数: {self.events['BTN1_LONG']}")
        print(f"  BTN2（GPIO{BTN2_PIN}）短按次数: {self.events['BTN2_SHORT']}")
        print(f"  BTN2（GPIO{BTN2_PIN}）长按次数: {self.events['BTN2_LONG']}")
        print(f"  总事件数  : {self.total()}")
        print()
        btns_both = (
            self.events["BTN1_SHORT"] + self.events["BTN1_LONG"] > 0 and
            self.events["BTN2_SHORT"] + self.events["BTN2_LONG"] > 0
        )
        long_detected = (
            self.events["BTN1_LONG"] > 0 or self.events["BTN2_LONG"] > 0
        )
        print(f"  双键均有响应: {'✓' if btns_both else '✗ 其中一颗未触发（请检查接线）'}")
        print(f"  长按已验证  : {'✓' if long_detected else '- 未进行长按测试'}")
        print()
        if self.total() > 0:
            print("  结果: ✓ 按键输入链路验证通过")
        else:
            print("  结果: ✗ 未检测到任何按键事件（请检查硬件接线和 GPIO 引脚编号）")
        print("=" * 50)


# ── 主流程 ───────────────────────────────────────────────────────────────────
def run():
    # 导入 RPi.GPIO
    try:
        import RPi.GPIO as GPIO
    except ImportError:
        print("[ERROR] RPi.GPIO 未找到。")
        print("  请执行: sudo apt install -y python3-rpi.gpio")
        print("  此脚本只能在树莓派上运行。")
        sys.exit(1)
    except RuntimeError as e:
        print(f"[ERROR] GPIO 初始化失败: {e}")
        print("  请确认在树莓派上以正确权限运行。")
        sys.exit(1)

    # 初始化 GPIO
    GPIO.setmode(GPIO.BCM)          # 使用 BCM 引脚编号（非物理引脚编号）
    GPIO.setwarnings(False)

    # 按键均使用内部上拉：未按下 = 高电平，按下接 GND = 低电平
    GPIO.setup(BTN1_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    GPIO.setup(BTN2_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)

    print("=" * 50)
    print("【GPIO 按键输入原型 — 开始验证】")
    print(f"  BTN1: GPIO{BTN1_PIN} (Pin 11) — 确认/拍照键")
    print(f"  BTN2: GPIO{BTN2_PIN} (Pin 12) — 返回键（暂定）")
    print(f"  长按阈值: {LONG_PRESS_MS} ms")
    print(f"  去抖延迟: {DEBOUNCE_MS} ms")
    print()
    print("  请按按键进行测试，Ctrl+C 退出并查看报告。")
    print("=" * 50)

    btn1  = ButtonState(BTN1_PIN, "BTN1")
    btn2  = ButtonState(BTN2_PIN, "BTN2")
    stats = Stats()

    try:
        while True:
            for btn in (btn1, btn2):
                event = btn.update(GPIO)
                if event:
                    duration_display = "长按" if "LONG" in event else "短按"
                    print(f"  [{btn.name}] {duration_display}  ({event})")
                    stats.record(btn.name, event)

            time.sleep(POLL_INTERVAL)

    except KeyboardInterrupt:
        print("\n[INFO] 用户中断。")
    finally:
        GPIO.cleanup()

    stats.report()


# ── 入口 ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    run()
