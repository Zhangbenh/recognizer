"""
TFLite 推理原型 — 阶段二技术验证 #2
======================================
验证目标（来自开发计划 §3.2 / 验收标准 US-1.3.1）：
  1. TFLite 模型文件可正常加载
  2. 单次推理时延 ≤ 2.5 秒（测量 10 次，取平均值）
  3. 输出类别维度正确（30 类）
  4. 输出类别名称可从标签列表正确映射

关键模型规格（来自模型训练记录）：
  - 框架      : MobileNetV2 + 自定义分类头，INT8 全整数量化
  - 输入 shape: [1, 224, 224, 3]，dtype = uint8
  - 输入范围  : [0, 255] 原始像素值——INT8 量化模型内部已编码归一化
                【重要】不能再做 preprocess_input（归一化到 [-1,1]）
  - 输出 shape: [1, 30]，dtype = uint8（softmax 概率的量化表示）
  - 类别数    : 30

运行方式（树莓派终端）：
  python3 inference_proto.py --model /path/to/plant_classifier_int8.tflite

    # 指定测试图片（可选）
  python3 inference_proto.py --model /path/to/plant_classifier_int8.tflite --image test.jpg

    # 若不指定 --image，程序会先尝试从 tests/ 目录自动选第一张图片；
    # 若 tests/ 没有可用图片，才会回退到随机张量。

依赖安装：
    当前树莓派 Python 3.13 环境建议使用 LiteRT 新包：
        pip install ai-edge-litert numpy pillow

    兼容路径：
        - ai-edge-litert：支持 cp313 manylinux aarch64，优先使用
        - tflite-runtime：旧包，在 aarch64 上通常只提供 cp310/cp311 wheel
        - tensorflow：最后回退方案，体积较大，不建议仅为推理原型安装
"""

import argparse
import os
import sys
import time

import numpy as np

# ── 常量配置 ─────────────────────────────────────────────────────────────────
IMG_SIZE         = 224
NUM_CLASSES      = 30
INFER_ROUNDS     = 10       # 推理次数，取平均时延
MAX_INFER_SEC    = 2.5      # 验收时延上限（秒）
SUPPORTED_IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".bmp", ".webp")

# 30 个类别名称（顺序与训练集 label 完全对应，来自模型训练记录 Cell 4）
CLASS_NAMES = [
    "aloevera",     "banana",        "bilimbi",       "cantaloupe",
    "cassava",      "coconut",       "corn",          "cucumber",
    "curcuma",      "eggplant",      "galangal",      "ginger",
    "guava",        "kale",          "longbeans",     "mango",
    "melon",        "orange",        "paddy",         "papaya",
    "peperchili",   "pineapple",     "pomelo",        "shallot",
    "soybeans",     "spinach",       "sweetpotatoes", "tobacco",
    "waterapple",   "watermelon",
]

assert len(CLASS_NAMES) == NUM_CLASSES, \
    f"CLASS_NAMES 长度 {len(CLASS_NAMES)} != NUM_CLASSES {NUM_CLASSES}"

# ── 工具函数 ─────────────────────────────────────────────────────────────────
def load_test_image(image_path: str) -> np.ndarray:
    """
    从文件加载测试图片，resize 到 224×224，返回 uint8 [0,255] 数组。
    INT8 量化模型输入为原始像素值，不做任何归一化。
    """
    from PIL import Image
    try:
        img = Image.open(image_path).convert("RGB")
    except Exception as exc:
        raise ValueError(f"无法读取图片文件: {image_path}") from exc

    img = img.resize((IMG_SIZE, IMG_SIZE), Image.BILINEAR)
    arr = np.array(img, dtype=np.uint8)          # shape: (224, 224, 3)
    arr = np.expand_dims(arr, axis=0)            # shape: (1, 224, 224, 3)
    return arr


def find_first_test_image(test_dir: str = "tests") -> str | None:
    """从 tests 目录自动挑选第一张支持格式的图片。"""
    if not os.path.isdir(test_dir):
        return None

    for name in sorted(os.listdir(test_dir)):
        path = os.path.join(test_dir, name)
        if not os.path.isfile(path):
            continue
        if name.lower().endswith(SUPPORTED_IMAGE_EXTS):
            return path

    return None


