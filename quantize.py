from onnxruntime.quantization import quantize_dynamic, QuantType

quantize_dynamic(
    model_input="models/30-cfb.onnx",
    model_output="models/30-cfb-int8.onnx",
    weight_type=QuantType.QUInt8
)

print("Done! Check the file size of 30-cfb-int8.onnx vs the original.")

