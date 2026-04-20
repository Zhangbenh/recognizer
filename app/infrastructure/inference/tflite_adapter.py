"""TFLite-based inference adapter."""

from __future__ import annotations

from typing import Any

from infrastructure.inference.base_inference_adapter import BaseInferenceAdapter, InferenceOutput


class TFLiteAdapter(BaseInferenceAdapter):
	"""Inference adapter compatible with ai-edge-litert and tflite runtimes."""

	def __init__(self, *, expected_output_classes: int = 30) -> None:
		self._expected_output_classes = expected_output_classes

		self._interpreter: Any = None
		self._input_details: dict[str, Any] | None = None
		self._output_details: dict[str, Any] | None = None

	@property
	def is_loaded(self) -> bool:
		return self._interpreter is not None

	def load_model(self, model_path: str) -> None:
		interpreter_cls = self._resolve_interpreter_class()
		self._interpreter = interpreter_cls(model_path=model_path)
		self._interpreter.allocate_tensors()

		self._input_details = self._interpreter.get_input_details()[0]
		self._output_details = self._interpreter.get_output_details()[0]

	def infer(self, image: Any) -> InferenceOutput:
		if not self.is_loaded or self._input_details is None or self._output_details is None:
			raise RuntimeError("model is not loaded")

		import numpy as np

		input_tensor = self._prepare_input_tensor(image)

		self._interpreter.set_tensor(self._input_details["index"], input_tensor)
		self._interpreter.invoke()
		raw_output = self._interpreter.get_tensor(self._output_details["index"])

		probs = self._to_probabilities(raw_output)

		class_id = int(np.argmax(probs))
		confidence = float(probs[class_id])

		top3_indices = np.argsort(probs)[::-1][:3]
		top3 = [(int(idx), float(probs[idx])) for idx in top3_indices]

		return InferenceOutput(
			class_id=class_id,
			confidence=confidence,
			top3=top3,
			probabilities=[float(value) for value in probs.tolist()],
		)

	def close(self) -> None:
		self._interpreter = None
		self._input_details = None
		self._output_details = None

	def _resolve_interpreter_class(self):
		try:
			from ai_edge_litert.interpreter import Interpreter

			return Interpreter
		except ImportError:
			pass

		try:
			import tflite_runtime.interpreter as tflite

			return tflite.Interpreter
		except ImportError:
			pass

		try:
			import tensorflow as tf

			return tf.lite.Interpreter
		except ImportError as exc:
			raise RuntimeError(
				"No TFLite runtime found. Install ai-edge-litert, tflite-runtime, or tensorflow."
			) from exc

	def _prepare_input_tensor(self, image: Any):
		if self._input_details is None:
			raise RuntimeError("input details are missing")

		import numpy as np

		input_shape = self._input_details["shape"].tolist()
		if len(input_shape) != 4 or input_shape[0] != 1:
			raise ValueError(f"unsupported model input shape: {input_shape}")

		target_h = int(input_shape[1])
		target_w = int(input_shape[2])

		frame = image
		if isinstance(frame, np.ndarray) and frame.ndim == 4 and frame.shape[0] == 1:
			frame = frame[0]

		if not isinstance(frame, np.ndarray):
			raise TypeError("image must be a numpy.ndarray")
		if frame.ndim != 3 or frame.shape[2] != 3:
			raise ValueError("image must have shape (H, W, 3)")

		if frame.shape[0] != target_h or frame.shape[1] != target_w:
			frame = self._resize_rgb(frame, target_w=target_w, target_h=target_h)

		frame = frame.astype(np.uint8, copy=False)
		return np.expand_dims(frame, axis=0)

	def _resize_rgb(self, frame, *, target_w: int, target_h: int):
		try:
			from PIL import Image
		except ImportError as exc:
			raise RuntimeError(
				"Pillow is required for resizing inference inputs. Install pillow package."
			) from exc

		image = Image.fromarray(frame, mode="RGB")
		image = image.resize((target_w, target_h), Image.BILINEAR)

		import numpy as np

		return np.asarray(image, dtype=np.uint8)

	def _to_probabilities(self, raw_output):
		import numpy as np

		logits = self._dequantize_if_needed(raw_output).reshape(-1)
		if self._expected_output_classes > 0 and logits.shape[0] != self._expected_output_classes:
			raise ValueError(
				f"model output classes mismatch: expected {self._expected_output_classes}, got {logits.shape[0]}"
			)

		if np.all(logits >= 0) and float(logits.sum()) > 0:
			probs = logits / logits.sum()
		else:
			shifted = logits - np.max(logits)
			exp_values = np.exp(shifted)
			denom = float(exp_values.sum())
			probs = exp_values / denom if denom > 0 else exp_values

		return probs.astype(float)

	def _dequantize_if_needed(self, raw_output):
		if self._output_details is None:
			return raw_output

		import numpy as np

		output = np.asarray(raw_output)
		if output.dtype not in (np.uint8, np.int8):
			return output.astype(float)

		q_params = self._output_details.get("quantization_parameters", {})
		scales = q_params.get("scales")
		zero_points = q_params.get("zero_points")

		if scales is not None and len(scales) > 0 and float(scales[0]) != 0.0:
			scale = float(scales[0])
			zero_point = float(zero_points[0]) if zero_points is not None and len(zero_points) > 0 else 0.0
			return (output.astype(float) - zero_point) * scale

		quantization = self._output_details.get("quantization")
		if isinstance(quantization, tuple) and len(quantization) == 2 and float(quantization[0]) != 0.0:
			scale = float(quantization[0])
			zero_point = float(quantization[1])
			return (output.astype(float) - zero_point) * scale

		return output.astype(float)