def make_random_input() -> np.ndarray:
    """生成随机 uint8 输入张量，用于无测试图片时验证推理链路。"""
    return np.random.randint(0, 256, (1, IMG_SIZE, IMG_SIZE, 3), dtype=np.uint8)


def dequantize_output(raw_output: np.ndarray,
                      output_details: dict) -> np.ndarray:
    """
    将 uint8 量化输出反量化为 float32 概率值。
    公式: float_val = (uint8_val - zero_point) * scale
    """
    scale      = output_details["quantization_parameters"]["scales"][0]
    zero_point = output_details["quantization_parameters"]["zero_points"][0]
    return (raw_output.astype(np.float32) - zero_point) * scale


# ── 主流程 ───────────────────────────────────────────────────────────────────
def run(model_path: str, image_path: str | None):
    # 1. 检查模型文件
    if not os.path.isfile(model_path):
        print(f"[ERROR] 模型文件不存在: {model_path}")
        print("  请将 plant_classifier_int8.tflite 传到树莓派后指定正确路径。")
        print("  SCP 示例: scp /mnt/workspace/PlantRecognizer/models/"
              "plant_classifier_int8.tflite pi@<host>:~/models/")
        sys.exit(1)

    # 2. 加载 TFLite Interpreter
    print("=" * 55)
    print("【推理原型 — 开始验证】")
    print(f"  模型路径: {model_path}")
    print(f"  模型大小: {os.path.getsize(model_path) / 1024:.1f} KB")

    try:
        from ai_edge_litert.interpreter import Interpreter
        print("  运行时  : ai-edge-litert ✓")
    except ImportError:
        try:
            import tflite_runtime.interpreter as tflite
            Interpreter = tflite.Interpreter
            print("  运行时  : tflite-runtime ✓")
        except ImportError:
            # 回退到完整 TensorFlow（兼容性）
            try:
                import tensorflow as tf
                Interpreter = tf.lite.Interpreter
                print("  运行时  : tensorflow.lite（回退路径）")
            except ImportError:
                print("[ERROR] 未找到 ai-edge-litert、tflite-runtime 或 tensorflow。")
                print(f"  当前 Python 版本: {sys.version.split()[0]}")
                print("  当前树莓派 Python 3.13 环境建议执行:")
                print("    pip install ai-edge-litert numpy pillow")
                print("  若坚持使用 tflite-runtime，则通常需要改用 Python 3.11。")
                sys.exit(1)

    t0 = time.monotonic()
    interpreter = Interpreter(model_path=model_path)
    interpreter.allocate_tensors()
    load_time = time.monotonic() - t0

    print(f"  加载耗时: {load_time:.3f} 秒")

    # 3. 获取输入/输出详情
    input_details  = interpreter.get_input_details()
    output_details = interpreter.get_output_details()
    in_d  = input_details[0]
    out_d = output_details[0]

    print("\n  输入详情:")
    print(f"    shape : {in_d['shape'].tolist()}")
    print(f"    dtype : {in_d['dtype']}")
    print(f"    index : {in_d['index']}")

    print("  输出详情:")
    print(f"    shape : {out_d['shape'].tolist()}")
    print(f"    dtype : {out_d['dtype']}")
    print(f"    index : {out_d['index']}")

    # 验证输出维度
    expected_output_shape = [1, NUM_CLASSES]
    actual_output_shape   = out_d["shape"].tolist()
    if actual_output_shape != expected_output_shape:
        print(f"\n[ERROR] 输出维度不匹配！期望 {expected_output_shape}，"
              f"实际 {actual_output_shape}")
        sys.exit(1)
    print(f"\n  输出维度验证: {actual_output_shape} == {expected_output_shape} ✓")

    # 验证输入 dtype 必须是 uint8
    if in_d["dtype"] != np.uint8:
        print(f"[WARNING] 输入 dtype 不是 uint8，实际为 {in_d['dtype']}。")
        print("  确认模型是否为 INT8 全整数量化版本。")

    # 4. 准备测试输入
    selected_image = image_path
    if not selected_image:
        selected_image = find_first_test_image("tests")
        if selected_image:
            print(f"  测试输入: 自动发现图片 {selected_image}")

    if selected_image:
        if not os.path.isfile(selected_image):
            print(f"[WARNING] 图片文件不存在: {selected_image}，改用随机输入。")
            test_input = make_random_input()
            print("  测试输入: 随机张量（uint8）")
        elif not selected_image.lower().endswith(SUPPORTED_IMAGE_EXTS):
            print(f"[ERROR] 不支持的图片格式: {selected_image}")
            print(f"  支持格式: {', '.join(SUPPORTED_IMAGE_EXTS)}")
            sys.exit(1)
        else:
            test_input = load_test_image(selected_image)
            print(f"  测试输入: {selected_image}")
    else:
        test_input = make_random_input()
        print("  测试输入: 随机张量（uint8，未指定图片且 tests/ 无可用图片）")

    print(f"  输入 shape: {test_input.shape}  dtype: {test_input.dtype}")

    # 5. 预热一次（避免首次推理 JIT 开销影响计时）
    interpreter.set_tensor(in_d["index"], test_input)
    interpreter.invoke()

    # 6. 正式计时推理 INFER_ROUNDS 次
    print(f"\n  开始 {INFER_ROUNDS} 次推理计时...")
    latencies = []

    for i in range(INFER_ROUNDS):
        t_start = time.monotonic()
        interpreter.set_tensor(in_d["index"], test_input)
        interpreter.invoke()
        t_end = time.monotonic()
        latency = t_end - t_start
        latencies.append(latency)
        print(f"    第 {i+1:2d} 次: {latency * 1000:.1f} ms")

    avg_latency = sum(latencies) / len(latencies)
    max_latency = max(latencies)
    min_latency = min(latencies)

    # 7. 获取最后一次推理结果并解析
    raw_output = interpreter.get_tensor(out_d["index"])   # shape: (1, 30), uint8

    # 反量化为概率
    probs = dequantize_output(raw_output, out_d)          # shape: (1, 30), float32
    probs = probs[0]                                       # shape: (30,)

    # 归一化（确保概率和为 1）
    prob_sum = probs.sum()
    if prob_sum > 0:
        probs = probs / prob_sum

    top1_idx   = int(np.argmax(probs))
    top1_name  = CLASS_NAMES[top1_idx]
    top1_prob  = float(probs[top1_idx])

    # Top-3
    top3_idx = np.argsort(probs)[::-1][:3]

    # 8. 报告
    print("\n" + "=" * 55)
    print("【推理原型 — 验证报告】")
    print(f"  推理次数    : {INFER_ROUNDS} 次")
    print(f"  平均时延    : {avg_latency * 1000:.1f} ms")
    print(f"  最大时延    : {max_latency * 1000:.1f} ms")
    print(f"  最小时延    : {min_latency * 1000:.1f} ms")
    print(f"  验收目标    : ≤ {MAX_INFER_SEC * 1000:.0f} ms")
    latency_pass = avg_latency <= MAX_INFER_SEC
    print(f"  时延结果    : {'✓ 通过' if latency_pass else '✗ 未通过'}")
    print()
    print(f"  输出类别数  : {len(probs)}  (期望 {NUM_CLASSES})")
    dim_pass = len(probs) == NUM_CLASSES
    print(f"  维度结果    : {'✓ 通过' if dim_pass else '✗ 未通过'}")
    print()
    print(f"  Top-1 类别  : {top1_name}（index={top1_idx}）")
    print(f"  Top-1 置信度: {top1_prob:.4f}")
    print("  Top-3 结果  :")
    for rank, idx in enumerate(top3_idx, 1):
        print(f"    #{rank}  {CLASS_NAMES[idx]:<18}  {probs[idx]:.4f}")
    print()
    overall_pass = latency_pass and dim_pass
    print(f"  总体结果    : {'✓ 全部通过' if overall_pass else '✗ 存在未通过项'}")
    print("=" * 55)

    return overall_pass


# ── 入口 ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="TFLite 推理原型 — 阶段二技术验证"
    )
    parser.add_argument(
        "--model",
        type=str,
        default="models/plant_classifier_int8.tflite",
        help="TFLite 模型文件路径（默认: models/plant_classifier_int8.tflite）",
    )
    parser.add_argument(
        "--image",
        type=str,
        default=None,
        help=(
            "测试图片路径（可选，支持 .jpg/.jpeg/.png/.bmp/.webp）；"
            "不指定时会先尝试 tests/ 目录自动选图"
        ),
    )
    args = parser.parse_args()

    success = run(model_path=args.model, image_path=args.image)
    sys.exit(0 if success else 1)
