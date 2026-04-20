"""
相机预览原型 — 阶段二技术验证 #1
====================================
验证目标（来自开发计划 §3.1 / 验收标准 US-1.1.1）：
  1. 能正常通过 Picamera2 采集帧
  2. 能通过 Pygame 在 480×320 HDMI 屏上显示（无桌面 framebuffer 模式）
  3. 帧率 ≥ 15 FPS（循环计数，终端打印实时 FPS）
  4. 画面中央可叠加十字准星 UI 元素

运行方式（树莓派终端）：
  # 无桌面环境强制使用 framebuffer
  SDL_VIDEODRIVER=fbcon SDL_FBDEV=/dev/fb0 python3 camera_proto.py

  # 若 fbcon 不可用（SSH 环境调试），改用 offscreen 模式（不显示，但验证采集链路）
  SDL_VIDEODRIVER=offscreen python3 camera_proto.py

硬件说明（来自参考硬件调试书）：
  - 摄像头：Camera Module 3（IMX708, CSI）
  - 屏幕：Waveshare 3.5inch HDMI LCD，分辨率 480×320
  - CSI 摄像头严禁热拔插，必须断电后插拔排线
  - 当前系统使用 rpicam-* 命令集（Picamera2 底层调用 libcamera，兼容）

依赖安装：
    推荐在树莓派系统中使用系统包，而不是直接在 venv 中 pip 安装：
        sudo apt update
        sudo apt install -y python3-picamera2 python3-pygame

    若必须在虚拟环境中通过 pip 安装，至少先补齐原生编译依赖：
        sudo apt install -y libcap-dev
        pip install pygame picamera2

    注意：若 picamera2 通过 apt 安装，而当前项目使用 venv，创建 venv 时需带上
    --system-site-packages，或直接使用系统 python3 运行本原型。
"""

import time
import sys

# ── 常量配置 ─────────────────────────────────────────────────────────────────
CAMERA_WIDTH  = 480
CAMERA_HEIGHT = 320
TARGET_FPS    = 15          # 验收目标
RUN_SECONDS   = 30          # 原型运行时长，超时后自动退出并报告

# 准星参数
CROSSHAIR_COLOR  = (0, 255, 0)   # 绿色
CROSSHAIR_SIZE   = 20            # 半径（像素）
CROSSHAIR_THICK  = 2             # 线宽

# FPS 统计刷新间隔（秒）
FPS_REPORT_INTERVAL = 2.0


def fit_surface_to_screen(pygame, surface, screen):
    screen_width, screen_height = screen.get_size()
    surface_width, surface_height = surface.get_size()

    scale = min(screen_width / surface_width, screen_height / surface_height)
    scaled_size = (
        max(1, int(surface_width * scale)),
        max(1, int(surface_height * scale)),
    )

    scaled_surface = pygame.transform.smoothscale(surface, scaled_size)
    offset_x = (screen_width - scaled_size[0]) // 2
    offset_y = (screen_height - scaled_size[1]) // 2
    return scaled_surface, offset_x, offset_y

# ── 主流程 ───────────────────────────────────────────────────────────────────
def run():
    # 1. 初始化 Pygame
    import os
    import pygame

    # 若未被外部环境变量覆盖，提示用户需要设置 SDL_VIDEODRIVER
    if "SDL_VIDEODRIVER" not in os.environ:
        print("[WARNING] SDL_VIDEODRIVER 未设置。")
        print("  在树莓派无桌面环境下，请使用：")
        print("    SDL_VIDEODRIVER=fbcon SDL_FBDEV=/dev/fb0 python3 camera_proto.py")
        print("  SSH 调试时使用（不显示画面）：")
        print("    SDL_VIDEODRIVER=offscreen python3 camera_proto.py")
        print("  当前继续尝试默认初始化...\n")

    pygame.init()
    try:
        display_info = pygame.display.Info()
        screen_width = display_info.current_w or CAMERA_WIDTH
        screen_height = display_info.current_h or CAMERA_HEIGHT

        screen = pygame.display.set_mode(
            (screen_width, screen_height),
            pygame.NOFRAME  # 无边框，适合嵌入式全屏显示
        )
    except pygame.error as e:
        print(f"[ERROR] Pygame 显示初始化失败: {e}")
        print("  请检查 SDL_VIDEODRIVER 环境变量设置。")
        sys.exit(1)

    pygame.display.set_caption("Camera Preview Prototype")
    clock = pygame.time.Clock()

    # 2. 初始化 Picamera2
    try:
        from picamera2 import Picamera2
    except ImportError:
        print("[ERROR] picamera2 未安装。")
        print("  树莓派建议执行: sudo apt install -y python3-picamera2")
        print("  若在 venv 中用 pip 安装失败，请先执行: sudo apt install -y libcap-dev")
        pygame.quit()
        sys.exit(1)

    picam2 = Picamera2()

    # 配置预览分辨率与格式
    # 使用 RGB888 格式，Pygame Surface 可直接使用
    preview_config = picam2.create_preview_configuration(
        main={"size": (CAMERA_WIDTH, CAMERA_HEIGHT), "format": "RGB888"}
    )
    picam2.configure(preview_config)
    picam2.start()

    should_rotate_preview = ((screen_width > screen_height) !=
                             (CAMERA_WIDTH > CAMERA_HEIGHT))

    # 等待摄像头暖机
    time.sleep(0.5)

    print(f"[INFO] 摄像头已启动，采集分辨率 {CAMERA_WIDTH}×{CAMERA_HEIGHT}")
    print(f"[INFO] 显示分辨率 {screen_width}×{screen_height}")
    if should_rotate_preview:
        print("[INFO] 检测到显示方向与相机方向不一致，已自动旋转预览画面。")
    print(f"[INFO] 原型将运行 {RUN_SECONDS} 秒，目标帧率 ≥ {TARGET_FPS} FPS")
    print("[INFO] 按 Ctrl+C 可提前退出\n")

    # 3. 主循环
    frame_count      = 0
    total_frame_count = 0
    start_time       = time.monotonic()
    fps_timer        = start_time
    current_fps      = 0.0

    try:
        while True:
            loop_start = time.monotonic()

            # 超时自动退出
            elapsed = loop_start - start_time
            if elapsed >= RUN_SECONDS:
                print(f"\n[INFO] 运行 {RUN_SECONDS} 秒完成，自动退出。")
                break

            # 处理 Pygame 事件（防止窗口假死）
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    raise KeyboardInterrupt
                if event.type == pygame.KEYDOWN and event.key == pygame.K_q:
                    raise KeyboardInterrupt

            # 采集一帧（返回 numpy ndarray，shape: H×W×3，RGB）
            frame = picam2.capture_array()

            # 将 numpy 数组转为 Pygame Surface
            # frame shape 是 (H, W, 3)，需要转置为 (W, H, 3) 才能正确 blit
            surface = pygame.surfarray.make_surface(frame.swapaxes(0, 1))

            if should_rotate_preview:
                surface = pygame.transform.rotate(surface, -90)

            scaled_surface, offset_x, offset_y = fit_surface_to_screen(
                pygame, surface, screen
            )

            # 绘制到屏幕
            screen.fill((0, 0, 0))
            screen.blit(scaled_surface, (offset_x, offset_y))

            # 叠加十字准星（中央位置）
            cx = screen_width  // 2
            cy = screen_height // 2
            # 水平线
            pygame.draw.line(screen, CROSSHAIR_COLOR,
                             (cx - CROSSHAIR_SIZE, cy),
                             (cx + CROSSHAIR_SIZE, cy),
                             CROSSHAIR_THICK)
            # 垂直线
            pygame.draw.line(screen, CROSSHAIR_COLOR,
                             (cx, cy - CROSSHAIR_SIZE),
                             (cx, cy + CROSSHAIR_SIZE),
                             CROSSHAIR_THICK)

            # 叠加 FPS 文字（仅调试用，正式版不显示）
            font = pygame.font.SysFont(None, 24)
            fps_text = font.render(f"FPS: {current_fps:.1f}", True, (255, 255, 0))
            screen.blit(fps_text, (8, 8))

            pygame.display.flip()

            # FPS 统计
            frame_count       += 1
            total_frame_count += 1
            now = time.monotonic()
            if now - fps_timer >= FPS_REPORT_INTERVAL:
                current_fps = frame_count / (now - fps_timer)
                status = "✓" if current_fps >= TARGET_FPS else "✗ 未达标"
                print(f"  FPS: {current_fps:.1f}  {status}  "
                      f"(经过 {now - start_time:.0f}s / {RUN_SECONDS}s)")
                frame_count = 0
                fps_timer   = now

            # 限制最大帧率，防止空跑占满 CPU
            clock.tick(60)

    except KeyboardInterrupt:
        print("\n[INFO] 用户中断。")
    finally:
        picam2.stop()
        picam2.close()
        pygame.quit()

    # 4. 最终报告
    total_elapsed = time.monotonic() - start_time
    avg_fps = total_frame_count / total_elapsed if total_elapsed > 0 else 0

    print("\n" + "=" * 50)
    print("【相机预览原型 — 验证报告】")
    print(f"  总帧数    : {total_frame_count}")
    print(f"  总运行时间: {total_elapsed:.1f} 秒")
    print(f"  平均帧率  : {avg_fps:.1f} FPS")
    print(f"  验收目标  : ≥ {TARGET_FPS} FPS")
    if avg_fps >= TARGET_FPS:
        print(f"  结果      : ✓ 通过")
    else:
        print(f"  结果      : ✗ 未通过（差 {TARGET_FPS - avg_fps:.1f} FPS）")
    print("=" * 50)


if __name__ == "__main__":
    run()
